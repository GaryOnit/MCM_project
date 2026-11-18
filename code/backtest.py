# -*- coding: utf-8 -*-
"""
backtest.py —— 四模型回测（Phase B 第 1 项，论文核心证据）

设置
----
训练 2023-08-01 ~ 2023-10-31（92 天）→ 验证 2023-11-01 ~ 2023-11-30（30 天），
固定起点（与真实使用场景一致：只用预测起点之前的数据）。

模型
----
A1 朴素均值 / A2 线性加权移动平均（21 天）/ A4 Holt-Winters 加法（周期 7）
A9 分解式稳健加权移动平均（水平 × 星期因子 × 趋势因子）——主模型

指标
----
WAPE（主）、MAPE（分母 max(y,1)）、RMSE；按中心与全网汇总。
另外单独给出「剔除大促日」的 WAPE_ex：11/1~11/3、11/10~11/13 这 7 天
任何模型都无法从 8—10 月外推，会把所有模型的误差同时抬高，掩盖模型差异；
12 月的常态日占绝大多数，所以**模型选择口径用 WAPE_ex**，同时报告全口径 WAPE。

输出
----
data/backtest_results.csv   长表：model × scope(ALL/中心) × 指标
data/backtest_grid.csv      A9 的 k / 星期因子 / 趋势因子 网格搜索结果
data/backtest_payload.json  绘图用（全网日总量曲线、指标）
data/model_choice.json      选定的主模型与参数（供 p1_daily.py 读取，避免硬编码漂移）
"""

from __future__ import annotations

import itertools
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import models as M

TRAIN_END = pd.Timestamp("2023-10-31")
VALID_START = pd.Timestamp("2023-11-01")
VALID_END = pd.Timestamp("2023-11-30")

# 验证期内无法外推的大促日（用于 WAPE_ex）
PROMO_VALID = pd.to_datetime(["2023-11-01", "2023-11-02", "2023-11-03",
                              "2023-11-10", "2023-11-11", "2023-11-12", "2023-11-13"])


# --------------------------------------------------------------------------- #
def train_mask(train: pd.DataFrame) -> pd.DataFrame:
    """只用训练窗口的分位数构造 IQR 掩码（避免用验证期信息）。"""
    ev = M.event_dates()
    cols = train.columns
    q1 = train.quantile(0.25, axis=1)
    q3 = train.quantile(0.75, axis=1)
    iqr = q3 - q1
    lo = (q1 - 1.5 * iqr).to_numpy()[:, None]
    hi = (q3 + 1.5 * iqr).to_numpy()[:, None]
    v = train.to_numpy()
    flag = (v < lo) | (v > hi)
    m = pd.DataFrame(flag, index=train.index, columns=cols)
    for d in cols:
        if pd.Timestamp(d) in set(ev):
            m[d] = True
    return m


def broadcast(series: pd.Series, horizon_dates) -> pd.DataFrame:
    """把 中心 级常量扩成 中心 × h 矩阵。"""
    vals = np.repeat(series.to_numpy()[:, None], len(horizon_dates), axis=1)
    return pd.DataFrame(vals, index=series.index,
                        columns=["h%d" % (i + 1) for i in range(len(horizon_dates))])


def eval_matrix(pred: pd.DataFrame, actual: pd.DataFrame, promo_mask) -> dict:
    """整体 + 分中心指标。pred/actual 都是 中心 × h。"""
    p = pred.to_numpy()
    a = actual.to_numpy()
    keep = ~promo_mask
    out = {"ALL": M.metrics(a.ravel(), p.ravel()),
           "ALL_ex": M.metrics(a[:, keep].ravel(), p[:, keep].ravel())}
    per = {}
    for i, c in enumerate(actual.index):
        per[c] = {"WAPE": M.metrics(a[i], p[i])["WAPE"],
                  "WAPE_ex": M.metrics(a[i, keep], p[i, keep])["WAPE"],
                  "MAPE": M.metrics(a[i], p[i])["MAPE"],
                  "RMSE": M.metrics(a[i], p[i])["RMSE"],
                  "实际合计": float(a[i].sum()), "预测合计": float(p[i].sum())}
    return out, per


# --------------------------------------------------------------------------- #
def main() -> None:
    C._force_utf8_stdout()
    daily = C.load_daily()
    wide = M.wide_matrix(daily)

    train = wide.loc[:, wide.columns <= TRAIN_END]
    valid = wide.loc[:, (wide.columns >= VALID_START) & (wide.columns <= VALID_END)]
    vdates = pd.DatetimeIndex(valid.columns)

    mask = train_mask(train)
    promo_mask = np.array([pd.Timestamp(d) in set(PROMO_VALID) for d in valid.columns])

    print("[backtest] 训练 %d 天（%s ~ %s），验证 %d 天（%s ~ %s）" % (
        train.shape[1], train.columns[0].date(), train.columns[-1].date(),
        valid.shape[1], valid.columns[0].date(), valid.columns[-1].date()))
    print("[backtest] 训练期被剔除的异常/事件格：%d / %d（%.2f%%）" % (
        int(mask.to_numpy().sum()), mask.size, mask.to_numpy().mean() * 100))

    preds = {}
    preds["A1_朴素均值"] = broadcast(M.naive_mean(train), vdates)
    preds["A2_加权移动平均21"] = broadcast(M.wma(train, 21), vdates)
    preds["A4_HoltWinters"] = M.holt_winters(train, len(vdates))

    # ---- A9 网格搜索（先定参，再进对比表）----
    grid = []
    for k, use_wd, use_tr in itertools.product([7, 10, 14, 21, 28, 35, 42, 56],
                                               [True, False], [True, False]):
        p = M.decomp(train, mask, vdates, k=k, shrink=4.0,
                     use_weekday=use_wd, use_trend=use_tr).clip(lower=0.0)
        agg, per = eval_matrix(p, valid, promo_mask)
        w = np.array([v["WAPE"] for v in per.values()])
        grid.append({"k": k, "weekday": use_wd, "trend": use_tr,
                     "WAPE": agg["ALL"]["WAPE"], "WAPE_ex": agg["ALL_ex"]["WAPE"],
                     "MAPE": agg["ALL"]["MAPE"], "RMSE": agg["ALL"]["RMSE"],
                     "median_center_WAPE": float(np.median(w))})
    gdf = pd.DataFrame(grid).sort_values("WAPE_ex").reset_index(drop=True)
    gdf.to_csv(os.path.join(C.DATA_DIR, "backtest_grid.csv"), index=False, encoding=C.ENC_OUT)
    best = gdf.iloc[0]
    print("\n[backtest] === A9 网格搜索 Top5（按 WAPE_ex 排序）===")
    print(gdf.head(5).to_string(index=False, float_format=lambda x: "%.4f" % x))

    preds["A9_分解式稳健WMA"] = M.decomp(train, mask, vdates, k=int(best["k"]), shrink=4.0,
                                        use_weekday=bool(best["weekday"]),
                                        use_trend=bool(best["trend"])).clip(lower=0.0)

    # ---- A10：A9 × 周增长率漂移 ----
    g_train, g_info = M.weekly_growth(train, weeks=8, clip=0.015, shrink=0.5)
    g_info.insert(0, "训练末端", str(train.columns[-1].date()))
    g_info.to_csv(os.path.join(C.DATA_DIR, "growth_table.csv"),
                  index=False, encoding=C.ENC_OUT)
    preds["A10_漂移A9"] = M.decomp(train, mask, vdates, k=int(best["k"]), shrink=4.0,
                                  use_weekday=bool(best["weekday"]),
                                  use_trend=bool(best["trend"]),
                                  growth=g_train).clip(lower=0.0)
    print("\n[backtest] === A10 周增长率（训练窗口最后 8 周）===")
    print("  g 原始：中位 %.4f%%/周，最大 %.4f%%，最小 %.4f%%，被收缩 %d 个中心；全网中位 g_net = %.4f%%/周" % (
        g_info["g_raw"].median() * 100, g_info["g_raw"].max() * 100, g_info["g_raw"].min() * 100,
        int(g_info["是否收缩"].sum()), g_info.attrs.get("g_net", float("nan")) * 100))
    print("  g 最终：中位 %.4f%%/周，范围 [%.4f%%, %.4f%%]" % (
        g_info["g_final"].median() * 100, g_info["g_final"].min() * 100, g_info["g_final"].max() * 100))

    # ---- 主表 ----
    rows = []
    summary = {}
    per_center = {}
    for name, pred in preds.items():
        pred = pred.clip(lower=0.0)
        agg, per = eval_matrix(pred, valid, promo_mask)
        summary[name] = agg
        per_center[name] = per
        rows.append({"model": name, "scope": "ALL",
                     "WAPE": agg["ALL"]["WAPE"], "WAPE_ex": agg["ALL_ex"]["WAPE"],
                     "MAPE": agg["ALL"]["MAPE"], "RMSE": agg["ALL"]["RMSE"],
                     "n": agg["ALL"]["n"]})
        for c, v in per.items():
            rows.append({"model": name, "scope": c,
                         "WAPE": v["WAPE"], "WAPE_ex": v["WAPE_ex"],
                         "MAPE": v["MAPE"], "RMSE": v["RMSE"],
                         "n": len(vdates)})
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(C.DATA_DIR, "backtest_results.csv"), index=False, encoding=C.ENC_OUT)

    print("\n[backtest] === 全网汇总（验证 11 月）===")
    print("%-22s %8s %8s %8s %12s" % ("模型", "WAPE", "WAPE_ex", "MAPE", "RMSE"))
    for name in preds:
        a = summary[name]
        print("%-22s %7.2f%% %7.2f%% %7.2f%% %12.0f" % (
            name, a["ALL"]["WAPE"] * 100, a["ALL_ex"]["WAPE"] * 100,
            a["ALL"]["MAPE"] * 100, a["ALL"]["RMSE"]))

    # 分中心 WAPE 中位数（衡量「普遍更好」而非「平均更好」）
    print("\n[backtest] 分中心 WAPE（中位数 / 90 分位 / 优于 A1 的中心数）：")
    a1 = per_center["A1_朴素均值"]
    for name in preds:
        w = np.array([v["WAPE"] for v in per_center[name].values()])
        better = sum(1 for c, v in per_center[name].items() if v["WAPE"] <= a1[c]["WAPE"] + 1e-12)
        print("  %-22s 中位 %6.2f%%  90分位 %6.2f%%  优于A1: %d/%d" % (
            name, np.median(w) * 100, np.percentile(w, 90) * 100, better, len(w)))

    # ---- A9 vs A10 判定 ----
    a9 = summary["A9_分解式稳健WMA"]["ALL_ex"]["WAPE"]
    a10 = summary["A10_漂移A9"]["ALL_ex"]["WAPE"]
    delta_pp = (a10 - a9) * 100
    g_net = float(g_info.attrs.get("g_net", 0.0))
    use_a10 = bool(a10 <= a9 + 0.003)
    n_shrunk = int(g_info["是否收缩"].sum())
    print("\n[backtest] === A9 vs A10 判定 ===")
    print("  A9  WAPE_ex = %.2f%%，A10 WAPE_ex = %.2f%%，差 %+.2fpp（阈值 +0.30pp）→ %s" % (
        a9 * 100, a10 * 100, delta_pp,
        "采用 A10（打破精确周期）" if use_a10 else "退回 A9 + 全网中位保守漂移"))

    # ---- 记录选定的主模型参数 ----
    choice = {"model": "A10_漂移A9" if use_a10 else "A10_保守漂移(全网中位g)",
              "base": "A9_分解式稳健WMA",
              "k": int(best["k"]),
              "weekday": bool(best["weekday"]),
              "trend": bool(best["trend"]),
              "shrink": 4.0,
              "growth": {"enabled": True,
                         "mode": "per_center" if use_a10 else "network_median",
                         "weeks": 8, "clip": 0.015, "shrink_c": 0.5,
                         "g_net_train": g_net,
                         "n_shrunk_train": n_shrunk},
            "select_metric": "WAPE_ex",
              "valid_WAPE": float(summary["A10_漂移A9" if use_a10 else "A9_分解式稳健WMA"]["ALL"]["WAPE"]),
              "valid_WAPE_ex": float(a10 if use_a10 else a9),
              "valid_WAPE_A9": float(a9), "valid_WAPE_A10": float(a10),
              "valid_MAPE_A9": float(summary["A9_分解式稳健WMA"]["ALL"]["MAPE"]),
              "valid_MAPE_A10": float(summary["A10_漂移A9"]["ALL"]["MAPE"]),
              "train_end": str(TRAIN_END.date()),
              "valid_range": [str(VALID_START.date()), str(VALID_END.date())]}
    with open(os.path.join(C.DATA_DIR, "model_choice.json"), "w", encoding="utf-8") as f:
        json.dump(choice, f, ensure_ascii=False, indent=1)

    # ---- 绘图用 payload ----
    actual_total = valid.sum(axis=0)
    payload = {
        "dates": [d.strftime("%Y-%m-%d") for d in vdates],
        "actual": [float(v) for v in actual_total.to_numpy()],
        "pred": {name: [float(v) for v in p.sum(axis=0).to_numpy()] for name, p in preds.items()},
        "summary": {name: {"WAPE": summary[name]["ALL"]["WAPE"],
                           "WAPE_ex": summary[name]["ALL_ex"]["WAPE"],
                           "MAPE": summary[name]["ALL"]["MAPE"],
                           "RMSE": summary[name]["ALL"]["RMSE"]} for name in preds},
        "grid": gdf.head(12).to_dict(orient="records"),
        "promo_days": [d.strftime("%Y-%m-%d") for d in PROMO_VALID],
        "per_center_wape": {name: {c: v["WAPE"] for c, v in per_center[name].items()}
                            for name in preds},
    }
    with open(os.path.join(C.DATA_DIR, "backtest_payload.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print("\n[backtest] 主模型选定：%s，k=%d，星期因子=%s，趋势因子=%s，漂移=%s" % (
        choice["model"], choice["k"], choice["weekday"], choice["trend"],
        choice["growth"]["mode"]))
    print("[backtest] 已写出 data/backtest_results.csv、backtest_grid.csv、growth_table.csv、"
          "backtest_payload.json、model_choice.json")


if __name__ == "__main__":
    main()
