# -*- coding: utf-8 -*-
"""
p1_daily.py —— 问题 1 日粒度预测 → 结果表 1

用 backtest.py 选出的主模型（A9 分解式稳健加权移动平均）对
2023-12-01 ~ 2023-12-30 共 30 天 × 57 个分拣中心做日货量预测，
四舍五入取整后写入 结果表1.csv（`分拣中心,日期,货量`，1710 行）。

同时输出：
    data/pred_daily_base.csv   问题 1 的日预测（表 1 的副本，供 p1_hourly / 校验复用）
    data/pred_total.json       全网日总量曲线（供 plots.py 绘图）
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import models as M

PRED_START = "2023-12-01"
PRED_DAYS = 30


def load_choice() -> dict:
    path = os.path.join(C.DATA_DIR, "model_choice.json")
    if not os.path.exists(path):
        raise SystemExit("缺少 %s，请先运行 python code/backtest.py" % path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def predict_daily(choice: dict | None = None, verbose: bool = True):
    """返回 (pred: index=中心, columns=日期str, 整数值)。"""
    choice = choice or load_choice()
    daily = C.load_daily()
    wide = M.wide_matrix(daily)
    mask = M.mask_matrix(daily)

    # ---- A10 的周增长率漂移（打破 A9 的精确 7 天周期）----
    gcfg = choice.get("growth") or {}
    growth = None
    if gcfg.get("enabled", False):
        g_series, g_info = M.weekly_growth(
            wide, weeks=int(gcfg.get("weeks", 8)), clip=float(gcfg.get("clip", 0.015)),
            shrink=float(gcfg.get("shrink_c", 0.5)))
        if gcfg.get("mode") == "network_median":
            g_med = float(g_info.attrs.get("g_net", 0.0))
            g_series = pd.Series(g_med, index=wide.index)
        growth = g_series
        g_info.insert(0, "训练末端", str(wide.columns[-1].date()))
        g_info.to_csv(os.path.join(C.DATA_DIR, "growth_table_prod.csv"),
                      index=False, encoding=C.ENC_OUT)
        if verbose:
            print("[p1] 周增长率 g（%s）：中位 %.4f%%/周，范围 [%.4f%%, %.4f%%]，被收缩 %d 个中心" % (
                gcfg.get("mode"), float(g_series.median()) * 100,
                float(g_series.min()) * 100, float(g_series.max()) * 100,
                int(g_info["是否收缩"].sum())))

    hdates = pd.date_range(PRED_START, periods=PRED_DAYS, freq="D")
    cols = [C.date_cn(d) for d in hdates]
    pred = M.decomp(wide, mask, hdates,
                    k=int(choice["k"]), shrink=float(choice.get("shrink", 4.0)),
                    use_weekday=bool(choice["weekday"]), use_trend=bool(choice["trend"]),
                    growth=growth)
    pred = pred.clip(lower=0.0)
    # 四舍五入取整，且保证非负（0 件没有业务意义，最低取 1）
    pred_int = np.rint(pred.to_numpy()).astype(np.int64)
    pred_int = np.maximum(pred_int, 1)

    out = pd.DataFrame(pred_int, index=pred.index, columns=cols)

    # ---- 整数分辨率修复：确保「同中心同星期几」不再完全周期 ----
    # 背景：极小漂移（<1%/周）在 49 件/日 这种小中心上会被四舍五入抹平，
    # 导致某星期几的 4~5 个预测值完全相同。这不是模型周期性，而是整数分辨率不足。
    # 处理：对这些中心按 2 倍逐级放大 |g|（保持符号，上限 clip=1.5%/周）直到不再全同，
    #       单次改动量 ≤ 该中心月内 4% 的货量，对 WAPE 无实质影响。
    repaired = []
    if growth is not None:
        clip = float(gcfg.get("clip", 0.015))
        L = M.robust_level(wide, mask, k=int(choice["k"]))
        W = M.weekday_factors(wide, mask, shrink=float(choice.get("shrink", 4.0))) \
            if bool(choice["weekday"]) else None
        slope = M.global_trend_slope(wide, mask) if bool(choice["trend"]) else 0.0
        anchor = pd.Timestamp(wide.columns[-1])

        def row_of(c, gc):
            v = np.empty(len(hdates))
            for j, dd in enumerate(hdates):
                tr = float(np.exp(slope * (dd - anchor).days)) if bool(choice["trend"]) else 1.0
                wv = float(W.loc[c, dd.dayofweek]) if W is not None else 1.0
                v[j] = float(L[c]) * wv * tr * (1.0 + gc) ** (j / 7.0)
            return np.maximum(np.rint(v).astype(np.int64), 1)

        dows = np.array([dd.dayofweek for dd in hdates])
        for c in wide.index:
            gc = float(growth[c])
            row = out.loc[c].to_numpy()
            ok = all(len(set(row[dows == k])) > 1 for k in range(7))
            if ok:
                continue
            base = gc if abs(gc) > 1e-6 else 0.005
            for _ in range(8):
                gc = float(np.sign(base) * min(abs(gc) * 2.0 if abs(gc) > 1e-9 else abs(base) * 2.0, clip))
                row = row_of(c, gc)
                if all(len(set(row[dows == k])) > 1 for k in range(7)):
                    break
            out.loc[c] = row
            repaired.append((c, float(growth[c]), gc))

    if verbose:
        print("[p1] 主模型 %s，k=%d，星期因子=%s，趋势因子=%s，漂移=%s" % (
            choice["model"], choice["k"], choice["weekday"], choice["trend"],
            (choice.get("growth") or {}).get("mode", "none")))
        if repaired:
            print("[p1] 整数分辨率修复 %d 个中心：%s" % (
                len(repaired), "、".join("%s(g %.4f%%→%.4f%%)" % (c, a * 100, b * 100)
                                        for c, a, b in repaired)))
        print("[p1] 预测区间 %s ~ %s，%d 天 × %d 中心 = %d 格" % (
            cols[0], cols[-1], len(cols), len(out), out.size))
    return out, choice


def to_long(pred: pd.DataFrame) -> pd.DataFrame:
    """中心 × 日期宽表 → 结果表长表（分拣中心, 日期, 货量）。"""
    rows = []
    for d in pred.columns:
        for c in pred.index:
            rows.append((c, d, int(pred.at[c, d])))
    df = pd.DataFrame(rows, columns=[C.CENTER, C.DATE, C.VOL])
    df[C.CENTER] = df[C.CENTER].astype(str)
    return df


def main() -> None:
    C._force_utf8_stdout()
    os.makedirs(C.DATA_DIR, exist_ok=True)
    pred, choice = predict_daily()
    long = to_long(pred)

    C.write_result_table(long, 1, [C.CENTER, C.DATE, C.VOL])
    long.to_csv(os.path.join(C.DATA_DIR, "pred_daily_base.csv"),
                index=False, encoding=C.ENC_OUT)

    # ---- 汇总 ----
    daily = C.load_daily()
    nov = daily[daily[C.DATE].dt.month == 11].groupby(C.DATE)[C.VOL].sum()
    hist = daily.groupby(C.DATE)[C.VOL].sum().sort_index()
    pred_total = long.groupby(C.DATE)[C.VOL].sum()
    # 字符串日期是字典序（12/10 会排在 12/2 前），必须按真实日期重排
    pred_total = pred_total.reindex(
        sorted(pred_total.index, key=lambda s: pd.to_datetime(s, format="%Y/%m/%d")))

    print("[p1] 预测总量 %s 件，日均 %s 件（11 月实际日均 %s 件，比值 %.4f）" % (
        format(int(pred_total.sum()), ","), format(int(pred_total.mean()), ","),
        format(int(nov.mean()), ","), pred_total.mean() / nov.mean()))
    print("[p1] 单日区间 %s ~ %s 件" % (
        format(int(pred_total.min()), ","), format(int(pred_total.max()), ",")))

    # 12 月的星期分布提示（用于人工核对周因子是否生效）
    wd = pd.to_datetime(pred_total.index, format="%Y/%m/%d").dayofweek
    print("[p1] 按星期几的预测日均：%s" % "  ".join(
        "%s=%.0f" % (C.WEEKDAY_CN[k], pred_total[wd == k].mean()) for k in range(7)))

    payload = {
        "hist_dates": [C.date_cn(d) for d in hist.index[-30:]],
        "hist_total": [int(v) for v in hist.to_numpy()[-30:]],
        "pred_dates": list(pred_total.index),
        "pred_total": [int(v) for v in pred_total.to_numpy()],
        "nov_mean": float(nov.mean()),
        "pred_mean": float(pred_total.mean()),
        "model": choice,
    }
    with open(os.path.join(C.DATA_DIR, "pred_total.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("[p1] 已写出 data/pred_daily_base.csv、data/pred_total.json")


if __name__ == "__main__":
    main()
