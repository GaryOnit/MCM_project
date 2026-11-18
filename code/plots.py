# -*- coding: utf-8 -*-
"""
plots.py —— Phase B 论文配图（读取 data/*.json，不依赖 pandas）

    python code/plots.py      （系统 python + matplotlib）

图10 回测四模型对比      fig10_backtest_models.png
图11 表1 全网日总量预测  fig11_pred_total.png
图12 小时形态对比        fig12_hour_shape.png
图13 线路修正因子 f 分布 fig13_factor_dist.png
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import matplotlib
import matplotlib.dates as mdates

matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.patches import Patch     # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plot_figs import (C_ACC, C_BAR, C_BAR2, C_GREY, C_MAIN,  # noqa: E402
                       footnote, save, style, _utf8)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        raise SystemExit("缺少 %s，请先跑完上游脚本" % p)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def d(s: str):
    """解析 '2023/12/1' 或 '2023-12-01'。"""
    parts = s.replace("-", "/").split("/")
    return datetime(int(parts[0]), int(parts[1]), int(parts[2]))


def wan(v, pos=None):
    return "%.0f" % (v / 1e4)


COLORS = {"A1_朴素均值": "#999999", "A2_加权移动平均21": "#e69f00",
          "A4_HoltWinters": "#56b4e9", "A9_分解式稳健WMA": "#c00000",
          "A10_漂移A9": "#7b3294"}


# --------------------------------------------------------------------------- #
def fig10(p):
    dates = [d(x) for x in p["dates"]]
    fig, ax = plt.subplots(figsize=(12.4, 5.4))

    for start, end in [("2023-11-01", "2023-11-03"), ("2023-11-10", "2023-11-13")]:
        ax.axvspan(d(start), d(end), color="#fdeaea", zorder=0, linewidth=0)

    ax.plot(dates, p["actual"], color="#333333", linewidth=2.6, label="实际值")
    for name, vals in p["pred"].items():
        m = p["summary"][name]
        ax.plot(dates, vals, color=COLORS.get(name, C_BAR), linewidth=1.6,
                linestyle="--" if name.startswith("A9") else "-",
                label="%s（WAPE %.2f%%）" % (name.split("_")[0], m["WAPE"] * 100))

    ax.set_title("五个候选模型在 2023 年 11 月（验证期）的全网日货量预测对比", fontsize=13.5, pad=10)
    ax.set_xlabel("日期")
    ax.set_ylabel("全网日货量（万件）")
    ax.yaxis.set_major_formatter(FuncFormatter(wan))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    style(ax)
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Patch(facecolor="#fdeaea"))
    labels.append("大促日（不参与选型）")
    ax.legend(handles, labels, loc="upper left", frameon=False, fontsize=9, ncol=2)
    footnote(fig, "注：训练 2023-08-01~10-31，验证 11-01~11-30；粉色区为大促日（双 11 开门红与双 11 当天），"
                  "任何模型都无法从 8—10 月外推，故模型选型用「剔除大促日」的 WAPE_ex。")
    fig.subplots_adjust(bottom=0.16)
    return save(fig, "fig10_backtest_models.png")


# --------------------------------------------------------------------------- #
def fig11(p):
    # 只画 11 月下半月：11 月上半月含双 11 脉冲，会把纵轴撑爆、看不清预测细节
    hd_all = [d(x) for x in p["hist_dates"]]
    vt_all = p["hist_total"]
    hd, vt = hd_all[-15:], vt_all[-15:]
    pd_ = [d(x) for x in p["pred_dates"]]
    fig, ax = plt.subplots(figsize=(12.4, 5.2))
    ax.plot(hd, vt, color=C_GREY, linewidth=1.8, marker="o", markersize=3.4,
            label="11 月下半月实际日货量")
    ax.plot(pd_, p["pred_total"], color=C_MAIN, linewidth=2.2, marker="o", markersize=3.2,
            label="12 月预测（问题 1，表 1）")
    ax.axvline(hd[-1], color="#888888", linestyle=":", linewidth=1.2)
    ax.text(hd[-1], 0.93, " 预测起点 11/30", fontsize=9, color="#666666",
            transform=ax.get_xaxis_transform())

    hist_mean = sum(vt) / len(vt)
    ax.axhline(hist_mean, color=C_GREY, linestyle="--", linewidth=1.0, alpha=0.9)
    ax.text(hd[0], hist_mean * 1.004, "11/16~11/30 实际日均 %.1f 万件" % (hist_mean / 1e4),
            fontsize=8.6, color="#555555")
    ax.axhline(p["pred_mean"], color=C_MAIN, linestyle="--", linewidth=1.0, alpha=0.9)
    ax.text(pd_[8], max(vt) * 1.005,
            "12 月预测日均 %.1f 万件（比 11 月下半月低 %.1f%%）"
            % (p["pred_mean"] / 1e4, (1 - p["pred_mean"] / hist_mean) * 100),
            fontsize=9, color=C_MAIN)

    ax.set_title("问题 1 预测结果：57 个中心的全网日货量（2023/12/1 ~ 2023/12/30）",
                 fontsize=13.5, pad=10)
    ax.set_xlabel("日期")
    ax.set_ylabel("全网日货量（万件）")
    ax.yaxis.set_major_formatter(FuncFormatter(wan))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    style(ax)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    footnote(fig, "注：预测为 A9 分解式稳健加权移动平均（k=%d，星期因子，无趋势外推）。"
                  "11 月上半月含双 11 脉冲（峰值 161 万件），为使预测细节可读，此处只画 11 月下半月。"
             % p["model"]["k"])
    fig.subplots_adjust(bottom=0.16)
    return save(fig, "fig11_pred_total.png")


# --------------------------------------------------------------------------- #
def fig12(p):
    hours = list(range(24))
    share = p["share"]
    net = p["net_share"]
    fig, ax = plt.subplots(figsize=(10.8, 4.8))
    ax.bar([h - 0.2 for h in hours], share, width=0.4, color=C_BAR,
           label="%s 的小时占比" % p["demo_center"])
    ax.bar([h + 0.2 for h in hours], net, width=0.4, color=C_BAR2,
           label="全网平均小时占比")
    ax.set_xticks(hours)
    ax.set_xlabel("小时（0~23）")
    ax.set_ylabel("占全天货量比重（%）")
    ax.set_title("小时形态：%s 与全网平均的 24 小时占比对比（表 2 的分配依据）"
                 % p["demo_center"], fontsize=13, pad=10)
    style(ax)
    ax.legend(frameon=False, fontsize=9)
    footnote(fig, "注：占比由附件 2（11 月，缺格补 0、不插值）按中心求得，已剔除 11/1~11/3、11/10~11/13 大促日；"
                  "所选方案在 11/16~11/30 上的小时级 WAPE = %.2f%%。" % (p["choice"]["valid_WAPE"] * 100))
    fig.subplots_adjust(bottom=0.16)
    return save(fig, "fig12_hour_shape.png")


# --------------------------------------------------------------------------- #
def fig13(p):
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.8))

    ax = axes[0]
    ax.hist(p["f"], bins=40, range=(0.94, 1.03), color=C_BAR, edgecolor="white")
    ax.axvline(1.0, color=C_ACC, linestyle="--", linewidth=1.2)
    ax.set_xlabel("线路修正因子 f")
    ax.set_ylabel("分拣中心数")
    ax.set_title("(a) f 的分布：多数中心不随线路变化，少数在 ±5% 内调整", fontsize=11)
    ax.set_yscale("log")
    style(ax)

    ax = axes[1]
    names = p["top_centers"][::-1]
    delta = p["top_delta"][::-1]
    colors = [C_ACC if d < 0 else C_BAR for d in delta]
    ax.barh(range(len(names)), delta, color=colors, height=0.66)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    ax.axvline(0, color="#333333", linewidth=0.9)
    ax.set_xlabel("线路承载日货量变化 ΔL（件/日）")
    ax.set_title("(b) 变化最大的 12 个中心（红=减少，蓝=增加）", fontsize=11)
    style(ax, grid_axis="x")

    fig.suptitle("问题 2 的线路修正：f 范围 [%.4f, %.4f]，全网 Σ 与表 1 一致（λ=%.6f）"
                 % (min(p["f"]), max(p["f"]), p["lam"]), fontsize=13)
    footnote(fig, "注：关闭 %d 条、新开 %d 条线路；线路货量仅占中心日货量 %.2f%%，故修正幅度天然很小；"
                  "|f-1| 超过 5%% 的中心被截断（%d 个）。"
             % (p["closed"], p["new"], p["route_share"] * 100, p["n_cap"]))
    fig.subplots_adjust(bottom=0.18, top=0.84, wspace=0.3)
    return save(fig, "fig13_factor_dist.png")


# --------------------------------------------------------------------------- #
def main() -> None:
    _utf8()
    bt = load("backtest_payload.json")
    pt = load("pred_total.json")
    hp = load("hourly_payload.json")
    fp = load("factor_payload.json")

    out = [fig10(bt), fig11(pt), fig12(hp), fig13(fp)]
    print("[plots] 共生成 %d 张图" % len(out))


if __name__ == "__main__":
    main()
