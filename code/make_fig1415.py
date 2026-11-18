# -*- coding: utf-8 -*-
"""
make_fig1415.py —— 论文图 12（班次人数热力图）与图 13（人天数 / 人效统计）
=======================================================================
图 12：(a) 日期 × 班次 的出勤人天数热力图（对数色标）+ (b) 六个班次的人天数与占比
图 13：(a) 逐日货量与人天数双轴曲线；(b) 1710 个（中心，日）的人效分布

数据：结果/结果/结果表5.csv + data/pred_hourly.csv（需求曲线，与求解器同源）
输出：论文/figs/fig14_shift_heatmap.png、论文/figs/fig15_staffing_stats.png（300 dpi）
"""
import collections
import csv
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.colors as mcolors
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import p3_staffing as p3  # noqa: E402

FIGS = os.path.join(ROOT, '论文', 'figs')
RES5 = os.path.join(ROOT, '结果', '结果', '结果表5.csv')

SHIFTS = ['00:00-08:00', '05:00-13:00', '08:00-16:00',
          '12:00-20:00', '14:00-22:00', '16:00-24:00']
SHORT = ['00-08', '05-13', '08-16', '12-20', '14-22', '16-24']

for path in (r'C:\Windows\Fonts\simhei.ttf', r'C:\Windows\Fonts\msyh.ttc'):
    if os.path.exists(path):
        fm.fontManager.addfont(path)
        name = fm.FontProperties(fname=path).get_name()
        break
plt.rcParams['font.sans-serif'] = [name, 'SimHei', 'Microsoft YaHei']
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False


def dkey(s):
    y, m, d = s.split('/')
    return (int(y), int(m), int(d))


def load_t5():
    by_ds = collections.Counter()
    by_d = collections.Counter()
    by_cd = collections.Counter()
    with open(RES5, encoding='gbk') as f:
        for r in csv.DictReader(f):
            n = int(float(r['正式工人数'])) + int(float(r['临时工人数']))
            by_ds[(r['日期'], r['班次'])] += n
            by_d[r['日期']] += n
            by_cd[(r['分拣中心'], r['日期'])] += n
    return by_ds, by_d, by_cd


def fig14():
    by_ds, by_d, _ = load_t5()
    dates = sorted(by_d, key=dkey)          # 按真实日期排序（不是字符串序）
    M = np.array([[by_ds[(d, s)] for s in SHIFTS] for d in dates], dtype=float)

    fig = plt.figure(figsize=(9.4, 4.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[3.05, 1.0], wspace=0.06)
    ax = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1], sharey=ax)

    norm = mcolors.LogNorm(vmin=40, vmax=M.max())
    im = ax.imshow(M.T, aspect='auto', cmap='YlOrRd', norm=norm,
                   interpolation='nearest')
    ax.set_xticks(range(0, len(dates), 2))
    ax.set_xticklabels([str(dkey(d)[2]) for d in dates[::2]], fontsize=8)
    ax.set_yticks(range(len(SHIFTS)))
    ax.set_yticklabels(SHORT, fontsize=9)
    ax.set_xlabel('12 月日期（日）', fontsize=9.5)
    ax.set_ylabel('班次（时）', fontsize=9.5)
    ax.set_title('(a) 日期 × 班次的出勤人天数（对数色标）', fontsize=10)
    cb = fig.colorbar(im, ax=ax, pad=0.015, fraction=0.035, ticks=[50, 100, 200, 500, 1000, 2500])
    cb.ax.set_yticklabels(['50', '100', '200', '500', '1000', '2500'])
    cb.ax.tick_params(labelsize=7.5)
    cb.set_label('人天数', fontsize=8)

    tot = M.sum(axis=0)
    share = tot / tot.sum() * 100
    colors = ['#C00000' if s > 50 else '#8FAADC' for s in share]
    ax2.barh(range(len(SHIFTS)), tot, color=colors, height=0.62)
    for i, (t, s) in enumerate(zip(tot, share)):
        ax2.text(t + tot.max() * 0.03, i, '%d（%.1f%%）' % (t, s),
                 va='center', fontsize=7.4, color='#333333')
    ax2.set_xlim(0, tot.max() * 1.42)
    ax2.set_xlabel('30 天合计人天数', fontsize=8.5)
    ax2.tick_params(axis='x', labelsize=7.5)
    ax2.set_title('(b) 班次结构', fontsize=9.5)
    plt.setp(ax2.get_yticklabels(), visible=False)

    fig.text(0.012, 0.015,
             '注：16:00-24:00 班次承担 64.98% 的人天数，00:00-08:00 与 05:00-13:00 合计 25.64%，'
             '08:00-16:00 与 12:00-20:00 仅 8.01%——人力向晚间集中是到货形态的必然结果。',
             fontsize=7.2, color='#444444')
    fig.subplots_adjust(left=0.075, right=0.995, top=0.90, bottom=0.20)
    out = os.path.join(FIGS, 'fig14_shift_heatmap.png')
    fig.savefig(out, dpi=300, facecolor='white')
    plt.close(fig)
    print('已输出：', out, os.path.getsize(out) // 1024, 'KB')
    print('班次人天数：', dict(zip(SHORT, tot.astype(int))))


def fig15():
    _, by_d, by_cd = load_t5()
    demand, meta = p3.load_demand('pred')
    dates = sorted(by_d, key=dkey)
    idx = {d: i for i, d in enumerate(dates)}

    vol = [sum(sum(demand[(c, i)]) for c in meta['centers']) for i in range(len(dates))]
    persons = [by_d[d] for d in dates]

    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.0))
    ax = axes[0]
    x = np.arange(len(dates))
    ax.plot(x, np.array(vol) / 1e4, color='#2F5597', lw=1.9, marker='o', ms=3.4,
            label='全网日货量（万件）')
    ax.set_xlabel('12 月日期（日）', fontsize=9.5)
    ax.set_ylabel('全网日货量（万件）', fontsize=9.5, color='#2F5597')
    ax.tick_params(axis='y', labelcolor='#2F5597', labelsize=8.5)
    ax.tick_params(axis='x', labelsize=8)
    ax.grid(axis='y', ls=':', lw=0.6, color='#CCCCCC')
    ax2 = ax.twinx()
    ax2.plot(x, persons, color='#C00000', lw=1.6, ls='--', marker='s', ms=3,
             label='日人天数（人）')
    ax2.set_ylabel('日人天数（人）', fontsize=9.5, color='#C00000')
    ax2.tick_params(axis='y', labelcolor='#C00000', labelsize=8.5)
    ax.set_xticks(x[::3])
    ax.set_xticklabels([str(dkey(dates[i])[2]) for i in x[::3]])
    peak = int(np.argmax(persons))
    ax.axvline(peak, color='#808080', ls=':', lw=1.0)
    ax.text(peak + 0.4, max(vol) / 1e4 * 0.985, '12/7 峰值',
            fontsize=8, color='#404040', va='top')
    ax.set_title('(a) 逐日货量与人天数的同步波动', fontsize=10.2)
    lo, hi = min(vol) / 1e4, max(vol) / 1e4
    ax.set_ylim(lo - (hi - lo) * 0.15, hi + (hi - lo) * 0.18)
    ax2.set_ylim(min(persons) - 60, max(persons) + 70)

    ax3 = axes[1]
    effs = np.array([sum(demand[(c, idx[d])]) / (8.0 * p) for (c, d), p in by_cd.items()])
    ax3.hist(effs, bins=44, color='#8FAADC', edgecolor='white', lw=0.4)
    ax3.axvline(effs.mean(), color='#C00000', ls='--', lw=1.4,
                label='中心日均值 %.2f' % effs.mean())
    ax3.axvline(25, color='#404040', ls=':', lw=1.2, label='题面上限 25')
    ax3.set_xlabel('人效（件/人·小时）', fontsize=9.5)
    ax3.set_ylabel('（中心，日）个数', fontsize=9.5)
    ax3.tick_params(labelsize=8.5)
    ax3.legend(frameon=False, fontsize=8, loc='upper left')
    ax3.set_title('(b) 1710 个（中心，日）的人效分布', fontsize=10.2)
    ax3.grid(axis='y', ls=':', lw=0.6, color='#CCCCCC')

    fig.suptitle('图13  问题三的人天数与人效统计', fontsize=11.5, y=0.995)
    fig.text(0.012, 0.015,
             '注：日人天数 3706~3968 人，与货量同向波动；人效按货量加权为 21.92 件/(人·小时)'
             '（上限 25 的 87.7%），按中心日简单平均为 %.2f。' % effs.mean(),
             fontsize=7.2, color='#444444')
    fig.subplots_adjust(left=0.065, right=0.925, top=0.845, bottom=0.19, wspace=0.42)
    out = os.path.join(FIGS, 'fig15_staffing_stats.png')
    fig.savefig(out, dpi=300, facecolor='white')
    plt.close(fig)
    print('已输出：', out, os.path.getsize(out) // 1024, 'KB')
    print('日人天数 %d~%d；中心日人效 均值 %.3f 标准差 %.3f'
          % (min(persons), max(persons), effs.mean(), effs.std(ddof=1)))


if __name__ == '__main__':
    fig14()
    fig15()
