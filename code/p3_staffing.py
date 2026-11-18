# -*- coding: utf-8 -*-
"""
p3_staffing.py —— 问题 3：57 个分拣中心 × 未来 30 天 × 6 个班次的出勤人数（结果表 5）

模型（每个 (分拣中心, 日期) 解一个 12 变量整数规划）
----------------------------------------------------
变量：x_s = 第 s 班正式工人数，y_s = 第 s 班临时工人数，s = 0..5
      班次 s 覆盖小时 [start_s, start_s+7]（各 8 小时），且 start = 0,5,8,12,14,16，
      故相邻班次在 5-7 时 / 12-15 时 / 14-20 时存在重叠。

目标：min  Σ_s (x_s + y_s)                     （人天数最少 = 出勤人数最少）
      第二目标（仅在最优解集内）：最小化各小时产能利用率 u_h = R_h / C_h 的标准差，
      即"实际小时人效尽量均衡"。

约束：Σ_{s∋h} (25 x_s + 20 y_s) ≥ R_h ,  ∀h = 0..23     （每小时产能覆盖该小时货量）
      Σ_s x_s ≤ 60                                     （每中心 60 名正式工，每人每天至多一班）
      x_s, y_s ∈ ℤ≥0

求解（只用 numpy / pandas / 标准库）
------------------------------------
引理 1（人天数可分离）：由于正式工人效 25 > 临时工 20，任意可行解 (x,y) 把临时工换成
正式工后产能不降、人数不变，故 "最少人天数" 等于 "全部用正式工（25 人效）" 时的最少人数。
       ⇒ 先解纯正式工覆盖问题：min Σ q_s, s.t. Σ_{s∋h} q_s ≥ ⌈R_h/25⌉。
引理 2（贪心最优）：6 个班次等长（8 小时），覆盖矩阵按小时呈"连续 1"（区间矩阵 ⇒ 全幺模），
       按时递增、缺口加到"最晚开始且覆盖该小时"的班次，可证明得到最优整数解
       （本文件 self_test_greedy() 用穷举对拍验证）。
若 Σ q* ≤ 60：直接取 x = q*, y = 0（此时必然全部用正式工，满足"优先正式工"）。
若 Σ q* > 60：正式工上限起作用 —— 先按 §"正式工分配" 把 60 人放到最需要的班次
       （坐标下降），再用同样的贪心按临时工人效 20 补齐缺口，最后做"逐人删除"去冗余。

人效口径（写死，供论文引用）
--------------------------
C_h = Σ_{s∋h} (25 x_s + 20 y_s)   ：第 h 小时投入的人工产能（包裹/小时）
u_h = R_h / C_h（仅统计 R_h > 0 的小时）：第 h 小时的实际小时人效 / 产能利用率
均衡度 = std(u_h)；另报日层面 人效 = Σ_h R_h / (8·Σ_s (x_s+y_s))（包裹/人天，越大越省人）

用法
----
    python code/p3_staffing.py                # 自动选数据源：有 pred_hourly.csv 用它，否则回退 hourly.csv
    python code/p3_staffing.py --source hourly --tag dev   # 强制用 11 月小时数据（dev 联调）
    python code/p3_staffing.py --source pred               # 强制用问题 2 的小时预测（正式运行）
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
RES_DIR = os.path.join(ROOT, "结果", "结果")
# 本会话的沙箱把 结果/、附件/ 设为只读，dev 产物改放 提交/（文件名带 _dev 后缀）
DEV_DIR = os.path.join(ROOT, "提交")

# ---------------------------------------------------------------- 题面常量
SHIFT_NAMES = ["00:00-08:00", "05:00-13:00", "08:00-16:00",
               "12:00-20:00", "14:00-22:00", "16:00-24:00"]
SHIFT_START = [0, 5, 8, 12, 14, 16]
NS = 6                                   # 6 个班次
HOURS = [list(range(st, st + 8)) for st in SHIFT_START]
COVER = [tuple(s for s in range(NS) if SHIFT_START[s] <= h <= SHIFT_START[s] + 7)
         for h in range(24)]
EFF_F = 25                               # 正式工小时人效上限（包裹/小时）
EFF_T = 20                               # 临时工小时人效上限（包裹/小时）
FORMAL_CAP = 60                          # 问题 3：每中心 60 名正式工
N_DAY = 30
DATES = ["2023/12/%d" % d for d in range(1, N_DAY + 1)]

CENTER = "分拣中心"
DATE = "日期"
HOUR = "小时"
VOL = "货量"
OUT_COLS = ["分拣中心", "日期", "班次", "正式工人数", "临时工人数"]


# ---------------------------------------------------------------- 小工具
def cdiv(v, k):
    """ceil(v / k)，对浮点货量稳健（避免 13850/25 因浮点误差多进一人）。"""
    return int(math.ceil(float(v) / k - 1e-9))


def shift_tags(s):
    return "SC%d" % int(s[2:])


def sort_centers(names):
    return sorted(set(names), key=lambda x: (int(x[2:]) if x[2:].isdigit() else 10 ** 6, x))


def _read_csv(path):
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit("无法识别编码：%s" % path)


def _date_key(v):
    s = str(v).strip().replace("-", "/").replace(".", "/")
    parts = s.split("/")
    if len(parts) != 3:
        raise SystemExit("无法解析日期：%r" % (v,))
    return int(parts[0]), int(parts[1]), int(parts[2])


def fmt_date(k):
    return "%d/%d/%d" % k


# ---------------------------------------------------------------- 需求曲线
def load_demand(source="auto"):
    """读入小时需求曲线，返回 (demand, meta)

    demand: dict[(分拣中心, 日序号 0..29)] -> np.array(24) 每小时货量 R_h
    数据源：
      * data/pred_hourly.csv （问题 2 的小时预测 = 表 4，正式运行）
      * data/hourly.csv      （附件 2 的 11 月小时数据，缺失小时按 0 补全；dev 回退）
    """
    pred = os.path.join(DATA_DIR, "pred_hourly.csv")
    hour = os.path.join(DATA_DIR, "hourly.csv")
    if source == "auto":
        source = "pred" if os.path.exists(pred) else "hourly"
    if source == "pred":
        path = pred
        if not os.path.exists(path):
            raise SystemExit("缺少 %s：请先拿到问题 2 的小时预测，或用 --source hourly 走 dev。" % path)
    elif source == "hourly":
        path = hour
    else:
        raise SystemExit("未知数据源：%s" % source)

    df = _read_csv(path)
    need_cols = [CENTER, DATE, HOUR, VOL]
    miss = [c for c in need_cols if c not in df.columns]
    if miss:
        raise SystemExit("%s 缺少列 %s（现有 %s）" % (path, miss, list(df.columns)))
    df = df[need_cols].copy()
    df[HOUR] = df[HOUR].astype(int)
    df[VOL] = df[VOL].astype(float)
    df = df[(df[HOUR] >= 0) & (df[HOUR] <= 23)]

    centers = sort_centers(df[CENTER].unique())
    days = sorted({_date_key(v) for v in df[DATE].unique()})
    if len(days) != N_DAY:
        raise SystemExit("数据源 %s 只有 %d 天（应为 30 天）" % (path, len(days)))
    dmap = {k: i for i, k in enumerate(days)}

    demand = {}
    for c in centers:
        sub = df[df[CENTER] == c]
        mat = np.zeros((N_DAY, 24), dtype=float)
        for v, h, q in zip(sub[DATE], sub[HOUR], sub[VOL]):
            mat[dmap[_date_key(v)], int(h)] += q
        for k in range(N_DAY):
            demand[(c, k)] = mat[k]

    meta = {
        "source": source,
        "path": os.path.relpath(path, ROOT),
        "src_dates": ["%d/%d/%d" % k for k in days],
        "out_dates": DATES,
        "n_center": len(centers),
        "centers": centers,
        "total_volume": float(sum(m.sum() for m in demand.values())),
    }
    return demand, meta


# ---------------------------------------------------------------- 覆盖 / 校验
def cover_capacity(x, y):
    """C_h = Σ_{s∋h}(25 x_s + 20 y_s)，返回长度 24 的列表。"""
    cap = [0] * 24
    for s in range(NS):
        c = EFF_F * int(x[s]) + EFF_T * int(y[s])
        if c:
            for h in HOURS[s]:
                cap[h] += c
    return cap


def verify_day(R, x, y, tol=1e-9):
    """独立校验单个 (中心, 日)：逐小时 Σ产能 ≥ R_h；返回 (ok, 明细列表)。"""
    cap = cover_capacity(x, y)
    bad = []
    for h in range(24):
        if cap[h] + tol < float(R[h]):
            bad.append((h, float(R[h]), cap[h]))
    return (len(bad) == 0), bad


def greedy_cover(need):
    """纯覆盖贪心：need[h] = 第 h 小时至少需要多少"覆盖该小时的人"。

    从 h=0 递增，缺口 δ 加给"覆盖 h 中开始最晚"的班次（索引最大者），
    使其对后续小时贡献最大。等长班次 + 区间矩阵，该贪心给出最优整数解。
    """
    p = [0] * NS
    for h in range(24):
        cov = COVER[h]
        cur = 0
        for s in cov:
            cur += p[s]
        d = need[h] - cur
        if d > 0:
            p[cov[-1]] += d
    return p


def temp_cover(R, x):
    """给定正式工分配 x，用临时工（20 人效）贪心覆盖剩余小时货量。"""
    cap = cover_capacity(x, [0] * NS)
    need = [max(0, cdiv(max(0.0, float(R[h]) - cap[h]), EFF_T)) for h in range(24)]
    return greedy_cover(need)


def is_feasible(R, x, y, tol=1e-9):
    cap = cover_capacity(x, y)
    for h in range(24):
        if cap[h] + tol < float(R[h]):
            return False
    return True


# ---------------------------------------------------------------- 人效均衡指标
def util_stats(R, x, y):
    """返回 (人效均衡度 std(u_h), 平均利用率, 人效[包裹/(人·小时)])。

    C_h = Σ_{s∋h}(25x_s+20y_s) 为第 h 小时投入的产能；u_h = R_h/C_h 仅统计 R_h>0 的小时。
    """
    cap = cover_capacity(x, y)
    us = [float(R[h]) / cap[h] for h in range(24)
          if float(R[h]) > 1e-9 and cap[h] > 0]
    if us:
        m = sum(us) / len(us)
        var = sum((u - m) ** 2 for u in us) / len(us)
        sd = math.sqrt(var)
    else:
        m, sd = 1.0, 0.0
    people = sum(int(v) for v in x) + sum(int(v) for v in y)
    vol = float(sum(max(0.0, v) for v in R))
    eff = vol / (8.0 * people) if people else 0.0
    return sd, m, eff


# ---------------------------------------------------------------- 混合求解
def _temp_total(R, x):
    return sum(temp_cover(R, x))


def _descent_units(R, x, max_pass=20):
    """单步坐标下降：把 1 名正式工在班次间挪动，最小化临时工人数。"""
    x = list(x)
    best = _temp_total(R, x)
    for _ in range(max_pass):
        improved = False
        for a in range(NS):
            for b in range(NS):
                if a == b or x[a] <= 0:      # 逐次检查，避免出现负人数
                    continue
                x[a] -= 1
                x[b] += 1
                val = _temp_total(R, x)
                if val < best:
                    best = val
                    improved = True
                else:
                    x[a] += 1
                    x[b] -= 1
        if not improved:
            break
    return x, best


def _pair_realloc(R, x):
    """成对穷举重分配：固定其他班次，把 x_a+x_b 在所有拆分上穷举（跳出单步局部最优）。"""
    x = list(x)
    best = _temp_total(R, x)
    improved = True
    while improved:
        improved = False
        for a in range(NS):
            for b in range(a + 1, NS):
                s = x[a] + x[b]
                bb = None
                bu = 0
                for u in range(s + 1):
                    x[a] = u
                    x[b] = s - u
                    val = _temp_total(R, x)
                    if bb is None or val < bb:
                        bb = val
                        bu = u
                x[a] = bu
                x[b] = s - bu
                if bb is not None and bb < best:
                    best = bb
                    improved = True
    return x, best


def best_formal_alloc(R, f, qF=None, pT=None):
    """把 f 名正式工分配到 6 个班次：多起点 + 坐标下降 + 成对穷举，最小化人天数。

    目标：min Σ_s (x_s+y_s)，其中 y 由临时工（20 人效）按剩余小时货量贪心得到。
    （正式工 25 人效 > 临时工 20 人效，故正式工用满 f 名不会变差。）
    多起点：按纯正式工解比例、按纯临时工解比例、以及"全部集中在某一班次"共 8 个起点；
    与穷举最优对拍（code/_scratch_p3_test.py）200 例差距为 0。
    """
    if qF is None:
        qF = greedy_cover([cdiv(R[h], EFF_F) for h in range(24)])
    if pT is None:
        pT = greedy_cover([cdiv(R[h], EFF_T) for h in range(24)])
    starts = []
    for base in (qF, pT):
        t = sum(base) or 1
        starts.append([int(round(f * base[s] / float(t))) for s in range(NS)])
    for s in range(NS):
        e = [0] * NS
        e[s] = f
        starts.append(e)
    best_x, best_v = None, None
    for st in starts:
        x = list(st)
        d = sum(x) - f
        if d > 0:
            for s in range(NS - 1, -1, -1):
                k = min(d, x[s])
                x[s] -= k
                d -= k
        elif d < 0:
            x[NS - 1] += -d
        x, v = _descent_units(R, x)
        v = sum(x) + _temp_total(R, x)
        if best_v is None or v < best_v:
            best_v, best_x = v, x
    best_x, _ = _pair_realloc(R, best_x)
    return best_x, sum(best_x) + _temp_total(R, best_x)


def delete_redundant(R, x, y):
    """逐人删除：能删就删（只减不增人天数），直到不可删为止。"""
    x = list(x)
    y = list(y)
    changed = True
    while changed:
        changed = False
        for s in range(NS):
            if y[s] > 0:
                y[s] -= 1
                if is_feasible(R, x, y):
                    changed = True
                    continue
                y[s] += 1
            if x[s] > 0:
                x[s] -= 1
                if is_feasible(R, x, y):
                    changed = True
                    continue
                x[s] += 1
    return x, y


def balance_search(R, x, y, max_pass=12):
    """在"人天数不变"的解集内最小化 std(u_h)（人效均衡，第二目标）。

    允许的邻域（都不改变总人数，也不改变正式工人数）：
      A. 临时工从一个班次挪到另一个班次：y_a-1, y_b+1
      B. 正式工/临时工互换：x_a-1, x_b+1, y_a+1, y_b-1
    """
    x = list(x)
    y = list(y)
    if not is_feasible(R, x, y):
        return x, y
    best = util_stats(R, x, y)[0]
    for _ in range(max_pass):
        improved = False
        moves = []
        for a in range(NS):
            if y[a] > 0:
                for b in range(NS):
                    if a != b:
                        moves.append(("t", a, b))
            if x[a] > 0:
                for b in range(NS):
                    if a != b:
                        moves.append(("s", a, b))
        for kind, a, b in moves:
            if kind == "t":
                if y[a] <= 0:
                    continue
                y[a] -= 1
                y[b] += 1
            else:
                if x[a] <= 0:
                    continue
                x[a] -= 1
                x[b] += 1
                y[a] += 1
                y[b] -= 1
                if y[b] < 0:
                    x[a] += 1
                    x[b] -= 1
                    y[a] -= 1
                    y[b] += 1
                    continue
            if is_feasible(R, x, y):
                val = util_stats(R, x, y)[0]
                if val < best - 1e-12:
                    best = val
                    improved = True
                    continue
            # 回滚
            if kind == "t":
                y[a] += 1
                y[b] -= 1
            else:
                x[a] += 1
                x[b] -= 1
                y[a] -= 1
                y[b] += 1
        if not improved:
            break
    return x, y


# ================================================================ 主口径：允许积压的累计产能模型
# 到第 t 小时末，班次 s 已投入的人·小时数：w_s(t) = max(0, min(a_s+8, t+1) - a_s)
W_CUM = [[max(0, min(SHIFT_START[s] + 8, t + 1) - SHIFT_START[s]) for t in range(24)]
         for s in range(NS)]
# 自第 t 小时起（含第 t 小时）班次 s 还能投入的人·小时数：覆盖 [t, 24) 的小时数
REM_CUM = [[sum(1 for h in HOURS[s] if h >= t) for t in range(24)] for s in range(NS)]


def cum_arrival(R):
    """累计到货量 A(t) = Σ_{h<=t} D_h。"""
    out, acc = [], 0.0
    for h in range(24):
        acc += max(0.0, float(R[h]))
        out.append(acc)
    return out


def rem_arrival(R):
    """自第 t 小时起的剩余到货量（用于物理可执行性附加校验）。"""
    out, acc = [0.0] * 24, 0.0
    for h in range(23, -1, -1):
        acc += max(0.0, float(R[h]))
        out[h] = acc
    return out


def cum_capacity(x, y):
    """累计产能 C(t) = Σ_s (25x_s+20y_s)·w_s(t)。"""
    return [sum((EFF_F * int(x[s]) + EFF_T * int(y[s])) * W_CUM[s][t] for s in range(NS))
            for t in range(24)]


def rem_capacity(x, y):
    return [sum((EFF_F * int(x[s]) + EFF_T * int(y[s])) * REM_CUM[s][t] for s in range(NS))
            for t in range(24)]


def feasible_cum(R, x, y, tol=1e-9):
    """主口径可行性：∀t 累计产能 ≥ 累计到货。"""
    A = cum_arrival(R)
    C = cum_capacity(x, y)
    return all(C[t] + tol >= A[t] for t in range(24))


def verify_day_cum(R, x, y, tol=1e-9):
    """独立校验（主口径）：逐 t 检查累计产能 ≥ 累计到货；返回 (ok, 违约明细)。"""
    A = cum_arrival(R)
    C = cum_capacity(x, y)
    bad = [(t, A[t], C[t]) for t in range(24) if C[t] + tol < A[t]]
    return (len(bad) == 0), bad


def verify_day_hall(R, x, y, tol=1e-9):
    """附加（物理可执行性）：∀t 自 t 起的剩余产能 ≥ 自 t 起的剩余到货。"""
    A = rem_arrival(R)
    C = rem_capacity(x, y)
    bad = [(t, A[t], C[t]) for t in range(24) if C[t] + tol < A[t]]
    return (len(bad) == 0), bad


def simulate_work(R, x, y):
    """按"到货先积压、在岗产能优先处理积压"的流体仿真，得到逐小时实际处理量。

    返回 (work[24], 日末积压, 逐小时在岗产能 cap[24])。
    """
    cap = cover_capacity(x, y)
    backlog = 0.0
    work = [0.0] * 24
    for h in range(24):
        avail = backlog + max(0.0, float(R[h]))
        w = min(cap[h], avail)
        work[h] = w
        backlog = avail - w
    return work, backlog, cap


def util_stats_cum(R, x, y):
    """主口径人效指标：(均衡度 std(u), 均值 u, 人效 包裹/(人·小时))

    u_h = 第 h 小时实际处理量 / 第 h 小时在岗产能（仅统计产能>0 且实际有活可干的小时）。
    人效 = 当日总货量 / (8·总人数)，即"实际处理货量 / 在岗工时"。
    """
    work, backlog, cap = simulate_work(R, x, y)
    us = [work[h] / cap[h] for h in range(24) if cap[h] > 0 and work[h] > 1e-9]
    if us:
        m = sum(us) / len(us)
        sd = math.sqrt(sum((u - m) ** 2 for u in us) / len(us))
    else:
        m, sd = 0.0, 0.0
    people = sum(int(v) for v in x) + sum(int(v) for v in y)
    vol = float(sum(max(0.0, v) for v in R))
    eff = vol / (8.0 * people) if people else 0.0
    return sd, m, eff


def _cum_capacity_at(x, y, t):
    return sum((EFF_F * int(x[s]) + EFF_T * int(y[s])) * W_CUM[s][t] for s in range(NS))


def greedy_cum(R, formal_cap=FORMAL_CAP, hall=False):
    """主口径贪心：按 t 递增，累计产能不足时给"t 时刻在岗、且新增 1 人使累计产能增量最大"
    的班次加 1 人（先用正式工到 60，再用临时工）。

    hall=True 时追加"物理可执行性"修补：自 t 起的剩余产能 ≥ 自 t 起的剩余到货
    （否则积压货没有后来又上班的人去处理）。
    """
    A = cum_arrival(R)
    x, y = [0] * NS, [0] * NS
    for t in range(24):
        guard = 0
        while _cum_capacity_at(x, y, t) + 1e-9 < A[t]:
            cand = [s for s in range(NS)
                    if W_CUM[s][t] > 0 and SHIFT_START[s] <= t <= SHIFT_START[s] + 7]
            if not cand:
                cand = [s for s in range(NS) if W_CUM[s][t] > 0]
            s = max(cand, key=lambda k: (W_CUM[k][t], -SHIFT_START[k]))
            if sum(x) < formal_cap:
                x[s] += 1
            else:
                y[s] += 1
            guard += 1
            if guard > 100000:
                raise RuntimeError("累计约束贪心不收敛：%s" % (R,))
    if hall:
        avail = rem_arrival(R)
        for t in range(23, -1, -1):
            guard = 0
            while _cum_rem_capacity_at(x, y, t) + 1e-9 < avail[t]:
                cand = [s for s in range(NS) if REM_CUM[s][t] > 0]
                s = max(cand, key=lambda k: (REM_CUM[k][t], -SHIFT_START[k]))
                if sum(x) < formal_cap:
                    x[s] += 1
                else:
                    y[s] += 1
                guard += 1
                if guard > 100000:
                    raise RuntimeError("剩余产能修补不收敛：%s" % (R,))
    return x, y


def _cum_rem_capacity_at(x, y, t):
    return sum((EFF_F * int(x[s]) + EFF_T * int(y[s])) * REM_CUM[s][t] for s in range(NS))


# ---------------------------------------------------------------- 方案 A：单班占比上限（叠加在 Hall 上）
def _capped_greedy(R, M, formal_cap=FORMAL_CAP):
    """Hall 贪心 + 每个班次人数 ≤ M；不可行返回 None。"""
    avail = rem_arrival(R)
    x, y = [0] * NS, [0] * NS
    for t in range(23, -1, -1):
        guard = 0
        while _cum_rem_capacity_at(x, y, t) + 1e-9 < avail[t]:
            cand = [s for s in range(NS) if REM_CUM[s][t] > 0 and x[s] + y[s] < M]
            if not cand:
                return None
            s = max(cand, key=lambda k: (REM_CUM[k][t], -SHIFT_START[k]))
            if sum(x) < formal_cap:
                x[s] += 1
            else:
                y[s] += 1
            guard += 1
            if guard > 200000:
                return None
    return x, y


def cap_ok(x, y, share=0.40):
    """每班人数 ≤ share × 总人数（人数很少时按整数下限放宽到 1 人）。"""
    tot = sum(int(v) for v in x) + sum(int(v) for v in y)
    if tot <= 2:
        return True
    M = max(1, int(math.floor(share * tot)))
    return max(int(x[s]) + int(y[s]) for s in range(NS)) <= M


def solve_day_cap(R, share=0.40, do_balance=True):
    """Hall + 单班占比 ≤ share。

    做法：先求 Hall 最少人天数解；若某班次超过 share×总人数，就**往其它班次加人**把总人数抬高
    （加人只会增加产能，绝不破坏 Hall 可行性），直到 share×总人数 ≥ 该班次人数；
    再做逐人回删（同时查 Hall 与占比）与均衡搜索。
    """
    R = [max(0.0, float(v)) for v in R]
    x, y = greedy_backlog(R)
    x, y = delete_redundant_backlog(R, x, y)

    def _shift_tot(a, b, s):
        return int(a[s]) + int(b[s])

    # 阶段 1：把超限班次的人**搬**到其它班次（不增人天数），搬到搬不动为止
    for _ in range(200000):
        tot = sum(x) + sum(y)
        M = max(1, int(math.floor(share * tot)))
        over = [s for s in range(NS) if _shift_tot(x, y, s) > M]
        if not over:
            break
        moved = False
        for s in sorted(over, key=lambda k: -_shift_tot(x, y, k)):
            for kind in ("y", "x"):
                if (y if kind == "y" else x)[s] <= 0:
                    continue
                for s2 in range(NS):
                    if s2 == s or _shift_tot(x, y, s2) >= M:
                        continue
                    xx, yy = list(x), list(y)
                    (yy if kind == "y" else xx)[s] -= 1
                    (yy if kind == "y" else xx)[s2] += 1
                    if feasible_backlog(R, xx, yy):
                        x, y = xx, yy
                        moved = True
                        break
                if moved:
                    break
            if moved:
                break
        if moved:
            continue
        # 阶段 2：确实搬不动了，才给人数最少的班次加 1 人把总人数抬高（加人不破坏 Hall）
        s = min(range(NS), key=lambda k: (_shift_tot(x, y, k), k))
        if sum(x) < FORMAL_CAP:
            x[s] += 1
        else:
            y[s] += 1

    def ok(a, b):
        return feasible_backlog(R, a, b) and cap_ok(a, b, share)

    changed = True
    while changed:
        changed = False
        for s in range(NS):
            if y[s] > 0:
                y[s] -= 1
                if ok(x, y):
                    changed = True
                    continue
                y[s] += 1
            if x[s] > 0:
                x[s] -= 1
                if ok(x, y):
                    changed = True
                    continue
                x[s] += 1
    if do_balance:
        x, y = balance_search_generic(R, x, y, lambda a, b: ok(a, b))
    for s in range(NS):
        if x[s] < 0 or y[s] < 0:
            raise AssertionError("班次 %d 出现负人数：x=%s y=%s" % (s, x, y))
    okk, bad = verify_day_hall(R, x, y)
    if not okk:
        raise AssertionError("占比上限口径破坏 Hall：%s" % (bad[:3],))
    work, backlog, _cap = simulate_work(R, x, y)
    sd, mean_u, eff = util_stats_cum(R, x, y)
    vol = float(sum(max(0.0, v) for v in R))
    info = {"mode": "mixed" if sum(x) >= FORMAL_CAP else "formal_only",
            "lb_pure": cdiv(vol, EFF_F * 8), "people": sum(x) + sum(y),
            "formal": sum(x), "temp": sum(y),
            "util_std": sd, "util_mean": mean_u, "eff": eff,
            "backlog_end": backlog, "hall_ok": okk, "cap_ok": cap_ok(x, y, share),
            "max_shift": max(int(x[s]) + int(y[s]) for s in range(NS))}
    return x, y, info


# ---------------------------------------------------------------- 真正的"允许积压"口径（物理可执行）
def greedy_backlog(R, formal_cap=FORMAL_CAP):
    """按 t 从 23 递减推进：自 t 起的剩余产能不足时，给"覆盖 [t,24) 且新增 1 人
    带来剩余产能增量最大"的班次加 1 人（先用正式工到 60，再用临时工）。

    该约束即"货可积压，但必须有后来上班的人把它清掉"（剩余产能 ≥ 剩余到货），
    与严格逐小时口径相比允许把早高峰的货留到后续班次处理。
    """
    avail = rem_arrival(R)
    x, y = [0] * NS, [0] * NS
    for t in range(23, -1, -1):
        guard = 0
        while _cum_rem_capacity_at(x, y, t) + 1e-9 < avail[t]:
            cand = [s for s in range(NS) if REM_CUM[s][t] > 0]
            s = max(cand, key=lambda k: (REM_CUM[k][t], -SHIFT_START[k]))
            if sum(x) < formal_cap:
                x[s] += 1
            else:
                y[s] += 1
            guard += 1
            if guard > 100000:
                raise RuntimeError("剩余产能贪心不收敛：%s" % (R,))
    return x, y


def feasible_backlog(R, x, y, tol=1e-9):
    """允许积压口径的可行性：∀t 剩余产能 ≥ 剩余到货（等价于 Hall 条件）。"""
    return verify_day_hall(R, x, y, tol=tol)[0]


def delete_redundant_backlog(R, x, y):
    """逐人回删（允许积压口径），只减不增人天数。"""
    x, y = list(x), list(y)
    changed = True
    while changed:
        changed = False
        for s in range(NS):
            if y[s] > 0:
                y[s] -= 1
                if feasible_backlog(R, x, y):
                    changed = True
                    continue
                y[s] += 1
            if x[s] > 0:
                x[s] -= 1
                if feasible_backlog(R, x, y):
                    changed = True
                    continue
                x[s] += 1
    return x, y


def _repair_backlog(R, x, y, formal_cap):
    """把不可行解修补到可行（贪心加人）。"""
    x, y = list(x), list(y)
    avail = rem_arrival(R)
    for t in range(23, -1, -1):
        guard = 0
        while _cum_rem_capacity_at(x, y, t) + 1e-9 < avail[t]:
            cand = [s for s in range(NS) if REM_CUM[s][t] > 0]
            s = max(cand, key=lambda k: (REM_CUM[k][t], -SHIFT_START[k]))
            if sum(x) < formal_cap:
                x[s] += 1
            else:
                y[s] += 1
            guard += 1
            if guard > 100000:
                break
    return x, y


def improve_backlog(R, x, y, formal_cap=FORMAL_CAP, max_round=40):
    """先用"去掉 1 人 + 邻域修补"再压缩人天数，再在人数不变下均衡人效。

    邻域：任意两班次之间搬 1 人（临时工）或做正式工/临时工互换。
    """
    x, y = list(x), list(y)
    best = sum(x) + sum(y)
    # 1) 尝试逐人删减并修补（修补后总人数若变小则接受）
    improved = True
    round_ = 0
    while improved and round_ < max_round:
        round_ += 1
        improved = False
        for s in range(NS):
            for kind in ("y", "x"):
                if (y if kind == "y" else x)[s] <= 0:
                    continue
                xx, yy = list(x), list(y)
                (yy if kind == "y" else xx)[s] -= 1
                if not feasible_backlog(R, xx, yy):
                    xx, yy = _repair_backlog(R, xx, yy, formal_cap)
                    if not feasible_backlog(R, xx, yy):
                        continue
                if sum(xx) + sum(yy) < best:
                    best = sum(xx) + sum(yy)
                    x, y = xx, yy
                    improved = True
    # 2) 人数不变，搬人/互换以降低不可行风险与峰值
    for _ in range(6):
        moved = False
        for a in range(NS):
            for b in range(NS):
                if a == b:
                    continue
                for kind in ("move", "swap"):
                    xx, yy = list(x), list(y)
                    if kind == "move":
                        if yy[a] <= 0:
                            continue
                        yy[a] -= 1
                        yy[b] += 1
                    else:
                        if xx[a] <= 0 or yy[b] <= 0:
                            continue
                        xx[a] -= 1
                        xx[b] += 1
                        yy[a] += 1
                        yy[b] -= 1
                    if sum(xx) + sum(yy) != best or not feasible_backlog(R, xx, yy):
                        continue
                    # 以"各小时产能与到货的匹配度"为次要目标
                    if _slack_score(R, xx, yy) < _slack_score(R, x, y) - 1e-9:
                        x, y = xx, yy
                        moved = True
        if not moved:
            break
    return x, y


def _slack_score(R, x, y):
    """辅助指标：逐小时"在岗产能 - 该小时到货"的平方和（越小说明人力与到货越贴合）。"""
    cap = cover_capacity(x, y)
    return sum((cap[h] - max(0.0, float(R[h]))) ** 2 for h in range(24))


def solve_day_backlog(R, formal_cap=FORMAL_CAP, do_balance=True):
    """允许积压口径：单个 (中心, 日) 的最少人天数解。返回 (x, y, info)。"""
    R = [max(0.0, float(v)) for v in R]
    x, y = greedy_backlog(R, formal_cap)
    x, y = delete_redundant_backlog(R, x, y)
    x, y = improve_backlog(R, x, y, formal_cap)
    x, y = delete_redundant_backlog(R, x, y)
    if do_balance:
        x, y = balance_search_cum(R, x, y, hall=True)
    for s in range(NS):
        if x[s] < 0 or y[s] < 0:
            raise AssertionError("班次 %d 出现负人数：x=%s y=%s" % (s, x, y))
    ok, bad = verify_day_hall(R, x, y)
    if not ok:
        raise AssertionError("允许积压口径不可行：%s" % (bad[:3],))
    work, backlog, _cap = simulate_work(R, x, y)
    sd, mean_u, eff = util_stats_cum(R, x, y)
    vol = float(sum(max(0.0, v) for v in R))
    lb_cd = cdiv(vol, EFF_F * 8)
    info = {"mode": "mixed" if sum(x) >= formal_cap else "formal_only",
            "lb_pure": lb_cd, "people": sum(x) + sum(y),
            "formal": sum(x), "temp": sum(y),
            "util_std": sd, "util_mean": mean_u, "eff": eff,
            "backlog_end": backlog, "hall_ok": ok,
            "cum_ok": verify_day_cum(R, x, y)[0]}
    return x, y, info


# ---------------------------------------------------------------- 8 小时周转口径（滑动窗口）
# 对每个时刻 T=1..24：窗口 [max(0,T-8), T)，要求
#   Σ_s (25x_s+20y_s)·|[a_s, a_s+8) ∩ [T-8, T)| ≥ Σ_{h∈[T-8,T)} D_h
# 即"最近 8 小时到达的货必须在 T 之前清掉"。T=24 的那条覆盖 16-23 时到货（当天清空），
# 而 T=8..23 的各条把"积压时长"钉死在 8 小时以内；三块不相交窗口相加即得日总量约束。
TURN_WINDOWS = []
for _T in range(1, 25):
    _lo, _hi = max(0, _T - 8), _T
    TURN_WINDOWS.append({"T": _T, "lo": _lo, "hi": _hi,
                         "ov": [max(0, min(a + 8, _hi) - max(a, _lo)) for a in SHIFT_START]})


def turn_demand(R):
    return [sum(max(0.0, float(R[h])) for h in range(w["lo"], w["hi"])) for w in TURN_WINDOWS]


def turn_cap(x, y, i):
    ov = TURN_WINDOWS[i]["ov"]
    return sum((EFF_F * int(x[s]) + EFF_T * int(y[s])) * ov[s] for s in range(NS))


def feasible_turn8(R, x, y, tol=1e-9):
    D = turn_demand(R)
    return all(turn_cap(x, y, i) + tol >= D[i] for i in range(len(D)))


def verify_day_turn8(R, x, y, tol=1e-9):
    """独立校验（8 小时周转口径）：逐窗口检查；返回 (ok, 违约明细)。"""
    D = turn_demand(R)
    bad = []
    for i, w in enumerate(TURN_WINDOWS):
        c = turn_cap(x, y, i)
        if c + tol < D[i]:
            bad.append((w["T"], w["lo"], w["hi"], D[i], c))
    return (len(bad) == 0), bad


def greedy_turn8(R, formal_cap=FORMAL_CAP):
    """8 小时周转口径贪心：按窗口 T 递增，缺口加给"在该窗口内覆盖小时数最多"的班次。"""
    D = turn_demand(R)
    x, y = [0] * NS, [0] * NS
    for i, w in enumerate(TURN_WINDOWS):
        guard = 0
        while turn_cap(x, y, i) + 1e-9 < D[i]:
            ov = w["ov"]
            cand = [s for s in range(NS) if ov[s] > 0]
            s = max(cand, key=lambda k: (ov[k], SHIFT_START[k]))
            if sum(x) < formal_cap:
                x[s] += 1
            else:
                y[s] += 1
            guard += 1
            if guard > 100000:
                raise RuntimeError("8 小时周转贪心不收敛：%s" % (R,))
    return x, y


def _repair_turn8(R, x, y, formal_cap=FORMAL_CAP):
    return greedy_turn8_add(R, formal_cap, x, y)


def greedy_turn8_add(R, formal_cap, x0, y0):
    """在已有解上按窗口缺口继续加人，直到可行。"""
    D = turn_demand(R)
    x, y = list(x0), list(y0)
    for i, w in enumerate(TURN_WINDOWS):
        guard = 0
        while turn_cap(x, y, i) + 1e-9 < D[i]:
            ov = w["ov"]
            cand = [s for s in range(NS) if ov[s] > 0]
            s = max(cand, key=lambda k: (ov[k], SHIFT_START[k]))
            if sum(x) < formal_cap:
                x[s] += 1
            else:
                y[s] += 1
            guard += 1
            if guard > 100000:
                break
    return x, y


def delete_redundant_turn8(R, x, y):
    x, y = list(x), list(y)
    changed = True
    while changed:
        changed = False
        for s in range(NS):
            if y[s] > 0:
                y[s] -= 1
                if feasible_turn8(R, x, y):
                    changed = True
                    continue
                y[s] += 1
            if x[s] > 0:
                x[s] -= 1
                if feasible_turn8(R, x, y):
                    changed = True
                    continue
                x[s] += 1
    return x, y


def improve_turn8(R, x, y, formal_cap=FORMAL_CAP, max_round=40):
    """先"删 1 人 + 修补"压缩人天数，再在人数不变下搬人/互换做均衡。"""
    x, y = list(x), list(y)
    best = sum(x) + sum(y)
    improved, round_ = True, 0
    while improved and round_ < max_round:
        round_ += 1
        improved = False
        for s in range(NS):
            for kind in ("y", "x"):
                if (y if kind == "y" else x)[s] <= 0:
                    continue
                xx, yy = list(x), list(y)
                (yy if kind == "y" else xx)[s] -= 1
                if not feasible_turn8(R, xx, yy):
                    xx, yy = greedy_turn8_add(R, formal_cap, xx, yy)
                    if not feasible_turn8(R, xx, yy):
                        continue
                if sum(xx) + sum(yy) < best:
                    best = sum(xx) + sum(yy)
                    x, y = xx, yy
                    improved = True
    for _ in range(6):
        moved = False
        for a in range(NS):
            for b in range(NS):
                if a == b:
                    continue
                for kind in ("move", "swap"):
                    xx, yy = list(x), list(y)
                    if kind == "move":
                        if yy[a] <= 0:
                            continue
                        yy[a] -= 1
                        yy[b] += 1
                    else:
                        if xx[a] <= 0 or yy[b] <= 0:
                            continue
                        xx[a] -= 1
                        xx[b] += 1
                        yy[a] += 1
                        yy[b] -= 1
                    if sum(xx) + sum(yy) != best or not feasible_turn8(R, xx, yy):
                        continue
                    if _slack_score(R, xx, yy) < _slack_score(R, x, y) - 1e-9:
                        x, y = xx, yy
                        moved = True
        if not moved:
            break
    return x, y


def solve_day_turn8(R, formal_cap=FORMAL_CAP, do_balance=True):
    """8 小时周转口径：单个 (中心, 日) 的最少人天数解。返回 (x, y, info)。"""
    R = [max(0.0, float(v)) for v in R]
    x, y = greedy_turn8(R, formal_cap)
    x, y = delete_redundant_turn8(R, x, y)
    x, y = improve_turn8(R, x, y, formal_cap)
    x, y = delete_redundant_turn8(R, x, y)
    if do_balance:
        x, y = balance_search_generic(R, x, y, lambda a, b: feasible_turn8(R, a, b))
    for s in range(NS):
        if x[s] < 0 or y[s] < 0:
            raise AssertionError("班次 %d 出现负人数：x=%s y=%s" % (s, x, y))
    ok, bad = verify_day_turn8(R, x, y)
    if not ok:
        raise AssertionError("8 小时周转口径不可行：%s" % (bad[:3],))
    work, backlog, _cap = simulate_work(R, x, y)
    sd, mean_u, eff = util_stats_cum(R, x, y)
    vol = float(sum(max(0.0, v) for v in R))
    info = {"mode": "mixed" if sum(x) >= formal_cap else "formal_only",
            "lb_pure": cdiv(vol, EFF_F * 8), "people": sum(x) + sum(y),
            "formal": sum(x), "temp": sum(y),
            "util_std": sd, "util_mean": mean_u, "eff": eff,
            "backlog_end": backlog, "hall_ok": verify_day_hall(R, x, y)[0],
            "cum_ok": verify_day_cum(R, x, y)[0], "turn8_ok": ok}
    return x, y, info


def balance_search_generic(R, x, y, feas, max_pass=10):
    """通用均衡搜索：保持人数不变，按 std(u_h) 下降方向搬人/互换（feas 为可行性判定）。"""
    x, y = list(x), list(y)
    if not feas(x, y):
        return x, y
    best = util_stats_cum(R, x, y)[0]
    for _ in range(max_pass):
        improved = False
        for a in range(NS):
            for b in range(NS):
                if a == b:
                    continue
                if y[a] > 0:
                    y[a] -= 1
                    y[b] += 1
                    if feas(x, y):
                        val = util_stats_cum(R, x, y)[0]
                        if val < best - 1e-12:
                            best = val
                            improved = True
                            continue
                    y[a] += 1
                    y[b] -= 1
                if x[a] > 0 and y[b] > 0:
                    x[a] -= 1
                    x[b] += 1
                    y[a] += 1
                    y[b] -= 1
                    if y[b] >= 0 and feas(x, y):
                        val = util_stats_cum(R, x, y)[0]
                        if val < best - 1e-12:
                            best = val
                            improved = True
                            continue
                    x[a] += 1
                    x[b] -= 1
                    y[a] -= 1
                    y[b] += 1
        if not improved:
            break
    return x, y


def delete_redundant_cum(R, x, y, hall=False):
    """逐人回删：删掉后仍满足全部累计约束才允许删（只减不增人天数）。"""
    x, y = list(x), list(y)

    def ok():
        if not feasible_cum(R, x, y):
            return False
        if hall:
            return verify_day_hall(R, x, y)[0]
        return True

    changed = True
    while changed:
        changed = False
        for s in range(NS):
            if y[s] > 0:
                y[s] -= 1
                if ok():
                    changed = True
                    continue
                y[s] += 1
            if x[s] > 0:
                x[s] -= 1
                if ok():
                    changed = True
                    continue
                x[s] += 1
    return x, y


def balance_search_cum(R, x, y, max_pass=12, hall=False):
    """第二目标（主口径）：在人数不变的前提下最小化逐小时利用率 std(u_h)。

    邻域同严格口径：临时工换班次、正式工/临时工互换；每次都检查累计约束。
    """
    x, y = list(x), list(y)

    def ok():
        if not feasible_cum(R, x, y):
            return False
        if hall:
            return verify_day_hall(R, x, y)[0]
        return True

    best = util_stats_cum(R, x, y)[0]
    for _ in range(max_pass):
        improved = False
        for a in range(NS):
            for b in range(NS):
                if a == b:
                    continue
                # A. 临时工换班次
                if y[a] > 0:
                    y[a] -= 1
                    y[b] += 1
                    if ok():
                        val = util_stats_cum(R, x, y)[0]
                        if val < best - 1e-12:
                            best = val
                            improved = True
                            continue
                    y[a] += 1
                    y[b] -= 1
                # B. 正式工/临时工互换
                if x[a] > 0 and y[b] > 0:
                    x[a] -= 1
                    x[b] += 1
                    y[a] += 1
                    y[b] -= 1
                    if y[b] >= 0 and ok():
                        val = util_stats_cum(R, x, y)[0]
                        if val < best - 1e-12:
                            best = val
                            improved = True
                            continue
                    x[a] += 1
                    x[b] -= 1
                    y[a] -= 1
                    y[b] += 1
        if not improved:
            break
    return x, y


def solve_day_cum(R, formal_cap=FORMAL_CAP, do_balance=True, hall=False):
    """主口径：单个 (中心, 日) 的最少人天数解（累计产能约束）。返回 (x, y, info)。"""
    R = [max(0.0, float(v)) for v in R]
    x, y = greedy_cum(R, formal_cap, hall=hall)
    x, y = delete_redundant_cum(R, x, y, hall=hall)
    if do_balance:
        x, y = balance_search_cum(R, x, y, hall=hall)
    for s in range(NS):
        if x[s] < 0 or y[s] < 0:
            raise AssertionError("班次 %d 出现负人数：x=%s y=%s" % (s, x, y))
    ok, bad = verify_day_cum(R, x, y)
    if not ok:
        raise AssertionError("累计口径不可行：%s" % (bad[:3],))
    sd, mean_u, eff = util_stats_cum(R, x, y)
    work, backlog, _cap = simulate_work(R, x, y)
    vol = float(sum(max(0.0, v) for v in R))
    # 人天数下界（该口径）：全部按正式工完成日总量的工时下界
    lb_cd = cdiv(vol, EFF_F * 8)
    info = {"mode": "mixed" if sum(x) >= formal_cap else "formal_only",
            "lb_pure": lb_cd, "people": sum(x) + sum(y),
            "formal": sum(x), "temp": sum(y),
            "util_std": sd, "util_mean": mean_u, "eff": eff,
            "backlog_end": backlog,
            "hall_ok": verify_day_hall(R, x, y)[0]}
    return x, y, info


def solve_day_strict(R, formal_cap=FORMAL_CAP, do_balance=True):
    """单个 (中心, 日) 的最优/近似最优排班。返回 (x, y, info)。"""
    R = [max(0.0, float(v)) for v in R]
    needF = [cdiv(R[h], EFF_F) for h in range(24)]
    qF = greedy_cover(needF)                      # 纯正式工最优人数（= 人天数下界）
    lb_pure = sum(qF)
    if lb_pure <= formal_cap:
        x, y = list(qF), [0] * NS
        mode = "formal_only"
    else:
        # 正式工上限起作用：60 名正式工按"多起点 + 成对穷举"放到最需要的班次，缺口用临时工
        pT = greedy_cover([cdiv(R[h], EFF_T) for h in range(24)])
        if formal_cap <= 0:
            x = [0] * NS
        else:
            x, _ = best_formal_alloc(R, formal_cap, qF=qF, pT=pT)
        y = temp_cover(R, x)
        x, y = delete_redundant(R, x, y)
        mode = "mixed"
    if do_balance:
        x, y = balance_search(R, x, y)
    # 硬断言：人数必须是非负整数
    for s in range(NS):
        if x[s] < 0 or y[s] < 0:
            raise AssertionError("班次 %d 出现负人数：x=%s y=%s" % (s, x, y))
    sd, mean_u, eff = util_stats(R, x, y)
    info = {"mode": mode, "lb_pure": lb_pure,
            "people": sum(x) + sum(y), "formal": sum(x), "temp": sum(y),
            "util_std": sd, "util_mean": mean_u, "eff": eff}
    return x, y, info


# ---------------------------------------------------------------- 算法自检
def self_test_greedy(n_case=300, seed=7):
    """贪心正确性对拍：随机小规模需求，与 6 变量穷举比对最小人数。"""
    import itertools
    import random
    rng = random.Random(seed)
    bad = 0
    for _ in range(n_case):
        need = [rng.randint(0, 4) for _ in range(24)]
        g = sum(greedy_cover(need))
        M = max(need) if need else 0
        best = 10 ** 9
        for q in itertools.product(range(M + 1), repeat=NS):
            if sum(q) >= best:
                continue
            if all(sum(q[s] for s in COVER[h]) >= need[h] for h in range(24)):
                best = sum(q)
        if g != best:
            bad += 1
            print("  [对拍失败] need=%s greedy=%d brute=%d" % (need, g, best))
    print("  贪心对拍：%d 例，失败 %d 例" % (n_case, bad))
    return bad == 0


def self_test_mixed(n_case=60, seed=11):
    """混合情形对拍：与"枚举全部正式工分配 x + 临时工贪心"的精确最优比较。

    f ≤ 4 时 Σx ≤ f 的整数分配只有数百~上万种，可完全枚举，因此这是精确参考解。
    """
    import itertools
    import random
    rng = random.Random(seed)
    bad = 0
    worst = 0
    for _ in range(n_case):
        scale = rng.choice([1, 2, 3])
        R = [rng.randint(0, 40 * scale) if rng.random() < 0.8 else 0 for _ in range(24)]
        f = rng.choice([0, 1, 2, 3, 4])
        best = None
        for x in itertools.product(range(f + 1), repeat=NS):
            if sum(x) > f:
                continue
            v = sum(x) + _temp_total(R, list(x))
            if best is None or v < best:
                best = v
        xs, ys, _info = solve_day(R, formal_cap=f, do_balance=False)
        got = sum(xs) + sum(ys)
        if got != best:
            bad += 1
            worst = max(worst, got - best)
    print("  混合情形对拍：%d 例，失败 %d 例，最大超出 %d 人" % (n_case, bad, worst))
    return bad == 0


# ---------------------------------------------------------------- 主流程
def build_rows(demand, centers, verbose=True, model="cum", hall=False):
    rows = []
    day_stats = []
    n_mixed = 0
    n_fail = 0
    for c in centers:
        for k in range(N_DAY):
            R = demand[(c, k)]
            if model == "cum":
                x, y, info = solve_day_cum(R, hall=hall)
                ok, bad = verify_day_cum(R, x, y)
            elif model == "backlog":
                x, y, info = solve_day_backlog(R)
                ok, bad = verify_day_hall(R, x, y)
            elif model == "turn8":
                x, y, info = solve_day_turn8(R)
                ok, bad = verify_day_turn8(R, x, y)
            elif model == "cap40":
                x, y, info = solve_day_cap(R)
                ok, bad = verify_day_hall(R, x, y)
            else:
                x, y, info = solve_day_strict(R)
                ok, bad = verify_day(R, x, y)
            if not ok:
                n_fail += 1
                print("  [校验失败] %s %s：%s" % (c, DATES[k], bad[:3]))
            if info["mode"] == "mixed":
                n_mixed += 1
            for s in range(NS):
                rows.append((c, DATES[k], SHIFT_NAMES[s], int(x[s]), int(y[s])))
            vol = float(sum(R))
            day_stats.append({
                "center": c, "day": DATES[k], "volume": vol,
                "people": info["people"], "formal": info["formal"], "temp": info["temp"],
                "mode": info["mode"], "lb_pure": info["lb_pure"],
                "util_std": info["util_std"], "util_mean": info["util_mean"], "eff": info["eff"],
                "hall_ok": info.get("hall_ok", True), "backlog_end": info.get("backlog_end", 0.0),
            })
        if verbose:
            print("  %-5s 完成（%d/%d）" % (c, centers.index(c) + 1, len(centers)))
    return rows, day_stats, n_mixed, n_fail


def summarize(rows, day_stats, demand, centers, meta, model="cum"):
    df = pd.DataFrame(rows, columns=OUT_COLS)
    tot_people = int(df["正式工人数"].sum() + df["临时工人数"].sum())
    tot_formal = int(df["正式工人数"].sum())
    tot_temp = int(df["临时工人数"].sum())
    vol = float(sum(float(np.sum(demand[(c, k)])) for c in centers for k in range(N_DAY)))

    per_day = {}
    for r in day_stats:
        d = per_day.setdefault(r["day"], {"volume": 0.0, "people": 0, "formal": 0, "temp": 0})
        d["volume"] += r["volume"]
        d["people"] += r["people"]
        d["formal"] += r["formal"]
        d["temp"] += r["temp"]
    day_list = []
    for d in DATES:
        v = per_day[d]
        day_list.append({
            "date": d, "volume": round(v["volume"], 2), "people": v["people"],
            "formal": v["formal"], "temp": v["temp"],
            "eff": round(v["volume"] / (8.0 * v["people"]), 4) if v["people"] else 0.0,
        })

    util_std = [r["util_std"] for r in day_stats]
    util_mean = [r["util_mean"] for r in day_stats]
    effs = [r["eff"] for r in day_stats]
    lb_pure = sum(r["lb_pure"] for r in day_stats)
    lb_work = vol / (8.0 * EFF_F)     # 总工时下界（全部按正式工人效）

    center_tot = {}
    for r in day_stats:
        a = center_tot.setdefault(r["center"], {"people": 0, "formal": 0, "temp": 0, "volume": 0.0})
        a["people"] += r["people"]
        a["formal"] += r["formal"]
        a["temp"] += r["temp"]
        a["volume"] += r["volume"]
    center_list = [{"center": c,
                    "people": center_tot[c]["people"],
                    "person_day": round(center_tot[c]["people"] / 30.0, 2),
                    "formal": center_tot[c]["formal"],
                    "temp": center_tot[c]["temp"],
                    "eff": round(center_tot[c]["volume"] / (8.0 * center_tot[c]["people"]), 3),
                    "formal_pct": round(100.0 * center_tot[c]["formal"] / center_tot[c]["people"], 2)}
                   for c in centers]

    top_temp = sorted(day_list, key=lambda x: -x["temp"])[:5]

    stats = {
        "data_source": meta,
        "n_center": len(centers),
        "n_day": N_DAY,
        "n_shift": NS,
        "n_row": len(df),
        "total_volume": round(vol, 2),
        "person_days": tot_people,
        "formal_person_days": tot_formal,
        "temp_person_days": tot_temp,
        "formal_share": round(100.0 * tot_formal / tot_people, 2),
        "temp_share": round(100.0 * tot_temp / tot_people, 2),
        "people_per_day": round(tot_people / float(N_DAY), 2),
        "eff_mean": round(float(np.mean(effs)), 4),
        "eff_person_day": round(vol / float(tot_people), 2),
        "eff_std_between_days": round(float(np.std(effs)), 4),
        "eff_min": round(float(np.min(effs)), 4),
        "eff_max": round(float(np.max(effs)), 4),
        "util_mean": round(float(np.mean(util_mean)), 4),
        "util_std_mean": round(float(np.mean(util_std)), 4),
        "util_std_max": round(float(np.max(util_std)), 4),
        "lb_pure_formal": lb_pure,
        "lb_work": round(lb_work, 2),
        "gap_pure_pct": round(100.0 * (tot_people - lb_pure) / lb_pure, 3) if lb_pure else 0.0,
        "gap_work_pct": round(100.0 * (tot_people - lb_work) / lb_work, 3) if lb_work else 0.0,
        "n_mixed_center_day": int(sum(1 for r in day_stats if r["mode"] == "mixed")),
        "n_center_day": len(day_stats),
        "model": model,
        "n_hall_fail": int(sum(1 for r in day_stats if not r.get("hall_ok", True))),
        "max_backlog_end": round(float(max(r.get("backlog_end", 0.0) for r in day_stats)), 2),
        "days": day_list,
        "top_temp_days": top_temp,
        "centers": center_list,
        "max_formal_per_center_day": int(max(r["formal"] for r in day_stats)),
        "min_formal_per_center_day": int(min(r["formal"] for r in day_stats)),
    }
    return df, stats


def write_table(df, path):
    """写表；若目标目录在本会话沙箱中只读（结果/结果、附件），自动回退到 提交/ 并提示。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        df.to_csv(path, index=False, encoding="gbk")
        print("  已写出 %s（%d 行，gbk）" % (os.path.relpath(path, ROOT), len(df)))
        return path
    except PermissionError:
        alt_dir = os.path.join(ROOT, "提交")
        os.makedirs(alt_dir, exist_ok=True)
        alt = os.path.join(alt_dir, os.path.basename(path))
        df.to_csv(alt, index=False, encoding="gbk")
        print("  ⚠ 目标目录只读（沙箱保护），已改写到 %s（%d 行，gbk）"
              % (os.path.relpath(alt, ROOT), len(df)))
        print("    请把该文件复制到 结果/结果/ 下（正式提交路径）。")
        return alt


def main(argv=None):
    ap = argparse.ArgumentParser(description="问题 3：出勤人数（结果表 5）")
    ap.add_argument("--source", default="auto", choices=["auto", "pred", "hourly"],
                    help="需求曲线来源：pred=问题2小时预测，hourly=附件2（dev），auto=有 pred 就用")
    ap.add_argument("--model", default="backlog",
                    choices=["backlog", "cap40", "turn8", "cum", "strict"],
                    help="backlog=允许积压+日末清零；turn8=到达后 8 小时内处理完（滑动窗口）；"
                         "cum=累计公式（仅作对照）；strict=严格逐小时（灵敏度）")
    ap.add_argument("--hall", action="store_true",
                    help="附加物理可执行性约束：自 t 起的剩余产能 ≥ 剩余到货（默认不启用，仅校验）")
    ap.add_argument("--tag", default=None, help="输出文件名后缀，如 dev")
    ap.add_argument("--out-dir", default=None, help="输出目录，默认 结果/结果")
    ap.add_argument("--out-file", default=None, help="直接指定输出文件名")
    ap.add_argument("--no-balance", action="store_true", help="关闭人效均衡的第二目标搜索")
    ap.add_argument("--no-self-test", action="store_true")
    args = ap.parse_args(argv)

    print("=" * 78)
    print("问题 3 —— 57 中心 × 30 天 × 6 班次 的最少人天数排班")
    print("口径：%s" % {"backlog": "允许积压 + 日末清零（剩余产能≥剩余到货，主口径）",
                     "cap40": "Hall + 单班占比 ≤40%（方案 A）",
                     "turn8": "到达后 8 小时内处理完（滑动 8 小时窗口）",
                     "cum": "累计产能≥累计到货（主 agent 指定公式，对照）",
                     "strict": "严格逐小时（不允许积压，灵敏度）"}[args.model])
    print("=" * 78)
    if not args.no_self_test:
        print("[0] 贪心正确性自检（与穷举对拍）")
        self_test_greedy()

    print("[1] 读取需求曲线")
    demand, meta = load_demand(args.source)
    centers = meta["centers"]
    print("  数据源：%s（%d 中心 × %d 天，合计货量 %.0f）"
          % (meta["path"], meta["n_center"], N_DAY, meta["total_volume"]))
    if meta["source"] == "hourly":
        print("  ⚠ dev 模式：用附件 2 的 11 月小时货量作为需求曲线的代理，"
              "表 5 仅供算法联调，正式结果需 pred_hourly.csv")

    print("[2] 逐 (中心, 日) 求解整数规划")
    rows, day_stats, n_mixed, n_fail = build_rows(demand, centers, model=args.model, hall=args.hall)
    if n_fail:
        raise SystemExit("有 %d 个 (中心, 日) 未通过产能校验，拒绝写表！" % n_fail)
    print("  全部 %d 个 (中心, 日) 通过产能校验" % len(day_stats))

    print("[3] 汇总统计")
    df, stats = summarize(rows, day_stats, demand, centers, meta, model=args.model)
    print("  总人天数 %d（正式工 %d = %.2f%%，临时工 %d = %.2f%%）"
          % (stats["person_days"], stats["formal_person_days"], stats["formal_share"],
             stats["temp_person_days"], stats["temp_share"]))
    print("  日均 %.2f 人，人天数下界（该口径工时下界）%d（gap %.3f%%）"
          % (stats["people_per_day"], stats["lb_pure_formal"], stats["gap_pure_pct"]))
    print("  人效 %.3f 包裹/(人·小时)（日间标准差 %.3f；折合 %.1f 包裹/人天），小时利用率 %.3f±%.3f"
          % (stats["eff_mean"], stats["eff_std_between_days"], stats["eff_person_day"],
             stats["util_mean"], stats["util_std_mean"]))
    print("  正式工上限起作用的 (中心,日)：%d / %d；日末积压未清空的最大值 %.2f"
          % (stats["n_mixed_center_day"], stats["n_center_day"], stats["max_backlog_end"]))
    print("  附加物理校验（剩余产能≥剩余到货）未通过的中心·日：%d" % stats["n_hall_fail"])

    # 安全阀：非 pred 数据源（11 月代理曲线）绝不覆盖正式表
    tag = args.tag
    if tag is None:
        tag = None if meta["source"] == "pred" else "dev"
    if args.out_file:
        out_csv = args.out_file
    else:
        if args.out_dir:
            out_dir = args.out_dir
        elif tag == "dev":
            out_dir = DEV_DIR
        elif args.model != "backlog":
            out_dir = DATA_DIR
        else:
            out_dir = RES_DIR
        suffix = "_%s" % tag if tag else ""
        name = "结果表5%s.csv" % suffix
        if args.model == "strict":
            name = "alt_strict_hourly_表5%s.csv" % suffix
        elif args.model == "cum":
            name = "alt_cum_aggregate_表5%s.csv" % suffix
        elif args.model == "turn8":
            name = "alt_turn8_表5%s.csv" % suffix
        elif args.model == "cap40":
            name = "alt_cap40_表5%s.csv" % suffix
        out_csv = os.path.join(out_dir, name)
    write_table(df, out_csv)

    sp_name = "p3_stats%s.json" % ("" if args.model == "backlog" else "_" + args.model)
    stats_path = os.path.join(DATA_DIR, sp_name)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print("  统计已写出 %s" % os.path.relpath(stats_path, ROOT))
    return stats


if __name__ == "__main__":
    main()
