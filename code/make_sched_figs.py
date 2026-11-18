# -*- coding: utf-8 -*-
"""
make_sched_figs.py —— 论文配图：班次人数热力图 + 排班统计双子图（问题 3，表 5）

图 1  fig14_sched_heatmap.png：横轴 30 个日期，纵轴 6 个班次，
      格值 = 全网当日该班次出勤总人数（正式工+临时工），colorbar + 关键格数值标注。
图 2  fig15_sched_stats.png：左 = 逐日人天数堆叠柱（正式工/临时工）+ 理论下界日均线；
      右 = 中心日人效分布直方图 + 人效上限 25 的竖线。

所有数字都从 `结果/结果/结果表5.csv`、`data/p3_stats.json` 实算（中心日货量取自
`data/pred_hourly.csv`，与表 5 用的是同一条需求曲线），不写死任何值。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.ticker import MultipleLocator

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
FIG_DIR = os.path.join(ROOT, "论文", "figs")
RES_DIR = os.path.join(ROOT, "结果", "结果")
SUB_DIR = os.path.join(ROOT, "提交")

SHIFT_NAMES = ["00:00-08:00", "05:00-13:00", "08:00-16:00",
               "12:00-20:00", "14:00-22:00", "16:00-24:00"]
N_DAY = 30
DATES = ["2023/12/%d" % d for d in range(1, N_DAY + 1)]
EFF_F = 25.0


def read_csv(path):
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit("无法解码 %s" % path)


def find(name):
    for d in (RES_DIR, SUB_DIR):
        p = os.path.join(d, name)
        if os.path.exists(p) and os.path.getsize(p) > 300:
            return p
    raise SystemExit("找不到 %s" % name)


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    t5 = find("结果表5.csv")
    df5 = read_csv(t5)
    df5["T"] = df5["正式工人数"] + df5["临时工人数"]
    stats = json.load(open(os.path.join(DATA_DIR, "p3_stats.json"), encoding="utf-8"))

    # ---------- 透视：6 班次 × 30 天 的全网出勤总人数
    piv = df5.pivot_table(index="班次", columns="日期", values="T",
                          aggfunc="sum", fill_value=0)
    piv = piv.reindex(index=SHIFT_NAMES, columns=DATES)
    mat = piv.values.astype(float)
    day_total = mat.sum(axis=0)
    shift_total = mat.sum(axis=1)
    formal_day = df5.groupby("日期")["正式工人数"].sum().reindex(DATES).values
    temp_day = df5.groupby("日期")["临时工人数"].sum().reindex(DATES).values

    # ---------- 图 1：班次人数热力图
    fig, ax = plt.subplots(figsize=(13.2, 5.6), dpi=300)
    norm = LogNorm(vmin=max(40.0, float(mat.min())), vmax=float(mat.max()))
    im = ax.imshow(mat, aspect="auto", cmap="YlOrRd", norm=norm, interpolation="nearest")
    ax.set_xticks(range(N_DAY))
    ax.set_xticklabels([d.split("/")[-1] for d in DATES], fontsize=8)
    ax.set_xlabel("日期（2023 年 12 月，日）", fontsize=11)
    ax.set_yticks(range(len(SHIFT_NAMES)))
    ax.set_yticklabels(SHIFT_NAMES, fontsize=10)
    ax.set_ylabel("班次", fontsize=11)

    # 全部格子标注数值（颜色按对数色阶归一化后决定黑/白字）
    vmin = max(40.0, float(mat.min()))
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            t = (np.log(v) - np.log(vmin)) / (np.log(mat.max()) - np.log(vmin) + 1e-12)
            ax.text(j, i, "%d" % int(v), ha="center", va="center", fontsize=5.6,
                    color="white" if t > 0.60 else "black")
    cb = fig.colorbar(im, ax=ax, pad=0.012, fraction=0.026)
    cb.set_label("全网出勤人数（人，对数色阶）", fontsize=10)
    ax.set_title("全网各班次逐日出勤人数（正式工 + 临时工）", fontsize=13, pad=10)
    fig.tight_layout()
    f1 = os.path.join(FIG_DIR, "fig14_sched_heatmap.png")
    fig.savefig(f1, dpi=300, bbox_inches="tight")
    plt.close(fig)

    # ---------- 图 2：左堆叠柱 + 左下界；右人效直方图
    lb_day = float(stats["lb_work"]) / N_DAY          # 100,716 / 30 ≈ 3,357
    # 中心日人效：货量（pred_hourly）/ (8 × 人数)
    pd_h = read_csv(os.path.join(DATA_DIR, "pred_hourly.csv")) \
        if os.path.exists(os.path.join(DATA_DIR, "pred_hourly.csv")) \
        else read_csv(os.path.join(DATA_DIR, "hourly.csv"))
    pd_h["日期"] = pd_h["日期"].astype(str).str.replace("-", "/")
    vol_cd = pd_h.groupby(["分拣中心", "日期"])["货量"].sum()
    ppl_cd = df5.groupby(["分拣中心", "日期"])["T"].sum()
    keys = sorted(set(vol_cd.index) & set(ppl_cd.index))
    eff = np.array([vol_cd[k] / (8.0 * ppl_cd[k]) for k in keys], dtype=float)
    eff = eff[ppl_cd.loc[keys].values > 0]
    eff_mean, eff_std = float(eff.mean()), float(eff.std())

    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.8), dpi=300,
                             gridspec_kw={"width_ratios": [1.35, 1.0], "wspace": 0.22})
    ax = axes[0]
    x = np.arange(N_DAY)
    ax.bar(x, formal_day, width=0.72, color="#4C72B0", label="正式工人天数")
    ax.bar(x, temp_day, width=0.72, bottom=formal_day, color="#DD8452", label="临时工人天数")
    ax.axhline(lb_day, color="#C44E52", linestyle="--", linewidth=1.4,
               label="理论下界日均 %.0f 人/日" % lb_day)
    imax0, imin0 = int(np.argmax(day_total)), int(np.argmin(day_total))
    n_max = int((day_total == day_total[imax0]).sum())
    n_min = int((day_total == day_total[imin0]).sum())
    ax.text(0.015, 0.63,
            "单日最高 %d 人（%s 等 %d 天）\n单日最低 %d 人（%s 等 %d 天）\n30 天平均 %.0f 人"
            % (day_total[imax0], DATES[imax0].split("/")[-1], n_max,
               day_total[imin0], DATES[imin0].split("/")[-1], n_min, day_total.mean()),
            transform=ax.transAxes, fontsize=8.5, ha="left", va="top",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                      edgecolor="#999999", lw=0.6))
    ax.set_xticks(x[::3])
    ax.set_xticklabels([DATES[i].split("/")[-1] for i in range(0, N_DAY, 3)], fontsize=8)
    ax.set_xlabel("日期（2023 年 12 月，日）", fontsize=10)
    ax.set_ylabel("人天数（人·日）", fontsize=10)
    ax.set_title("逐日人天数（正式工 + 临时工）", fontsize=11)
    ax.legend(fontsize=8.5, loc="upper center", ncol=3, framealpha=0.92,
              bbox_to_anchor=(0.5, 1.0))
    ax.grid(axis="y", linestyle=":", alpha=0.45)
    ax.set_axisbelow(True)
    ax.set_ylim(0, float(day_total.max()) * 1.34)

    ax = axes[1]
    ax.hist(eff, bins=36, color="#55A868", edgecolor="white", linewidth=0.6)
    ax.axvline(25.0, color="#C44E52", linestyle="--", linewidth=1.4, label="人效上限 25")
    ax.axvline(eff_mean, color="#4C72B0", linestyle="-", linewidth=1.2,
               label="均值 %.2f" % eff_mean)
    ax.set_xlabel("中心日人效（件/(人·小时)）", fontsize=10)
    ax.set_ylabel("中心·日 个数", fontsize=10)
    ax.set_title("中心日人效分布（57 中心 × 30 天 = %d 个）" % len(eff), fontsize=11)
    ax.legend(fontsize=8.5, loc="upper left", framealpha=0.92)
    ax.grid(axis="y", linestyle=":", alpha=0.45)
    ax.set_axisbelow(True)
    ax.text(0.97, 0.62,
            "n = %d\n均值 = %.2f\n标准差 = %.2f\n最小 = %.2f\n达到 25 上限的 = %d 个"
            % (len(eff), eff_mean, eff_std, eff.min(), int((eff >= 25 - 1e-9).sum())),
            transform=ax.transAxes, fontsize=8.5, ha="right", va="top",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#999999", lw=0.6))

    fig.tight_layout()
    f2 = os.path.join(FIG_DIR, "fig15_sched_stats.png")
    fig.savefig(f2, dpi=300, bbox_inches="tight")
    plt.close(fig)

    # ---------- 关键数字
    imax, imin = int(np.argmax(day_total)), int(np.argmin(day_total))
    print("表 5 来源：%s" % os.path.relpath(t5, ROOT))
    print("图 1：%s" % os.path.relpath(f1, ROOT))
    print("图 2：%s" % os.path.relpath(f2, ROOT))
    print("全网单日人数：最高 %s（%d 人）；最低 %s（%d 人）；30 天平均 %.1f 人"
          % (DATES[imax], int(day_total[imax]), DATES[imin], int(day_total[imin]), day_total.mean()))
    print("班次累计人数（30 天）：")
    for s, v in zip(SHIFT_NAMES, shift_total):
        print("  %-12s %8d 人（占 %.2f%%）" % (s, int(v), 100.0 * v / shift_total.sum()))
    print("班次人数最多的班次：%s（%d 人）" % (SHIFT_NAMES[int(np.argmax(shift_total))],
                                            int(shift_total.max())))
    print("热力图最大值格：%s × %s = %d 人"
          % (SHIFT_NAMES[int(np.unravel_index(int(np.argmax(mat)), mat.shape)[0])],
             DATES[int(np.unravel_index(int(np.argmax(mat)), mat.shape)[1])], int(mat.max())))
    print("中心日人效：n=%d，均值 %.3f，标准差 %.3f，最小 %.3f，最大 %.3f，达到上限 25 的 %d 个"
          % (len(eff), eff_mean, eff_std, eff.min(), eff.max(), int((eff >= 25 - 1e-9).sum())))
    print("p3_stats 对照：eff_mean=%.3f（每日口径 std=%.3f），人天数=%d，下界日均=%.1f"
          % (stats["eff_mean"], stats["eff_std_between_days"], stats["person_days"], lb_day))
    return 0


if __name__ == "__main__":
    sys.exit(main())
