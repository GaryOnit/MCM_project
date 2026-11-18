# -*- coding: utf-8 -*-
"""
plot_figs.py —— 出图脚本（Phase A 第 3 项）

只依赖 matplotlib + 标准库：读取 code/eda.py 生成的 data/eda_payload.json，
把 9 张 300dpi 中文图写到 论文/figs/。

用系统 python 运行（已装 matplotlib）：
    python code/plot_figs.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
import matplotlib.dates as mdates                    # noqa: E402
from matplotlib.ticker import FuncFormatter           # noqa: E402

matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun"]
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.rcParams["figure.dpi"] = 110
matplotlib.rcParams["savefig.dpi"] = 300
matplotlib.rcParams["axes.edgecolor"] = "#555555"
matplotlib.rcParams["axes.linewidth"] = 0.8

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAYLOAD = os.path.join(ROOT, "data", "eda_payload.json")
FIG_DIR = os.path.join(ROOT, "论文", "figs")

C_MAIN = "#1f4e79"
C_ACC = "#c00000"
C_BAR = "#4a7ebb"
C_BAR2 = "#9dc3e6"
C_GREY = "#7f7f7f"


def _utf8() -> None:
    for st in (sys.stdout, sys.stderr):
        try:
            if hasattr(st, "reconfigure"):
                st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def wan(x, pos=None):
    return "%.1f" % (x / 1e4)


def style(ax, grid_axis="y"):
    ax.grid(axis=grid_axis, alpha=0.25, linestyle=":", linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def footnote(fig, text, y=0.01):
    fig.text(0.012, y, text, fontsize=8, color="#666666", ha="left", va="bottom")


def save(fig, name):
    os.makedirs(FIG_DIR, exist_ok=True)
    path = os.path.join(FIG_DIR, name)
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("[plot] %s" % path)
    return path


# --------------------------------------------------------------------------- #
# 图1 全网日货量走势
# --------------------------------------------------------------------------- #
def fig01(p):
    d = p["plot"]["daily"]
    dates = [datetime.strptime(x, "%Y-%m-%d") for x in d["dates"]]
    total = d["total"]
    ma7 = d["ma7"]
    wk = d["weekend"]

    fig, ax = plt.subplots(figsize=(12.4, 5.4))
    # 周末阴影（连续周末合并）
    i = 0
    while i < len(dates):
        if wk[i]:
            j = i
            while j + 1 < len(dates) and wk[j + 1]:
                j += 1
            ax.axvspan(dates[i], dates[j], color="#eeeeee", zorder=0, linewidth=0)
            i = j + 1
        else:
            i += 1

    ax.plot(dates, total, color=C_BAR2, linewidth=1.2, label="日货量", zorder=2)
    ax.plot(dates, ma7, color=C_MAIN, linewidth=2.4, label="7 日居中移动平均", zorder=3)

    ymax = max(total) * 1.08
    k = 0
    for e in d["events"]:
        if e["label"] == "双11续":
            continue
        x = datetime.strptime(e["date"], "%Y-%m-%d")
        ax.axvline(x, color=C_ACC, linestyle="--", linewidth=1.0, alpha=0.75, zorder=1)
        ax.text(x, ymax * (0.995 if k % 2 == 0 else 0.90), " " + e["label"], rotation=90,
                va="top", ha="left", fontsize=9, color=C_ACC)
        k += 1
    ax.set_ylim(0, ymax)

    ax.set_title("全网 57 个分拣中心日货量走势（2023-08-01 ~ 2023-11-30）",
                 fontsize=14, pad=12)
    ax.set_xlabel("日期")
    ax.set_ylabel("日货量（万件）")
    ax.yaxis.set_major_formatter(FuncFormatter(wan))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval=7))
    style(ax)
    ax.legend(loc="upper left", frameon=False, fontsize=10)
    footnote(fig, "注：灰色阴影为周末；红色虚线为大促/节假日；灰色细线为原始日货量，深蓝粗线为 7 日居中移动平均。"
                  "双 12（12/12）超出数据覆盖范围，无法标注。")
    fig.subplots_adjust(bottom=0.16)
    return save(fig, "fig01_daily_total_trend.png")


# --------------------------------------------------------------------------- #
# 图2 最大两个中心
# --------------------------------------------------------------------------- #
def fig02(p):
    series = p["plot"]["top2"]
    dates = [datetime.strptime(x, "%Y-%m-%d") for x in p["plot"]["daily"]["dates"]]
    fig, axes = plt.subplots(len(series), 1, figsize=(12.4, 3.2 * len(series)), sharex=True)
    if len(series) == 1:
        axes = [axes]
    for ax, s in zip(axes, series):
        ax.plot(dates, s["values"], color=C_BAR2, linewidth=1.1, label="日货量")
        ax.plot(dates, s["ma7"], color=C_MAIN, linewidth=2.2, label="7 日移动平均")
        ax.set_title("%s  日货量（累计 %.2f 万件）" % (s["center"], sum(s["values"]) / 1e4),
                     fontsize=12, loc="left")
        ax.set_ylabel("件/日")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: format(v, ",.0f")))
        style(ax)
        ax.legend(loc="upper left", frameon=False, fontsize=9)
    axes[0].set_title("货量最大的两个分拣中心日货量走势\n" + axes[0].get_title(),
                      fontsize=13)
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axes[-1].set_xlabel("日期")
    footnote(fig, "注：灰线为原始日货量，深蓝线为 7 日居中移动平均；两中心分别为全网累计货量第 1、第 2 名。")
    fig.subplots_adjust(bottom=0.12, hspace=0.35)
    return save(fig, "fig02_top2_centers.png")


# --------------------------------------------------------------------------- #
# 图3 小时分布
# --------------------------------------------------------------------------- #
def fig03(p):
    h = p["plot"]["hours"]
    hours = h["hour"]
    mean_total = h["mean_total"]
    share = h["share_pct"]

    fig, ax = plt.subplots(figsize=(11.2, 5.0))
    colors = [C_ACC if s == max(share) else (C_GREY if s == min(share) else C_BAR) for s in share]
    bars = ax.bar(hours, mean_total, color=colors, width=0.72, label="平均每小时总货量")
    for x, v, s in zip(hours, mean_total, share):
        ax.text(x, v * 1.02, "%.1f%%" % s, ha="center", va="bottom", fontsize=7.4,
                color=(C_ACC if s == max(share) else "#444444"))
    ax.set_xlabel("小时（0~23）")
    ax.set_ylabel("全网平均每小时总货量（件/小时）")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: format(v, ",.0f")))
    ax.set_xticks(hours)
    ax.set_ylim(0, max(mean_total) * 1.15)
    style(ax)

    ax2 = ax.twinx()
    ax2.plot(hours, share, color=C_MAIN, marker="o", markersize=3.2, linewidth=1.3,
             label="占全天比重")
    ax2.set_ylabel("占全天货量比重（%）")
    ax2.set_ylim(0, max(share) * 1.25)
    ax2.spines["top"].set_visible(False)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False, fontsize=9)
    ax.set_title("全网分拣中心按小时的平均货量与占比（2023-11-01 ~ 2023-11-30）",
                 fontsize=13.5, pad=10)
    footnote(fig, "注：柱高为 30 天平均的每小时全网总货量；红色柱为占比最高的小时（21 点），灰色柱为最低的小时（6 点）；"
                  "折线为各小时占全天货量的比重。")
    fig.subplots_adjust(bottom=0.16)
    return save(fig, "fig03_hour_profile.png")


# --------------------------------------------------------------------------- #
# 图4 单中心 24 小时箱线图
# --------------------------------------------------------------------------- #
def fig04(p):
    boxes = p["plot"]["box"]
    fig, axes = plt.subplots(1, len(boxes), figsize=(12.6, 5.0))
    if len(boxes) == 1:
        axes = [axes]
    for ax, b in zip(axes, boxes):
        bp = ax.boxplot(b["values"], positions=list(range(24)), widths=0.62,
                        patch_artist=True, showfliers=True,
                        flierprops=dict(marker="o", markersize=2.4, markerfacecolor="#999999",
                                        markeredgecolor="none", alpha=0.7),
                        medianprops=dict(color=C_ACC, linewidth=1.4),
                        boxprops=dict(facecolor=C_BAR2, edgecolor=C_MAIN, linewidth=0.7),
                        whiskerprops=dict(color=C_MAIN, linewidth=0.7),
                        capprops=dict(color=C_MAIN, linewidth=0.7))
        ax.set_xticks(list(range(24)))
        ax.set_xticklabels([str(i) for i in range(24)], fontsize=7.5)
        ax.set_xlabel("小时（0~23）")
        ax.set_ylabel("小时货量（件）")
        ax.set_title("%s（30 天 × 24 小时）" % b["center"], fontsize=11.5)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: format(v, ",.0f")))
        style(ax)
    fig.suptitle("单中心 24 小时货量箱线图：左为最大中心、右为形态差异大的小中心",
                 fontsize=13, y=1.0)
    footnote(fig, "注：箱体为上四分位~下四分位，红线为中位数，须为 1.5×IQR，圆点为离群日；"
                  "左图可见「夜间高位 + 清晨深谷 + 晚间抬升」，右图小中心大量小时为 0（本就无货），"
                  "可直观看到「中心间形态不同、中心内跨日稳定」。")
    fig.subplots_adjust(bottom=0.17, wspace=0.22, top=0.86)
    return save(fig, "fig04_hour_box.png")


# --------------------------------------------------------------------------- #
# 图5 周季节性
# --------------------------------------------------------------------------- #
def fig05(p):
    d = p["plot"]["dow"]
    x = list(range(7))
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.4))

    ax = axes[0]
    bars = ax.bar(x, d["raw_mean"], color=C_BAR, width=0.66)
    for b, v in zip(bars, d["raw_mean"]):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.005, "%.1f" % (v / 1e4),
                ha="center", va="bottom", fontsize=8.4)
    ax.set_xticks(x)
    ax.set_xticklabels(d["labels"])
    ax.set_ylabel("日货量（万件）")
    ax.set_ylim(0, max(d["raw_mean"]) * 1.12)
    ax.set_title("(a) 各星期几的原始日均货量", fontsize=11.5)
    style(ax)

    ax = axes[1]
    colors = [C_ACC if v == max(d["ratio"]) else (C_GREY if v == min(d["ratio"]) else C_BAR)
              for v in d["ratio"]]
    bars = ax.bar(x, d["ratio"], color=colors, width=0.66)
    ax.axhline(1.0, color="#333333", linewidth=1.0, linestyle="--")
    for b, v in zip(bars, d["ratio"]):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.004, "%.3f" % v,
                ha="center", va="bottom", fontsize=8.4)
    ax.set_xticks(x)
    ax.set_xticklabels(d["labels"])
    ax.set_ylabel("去趋势比值（当日 / 7 日居中均值）")
    ax.set_ylim(min(d["ratio"]) * 0.965, max(d["ratio"]) * 1.03)
    ax.set_title("(b) 剔除趋势后的星期几效应", fontsize=11.5)
    style(ax)

    fig.suptitle("周季节性：周三/周五偏高、周日最低（振幅约 9%）", fontsize=13.5, y=1.0)
    footnote(fig, "注：左图原始均值受趋势与大促污染，仅作参照；右图用 7 日居中移动平均去趋势，已剔除大促/节假日，"
                  "红色为最高、灰色为最低。")
    fig.subplots_adjust(bottom=0.17, wspace=0.25, top=0.86)
    return save(fig, "fig05_dow_effect.png")


# --------------------------------------------------------------------------- #
# 图6 中心 Top20
# --------------------------------------------------------------------------- #
def fig06(p):
    c = p["plot"]["centers"]
    names = c["top20_names"]
    vals = c["top20_values"]
    share = [v / c["all_total"] * 100 for v in vals]

    fig, ax = plt.subplots(figsize=(9.6, 7.4))
    y = list(range(len(names)))[::-1]
    bars = ax.barh(y, vals, color=C_BAR, height=0.68)
    for yy, v, sh in zip(y, vals, share):
        ax.text(v * 1.01, yy, "%.2f 万件 (%.1f%%)" % (v / 1e4, sh), va="center", fontsize=8.4)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9.5)
    ax.set_xlabel("累计货量（件，2023-08-01 ~ 2023-11-30）")
    ax.set_xlim(0, max(vals) * 1.22)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: format(v, ",.0f")))
    ax.set_title("各分拣中心累计货量 Top20（括号内为占全网比重）", fontsize=13.5, pad=10)
    style(ax, grid_axis="x")
    footnote(fig, "注：全网 57 个中心累计 %s 件；Top5 合计占 %.1f%%，头部集中度较高。"
             % ("{:,.0f}".format(c["all_total"]), sum(share[:5])))
    fig.subplots_adjust(bottom=0.12, left=0.12)
    return save(fig, "fig06_center_top20.png")


# --------------------------------------------------------------------------- #
# 图7 线路 Top15
# --------------------------------------------------------------------------- #
def fig07(p):
    r = p["plot"]["routes"]
    labels = r["labels"]
    vals = r["values"]
    share = [v / r["total"] * 100 for v in vals]

    fig, ax = plt.subplots(figsize=(9.4, 6.4))
    y = list(range(len(labels)))[::-1]
    ax.barh(y, vals, color=C_BAR, height=0.68)
    for yy, v, sh in zip(y, vals, share):
        ax.text(v + max(vals) * 0.012, yy, "%d 件 (%.1f%%)" % (v, sh), va="center", fontsize=8.4)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9.5)
    ax.set_xlabel("线路货量（件）")
    ax.set_xlim(0, max(vals) * 1.3)
    ax.set_title("附件3 货量 Top15 有向线路（共 %d 条，合计 %s 件）"
                 % (r["n"], "{:,.0f}".format(r["total"])), fontsize=13, pad=10)
    style(ax, grid_axis="x")
    footnote(fig, "注：按「始发分拣中心→到达分拣中心」的有向线路排序；括号内为该线路占附件3 总货量的比重"
                  "（分母=附件3 自身合计 %s 件）。" % "{:,.0f}".format(r["total"]))
    fig.subplots_adjust(bottom=0.14, left=0.14)
    return save(fig, "fig07_route_top15.png")


# --------------------------------------------------------------------------- #
# 图8 连通性
# --------------------------------------------------------------------------- #
def fig08(p):
    nw = p["plot"]["network"]
    labels = nw["labels"]
    mat = nw["matrix"]
    outd = nw["out_deg"]
    ind = nw["in_deg"]

    fig = plt.figure(figsize=(13.4, 6.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1], wspace=0.28)

    ax = fig.add_subplot(gs[0, 0])
    im = ax.imshow(mat, cmap="Blues", interpolation="nearest", aspect="equal")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=90, fontsize=5.6)
    ax.set_yticklabels(labels, fontsize=5.6)
    ax.set_xlabel("到达分拣中心")
    ax.set_ylabel("始发分拣中心")
    ax.set_title("(a) 附件4 邻接矩阵（行=始发，列=到达，深色=有线路）", fontsize=11)
    cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
    cb.set_ticks([0, 1])
    cb.set_ticklabels(["无", "有"])

    ax2 = fig.add_subplot(gs[0, 1])
    k = 15
    idx = list(range(k))
    y = list(range(k))[::-1]
    ax2.barh([yy + 0.19 for yy in y], ind[:k], height=0.36, color=C_ACC, label="入度（接收）")
    ax2.barh([yy - 0.19 for yy in y], outd[:k], height=0.36, color=C_BAR, label="出度（发出）")
    ax2.set_yticks(y)
    ax2.set_yticklabels(labels[:k], fontsize=8.6)
    ax2.set_xlabel("线路条数")
    ax2.set_title("(b) 入度 Top15 中心的出/入度", fontsize=11)
    ax2.legend(frameon=False, fontsize=9, loc="lower right")
    style(ax2, grid_axis="x")

    fig.suptitle("附件4 线路连通性：轴辐结构（少数到达枢纽 + 大量始发节点）", fontsize=13.5, y=0.99)
    footnote(fig, "注：附件4 共 %d 条有向线路、%d 个中心；最大入度 %d（%s），最大出度 %d。"
                  "矩阵按入度降序排列。"
             % (p["stats"]["open"]["n"], p["stats"]["open"]["centers"],
                p["stats"]["open"]["in_max"], p["stats"]["open"]["in_max_center"],
                p["stats"]["open"]["out_max"]))
    fig.subplots_adjust(bottom=0.14, top=0.90, left=0.08, right=0.97)
    return save(fig, "fig08_network.png")


# --------------------------------------------------------------------------- #
# 图9 小时占比热力图
# --------------------------------------------------------------------------- #
def fig09(p):
    sh = p["plot"]["share_heat"]
    centers = sh["centers"]
    mat = sh["matrix"]
    n = len(centers)

    fig, ax = plt.subplots(figsize=(10.6, 12.4))
    im = ax.imshow(mat, cmap="YlGnBu", aspect="auto", interpolation="nearest")
    ax.set_xticks(range(24))
    ax.set_xticklabels([str(i) for i in range(24)], fontsize=8)
    ax.set_yticks(range(n))
    ax.set_yticklabels(centers, fontsize=5.8)
    ax.set_xlabel("小时（0~23）")
    ax.set_ylabel("分拣中心（按高峰小时、再按规模排序）")
    ax.set_title("各分拣中心 24 小时货量占比（%），形态差异一目了然", fontsize=13.5, pad=10)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("占该中心全天货量比重（%）", fontsize=9)
    footnote(fig, "注：每行是一个中心的小时占比向量（30 天均值，缺格按 0 计）。行间颜色分布差异大 = 中心间形态不同；"
                  "行内即使相邻也很少跳变 = 单中心跨日稳定。")
    fig.subplots_adjust(bottom=0.08, left=0.13, right=0.93, top=0.95)
    return save(fig, "fig09_hour_share_heatmap.png")


# --------------------------------------------------------------------------- #
def main() -> None:
    _utf8()
    if not os.path.exists(PAYLOAD):
        raise SystemExit("找不到 %s，请先运行 python code/eda.py" % PAYLOAD)
    with open(PAYLOAD, "r", encoding="utf-8") as f:
        payload = json.load(f)

    os.makedirs(FIG_DIR, exist_ok=True)
    outputs = [fig01(payload), fig02(payload), fig03(payload), fig04(payload),
               fig05(payload), fig06(payload), fig07(payload), fig08(payload),
               fig09(payload)]
    print("[plot] 共生成 %d 张图 → %s" % (len(outputs), FIG_DIR))


if __name__ == "__main__":
    main()


