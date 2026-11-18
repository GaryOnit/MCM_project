# -*- coding: utf-8 -*-
"""
make_flow_fig.py —— 生成论文图 1「总体技术路线」流程图
=====================================================
数据清洗与探索 → 日货量预测 → 小时货量分配 → 线路结构修正
              → 班次人数优化 → 逐人排班 → 结果表 1~6

采用 S 形两行布局（第一行自左向右，第二行自右向左），使图幅控制在
6.6 in × 4.6 in：插入 Word 时按 15.5 cm 宽度缩放约 0.92，图内文字
仍保持 7~10 pt 的实际字号，避免「整行 7 个方框 + 图内 3 pt 小字」。

输出：论文/figs/flow.png（300 dpi）
运行：python code/make_flow_fig.py
"""

import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, '论文', 'figs', 'flow.png')

# ---------------- 中文字体：显式注册，避免方块 ----------------
CANDIDATES = [
    r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\msyh.ttc',
    r'C:\Windows\Fonts\simsun.ttc',
]
FONT_NAME = None
for path in CANDIDATES:
    if os.path.exists(path):
        fm.fontManager.addfont(path)
        FONT_NAME = fm.FontProperties(fname=path).get_name()
        break
if FONT_NAME is None:
    sys.exit('未找到可用中文字体')

plt.rcParams['font.sans-serif'] = [FONT_NAME, 'SimHei', 'Microsoft YaHei']
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['mathtext.fontset'] = 'dejavusans'
print('使用字体：', FONT_NAME)

# ---------------- 画布：1 坐标单位 = 1 英寸 ----------------
W, H = 6.6, 4.35
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0.15, 4.50)
ax.axis('off')

BLUE_FC, BLUE_EC = '#EAF1FB', '#2F5597'
GOLD_FC = '#FFF6E8'
GRAY_FC, GRAY_EC = '#F2F2F2', '#808080'

BW, GAP = 1.44, 0.14
SPACING = BW + GAP
X_LEFT = 0.16
BOX_H = 1.16
ROW1_BOT, ROW1_TOP = 3.24, 3.24 + BOX_H
ROW2_BOT, ROW2_TOP = 1.52, 1.52 + BOX_H

STAGES = [
    ('数据清洗\n与探索', ['附件 1～4 读取', '缺失补 0、异常标记'], '第 4 章'),
    ('日货量\n预测', ['四模型回测对比', 'RTW-WMA 选优'], '→ 表 1'),
    ('小时货量\n分配', ['分中心占比＋余数法', '层级一致性校验'], '→ 表 2'),
    ('线路结构\n修正', ['结构因子 $f_c$＋守恒', '双假设敏感性'], '→ 表 3、表 4'),
    ('班次人数\n优化', ['12 变量整数规划', '下界＋±1 枚举'], '→ 表 5'),
    ('逐人\n排班', ['模式池＋贪心轮转', '出勤率均衡'], '→ 表 6'),
    ('结果\n输出', ['六张结果表生成', '守恒与产能校验'], '第 5～9 章'),
]


def center(i):
    return X_LEFT + BW / 2.0 + i * SPACING


def draw_box(cx, ybot, ytop, title, details, tag, fc, ec):
    ax.add_patch(mpatches.FancyBboxPatch(
        (cx - BW / 2.0, ybot), BW, ytop - ybot,
        boxstyle='round,pad=0.00,rounding_size=0.07',
        linewidth=1.2, edgecolor=ec, facecolor=fc, zorder=2))
    t1, t2 = title.split('\n')
    ax.text(cx, ytop - 0.23, t1, ha='center', va='center', fontsize=11.5,
            fontweight='bold', color='#1F3864', zorder=3)
    ax.text(cx, ytop - 0.45, t2, ha='center', va='center', fontsize=11.5,
            fontweight='bold', color='#1F3864', zorder=3)
    for k, line in enumerate(details):
        ax.text(cx, ytop - 0.69 - k * 0.19, line, ha='center', va='center',
                fontsize=8.0, color='#333333', zorder=3)
    ax.text(cx, ybot + 0.15, tag, ha='center', va='center', fontsize=7.6,
            color='#7F7F7F', style='italic', zorder=3)


# 第一行：0~3 号阶段，自左向右
for i in range(4):
    fc = GOLD_FC if i == 0 else BLUE_FC
    draw_box(center(i), ROW1_BOT, ROW1_TOP, *STAGES[i], fc, BLUE_EC)

# 第二行：4~6 号阶段，自右向左（S 形），末位让出左侧空位放图例
for j, i in enumerate((4, 5, 6)):
    cx = center(3 - j)
    draw_box(cx, ROW2_BOT, ROW2_TOP, *STAGES[i], BLUE_FC, BLUE_EC)

# ---------------- 箭头 ----------------
arrow_kw = dict(arrowstyle='-|>', mutation_scale=13, linewidth=1.5,
                color=BLUE_EC, shrinkA=0, shrinkB=0, zorder=4)
y_mid1 = (ROW1_BOT + ROW1_TOP) / 2.0
for i in range(3):
    ax.add_patch(FancyArrowPatch((center(i) + BW / 2.0 + 0.01, y_mid1),
                                 (center(i + 1) - BW / 2.0 - 0.01, y_mid1),
                                 **arrow_kw))
# 第一行末端折向第二行首端（同一 x 坐标，竖直向下）
ax.add_patch(FancyArrowPatch((center(3), ROW1_BOT - 0.01),
                             (center(3), ROW2_TOP + 0.01), **arrow_kw))

y_mid2 = (ROW2_BOT + ROW2_TOP) / 2.0
for j in range(2):
    ax.add_patch(FancyArrowPatch((center(3 - j) - BW / 2.0 - 0.01, y_mid2),
                                 (center(2 - j) + BW / 2.0 + 0.01, y_mid2),
                                 **arrow_kw))

# ---------------- 左侧空位：阅读方向图例 ----------------
lx, ly = X_LEFT, ROW2_BOT
ax.add_patch(mpatches.FancyBboxPatch(
    (lx, ly), BW, ROW2_TOP - ROW2_BOT,
    boxstyle='round,pad=0.00,rounding_size=0.07',
    linewidth=0.9, edgecolor='#BFBFBF', facecolor='white', zorder=2))
ax.text(lx + BW / 2.0, ly + 0.78, '阅读方向', ha='center', va='center',
        fontsize=9.0, color='#404040', fontweight='bold', zorder=3)
ax.text(lx + BW / 2.0, ly + 0.50, '第 1 行 → 向右', ha='center', va='center',
        fontsize=7.8, color='#595959', zorder=3)
ax.text(lx + BW / 2.0, ly + 0.30, '第 2 行 → 向左', ha='center', va='center',
        fontsize=7.8, color='#595959', zorder=3)
ax.text(lx + BW / 2.0, ly + 0.12, '（S 形串联）', ha='center', va='center',
        fontsize=7.2, color='#808080', zorder=3)

# ---------------- 底部说明 ----------------
ax.text(0.16, 0.95, '注：', fontsize=8.2, color='#333333',
        ha='left', va='center', fontweight='bold')
ax.text(0.44, 0.95,
        '实线箭头为建模顺序；首行末端的竖箭头折入第二行。',
        fontsize=8.0, color='#333333', ha='left', va='center')
ax.text(0.16, 0.68,
        '整条链路依次满足「日总量守恒—小时合计一致—线路修正归一—'
        '逐时产能覆盖」四类一致性约束。',
        fontsize=8.0, color='#333333', ha='left', va='center')

os.makedirs(os.path.dirname(OUT), exist_ok=True)
fig.savefig(OUT, dpi=300, facecolor='white')
plt.close(fig)
print('已输出：', OUT, os.path.getsize(OUT) // 1024, 'KB')
