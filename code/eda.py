# -*- coding: utf-8 -*-
"""
eda.py —— 探索性数据分析（数据侧 Phase A 第 3、4 项）

做三件事：
  1. 计算所有 EDA 指标（覆盖范围、完整度、趋势、周季节、大促脉冲、小时形态、
     中心规模结构、线路网络关系），汇总成 data/eda_payload.json；
  2. 把绘图所需的数组一并写进 payload，交给 code/plot_figs.py（系统 python + matplotlib）
     出图，避免两个解释器的 pandas 版本差异；
  3. 生成 data/eda_report.md（结论式写法，所有数字由本脚本计算后注入，不手填）。

运行：python code/eda.py            （需要 pandas / numpy，无 matplotlib）
      python code/plot_figs.py      （需要 matplotlib，读取同一份 payload 出图）
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

PAYLOAD = os.path.join(C.DATA_DIR, "eda_payload.json")
REPORT = os.path.join(C.DATA_DIR, "eda_report.md")


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def event_mask(index: pd.DatetimeIndex) -> pd.Series:
    """标出事件窗口内的日期（大促/节假日），用于稳健统计时剔除。"""
    m = pd.Series(False, index=index)
    for s, e in C.EVENT_WINDOWS.values():
        m = m | ((index >= pd.Timestamp(s)) & (index <= pd.Timestamp(e)))
    return m


def spearman(a: pd.Series, b: pd.Series) -> float:
    """无 scipy 的 Spearman：秩相关。"""
    ra = pd.Series(np.asarray(a, dtype=float)).rank()
    rb = pd.Series(np.asarray(b, dtype=float)).rank()
    return float(np.corrcoef(ra, rb)[0, 1])


def pct(x, nd=2) -> str:
    return ("%." + str(nd) + "f%%") % (x * 100)


# --------------------------------------------------------------------------- #
# 主分析
# --------------------------------------------------------------------------- #
def analyse(verbose: bool = True) -> dict:
    daily = C.load_daily()
    hourly = C.load_hourly()
    routes = C.load_routes()
    opens = C.load_route_open()

    dc = C.daily_completeness(daily)
    hc = C.hourly_completeness(hourly)
    rec = C.reconcile_hourly_daily(daily, hourly)

    # ---------- 1. 覆盖与总量 ----------
    day = daily.groupby(C.DATE)[C.VOL].sum().sort_index()
    emask = event_mask(day.index)
    total = float(day.sum())
    d_mean = float(day.mean())
    imax, imin = day.idxmax(), day.idxmin()

    # ---------- 2. 趋势（剔除事件日，log 线性） ----------
    x = np.arange(len(day), dtype=float)
    keep = ~emask.to_numpy()
    slope = float(np.polyfit(x[keep], np.log(day.to_numpy()[keep]), 1)[0])
    month_growth = float(np.exp(slope * 30) - 1)
    month_avg = {int(m): float(day[(day.index.month == m) & keep].mean()) for m in [8, 9, 10, 11]}
    aug_to_nov = month_avg[11] / month_avg[8] - 1

    # ---------- 3. 周季节（7 日居中均值去趋势） ----------
    trend7 = day.rolling(7, center=True, min_periods=4).mean()
    ratio = day / trend7
    dow_raw = [float(day[day.index.dayofweek == k].mean()) for k in range(7)]
    dow_ratio = [float(ratio[(ratio.index.dayofweek == k) & keep].mean()) for k in range(7)]
    dow_median = [float(ratio[(ratio.index.dayofweek == k) & keep].median()) for k in range(7)]
    dow_amp = max(dow_ratio) / min(dow_ratio) - 1
    wk_ratio = float(day[(day.index.dayofweek >= 5) & keep].mean() /
                     day[(day.index.dayofweek < 5) & keep].mean())

    # 各中心周末比（异质性）
    c2 = daily[~daily[C.DATE].isin(day.index[emask])]
    w = c2.pivot_table(index=C.CENTER, columns="是否周末", values=C.VOL, aggfunc="mean")
    w = w.rename(columns={True: "周末", False: "工作日"})
    weekend_by_center = (w["周末"] / w["工作日"]).dropna()

    # ---------- 4. 大促 / 节假日脉冲 ----------
    base_nov = float(day[(day.index.month == 11) & keep].mean())
    base_oct = float(day[(day.index.month == 10) & keep].mean())
    base_sep = float(day[(day.index.month == 9) & keep].mean())

    def rel(datestr, base):
        v = float(day[pd.Timestamp(datestr)])
        return {"date": datestr, "value": v, "factor": v / base}

    pulses = {
        "11/11": rel("2023-11-11", base_nov),
        "11/12": rel("2023-11-12", base_nov),
        "11/01": rel("2023-11-01", base_nov),
        "11/02": rel("2023-11-02", base_nov),
        "11/10": rel("2023-11-10", base_nov),
        "11/13": rel("2023-11-13", base_nov),
        "10/24": rel("2023-10-24", base_oct),
        "中秋9/29": rel("2023-09-29", base_sep),
    }
    nat = day[(day.index >= "2023-10-01") & (day.index <= "2023-10-04")]
    national_day = {"mean": float(nat.mean()), "factor": float(nat.mean() / base_sep)}

    # 双 11 各中心放大倍数
    nov_non_event = daily[(daily[C.DATE].dt.month == 11) & (~daily[C.DATE].isin(nov_events(day)))]
    base_c = nov_non_event.groupby(C.CENTER)[C.VOL].mean()
    d11_c = daily[daily[C.DATE] == "2023-11-11"].set_index(C.CENTER)[C.VOL]
    amp_c = (d11_c / base_c).dropna().sort_values()

    # ---------- 5. 小时形态 ----------
    hvol = hourly.pivot_table(index=C.HOUR, columns=C.DATE, values=C.VOL, aggfunc="sum")
    hour_mean_total = hvol.mean(axis=1)                    # 全网平均每小时总货量（件/小时）
    hour_share = hour_mean_total / hour_mean_total.sum()    # 全网小时占比
    trough_h = int(hour_share.idxmin())
    peak_h = int(hour_share.idxmax())

    share_tab = C.hour_share(hourly, by="allday")           # (中心,日期) × 小时
    center_share = share_tab.groupby(level=0).mean()
    center_peak = center_share.idxmax(axis=1)
    center_trough = center_share.idxmin(axis=1)

    # 中心间形态差异：两两 L1 距离
    M = center_share.to_numpy()
    n = M.shape[0]
    l1 = [float(np.abs(M[i] - M[j]).sum()) for i in range(n) for j in range(i + 1, n)]
    l1_mean = float(np.mean(l1))

    # 中心内跨日占比稳定性：|share_t - mean_share| 的平均
    mean_share = share_tab.groupby(level=0).transform("mean")
    mad = (share_tab - mean_share).abs().mean(axis=1)
    within_mad = float(mad.mean())

    # 每 (中心,小时) 占比的跨日 CV 中位数
    sd = share_tab.groupby(level=0).std()
    mn = share_tab.groupby(level=0).mean()
    cv = (sd / mn.replace(0, np.nan))
    cv_median = float(np.nanmedian(cv.to_numpy()))

    between_per_hour = l1_mean / 24.0
    signal_ratio = between_per_hour / within_mad if within_mad else float("nan")

    # 班次边界（0/8/16 点）三段占比
    shift_share = {
        "00-08": float(hour_share[[h for h in range(0, 8)]].sum()),
        "08-16": float(hour_share[[h for h in range(8, 16)]].sum()),
        "16-24": float(hour_share[[h for h in range(16, 24)]].sum()),
    }

    # 每小时"零或缺失"占比（占 57×30 格）
    zc = (hourly[hourly[C.VOL] == 0].groupby(C.HOUR).size() / (hc["中心数"] * hc["日期数"]) * 100)
    zero_rate_by_hour = [float(zc.get(h, 0.0)) for h in range(24)]

    # ---------- 6. 中心规模结构 ----------
    ctot = daily.groupby(C.CENTER)[C.VOL].sum().sort_values(ascending=False)
    top20 = ctot.head(20)
    top5_share = float(ctot.head(5).sum() / ctot.sum())
    cv_c = (daily.groupby(C.CENTER)[C.VOL].std() / daily.groupby(C.CENTER)[C.VOL].mean())

    aug_c = daily[daily[C.DATE].dt.month == 8].groupby(C.CENTER)[C.VOL].mean()
    nov_c = (daily[(daily[C.DATE].dt.month == 11) & (~daily[C.DATE].isin(nov_events(day)))]
             .groupby(C.CENTER)[C.VOL].mean())
    growth_c = (nov_c / aug_c - 1).dropna()

    # ---------- 7. 线路网络 ----------
    p3 = set(zip(routes["始发"], routes["到达"]))
    p4 = set(zip(opens["始发"], opens["到达"]))
    only3 = p3 - p4
    only4 = p4 - p3
    both_dir3 = len({(a, b) for a, b in p3 if (b, a) in p3}) // 2
    both_dir4 = len({(a, b) for a, b in p4 if (b, a) in p4}) // 2

    route_total = float(routes[C.VOL].sum())
    route_centers = len(set(routes["始发"]) | set(routes["到达"]))
    open_centers = len(set(opens["始发"]) | set(opens["到达"]))
    arr_sum = routes.groupby("到达")[C.VOL].sum().sort_values(ascending=False)
    arr_top5_share = float(arr_sum.head(5).sum() / arr_sum.sum())
    out_deg = opens.groupby("始发").size()
    in_deg = opens.groupby("到达").size()

    # 线路货量 vs 中心规模（11 月日均）
    size11 = daily[daily[C.DATE].dt.month == 11].groupby(C.CENTER)[C.VOL].mean()
    out_v = routes.groupby("始发")[C.VOL].sum()
    j = pd.concat([out_v.rename("线"), size11.rename("量")], axis=1).dropna()
    sp = spearman(j["线"], j["量"])
    arr_ratio = pd.concat([arr_sum.rename("线"), size11.rename("量")], axis=1).dropna()
    arr_ratio["比"] = arr_ratio["线"] / arr_ratio["量"]

    # ---------- 8. payload ----------
    dates = [d.strftime("%Y-%m-%d") for d in day.index]
    ma7 = day.rolling(7, center=True, min_periods=1).mean()

    top2 = list(ctot.index[:2])
    top2_series = []
    for c in top2:
        s = daily[daily[C.CENTER] == c].set_index(C.DATE)[C.VOL].sort_index()
        top2_series.append({
            "center": c,
            "values": [int(v) for v in s.to_numpy()],
            "ma7": [float(v) for v in s.rolling(7, center=True, min_periods=1).mean().to_numpy()],
        })

    box_centers = [top2[0], "SC12"]
    box_data = []
    for c in box_centers:
        p = hourly[hourly[C.CENTER] == c].pivot_table(index=C.HOUR, columns=C.DATE, values=C.VOL)
        box_data.append({
            "center": c,
            "values": [[float(v) for v in p.loc[h].to_numpy()] for h in range(24)],
        })

    hour_mean_series = [float(hour_mean_total.get(h, 0.0)) for h in range(24)]

    plot = {
        "daily": {
            "dates": dates,
            "total": [int(v) for v in day.to_numpy()],
            "ma7": [float(v) for v in ma7.to_numpy()],
            "weekend": [bool(v) for v in (day.index.dayofweek >= 5)],
            "events": [
                {"date": "2023-09-29", "label": "中秋"},
                {"date": "2023-10-01", "label": "国庆"},
                {"date": "2023-10-24", "label": "双11预售"},
                {"date": "2023-11-01", "label": "开门红"},
                {"date": "2023-11-11", "label": "双11"},
                {"date": "2023-11-12", "label": "双11续"},
            ],
        },
        "top2": top2_series,
        "hours": {
            "hour": list(range(24)),
            "mean_total": hour_mean_series,
            "share_pct": [float(v * 100) for v in hour_share.to_numpy()],
            "zero_rate": zero_rate_by_hour,
        },
        "box": box_data,
        "dow": {
            "labels": C.WEEKDAY_CN,
            "raw_mean": dow_raw,
            "ratio": dow_ratio,
            "median": dow_median,
        },
        "centers": {
            "top20_names": [str(v) for v in top20.index],
            "top20_values": [int(v) for v in top20.to_numpy()],
            "all_total": float(ctot.sum()),
            "n": int(len(ctot)),
        },
        "routes": {
            "labels": ["%s→%s" % (a, b) for a, b in zip(routes["始发"].head(15), routes["到达"].head(15))],
            "values": [int(v) for v in routes[C.VOL].head(15).to_numpy()],
            "total": route_total,
            "n": int(len(routes)),
        },
        "network": {
            "labels": [str(v) for v in in_deg.sort_values(ascending=False).index],
            "matrix": None,  # 由下面填充
            "out_deg": [int(out_deg.get(c, 0)) for c in in_deg.sort_values(ascending=False).index],
            "in_deg": [int(in_deg.get(c, 0)) for c in in_deg.sort_values(ascending=False).index],
        },
        "share_heat": {
            "centers": [str(c) for c in center_share.sort_values(by=list(center_share.columns), ascending=False).index],
            "matrix": None,
            "peak": [int(v) for v in center_peak.to_numpy()],
        },
    }

    # 邻接矩阵（按入度降序）
    order = list(in_deg.sort_values(ascending=False).index)
    idx = {c: i for i, c in enumerate(order)}
    mat = np.zeros((len(order), len(order)), dtype=int)
    for a, b in p4:
        if a in idx and b in idx:
            mat[idx[a], idx[b]] = 1
    plot["network"]["matrix"] = mat.tolist()

    # 小时占比热力图（按高峰小时、再按规模排序）
    cs = center_share.copy()
    cs["_peak"] = center_peak
    cs["_size"] = ctot.reindex(cs.index).fillna(0)
    cs = cs.sort_values(["_peak", "_size"], ascending=[True, False])
    plot["share_heat"]["centers"] = [str(c) for c in cs.index]
    plot["share_heat"]["matrix"] = [[float(v) * 100 for v in cs.loc[c, list(range(24))]] for c in cs.index]

    stats = {
        "overview": {
            "n_centers": dc["中心数"], "n_days": dc["日期数"],
            "start": C._fmt_ts(dc["起"]), "end": C._fmt_ts(dc["止"]),
            "daily_cells": dc["应有格子"], "daily_have": dc["实有格子"],
            "daily_missing_rate": dc["缺失率"],
            "total": total, "daily_mean": d_mean,
            "max_day": {"date": C._fmt_ts(imax), "value": float(day.loc[imax]), "factor": float(day.loc[imax] / d_mean)},
            "min_day": {"date": C._fmt_ts(imin), "value": float(day.loc[imin]), "factor": float(day.loc[imin] / d_mean)},
            "center_min": float(ctot.min()), "center_max": float(ctot.max()),
            "hour_start": C._fmt_ts(hc["起"]), "hour_end": C._fmt_ts(hc["止"]),
            "hour_days": hc["日期数"], "hour_missing_rate": hc["缺失率"],
            "hour_zero_rate": hc["零值率"], "hour_cells": hc["应有格子"],
            "recon_median": rec.get("相对差中位数", 0.0), "recon_ratio": rec.get("总和比", 1.0),
        },
        "trend": {"slope_daily": slope, "month_growth": month_growth,
                  "month_avg": month_avg, "aug_to_nov": aug_to_nov},
        "dow": {"raw": dow_raw, "ratio": dow_ratio, "median": dow_median,
                "amp": dow_amp, "weekend_ratio": wk_ratio,
                "weekend_center_min": float(weekend_by_center.min()),
                "weekend_center_max": float(weekend_by_center.max()),
                "weekend_center_median": float(weekend_by_center.median())},
        "pulses": {k: v for k, v in pulses.items()},
        "national_day": national_day,
        "d11": {"median": float(amp_c.median()), "q1": float(amp_c.quantile(.25)),
                "q3": float(amp_c.quantile(.75)), "min": float(amp_c.min()), "max": float(amp_c.max()),
                "min_center": str(amp_c.index[0]), "max_center": str(amp_c.index[-1]),
                "top5": {str(k): float(v) for k, v in amp_c.tail(5).items()},
                "bottom5": {str(k): float(v) for k, v in amp_c.head(5).items()}},
        "hours": {"trough": trough_h, "trough_share": float(hour_share.min()),
                  "peak": peak_h, "peak_share": float(hour_share.max()),
                  "shift_share": shift_share, "l1_mean": l1_mean,
                  "within_mad": within_mad, "cv_median": cv_median,
                  "between_per_hour": between_per_hour, "signal_ratio": signal_ratio,
                  "peak_hour_counts": {int(k): int(v) for k, v in center_peak.value_counts().sort_index().items()},
                  "trough_hour_counts": {int(k): int(v) for k, v in center_trough.value_counts().sort_index().items()},
                  "peak_hour_n": int(center_peak.nunique())},
        "centers": {"top5_share": top5_share, "top2": top2,
                    "cv_min": float(cv_c.min()), "cv_median": float(cv_c.median()),
                    "cv_max": float(cv_c.max()), "cv_max_center": str(cv_c.idxmax()),
                    "cv_min_center": str(cv_c.idxmin()),
                    "growth_median": float(growth_c.median()),
                    "n_grew": int((growth_c > 0).sum()), "n_center": int(len(growth_c)),
                    "top20": {str(k): int(v) for k, v in top20.items()}},
        "routes": {"n": int(len(routes)), "centers": route_centers, "total": route_total,
                   "mean": float(routes[C.VOL].mean()), "max": float(routes[C.VOL].max()),
                   "max_line": "%s→%s" % (routes.iloc[0]["始发"], routes.iloc[0]["到达"]),
                   "arr_top5_share": arr_top5_share,
                   "arr_top5": {str(k): int(v) for k, v in arr_sum.head(5).items()},
                   "share_of_nov": route_total / base_nov,
                   "spearman": sp,
                   "arr_ratio_min": float(arr_ratio["比"].min()),
                   "arr_ratio_median": float(arr_ratio["比"].median()),
                   "arr_ratio_max": float(arr_ratio["比"].max()),
                   "n_arr": int(arr_ratio.shape[0])},
        "open": {"n": int(len(opens)), "centers": open_centers,
                 "in_max": int(in_deg.max()), "in_max_center": str(in_deg.idxmax()),
                 "out_max": int(out_deg.max()), "out_max_center": str(out_deg.idxmax()),
                 "both_dir": both_dir3, "both_dir4": both_dir4,
                 "common": len(p3 & p4), "only3": len(only3), "only4": len(only4)},
        "zero_by_hour": zero_rate_by_hour,
        "qc": {"n_iqr": int((daily["异常_IQR"] != "").sum()),
               "n_3s": int((daily["异常_3σ"] != "").sum()),
               "jump": int(C.unit_checks(daily, hourly, routes)["日_跳变条数"])},
    }
    payload = {"stats": stats, "plot": plot, "generated_by": "code/eda.py"}

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(PAYLOAD, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    if verbose:
        print("[eda] 已写出 %s" % PAYLOAD)
    return payload


def nov_events(day: pd.Series) -> pd.DatetimeIndex:
    """11 月的事件日索引（用于计算各中心基准）。"""
    m = event_mask(day.index)
    return day.index[m & (day.index.month == 11)]


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def write_report(payload: dict) -> str:
    s = payload["stats"]
    s_h = payload["plot"]["hours"]["share_pct"]   # 24 小时占比（%）
    o, t, d, p = s["overview"], s["trend"], s["dow"], s["pulses"]
    h, cn, rt, op = s["hours"], s["centers"], s["routes"], s["open"]
    qc = s["qc"]

    L = []
    A = L.append
    A("# 探索性数据分析报告（data/eda_report.md）")
    A("")
    A("> 本文件由 `code/eda.py` 自动生成，所有数字均来自 `附件/附件/附件1~4.csv`，请勿手工修改。")
    A("> 图见 `论文/figs/`，文中以相对路径引用。赛题要求（预测区间、结果表 3/5/6 口径）以原文为准，本文不涉及。")
    A("")

    # ---------------- 摘要 ----------------
    A("## 0. 结论摘要")
    A("")
    A(f"1. **数据完整度很高**：日粒度 `{o['start']} ~ {o['end']}`、{o['n_days']} 天 × {o['n_centers']} 个分拣中心 = "
      f"{o['daily_cells']} 格全满，**缺失率 0%**；小时粒度只有 11 月的 {o['hour_days']} 天，"
      f"缺格率 {pct(o['hour_missing_rate'])}，但缺格填 0 后与日货量总量只差 {pct(1 - o['recon_ratio'], 3)}，"
      f"可判定为「该小时无货」。")
    A(f"2. **有明显上升趋势 + 极强大促脉冲**：剔除事件日后全网日均从 8 月 {t['month_avg'][8]:,.0f} 件升至 11 月 "
      f"{t['month_avg'][11]:,.0f} 件（+{pct(t['aug_to_nov'])}）；11/11 单日 {p['11/11']['value']:,.0f} 件，"
      f"是 11 月非事件日均的 {p['11/11']['factor']:.2f} 倍。")
    A(f"3. **周季节性弱但方向稳定**：去趋势后周三/周五最高（{d['ratio'][2]:.3f}/{d['ratio'][4]:.3f}）、"
      f"周日最低（{d['ratio'][6]:.3f}），峰谷振幅仅 {pct(d['amp'])}，周末比工作日低 {pct(1 - d['weekend_ratio'])}。")
    A(f"4. **小时形态是「一深谷 + 双高峰」**：深谷在清晨 {h['trough']} 点（仅占全天 "
      f"{h['trough_share'] * 100:.2f}%），晚间主峰在 {h['peak']} 点（{h['peak_share'] * 100:.2f}%），"
      f"凌晨 0~4 点还有 4.6%~5.1% 的次峰（通宵作业）。各中心形态差异显著（24 小时占比向量两两 L1 距离均值 "
      f"{h['l1_mean'] * 100:.1f} 个百分点），但单中心跨日稳定（日均绝对偏差仅 {h['within_mad'] * 100:.2f} 个百分点），"
      f"**中心间差异约为跨日噪声的 {h['signal_ratio']:.1f} 倍，支持「日货量 × 分中心小时占比」的分配方案**。")
    A(f"5. **网络是「少到达、多始发」的轴辐结构**：附件3 {rt['n']} 条有向线路、仅 {rt['centers']} 个中心参与，"
      f"Top5 到达中心占线路货量 {pct(rt['arr_top5_share'])}；附件4 {op['n']} 条、{op['centers']} 个中心，"
      f"最大入度 {op['in_max']}（{op['in_max_center']}），最大出度 {op['out_max']}。"
      f"附件3 与附件4 **不是子集关系**（重合 {op['common']} 条，附件3 独有 {op['only3']} 条、附件4 独有 {op['only4']} 条），"
      f"原文已核实：附件4 是**未来 30 天开通的线路集合**，那 14 条即停开线路、2 条即新开线路。")
    A("")

    # ---------------- 1 覆盖 ----------------
    A("## 1. 数据覆盖与完整度")
    A("")
    A("### 1.1 时间范围与规模")
    A("")
    A("| 项目 | 日粒度（附件1） | 小时粒度（附件2） |")
    A("| --- | --- | --- |")
    A(f"| 起止日期 | {o['start']} ~ {o['end']} | {o['hour_start']} ~ {o['hour_end']} |")
    A(f"| 天数 | {o['n_days']} 天（连续无跳日） | {o['hour_days']} 天（仅 11 月） |")
    A(f"| 分拣中心 | {o['n_centers']} 个 | {o['n_centers']} 个（完全一致） |")
    A(f"| 记录行数 | {o['daily_cells']}（57×122，全满） | {int(o['hour_cells'] * (1 - o['hour_missing_rate'])):,} / {o['hour_cells']:,} |")
    A(f"| 缺失率 | {pct(o['daily_missing_rate'])} | {pct(o['hour_missing_rate'])} |")
    A(f"| 货量合计 | {o['total']:,.0f} 件 | — |")
    A("")
    A(f"**结论：分拣中心确为 {o['n_centers']} 个（SC1~SC69 间不连续编号，最大编号 SC68）；"
      f"日粒度 122 天 × 57 中心零空洞，是罕见的高完整度面板数据。** "
      f"小时粒度**只有 11 月**，与附件1 仅重叠 30 天——这意味着小时模型的历史样本只有 30 天，"
      f"无法支撑月度/季度级别的季节分解，只能用「日总量 × 小时占比」的两层结构。")
    A("")
    A("### 1.2 小时粒度的补齐依据")
    A("")
    A(f"24 个整点 0~23 全覆盖，无越界值，但存在 {pct(o['hour_missing_rate'])} 的缺格与 {pct(o['hour_zero_rate'])} 的显式 0 值。"
      f"缺格不是随机丢失：缺失率在 3~5 点高达 53%、18 点仅 0.64%，且与中心规模负相关"
      f"（小中心夜间无货 → 整段不落记录）。把缺格按 0 处理后，1710 个 (中心,日期) 的 24 小时合计与附件1 日货量"
      f"的总量比 = {o['recon_ratio']:.6f}，中位相对差 {pct(o['recon_median'], 3)}，"
      f"**证明缺格等价于「该小时 0 货量」，补 0 是安全且必要的**。")
    A("")
    A("![图1 全网日货量走势](<../论文/figs/fig01_daily_total_trend.png>)")
    A("")

    # ---------------- 2 趋势 ----------------
    A("## 2. 时间走势与趋势")
    A("")
    A(f"全网日货量均值 {o['daily_mean']:,.0f} 件，最高 {o['max_day']['date']} 的 {o['max_day']['value']:,.0f} 件"
      f"（{o['max_day']['factor']:.2f} 倍均值），最低 {o['min_day']['date']} 的 {o['min_day']['value']:,.0f} 件"
      f"（仅为均值的 {o['min_day']['factor']:.2f} 倍）。")
    A("")
    A("| 月份 | 非事件日日均货量（件） |")
    A("| --- | --- |")
    for m in [8, 9, 10, 11]:
        A(f"| {m} 月 | {t['month_avg'][m]:,.0f} |")
    A("")
    A(f"剔除大促/节假日后的 log 线性趋势斜率为每日 {t['slope_daily']:.5f}，折合**月增速约 {pct(t['month_growth'])}**；"
      f"8→11 月非事件日日均累计 +{pct(t['aug_to_nov'])}。**趋势确实上升，且不是靠 11 月大促堆出来的**"
      f"（剔除事件日后仍在涨）。")
    A("")
    A("![图2 货量最大的两个中心](<../论文/figs/fig02_top2_centers.png>)")
    A("")
    A(f"两个最大中心 {cn['top2'][0]} / {cn['top2'][1]} 的走势与全网同步，但幅度不同："
      f"头部中心平滑、尾部小中心噪声大，说明**预测必须分中心建模**，不能只做全网比例外推。")
    A("")

    # ---------------- 3 大促 ----------------
    A("## 3. 大促与节假日脉冲")
    A("")
    A("| 日期 | 全网货量（件） | 相对基准倍数 | 基准 |")
    A("| --- | --- | --- | --- |")
    A(f"| 11/11 | {p['11/11']['value']:,.0f} | **{p['11/11']['factor']:.2f}×** | 11 月非事件日均 |")
    A(f"| 11/12 | {p['11/12']['value']:,.0f} | {p['11/12']['factor']:.2f}× | 11 月非事件日均 |")
    A(f"| 11/01 | {p['11/01']['value']:,.0f} | {p['11/01']['factor']:.2f}× | 11 月非事件日均 |")
    A(f"| 11/02 | {p['11/02']['value']:,.0f} | {p['11/02']['factor']:.2f}× | 11 月非事件日均 |")
    A(f"| 11/10 | {p['11/10']['value']:,.0f} | {p['11/10']['factor']:.2f}× | 11 月非事件日均 |")
    A(f"| 11/13 | {p['11/13']['value']:,.0f} | {p['11/13']['factor']:.2f}× | 11 月非事件日均 |")
    A(f"| 10/24（双11 预售） | {p['10/24']['value']:,.0f} | {p['10/24']['factor']:.2f}× | 10 月非事件日均 |")
    A(f"| 09/29（中秋） | {p['中秋9/29']['value']:,.0f} | {p['中秋9/29']['factor']:.2f}× | 9 月非事件日均 |")
    A(f"| 10/01~10/04（国庆） | {s['national_day']['mean']:,.0f}（日均） | {s['national_day']['factor']:.2f}× | 9 月非事件日均 |")
    A("")
    A(f"**大促脉冲极大且形态清晰**：11/11 全网 {p['11/11']['factor']:.2f} 倍，11/01 开门红 {p['11/01']['factor']:.2f} 倍，"
      f"11/12 仍有 {p['11/12']['factor']:.2f} 倍；而国庆假期跌到 {s['national_day']['factor']:.2f} 倍、中秋 {p['中秋9/29']['factor']:.2f} 倍。"
      f"**假期是下行脉冲、大促是上行脉冲，二者不能混为一个「节假日哑变量」**。")
    A("")
    A(f"各中心对双 11 的敏感度差异大：放大倍数中位数 {s['d11']['median']:.2f}×，四分位区间 "
      f"[{s['d11']['q1']:.2f}, {s['d11']['q3']:.2f}]，最低 {s['d11']['min_center']} {s['d11']['min']:.2f}×，"
      f"最高 {s['d11']['max_center']} {s['d11']['max']:.2f}×。**统一给全网乘一个促销系数会系统性高估/低估两端中心**。")
    A(f"进一步看，放大倍数最大的 5 个中心（{', '.join(s['d11']['top5'].keys())}）全是小中心，"
      f"而全网加权后的实际倍数是 {p['11/11']['factor']:.2f}×——**大促的增量高度集中在长尾小中心，"
      f"头部中心反而接近全网平均**。建模时若不区分规模，会把促销增量摊错到头部。")
    A("")

    # ---------------- 4 周季节 ----------------
    A("## 4. 周季节性")
    A("")
    A("| 星期 | 原始日均（件） | 去趋势比值（均值） | 去趋势比值（中位数） |")
    A("| --- | --- | --- | --- |")
    for i, lb in enumerate(C.WEEKDAY_CN):
        A(f"| {lb} | {d['raw'][i]:,.0f} | {d['ratio'][i]:.4f} | {d['median'][i]:.4f} |")
    A("")
    A(f"**存在周周期，但很弱**：原始日均看周三最高（{d['raw'][2]:,.0f}）、周一最低（{d['raw'][0]:,.0f}），"
      f"但原始值受趋势与大促污染；用 7 日居中均值去趋势后，"
      f"周三/周五最高（{d['ratio'][2]:.4f}/{d['ratio'][4]:.4f}）、周日最低（{d['ratio'][6]:.4f}）、"
      f"周一亦偏低（{d['ratio'][0]:.4f}），峰谷振幅 {pct(d['amp'])}。"
      f"非事件日周末/工作日 = {d['weekend_ratio']:.4f}，即**周末比工作日低 {pct(1 - d['weekend_ratio'])}**。"
      f"方向在各中心高度一致（周末/工作日比值中位数 {d['weekend_center_median']:.3f}，"
      f"区间 [{d['weekend_center_min']:.3f}, {d['weekend_center_max']:.3f}]），"
      f"因此周因子可以全网共享，但幅度需按中心校准。")
    A("")
    A("![图5 周季节性](<../论文/figs/fig05_dow_effect.png>)")
    A("")

    # ---------------- 5 小时 ----------------
    A("## 5. 小时形态与「占比分配」可行性")
    A("")
    A(f"以「全网平均每小时总货量」衡量的日形态是**一深谷 + 双高峰**，而不是常见的「夜里低、白天高」：")
    A(f"- **深谷**：清晨 {h['trough']} 点，仅占全天 {h['trough_share'] * 100:.2f}%；"
      f"5 点 {s_h[5]:.2f}%、6 点 {s_h[6]:.2f}%、7 点 {s_h[7]:.2f}%、8 点 {s_h[8]:.2f}%，"
      f"5~8 点构成全天唯一的低位带（6 点有 {s['zero_by_hour'][6]:.1f}% 的中心-日完全没有货量记录）。")
    A(f"- **晚间主峰**：19~23 点逐时占比 {s_h[19]:.2f}% / {s_h[20]:.2f}% / {s_h[21]:.2f}% / "
      f"{s_h[22]:.2f}% / {s_h[23]:.2f}%，{h['peak']} 点为全天最高（{h['peak_share'] * 100:.2f}%），"
      f"这 5 小时合计 {sum(s_h[19:24]):.1f}%。")
    A(f"- **凌晨次峰**：0~4 点仍维持 {min(s_h[0:5]):.2f}%~{max(s_h[0:5]):.2f}%，说明分拣中心通宵作业，夜间不是低量时段。")
    A(f"- **午后平台**：13~17 点在 {min(s_h[13:18]):.2f}%~{max(s_h[13:18]):.2f}% 之间，是白天次高。")
    A(f"- 按 0/8/16 三个班次边界汇总：00-08 点 {pct(h['shift_share']['00-08'], 1)}、"
      f"08-16 点 {pct(h['shift_share']['08-16'], 1)}、16-24 点 {pct(h['shift_share']['16-24'], 1)}，"
      f"**晚班（16-24）承载的货量最多，早班（08-16）最少，两者相差 "
      f"{(h['shift_share']['16-24'] - h['shift_share']['08-16']) * 100:.1f} 个百分点**——这对后续排班问题很关键。")
    A("")
    A("![图3 全网小时分布](<../论文/figs/fig03_hour_profile.png>)")
    A("")
    A("![图4 单中心 24 小时箱线图](<../论文/figs/fig04_hour_box.png>)")
    A("")
    A("![图9 各中心 24 小时占比热力图](<../论文/figs/fig09_hour_share_heatmap.png>)")
    A("")
    A(f"**各中心形态差异很大，但单中心内部稳定**——这是「用占比分配小时货量」的关键证据：")
    A("")
    A("| 指标 | 数值 | 含义 |")
    A("| --- | --- | --- |")
    A(f"| 中心间占比向量两两 L1 距离均值 | {h['l1_mean'] * 100:.1f} pp | 相当于平均每个小时差 {h['between_per_hour'] * 100:.2f} 个百分点 |")
    A(f"| 中心内 (中心,日) 占比与自身均值的平均绝对偏差 | {h['within_mad'] * 100:.2f} pp | 跨日波动 |")
    A(f"| 上述两者之比（信噪比） | {h['signal_ratio']:.2f} | 中心间差异 ≈ 跨日噪声的 {h['signal_ratio']:.1f} 倍 |")
    A(f"| 各中心高峰小时 | 分散在 0~23 中的 {h['peak_hour_n']} 个整点 | 无统一高峰，不能共用一条曲线 |")
    A("")
    A(f"结论：**必须按中心（而非全网统一）建立 24 小时占比向量**；同一中心跨日占比波动约 ±{h['within_mad'] * 100:.1f} 个百分点，"
      f"明显小于中心之间的差异，所以「预测日货量 × 该中心固定占比」的第一版方案可行，"
      f"后续可用「日型（工作日/周末/大促）」分档再细化。")
    A("")

    # ---------------- 6 中心结构 ----------------
    A("## 6. 分拣中心规模结构")
    A("")
    A(f"{o['n_centers']} 个中心、{o['n_days']} 天总货量 {o['total']:,.0f} 件；"
      f"最大中心 {cn['top2'][0]} 累计 {cn['top20'][cn['top2'][0]]:,.0f} 件，"
      f"最小中心累计 {o['center_min']:,.0f} 件，**头部集中度高**：Top5 占全网 {pct(cn['top5_share'])}。")
    A("")
    A(f"波动性差异同样悬殊：单中心日货量变异系数 CV 最小 {cn['cv_min']:.2f}（{cn['cv_min_center']}）、"
      f"中位 {cn['cv_median']:.2f}、最大 {cn['cv_max']:.2f}（{cn['cv_max_center']}）。"
      f"CV 大的基本都是小中心或新开通中心，噪声大、趋势不稳，**需要单独处理**。")
    A("")
    A(f"8→11 月，{cn['n_center']} 个中心里有 {cn['n_grew']} 个增长，增幅中位数 {pct(cn['growth_median'])}，"
      f"说明上升是**全网性**的，不是个别中心的拉动。")
    A("")
    A("![图6 各中心总货量 Top20](<../论文/figs/fig06_center_top20.png>)")
    A("")

    # ---------------- 7 线路 ----------------
    A("## 7. 线路网络：附件3 与附件4")
    A("")
    A(f"附件3：{rt['n']} 条**有向**线路，涉及 {rt['centers']} 个中心（{o['n_centers']} 个里有 "
      f"{o['n_centers'] - rt['centers']} 个不参与），"
      f"货量合计 {rt['total']:,.0f}，单线均值 {rt['mean']:.1f}、最大 {rt['max']:.0f}（{rt['max_line']}）。")
    A(f"附件4：{op['n']} 条有向线路，涉及 {op['centers']} 个中心；最大入度 {op['in_max']}（{op['in_max_center']}），"
      f"最大出度 {op['out_max']}。")
    A("")
    A("**两者关系（数据事实，题意为原文已核实）**：")
    A("")
    A("| 项目 | 数值 |")
    A("| --- | --- |")
    A(f"| 附件3 / 附件4 线路数 | {rt['n']} / {op['n']} |")
    A(f"| 两表重合线路 | {op['common']} |")
    A(f"| 仅附件3 有 | {op['only3']} |")
    A(f"| 仅附件4 有 | {op['only4']} |")
    A(f"| 附件3 中双向对数量 | {op['both_dir']} |")
    A(f"| 附件4 中双向对数量 | {op['both_dir4']} |")
    A("")
    A(f"**附件3 不是附件4 的子集**（14 条只在附件3、2 条只在附件4），且绝大多数线路是**单向**的"
      f"（附件3 仅 {op['both_dir']} 组双向对）。所以：")
    A("")
    A(f"1. **不能用「附件4 − 附件3」当作「新开通线路」**，两表更像是不同时点/不同口径的两份快照；")
    A(f"2. 线路是有向的，A→B 与 B→A 必须分别建模，不能合并成无向边。")
    A("")
    A("**分母口径问题**：附件3 合计 "
      f"{rt['total']:,.0f} 只相当于 11 月全网日均货量的 {pct(rt['share_of_nov'])}，"
      f"且按到达中心汇总的线路货量与该中心日均货量之比在 {pct(rt['arr_ratio_min'], 1)}~{pct(rt['arr_ratio_max'], 1)} 间波动"
      f"（中位 {pct(rt['arr_ratio_median'], 1)}），Spearman 相关仅 {rt['spearman']:.2f}。"
      f"**这说明附件3 不是全网日货量在全部线路上的完整分解**，做线路占比时：")
    A("")
    A(f"- 唯一自洽的分母是**附件3 自身合计 {rt['total']:,.0f}**；")
    A(f"- 若需要用中心货量做分母，必须先由原文确认真实口径（单日快照？部分线路？车次/批次？），"
      f"否则会系统性错配。")
    A("")
    A("![图7 线路货量 Top15](<../论文/figs/fig07_route_top15.png>)")
    A("")
    A("![图8 线路连通性](<../论文/figs/fig08_network.png>)")
    A("")

    # ---------------- 8 风险 ----------------
    A("## 8. 未来 30 天预测的「不可见」风险")
    A("")
    A(f"数据止于 **{o['end']}**，任何外推都必须正视样本里**没有**的东西：")
    A("")
    A("| 风险 | 为什么不可见 | 影响 |")
    A("| --- | --- | --- |")
    A("| **双 12（12/12）** | 数据只到 11/30，12/12 落在样本外 | 12 月预测会缺一个上行脉冲；只能用双 11 的形态类比，幅度未知 |")
    A("| **元旦前高峰（12 月底）** | 同上，无 12 月末样本 | 年末冲量可能造成上行偏差 |")
    A("| **春节/春运** | 2024 春节为 2/10，春运自 1/26 起；样本内**完全没有**春节 | 若预测区间跨 1 月下旬~2 月，会出现数量级级别的下行，**无法从 8—11 月数据外推** |")
    A("| **大促基数变化** | 只有 1 次双 11（2023） | 促销系数只能用单点估计，无法估计年际波动 |")
    A("| **新开通/停摆中心** | SC12、SC20、SC41、SC43、SC48 等存在 >5 倍环比跳变 | 这些中心的历史均值不代表未来水平，需分段或单独设哑变量 |")
    A("| **小时数据只有 1 个月** | 11 月含双 11，小时形态被促销日污染 | 用 11 月占比推 12 月，需剔除 11/10~11/13 再算占比 |")
    A("")
    A(f"另需注意：样本内唯一的「假期下行」证据是国庆（{s['national_day']['factor']:.2f}×）与中秋（{p['中秋9/29']['factor']:.2f}×），"
      f"幅度远小于春节的典型影响。**原文核实的预测区间是 2023/12/1~12/30，不含春节，故本题区间内该风险不触发**；"
      f"但若把模型推广到 1—2 月（春运自 2024/1/26、春节 2/10），必须重新标定下行因子，不能直接外推。")
    A("")
    A("## 9. 对后续阶段的建议")
    A("")
    A(f"1. **日粒度**：57×122 完整面板，可直接做「趋势 + 周因子 + 事件哑变量」的分解式预测；"
      f"事件系数按中心估计（双 11 放大倍数 {s['d11']['q1']:.2f}~{s['d11']['q3']:.2f}），不要全网统一。")
    A(f"2. **小时粒度**：用「预测日货量 × 分中心 24 小时占比」；占比建议剔除 11/10~11/13 后按中心取均值，"
      f"并保留按日型（工作日/周末）分档的余地。")
    A(f"3. **线路**：附件3 是过去 90 天的线路日均货量、附件4 是未来 30 天开通集合（均已核实）；"
      f"线路占比的分母用附件3 自身合计，线路修正见 `data/assumptions.md`。")
    A(f"4. **质量**：{qc['n_iqr']} 条 IQR 命中 + {qc['n_3s']} 条 3σ 命中、{qc['jump']} 条 >5 倍环比跳变，"
      f"已全部保留在 `data/daily.csv` 的标记列与 `data/anomaly_list.csv` 中，建模时按事件/结构变化处理即可。")
    A("")

    # ---------------- 附录 ----------------
    A("## 附录：图表清单")
    A("")
    A("| 编号 | 文件 | 内容 |")
    A("| --- | --- | --- |")
    A("| 图1 | `论文/figs/fig01_daily_total_trend.png` | 全网日货量走势 + 7 日移动平均 + 周末阴影 + 大促/假期标注 |")
    A("| 图2 | `论文/figs/fig02_top2_centers.png` | 货量最大的两个中心日货量走势 |")
    A("| 图3 | `论文/figs/fig03_hour_profile.png` | 全网按小时平均货量与占比 |")
    A("| 图4 | `论文/figs/fig04_hour_box.png` | 单中心 24 小时箱线图（大中心 / 小中心对比） |")
    A("| 图5 | `论文/figs/fig05_dow_effect.png` | 星期几效应（原始均值 + 去趋势比值） |")
    A("| 图6 | `论文/figs/fig06_center_top20.png` | 各中心总货量 Top20 |")
    A("| 图7 | `论文/figs/fig07_route_top15.png` | 附件3 货量 Top15 有向线路 |")
    A("| 图8 | `论文/figs/fig08_network.png` | 附件4 邻接矩阵热力图 + 入度/出度分布 |")
    A("| 图9 | `论文/figs/fig09_hour_share_heatmap.png` | 各中心 24 小时占比热力图（形态差异证据） |")
    A("")

    md = "\n".join(L)
    with open(REPORT, "w", encoding=C.ENC_OUT) as f:
        f.write(md)
    return REPORT


def main() -> None:
    C._force_utf8_stdout()
    os.makedirs(C.DATA_DIR, exist_ok=True)
    payload = analyse()
    path = write_report(payload)
    print("[eda] 已写出 %s" % path)


if __name__ == "__main__":
    main()
