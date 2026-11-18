# -*- coding: utf-8 -*-
"""
p1_hourly.py —— 问题 1 小时粒度分配 → 结果表 2

思路：固定小时占比法（附件2 缺格补 0，不插值）
    日预测（表 1）× 中心 24 小时占比 → 小时货量
    → 最大余数法取整，保证 Σ_小时 = 当日日预测（整数）

占比的三点处理
--------------
1. 分母用「该中心当日 24 小时合计」，占比天然和为 1；
2. 可选向「全网平均占比」做 shrink 倍收缩（小中心噪声大，收缩更稳）；
3. 可选「按星期几分档」占比（工作日/周末形态不同）。

回测（附件2 只有 11 月，故用 11 月内切分）
------------------------------------------
训练 11/1~11/15 → 验证 11/16~11/30；为避免日粒度误差掩盖小时模型差异，
**验证时用真实日货量**去乘占比（只评估「小时分配」这一步）。
指标同为 WAPE（主）/ MAPE / RMSE。

输出
----
结果表2.csv                  41040 行（分拣中心, 日期, 小时, 货量）
data/hour_share.csv          选定方案的中心×24 占比（供 p2_adjust 复用）
data/pred_hourly_base.csv    表 2 的副本
data/hourly_backtest.csv     四个占比方案的回测对比
data/model_choice.json       追加 hourly 选择结果
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

TRAIN_END = pd.Timestamp("2023-11-15")
VALID_START = pd.Timestamp("2023-11-16")
VALID_END = pd.Timestamp("2023-11-30")


# --------------------------------------------------------------------------- #
def build_share(hourly: pd.DataFrame, shrink: float, by_weekday: bool, days=None):
    return M.hourly_share(hourly, shrink=shrink, by_weekday=by_weekday, days=days)


def eval_share(hourly: pd.DataFrame, daily: pd.DataFrame, share,
               days) -> dict:
    """用真实日货量 × 占比 还原小时，评估小时分配误差。"""
    h = hourly[hourly[C.DATE].isin(list(days))]
    dmap = daily.set_index([C.CENTER, C.DATE])[C.VOL]
    rows = []
    for d in days:
        ts = pd.Timestamp(d)
        sh = share[ts.dayofweek] if isinstance(share, dict) else share
        sub = h[h[C.DATE] == ts]
        for c, g in sub.groupby(C.CENTER):
            if c not in sh.index or (c, ts) not in dmap.index:
                continue
            tot = float(dmap.loc[(c, ts)])
            w = sh.loc[c].to_numpy()
            pred = np.rint(w * tot).astype(np.int64)
            act = g.set_index(C.HOUR)[C.VOL].reindex(range(24)).fillna(0.0).to_numpy()
            rows.append((act, pred))
    a = np.concatenate([r[0] for r in rows])
    p = np.concatenate([r[1] for r in rows])
    m = M.metrics(a, p)
    m["总实际"] = float(a.sum())
    m["总预测"] = float(p.sum())
    return m


def choose_share(hourly: pd.DataFrame, daily: pd.DataFrame, verbose: bool = True):
    train_days = [d for d in sorted(hourly[C.DATE].unique())
                  if pd.Timestamp(d) <= TRAIN_END]
    valid_days = [d for d in sorted(hourly[C.DATE].unique())
                  if VALID_START <= pd.Timestamp(d) <= VALID_END]

    promo = pd.to_datetime(["2023-11-01", "2023-11-02", "2023-11-03",
                            "2023-11-10", "2023-11-11", "2023-11-12", "2023-11-13"])
    train_clean = [d for d in train_days if pd.Timestamp(d) not in set(promo)]

    variants = [
        ("固定占比(全部日)", 0.0, False, train_days),
        ("固定占比(0.5收缩)", 0.5, False, train_days),
        ("固定占比(剔除大促日)", 0.0, False, train_clean),
        ("按星期几占比(全部日)", 0.0, True, train_days),
        ("按星期几占比(剔除大促日)", 0.0, True, train_clean),
        ("按星期几占比(0.5收缩)", 0.5, True, train_days),
    ]
    rows = []
    for name, shrink, by_wd, days in variants:
        sh = build_share(hourly, shrink, by_wd, days=days)
        m = eval_share(hourly, daily, sh, valid_days)
        rows.append({"方案": name, "shrink": shrink, "按星期几": by_wd,
                     "估计用天数": len(days),
                     "WAPE": m["WAPE"], "MAPE": m["MAPE"], "RMSE": m["RMSE"],
                     "总实际": m["总实际"], "总预测": m["总预测"]})
    cmp = pd.DataFrame(rows).sort_values("WAPE").reset_index(drop=True)
    cmp.to_csv(os.path.join(C.DATA_DIR, "hourly_backtest.csv"),
               index=False, encoding=C.ENC_OUT)

    if verbose:
        print("\n[p1h] === 小时占比方案回测（训练 11/1-11/15，验证 11/16-11/30）===")
        print(cmp.to_string(index=False, float_format=lambda x: "%.4f" % x))

    best = cmp.iloc[0]
    return cmp, {"name": best["方案"], "shrink": float(best["shrink"]),
                 "by_weekday": bool(best["按星期几"]),
                 "exclude_promo": "剔除" in str(best["方案"]),
                 "valid_WAPE": float(best["WAPE"]),
                 "valid_days": [C.date_cn(d) for d in valid_days]}


# --------------------------------------------------------------------------- #
def main() -> None:
    C._force_utf8_stdout()
    hourly = C.load_hourly()          # 缺格已按 0 补齐
    daily = C.load_daily()

    cmp, choice_h = choose_share(hourly, daily)

    # 最终占比：用全 11 月（若选中「剔除大促日」方案则去掉 11/1-11/3、11/10-11/13）
    promo = pd.to_datetime(["2023-11-01", "2023-11-02", "2023-11-03",
                            "2023-11-10", "2023-11-11", "2023-11-12", "2023-11-13"])
    all_days = sorted(hourly[C.DATE].unique())
    fit_days = [d for d in all_days if pd.Timestamp(d) not in set(promo)] \
        if choice_h.get("exclude_promo") else all_days
    share_final = build_share(hourly, choice_h["shrink"], choice_h["by_weekday"], days=fit_days)
    if isinstance(share_final, dict):
        # 按星期几方案 → 落地为 7×中心×24 的三维表，便于下游复用
        share_tab = pd.concat(
            {k: v for k, v in share_final.items()}, names=["星期几", C.CENTER]
        ).reset_index()
        share_tab.columns = ["星期几", C.CENTER] + [str(h) for h in range(24)]
        share_tab.to_csv(os.path.join(C.DATA_DIR, "hour_share_by_weekday.csv"),
                         index=False, encoding=C.ENC_OUT)
        share_for_split = share_final
        share_single = share_final[0]      # 供落盘/展示的参考（周一）
    else:
        share_single = share_final
        share_for_split = share_final

    out = share_single.copy()
    out.index.name = C.CENTER
    out.columns = [str(h) for h in range(24)]
    out.round(8).to_csv(os.path.join(C.DATA_DIR, "hour_share.csv"), encoding=C.ENC_OUT)

    # ---- 生成表 2 ----
    base_path = os.path.join(C.DATA_DIR, "pred_daily_base.csv")
    if not os.path.exists(base_path):
        raise SystemExit("缺少 %s，请先运行 python code/p1_daily.py" % base_path)
    base = pd.read_csv(base_path, encoding=C.ENC_OUT)
    dates = list(dict.fromkeys(base[C.DATE].tolist()))
    wide = base.pivot(index=C.CENTER, columns=C.DATE, values=C.VOL)
    wide = wide.reindex(sorted(wide.index, key=C.center_rank))
    wide = wide[dates]

    long = M.split_daily_to_hourly(wide, share_for_split, dates)
    long[C.CENTER] = long[C.CENTER].astype(str)
    long[C.HOUR] = long[C.HOUR].astype(int)
    long[C.VOL] = long[C.VOL].astype(int)

    C.write_result_table(long, 2, [C.CENTER, C.DATE, C.HOUR, C.VOL])
    long.to_csv(os.path.join(C.DATA_DIR, "pred_hourly_base.csv"),
                index=False, encoding=C.ENC_OUT)

    # 自检：Σ小时 = 日
    chk = long.groupby([C.CENTER, C.DATE])[C.VOL].sum().rename("小时合计").reset_index()
    m = chk.merge(base, on=[C.CENTER, C.DATE])
    bad = int((m["小时合计"] != m[C.VOL]).sum())
    print("[p1h] 表2 行数 %d，日合计不符的 (中心,日期) 数：%d" % (len(long), bad))
    print("[p1h] 选定方案：%s（验证 WAPE %.2f%%）" % (choice_h["name"], choice_h["valid_WAPE"] * 100))

    # 追加到 model_choice.json
    choice_path = os.path.join(C.DATA_DIR, "model_choice.json")
    with open(choice_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["hourly"] = choice_h
    with open(choice_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)

    # 绘图用：某中心 12 月首日的小时占比曲线
    demo_center = "SC60"
    sh = share_for_split[0] if isinstance(share_for_split, dict) else share_for_split
    payload = {
        "demo_center": demo_center,
        "share": [float(x) * 100 for x in sh.loc[demo_center].to_numpy()] if demo_center in sh.index else [],
        "net_share": [float(x) * 100 for x in
                      M.hourly_share(hourly).mean(axis=0).to_numpy()],
        "choice": choice_h,
        "grid": cmp.to_dict(orient="records"),
    }
    with open(os.path.join(C.DATA_DIR, "hourly_payload.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("[p1h] 已写出 表2、data/hour_share.csv、hourly_backtest.csv、hourly_payload.json")


if __name__ == "__main__":
    main()
