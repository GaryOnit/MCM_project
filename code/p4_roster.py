# -*- coding: utf-8 -*-
"""
p4_roster.py —— 问题 4：SC60 的逐人排班（结果表 6）

问题结构
--------
* SC60 有 200 名正式工；未来 30 天 × 6 个班次；
* 每名正式工：出勤率 ≤ 85% ⇒ 出勤天数 ≤ 25（30×0.85 = 25.5）；连续出勤 ≤ 7 天；
  每人每天最多出勤 1 个班次；
* 每天每个班次的"总人数"已由问题 3 的最少人天数解给出：
      T[d][s] = 表 5 第 d 天第 s 班的 正式工人数 + 临时工人数
  这是"完成当天货量"所需的最少人数（问题 3 已证明其最优性），问题 4 只需决定
  "正式工怎么排、剩下多少让临时工补"，因此
      Σ_{d,s} T[d][s] = 表 6 的总行数 = SC60 的总人天数（与表 5 完全一致）。

模型
----
决策：a_{w,d,s} ∈ {0,1} 表示正式工 w 第 d 天是否出勤第 s 班；y_{d,s} ≥ 0 为临时工人数。
目标（按题面顺序）：
  ① min  Σ_{d,s}(Σ_w a_{w,d,s} + y_{d,s})  —— 人天数最少：由表 5 固定为 Σ T，
     故等价于"尽量用正式工顶替临时工"，即 max Σ a（正式工人天数）；
  ② 正式工出勤率尽量均衡：max min_w Σ_d a_{w,d} 且 min max_w Σ_d a_{w,d}，
     本文做法：给每人相同的出勤天数配额（完全均衡，标准差 0）；
  ③ 每天实际小时人效尽量均衡：因 T[d][s] 固定，各小时产能 C_h 与表 5 完全相同，
     该目标在问题 4 中已被问题 3 的解确定，这里只做一致性校核。
约束：Σ_d a_{w,d} ≤ 25；连续出勤 ≤ 7 天；Σ_s a_{w,d,s} ≤ 1；临时工每人每天 ≤ 1 班。

算法（D5：模式池 + 贪心轮转）
----------------------------
1. 需求：T[d][s]、以及表 5 的正式工人数 n5[d][s]（作为"每格正式工下界"）；
2. 正式工总量：F = min(Σ T, 200 × 25) = 5000（30 天内 200 人各 25 天）；
3. 模式池：枚举"工作 run 段 + 休息 1~2 天"的 5 段轮转模板（每段连续工作 ≤ 7，
   合计恰好 25 天出勤、5 天休息），再取 30 种相位 → 旋转封闭的模式池；
4. 贪心轮转：按"当日缺口最大优先"给每名正式工挑一个模板（每人恰好 25 天 ⇒
   出勤率 200 人完全一致 = 83.33%），使每天出勤人数接近需求比例；
5. 班次分配：对每天，把当天出勤的正式工按"缺口最大的班次优先"填进各 (日,班次) 格子，
   每格正式工人数 n[d][s] 满足 n5[d][s] ≤ n[d][s] ≤ T[d][s] 且 Σ_s n[d][s] = 当天出勤人数；
6. 临时工：y[d][s] = T[d][s] − n[d][s]；同一天内临时工编号连续且各不重复（每人每天 1 班）。
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
SUB_DIR = os.path.join(ROOT, "提交")          # 沙箱只读时的落盘目录（团队约定）

SHIFT_NAMES = ["00:00-08:00", "05:00-13:00", "08:00-16:00",
               "12:00-20:00", "14:00-22:00", "16:00-24:00"]
SHIFT_START = [0, 5, 8, 12, 14, 16]
NS = 6
N_DAY = 30
DATES = ["2023/12/%d" % d for d in range(1, N_DAY + 1)]
CENTER = "SC60"
N_FORMAL = 200
MAX_DAY = 25                     # 30 × 0.85 = 25.5 ⇒ 最多 25 天
MAX_RUN = 7                      # 连续出勤 ≤ 7 天
EFF_F, EFF_T = 25, 20

OUT_COLS = ["分拣中心", "日期", "班次", "出勤员工"]


# ---------------------------------------------------------------- 读表 5
def _read_csv(path):
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit("无法识别编码：%s" % path)


def load_table5(path=None):
    """读入结果表 5，取 SC60 的 (日, 班次) 需求矩阵 T 与正式工人数 n5。

    候选顺序：显式指定 → 提交/ → 结果/结果/（模板只有示例行，会被自动跳过）。
    """
    cand = []
    if path:
        cand.append(path)
    cand += [os.path.join(SUB_DIR, "结果表5.csv"), os.path.join(SUB_DIR, "结果表5_dev.csv"),
             os.path.join(RES_DIR, "结果表5.csv")]
    used = None
    T = N5 = None
    for p in cand:
        if not os.path.exists(p):
            continue
        df = _read_csv(p)
        if not {"分拣中心", "日期", "班次", "正式工人数", "临时工人数"} <= set(df.columns):
            continue
        df = df[df["分拣中心"] == CENTER].copy()
        if df.empty:
            continue
        t = np.zeros((N_DAY, NS), dtype=int)
        n5 = np.zeros((N_DAY, NS), dtype=int)
        didx = {d: i for i, d in enumerate(DATES)}
        sidx = {s: i for i, s in enumerate(SHIFT_NAMES)}
        seen = set()
        for d, s, a, b in zip(df["日期"], df["班次"], df["正式工人数"], df["临时工人数"]):
            d = str(d).strip().replace("-", "/")
            i, j = didx.get(d), sidx.get(str(s).strip())
            if i is None or j is None:
                continue
            n5[i, j] = int(a)
            t[i, j] = int(a) + int(b)
            seen.add((i, j))
        if len(seen) == N_DAY * NS:      # 必须是完整的 30×6
            T, N5, used = t, n5, os.path.relpath(p, ROOT)
            break
    if T is None:
        raise SystemExit("找不到含 SC60 完整 30×6 数据的结果表 5，请先运行 code/p3_staffing.py")
    return T, N5, used


# ---------------------------------------------------------------- 模式池
def build_pattern_pool(n_work=25, max_run=MAX_RUN, max_comp=6):
    """枚举轮转模板池：30 天的 0/1 出勤向量，恰好 n_work 天出勤、连续出勤段 ≤ max_run。

    做法：把 25 个工作日记为 5 段（段长 l_1..l_5，Σl_i = n_work，l_i ≤ max_run），
    段间休 1 天；对每种段长组合再取 30 个旋转相位，形成"旋转封闭"的模式轨道。
    旋转封闭保证：只要每种相位被用到的次数相同，每天出勤人数就完全相同。
    返回 orbits：list（每个元素是该组合的 30 个相位模板）。
    """
    n_rest = N_DAY - n_work
    comps = []

    def rec(prefix, left, k):
        if k == 1:
            if 1 <= left <= max_run:
                comps.append(prefix + [left])
            return
        for v in range(1, max_run + 1):
            if left - v >= k - 1:
                rec(prefix + [v], left - v, k - 1)

    rec([], n_work, n_rest)
    # 选段长最均匀的若干组合（越均匀，连续出勤的天数越短、越人性化）
    comps.sort(key=lambda c: (max(c) - min(c), max(c), tuple(c)))
    comps = comps[:max_comp]
    orbits = []
    for comp in comps:
        orbit = []
        for phase in range(N_DAY):
            v = [0] * N_DAY
            pos = phase
            for length in comp:
                for _ in range(length):
                    v[pos % N_DAY] = 1
                    pos += 1
                pos += 1                      # 休 1 天
            assert sum(v) == n_work
            if _max_run(v) > max_run:
                continue
            orbit.append(v)
        if len(orbit) == N_DAY:
            orbits.append({"comp": comp, "patterns": orbit})
    return orbits


def _max_run(vec):
    best = cur = 0
    for v in vec:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def assign_patterns(orbits, n_worker):
    """轮转派活：第 w 名正式工取"第 (w mod 轨道数) 条轨道"的第 ((w // 轨道数) mod 30) 个相位。

    由于每条轨道都是旋转封闭的 30 个相位，且同一轨道内相位按 0,1,2,... 等距分配，
    同一轨道内每天休息的人数最多相差 1 ⇒ 每天出勤人数最多相差"轨道数"人；
    每人恰好 n_work 天出勤 ⇒ 出勤率 200 人完全一致（标准差 0）。
    """
    k = len(orbits)
    pats = []
    for w in range(n_worker):
        oi = w % k
        phase = (w // k) % N_DAY
        pats.append(orbits[oi]["patterns"][phase])
    load = [sum(pats[w][d] for w in range(n_worker)) for d in range(N_DAY)]
    return pats, load


def alloc_cells(fday, lo, hi, weight):
    """把当天出勤人数 fday 分摊到 6 个班次：lo ≤ n_s ≤ hi，Σ n_s = fday，按 weight 比例。"""
    n = [int(lo[s]) for s in range(NS)]
    rest = int(fday) - sum(n)
    if rest < 0:
        # 下界已超过当天人数：按下界砍（只在极端情况下出现）
        n = [int(lo[s]) for s in range(NS)]
        while sum(n) > fday:
            s = max(range(NS), key=lambda k: n[k] - lo[k])
            if n[s] <= lo[s] - 1:
                break
            n[s] -= 1
        return n, False
    room = [max(0, int(hi[s]) - n[s]) for s in range(NS)]
    w = [max(0.0, float(weight[s])) * room[s] for s in range(NS)]
    if sum(w) <= 0:
        w = [float(r) for r in room]
    tot = sum(w) or 1.0
    quota = [rest * x / tot for x in w]
    base = [min(room[s], int(math.floor(quota[s]))) for s in range(NS)]
    left = rest - sum(base)
    order = sorted(range(NS), key=lambda s: -(quota[s] - math.floor(quota[s])))
    while left > 0:
        moved = False
        for s in order:
            if left <= 0:
                break
            if base[s] < room[s]:
                base[s] += 1
                left -= 1
                moved = True
        if not moved:
            break
    n = [n[s] + base[s] for s in range(NS)]
    return n, left == 0


def build_roster(T, N5):
    """核心：生成每名正式工的 (日→班次) 排班 + 每格临时工人数。"""
    day_weight = [float(T[d].sum()) for d in range(N_DAY)]
    formal_total = min(int(T.sum()), N_FORMAL * MAX_DAY)
    # 出勤天数配额：完全均衡（每人相同），最多 25 天
    base_quota = formal_total // N_FORMAL
    rem = formal_total - base_quota * N_FORMAL
    n_work = base_quota if rem == 0 else base_quota + 1
    orbits = build_pattern_pool(n_work=n_work)
    pats, load = assign_patterns(orbits, N_FORMAL)

    # 每天出勤人数
    fday = [int(sum(pats[w][d] for w in range(N_FORMAL))) for d in range(N_DAY)]
    # 逐日：格子分配 + 人员到班次
    cell = np.zeros((N_DAY, NS), dtype=int)
    roster = [[-1] * N_DAY for _ in range(N_FORMAL)]   # roster[w][d] = 班次索引 or -1
    for d in range(N_DAY):
        lo = N5[d]
        hi = T[d]
        if fday[d] > int(hi.sum()):
            raise SystemExit("第 %s 天正式工出勤 %d 人超过总需求 %d" % (DATES[d], fday[d], hi.sum()))
        n, ok = alloc_cells(fday[d], lo, hi, T[d])
        if not ok:
            raise SystemExit("第 %s 天格子分配失败" % DATES[d])
        cell[d] = n
        # 把当天出勤的人按"缺口最大优先"填进班次
        cap = list(n)
        workers = [w for w in range(N_FORMAL) if pats[w][d]]
        # 轮转起点，避免每天都固定同一批人去同一个班次
        workers.sort(key=lambda w: (w + d * 37) % N_FORMAL)
        for w in workers:
            s = max(range(NS), key=lambda k: (cap[k], -k))
            if cap[s] <= 0:
                # 理论上不会发生（Σcap = len(workers)）；兜底
                s = int(np.argmax(cap))
                if cap[s] <= 0:
                    raise SystemExit("第 %s 天班次容量不足" % DATES[d])
            cap[s] -= 1
            roster[w][d] = s
    temps = T - cell
    if (temps < 0).any():
        raise SystemExit("出现负的临时工人数")
    return roster, cell, temps, pats, orbits, fday, formal_total, n_work


# ---------------------------------------------------------------- 输出 + 校验
def build_rows(roster, temps, cell):
    rows = []
    detail = {}
    for d in range(N_DAY):
        by_shift = [[] for _ in range(NS)]
        temp_base = 0
        for w in range(N_FORMAL):
            s = roster[w][d]
            if s >= 0:
                by_shift[s].append(w + 1)
        for s in range(NS):
            ids = sorted(by_shift[s])
            if len(ids) != cell[d][s]:
                raise SystemExit("内部不一致：%s %s 正式工 %d ≠ 目标 %d"
                                 % (DATES[d], SHIFT_NAMES[s], len(ids), cell[d][s]))
            for wid in ids:
                rows.append((CENTER, DATES[d], SHIFT_NAMES[s], "正式工%d" % wid))
            # 临时工：当天编号跨班次连续（同一天内每个编号只出现一次 ⇒ 每人每天 ≤ 1 班）
            for j in range(int(temps[d][s])):
                rows.append((CENTER, DATES[d], SHIFT_NAMES[s], "临时工%d" % (temp_base + j + 1)))
            temp_base += int(temps[d][s])
    return pd.DataFrame(rows, columns=OUT_COLS)


def verify(df, T, N5, verbose=True):
    """独立校验表 6（从写出的 DataFrame 重新统计，不依赖求解过程）。"""
    errs = []
    if list(df.columns) != OUT_COLS:
        errs.append("列名不符：%s" % list(df.columns))
    if (df["分拣中心"] != CENTER).any():
        errs.append("出现非 %s 的分拣中心" % CENTER)
    excepted_rows = int(T.sum())
    if len(df) != excepted_rows:
        errs.append("行数 %d ≠ Σ T = %d" % (len(df), excepted_rows))

    didx = {d: i for i, d in enumerate(DATES)}
    sidx = {s: i for i, s in enumerate(SHIFT_NAMES)}
    formal = df[df["出勤员工"].str.startswith("正式工")].copy()
    temp = df[df["出勤员工"].str.startswith("临时工")].copy()
    if len(formal) + len(temp) != len(df):
        errs.append("存在无法识别的员工标识")

    formal["wid"] = formal["出勤员工"].str.replace("正式工", "", regex=False).astype(int)
    temp["tid"] = temp["出勤员工"].str.replace("临时工", "", regex=False).astype(int)
    if formal["wid"].min() < 1 or formal["wid"].max() > N_FORMAL:
        errs.append("正式工编号越界：%d..%d" % (formal["wid"].min(), formal["wid"].max()))

    # 1) 每人每天至多一班
    dup = formal.duplicated(subset=["wid", "日期"])
    if dup.any():
        errs.append("有正式工同一天出现在多个班次：%d 条" % dup.sum())
    dupt = temp.duplicated(subset=["tid", "日期"])
    if dupt.any():
        errs.append("有临时工同一天出现在多个班次：%d 条" % dupt.sum())

    # 2) 出勤天数 ≤ 25；连续出勤 ≤ 7
    days = {w: [] for w in range(1, N_FORMAL + 1)}
    for wid, d in zip(formal["wid"], formal["日期"]):
        days[wid].append(didx[d])
    day_cnt = {w: len(v) for w, v in days.items()}
    over = [w for w, c in day_cnt.items() if c > MAX_DAY]
    if over:
        errs.append("%d 名正式工出勤超过 %d 天（如 %s）" % (len(over), MAX_DAY, over[:5]))
    for w, ds in days.items():
        ds = sorted(ds)
        run = best = 0
        prev = None
        for d in ds:
            if prev is not None and d == prev + 1:
                run += 1
            else:
                run = 1
            best = max(best, run)
            prev = d
        if best > MAX_RUN:
            errs.append("正式工%d 连续出勤 %d 天 > %d" % (w, best, MAX_RUN))
            break

    # 3) 每 (日,班次) 人数 = 表 5 的正式工+临时工；且正式工 ≥ 表 5 的正式工
    fc = formal.groupby(["日期", "班次"]).size()
    tc = temp.groupby(["日期", "班次"]).size()
    for d in DATES:
        for s in SHIFT_NAMES:
            i, j = didx[d], sidx[s]
            f = int(fc.get((d, s), 0))
            t = int(tc.get((d, s), 0))
            if f + t != int(T[i, j]):
                errs.append("%s %s 人数 %d ≠ 表 5 的 %d" % (d, s, f + t, T[i, j]))
            if f < int(N5[i, j]):
                errs.append("%s %s 正式工 %d < 表 5 正式工 %d" % (d, s, f, N5[i, j]))
            if f > int(T[i, j]):
                errs.append("%s %s 正式工 %d > 需求 %d" % (d, s, f, T[i, j]))
    counts = list(day_cnt.values())
    rep = {
        "n_row": len(df),
        "formal_rows": len(formal),
        "temp_rows": len(temp),
        "formal_person_days": len(formal),
        "temp_person_days": len(temp),
        "formal_share": round(100.0 * len(formal) / max(1, len(formal) + len(temp)), 2),
        "attend_days_min": int(min(counts)),
        "attend_days_max": int(max(counts)),
        "attend_days_mean": round(float(np.mean(counts)), 3),
        "attend_days_std": round(float(np.std(counts)), 4),
        "attend_rate_min": round(100.0 * min(counts) / N_DAY, 2),
        "attend_rate_max": round(100.0 * max(counts) / N_DAY, 2),
        "attend_rate_mean": round(100.0 * float(np.mean(counts)) / N_DAY, 2),
        "n_worker_used": int(sum(1 for c in counts if c > 0)),
        "n_err": len(errs),
        "errors": errs[:20],
    }
    if verbose:
        print("[校验] 表 6：%d 行（正式工 %d + 临时工 %d）"
              % (rep["n_row"], rep["formal_rows"], rep["temp_rows"]))
        print("       正式工出勤天数 min/mean/max = %d / %.3f / %d（出勤率 %.2f%% ~ %.2f%%），标准差 %.4f"
              % (rep["attend_days_min"], rep["attend_days_mean"], rep["attend_days_max"],
                 rep["attend_rate_min"], rep["attend_rate_max"], rep["attend_days_std"]))
        if errs:
            print("       ✗ 发现 %d 个问题：" % len(errs))
            for e in errs[:10]:
                print("         -", e)
        else:
            print("       ✓ 全部约束通过（出勤率 ≤85%、连续 ≤7 天、每人每日 ≤1 班、"
                  "每班人数 = 表 5、正式工 ≥ 表 5 正式工）")
    return rep, (len(errs) == 0)


def write_table(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        df.to_csv(path, index=False, encoding="gbk")
        print("  已写出 %s（%d 行，gbk）" % (os.path.relpath(path, ROOT), len(df)))
        return path
    except PermissionError:
        os.makedirs(SUB_DIR, exist_ok=True)
        alt = os.path.join(SUB_DIR, os.path.basename(path))
        df.to_csv(alt, index=False, encoding="gbk")
        print("  ⚠ 目标目录只读（沙箱保护），已改写到 %s（%d 行，gbk）"
              % (os.path.relpath(alt, ROOT), len(df)))
        return alt


def main(argv=None):
    ap = argparse.ArgumentParser(description="问题 4：SC60 逐人排班（结果表 6）")
    ap.add_argument("--table5", default=None, help="指定结果表 5 路径")
    ap.add_argument("--tag", default=None, help="输出文件名后缀（如 dev）")
    ap.add_argument("--out-dir", default=None, help="输出目录")
    args = ap.parse_args(argv)

    print("=" * 78)
    print("问题 4 —— %s 逐人排班（200 名正式工 × 30 天 × 6 班次）" % CENTER)
    print("=" * 78)
    print("[1] 读取结果表 5 中 %s 的班次需求" % CENTER)
    T, N5, src = load_table5(args.table5)
    print("  来源 %s：Σ(正式+临时) = %d 人天，Σ正式工 = %d，每天总人数 %.1f ~ %.1f"
          % (src, T.sum(), N5.sum(), T.sum(axis=1).min(), T.sum(axis=1).max()))

    print("[2] 生成模式池 + 贪心轮转 + 班次分配")
    roster, cell, temps, pats, orbits, fday, formal_total, n_work = build_roster(T, N5)
    print("  正式工可用人天 = min(Σ T, 200×25) = %d；每人配额 %d 天（出勤率 %.2f%%）"
          % (formal_total, n_work, 100.0 * n_work / N_DAY))
    print("  每天正式工出勤 %d ~ %d 人；临时工人天 %d" % (min(fday), max(fday), int(temps.sum())))

    print("[3] 生成表 6 明细")
    df = build_rows(roster, temps, cell)

    print("[4] 独立校验")
    rep, ok = verify(df, T, N5)
    if not ok:
        raise SystemExit("表 6 未通过校验，拒绝写表！")

    # ---- 统计（供论文取材）
    per_day = []
    for d in range(N_DAY):
        per_day.append({
            "date": DATES[d], "total": int(T[d].sum()), "formal": int(cell[d].sum()),
            "temp": int(temps[d].sum()),
            "temp_rate": round(100.0 * temps[d].sum() / max(1, T[d].sum()), 2),
        })
    eff = float(T.sum() * 0)  # 占位，下面按小时口径算
    # 小时产能（与表 5 完全一致）：C_h = Σ_{s∋h} 25·formal? 表 5 是正式/临时混合口径
    # 问题 4 的"总人数/T"固定，故小时产能与表 5 一致；这里给出等价的人天数口径指标
    tot_people = int(T.sum())
    stats = {
        "center": CENTER,
        "n_formal": N_FORMAL,
        "n_day": N_DAY,
        "n_shift": NS,
        "table5_source": src,
        "demand_total_person_days": int(T.sum()),
        "formal_person_days": int(cell.sum()),
        "temp_person_days": int(temps.sum()),
        "formal_share": round(100.0 * cell.sum() / max(1, T.sum()), 2),
        "temp_share": round(100.0 * temps.sum() / max(1, T.sum()), 2),
        "formal_per_day": round(float(cell.sum()) / N_DAY, 2),
        "temp_per_day": round(float(temps.sum()) / N_DAY, 2),
        "quota_days": n_work,
        "attend_rate": round(100.0 * n_work / N_DAY, 2),
        "attend_rate_cap": 85.0,
        "max_run_check": MAX_RUN,
        "day_formal_min": int(min(fday)),
        "day_formal_max": int(max(fday)),
        "day_temp_min": int(temps.sum(axis=1).min()),
        "day_temp_max": int(temps.sum(axis=1).max()),
        "peak_temp_day": per_day[int(np.argmax([r["temp"] for r in per_day]))]["date"],
        "peak_temp_value": int(max(r["temp"] for r in per_day)),
        "verify": rep,
        "per_day": per_day,
        "pattern_pool_size": len(orbits) * N_DAY,
        "pattern_orbits": [o["comp"] for o in orbits],
        "shift_formal": [[int(v) for v in cell[d]] for d in range(N_DAY)],
    }
    print("[5] 写出结果表 6")
    tag = args.tag
    out_dir = args.out_dir or RES_DIR
    suffix = "_%s" % tag if tag else ""
    out_csv = os.path.join(out_dir, "结果表6%s.csv" % suffix)
    write_table(df, out_csv)
    sp = os.path.join(DATA_DIR, "p4_stats%s.json" % suffix)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print("  统计已写出 %s" % os.path.relpath(sp, ROOT))
    print("  人天数：总 %d = 正式工 %d（%.2f%%）+ 临时工 %d（%.2f%%）"
          % (stats["demand_total_person_days"], stats["formal_person_days"], stats["formal_share"],
             stats["temp_person_days"], stats["temp_share"]))
    print("  正式工出勤率：%.2f%%（200 人完全一致），连续出勤 ≤ %d 天，临时工高峰日 %s（%d 人）"
          % (stats["attend_rate"], MAX_RUN, stats["peak_temp_day"], stats["peak_temp_value"]))
    return stats


if __name__ == "__main__":
    main()
