# -*- coding: utf-8 -*-
"""
validate_schedule.py —— 结果表 5 / 表 6 的独立校验器（不复用求解器代码）

支持三种产能口径（--mode）：
  backlog（默认，主口径）允许积压，但要求"自第 t 小时起的剩余产能 ≥ 剩余到货"
                         （Hall 条件，等价于"当天 24 点前一定能把货清完"），
                         并用流体仿真确认日末积压 = 0；
  cum                    累计产能 ≥ 累计到货（主 agent 指定的对照公式，见报告灵敏度一节）；
  strict                 严格逐小时产能 ≥ 该小时货量（不允许任何积压）。

通用校验（任何口径都查）：
  表 5：行数 10260、列名、日期 2023/12/1..30、6 个班次字符串、(中心,日,班次) 唯一、
        人数非负整数、Σ_s x_s ≤ 60；
  表 6：列名、中心只能是 SC60、员工标识合法、每人每天 ≤1 班、正式工出勤 ≤25 天、
        连续出勤 ≤7 天、每 (日,班次) 人数 = 表 5 的同格人数、行数 = 表 5 中 SC60 的总人天数。

用法：
    python code/validate_schedule.py                      # 主口径 backlog
    python code/validate_schedule.py --mode strict        # 校验严格逐小时版（对照表）
    python code/validate_schedule.py --mode cum --table5 data/alt_cum_aggregate_结果表5.csv
"""
import argparse
import math
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
RES_DIR = os.path.join(ROOT, "结果", "结果")
SUB_DIR = os.path.join(ROOT, "提交")

SHIFT_NAMES = ["00:00-08:00", "05:00-13:00", "08:00-16:00",
               "12:00-20:00", "14:00-22:00", "16:00-24:00"]
SHIFT_START = [0, 5, 8, 12, 14, 16]
NS = 6
N_DAY = 30
DATES = ["2023/12/%d" % d for d in range(1, N_DAY + 1)]
EFF_F, EFF_T = 25, 20
FORMAL_CAP = 60
CENTER_SC60 = "SC60"
N_FORMAL_P4 = 200
MAX_WORK_DAYS = 25
MAX_RUN = 7
T5_COLS = ["分拣中心", "日期", "班次", "正式工人数", "临时工人数"]
T6_COLS = ["分拣中心", "日期", "班次", "出勤员工"]
MODE_CN = {"backlog": "允许积压 + 日末清零（主口径）",
           "turn8": "到达后 8 小时内处理完（滑动 8 小时窗口）",
           "cum": "累计产能 ≥ 累计到货（对照）",
           "strict": "严格逐小时（不允许积压）"}

FAILS = []
WARNS = []


def fail(msg):
    FAILS.append(msg)


def warn(msg):
    WARNS.append(msg)


def read_csv(path):
    import csv
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            continue
    raise SystemExit("无法解码：%s" % path)


def find_file(name, explicit=None):
    cand = [explicit] if explicit else []
    cand += [os.path.join(RES_DIR, name), os.path.join(SUB_DIR, name)]
    for p in cand:
        if p and os.path.exists(p) and os.path.getsize(p) > 300:   # 跳过只有示例行的模板
            return p
    for p in cand:
        if p and os.path.exists(p):
            return p
    return None


def load_demand():
    """独立重算小时需求：dict[(中心, '日字符串')] -> [24 float]；返回 (demand, 来源)"""
    path = os.path.join(DATA_DIR, "pred_hourly.csv")
    if not os.path.exists(path):
        path = os.path.join(DATA_DIR, "hourly.csv")
        warn("未找到 data/pred_hourly.csv，需求曲线回退到 data/hourly.csv（仅用于联调校验）")
    rows = read_csv(path)
    head = rows[0]
    idx = {h: i for i, h in enumerate(head)}
    for c in ("分拣中心", "日期", "小时", "货量"):
        if c not in idx:
            raise SystemExit("%s 缺少列 %s" % (path, c))
    dem = defaultdict(lambda: [0.0] * 24)
    for r in rows[1:]:
        if len(r) <= max(idx["分拣中心"], idx["日期"], idx["小时"], idx["货量"]):
            continue
        c = r[idx["分拣中心"]].strip()
        d = r[idx["日期"]].strip().replace("-", "/")
        try:
            h = int(float(r[idx["小时"]]))
            v = float(r[idx["货量"]])
        except ValueError:
            fail("需求文件有无法解析的行：%s" % (r,))
            continue
        if 0 <= h <= 23:
            dem[(c, d)][h] += v
    return dem, os.path.relpath(path, ROOT)


def _cap_tables(x, y):
    """返回 (逐小时产能 cap[24], 逐 t 累计产能 cum[24], 逐 t 剩余产能 rem[24])"""
    cap = [0] * 24
    for s in range(NS):
        c = EFF_F * x[s] + EFF_T * y[s]
        for h in range(SHIFT_START[s], SHIFT_START[s] + 8):
            cap[h] += c
    cum, rem = [0] * 24, [0] * 24
    for t in range(24):
        cum[t] = sum((EFF_F * x[s] + EFF_T * y[s]) *
                     max(0, min(SHIFT_START[s] + 8, t + 1) - SHIFT_START[s]) for s in range(NS))
        rem[t] = sum((EFF_F * x[s] + EFF_T * y[s]) *
                     sum(1 for h in range(SHIFT_START[s], SHIFT_START[s] + 8) if h >= t)
                     for s in range(NS))
    return cap, cum, rem


def _queue(R, cap):
    """流体仿真：到货先积压、在岗产能优先处理积压；返回 (日末积压, 逐小时处理量)。"""
    backlog, work = 0.0, [0.0] * 24
    for h in range(24):
        avail = backlog + max(0.0, R[h])
        work[h] = min(cap[h], avail)
        backlog = avail - work[h]
    return backlog, work


# 8 小时周转口径的滑动窗口：T=1..24，窗口 [max(0,T-8), T)
TURN_WINDOWS = []
for _T in range(1, 25):
    _lo, _hi = max(0, _T - 8), _T
    TURN_WINDOWS.append({"T": _T, "lo": _lo, "hi": _hi,
                         "ov": [max(0, min(a + 8, _hi) - max(a, _lo)) for a in SHIFT_START]})


def _turn_tables(x, y):
    out = []
    for w in TURN_WINDOWS:
        out.append(sum((EFF_F * x[s] + EFF_T * y[s]) * w["ov"][s] for s in range(NS)))
    return out


def check_table5(path, dem, mode="backlog"):
    print("\n" + "=" * 78)
    print("表 5 校验：%s" % os.path.relpath(path, ROOT))
    print("口径：%s" % MODE_CN[mode])
    print("=" * 78)
    rows = read_csv(path)
    header, body = rows[0], [r for r in rows[1:] if any(x.strip() for x in r)]
    if header[:5] != T5_COLS:
        fail("表 5 列名不符：%s（应为 %s）" % (header[:5], T5_COLS))
    if len(header) > 5 and any(x.strip() for x in header[5:]):
        fail("表 5 有多余列：%s" % header[5:])
    if len(body) != 57 * N_DAY * NS:
        fail("表 5 行数 %d ≠ 57×30×6 = %d" % (len(body), 57 * N_DAY * NS))

    need = defaultdict(dict)
    seen = set()
    bad_fmt = 0
    for r in body:
        if len(r) < 5:
            bad_fmt += 1
            continue
        c, d, s = r[0].strip(), r[1].strip().replace("-", "/"), r[2].strip()
        try:
            x, y = int(float(r[3])), int(float(r[4]))
        except ValueError:
            bad_fmt += 1
            continue
        if (c, d, s) in seen:
            fail("表 5 重复行：%s %s %s" % (c, d, s))
        seen.add((c, d, s))
        if d not in DATES:
            fail("表 5 日期越界：%r" % d)
        if s not in SHIFT_NAMES:
            fail("表 5 班次非法：%r" % s)
        if x < 0 or y < 0:
            fail("表 5 出现负数：%s %s %s -> %s %s" % (c, d, s, x, y))
        if d in DATES and s in SHIFT_NAMES:
            need[(c, d)][SHIFT_NAMES.index(s)] = (x, y)
    if bad_fmt:
        fail("表 5 有 %d 行格式异常" % bad_fmt)

    centers = sorted({c for (c, _) in need})
    days = sorted({d for (_, d) in need})
    print("  行数 %d；中心 %d 个；日期 %d 天；班次 %d 个"
          % (len(body), len(centers), len(days), len({s for (_, _, s) in seen})))
    if len(centers) != 57:
        fail("表 5 中心数 %d ≠ 57" % len(centers))
    if set(days) != set(DATES):
        fail("表 5 日期集合不等于 2023/12/1..12/30")

    tot_x = tot_y = 0
    vol_all = 0.0
    n_over60 = 0
    n_cell_missing = 0
    n_fail_mode = n_fail_strict = n_fail_cum = 0
    n_backlog_left = 0
    worst = (1e18, None)
    util_all = []
    dem_centers = {c for (c, _) in dem}
    for c in centers:
        if dem_centers and c not in dem_centers:
            fail("需求曲线里没有中心 %s" % c)
    for c in centers:
        for d in DATES:
            cells = need.get((c, d), {})
            if len(cells) != NS:
                n_cell_missing += 1
                continue
            R = dem.get((c, d))
            if R is None:
                fail("需求曲线缺少 %s %s" % (c, d))
                continue
            x = [cells[s][0] for s in range(NS)]
            y = [cells[s][1] for s in range(NS)]
            if sum(x) > FORMAL_CAP:
                n_over60 += 1
            tot_x += sum(x)
            tot_y += sum(y)
            vol_all += sum(R)
            cap, cum, rem = _cap_tables(x, y)
            backlog_end, work = _queue(R, cap)
            if backlog_end > 1e-6:
                n_backlog_left += 1

            ok = True
            if mode == "turn8":
                tcap = _turn_tables(x, y)
                for i, w in enumerate(TURN_WINDOWS):
                    dm = sum(R[w["lo"]:w["hi"]])
                    if tcap[i] + 1e-9 < dm:
                        ok = False
                        if tcap[i] - dm < worst[0]:
                            worst = (tcap[i] - dm, (c, d, w["T"]))
                        fail("8 小时窗口不足：%s %s 窗口[%d,%d) 需 %.0f > 产能 %d"
                             % (c, d, w["lo"], w["hi"], dm, tcap[i]))
                        break
                if ok and backlog_end > 1e-6:
                    ok = False
                    fail("日末仍有积压：%s %s 剩 %.1f 件" % (c, d, backlog_end))
            elif mode == "backlog":
                for t in range(24):
                    r = sum(R[t:])
                    if rem[t] + 1e-9 < r:
                        ok = False
                        if rem[t] - r < worst[0]:
                            worst = (rem[t] - r, (c, d, t))
                        fail("剩余产能不足：%s %s 自 %dh 起需 %.0f > 产能 %d" % (c, d, t, r, rem[t]))
                        break
                if ok and backlog_end > 1e-6:
                    ok = False
                    fail("日末仍有积压：%s %s 剩 %.1f 件" % (c, d, backlog_end))
            elif mode == "cum":
                for t in range(24):
                    a = sum(R[:t + 1])
                    if cum[t] + 1e-9 < a:
                        ok = False
                        if cum[t] - a < worst[0]:
                            worst = (cum[t] - a, (c, d, t))
                        fail("累计产能不足：%s %s 到 %dh 需 %.0f > 产能 %d" % (c, d, t, a, cum[t]))
                        break
            else:
                for h in range(24):
                    slack = cap[h] - R[h]
                    if slack < worst[0]:
                        worst = (slack, (c, d, h))
                    if slack < -1e-6:
                        ok = False
                        fail("产能不足：%s %s %dh 需求 %.0f > 产能 %d" % (c, d, h, R[h], cap[h]))
                        break
            if not ok:
                n_fail_mode += 1

            if any(cap[h] + 1e-9 < R[h] for h in range(24)):
                n_fail_strict += 1
            if any(cum[t] + 1e-9 < sum(R[:t + 1]) for t in range(24)):
                n_fail_cum += 1
            for h in range(24):
                if cap[h] > 0 and work[h] > 1e-9:
                    util_all.append(work[h] / cap[h])

    if n_cell_missing:
        fail("有 %d 个 (中心,日) 不是完整的 6 个班次" % n_cell_missing)
    if n_over60:
        fail("有 %d 个 (中心,日) 正式工人数超过 60" % n_over60)

    people = tot_x + tot_y
    print("  总人天数 %d（正式工 %d = %.2f%%，临时工 %d = %.2f%%）"
          % (people, tot_x, 100.0 * tot_x / max(1, people), tot_y, 100.0 * tot_y / max(1, people)))
    print("  总货量 %.0f；人效 %.3f 包裹/(人·小时)（= %.1f 包裹/人天）"
          % (vol_all, vol_all / (8.0 * people) if people else 0,
             vol_all / people if people else 0))
    um = sum(util_all) / len(util_all)
    usd = math.sqrt(sum((u - um) ** 2 for u in util_all) / len(util_all))
    print("  小时利用率 u_h = 实际处理量/在岗产能：均值 %.4f，标准差 %.4f，最小 %.4f，最大 %.4f"
          % (um, usd, min(util_all), max(util_all)))
    print("  主口径通过率：%d/1710 个 (中心,日)" % (1710 - n_fail_mode))
    print("  三种口径对照（同一张表）：严格逐小时可满足 %d/1710；累计公式可满足 %d/1710；"
          "日末未清零 %d/1710" % (1710 - n_fail_strict, 1710 - n_fail_cum, n_backlog_left))
    if worst[1] is not None:
        tail = ("自 %dh 起" % worst[1][2]) if mode != "strict" else ("%dh" % worst[1][2])
        print("  最紧约束：%s %s %s（余量 %.0f）" % (worst[1][0], worst[1][1], tail, worst[0]))
    return {"rows": len(body), "centers": len(centers), "person_days": people,
            "formal": tot_x, "temp": tot_y, "volume": vol_all,
            "util_mean": um, "util_std": usd,
            "eff_per_hour": vol_all / (8.0 * people) if people else 0.0,
            "n_fail_mode": n_fail_mode, "n_fail_strict": n_fail_strict,
            "n_fail_cum": n_fail_cum, "n_backlog_left": n_backlog_left}


def check_table6(path):
    print("\n" + "=" * 78)
    print("表 6 校验：%s" % os.path.relpath(path, ROOT))
    print("=" * 78)
    rows = read_csv(path)
    header, body = rows[0], [r for r in rows[1:] if any(x.strip() for x in r)]
    if header[:4] != T6_COLS:
        fail("表 6 列名不符：%s（应为 %s）" % (header[:4], T6_COLS))
    if len(header) > 4 and any(x.strip() for x in header[4:]):
        fail("表 6 有多余列：%s" % header[4:])
    print("  行数 %d" % len(body))

    formal_days = defaultdict(set)
    formal_cell = defaultdict(int)
    temp_cell = defaultdict(int)
    temp_slots = set()
    bad = 0
    for r in body:
        if len(r) < 4:
            bad += 1
            continue
        c, d, s, who = r[0].strip(), r[1].strip().replace("-", "/"), r[2].strip(), r[3].strip()
        if c != CENTER_SC60:
            fail("表 6 出现非 SC60 的分拣中心：%r" % c)
            break
        if d not in DATES:
            fail("表 6 日期越界：%r" % d)
        if s not in SHIFT_NAMES:
            fail("表 6 班次非法：%r" % s)
        if who.startswith("正式工"):
            try:
                wid = int(who[3:])
            except ValueError:
                bad += 1
                continue
            if not 1 <= wid <= N_FORMAL_P4:
                fail("正式工编号越界：%s" % who)
            if d in formal_days[wid]:
                fail("正式工%d 在 %s 出现在多个班次" % (wid, d))
            formal_days[wid].add(d)
            formal_cell[(d, s)] += 1
        elif who.startswith("临时工"):
            try:
                tid = int(who[3:])
            except ValueError:
                bad += 1
                continue
            if tid < 1:
                fail("临时工编号非法：%s" % who)
            if (tid, d) in temp_slots:
                fail("临时工%d 在 %s 出现在多个班次" % (tid, d))
            temp_slots.add((tid, d))
            temp_cell[(d, s)] += 1
        else:
            fail("员工标识无法识别：%r" % who)
    if bad:
        fail("表 6 有 %d 行格式异常" % bad)

    t5 = find_table5_for_cross()
    if t5 is None:
        warn("没有可用的表 5，跳过『表 6 人数 = 表 5 人数』的交叉校验")
    else:
        T, N5 = t5
        for d in DATES:
            for s in SHIFT_NAMES:
                f = formal_cell.get((d, s), 0)
                t = temp_cell.get((d, s), 0)
                i, j = DATES.index(d), SHIFT_NAMES.index(s)
                if f + t != int(T[i][j]):
                    fail("%s %s 人数 %d ≠ 表 5 的 %d" % (d, s, f + t, int(T[i][j])))
                if f > int(T[i][j]):
                    fail("%s %s 正式工 %d 超过需求 %d" % (d, s, f, int(T[i][j])))
                if f < int(N5[i][j]):
                    fail("%s %s 正式工 %d < 表 5 正式工 %d" % (d, s, f, int(N5[i][j])))
        tot_t = sum(int(v) for row in T for v in row)
        if len(body) != tot_t:
            fail("表 6 行数 %d ≠ 表 5 的 SC60 总人天数 %d" % (len(body), tot_t))
        else:
            print("  行数 = 表 5 中 SC60 总人天数 = %d ✓" % tot_t)

    counts = []
    for w in range(1, N_FORMAL_P4 + 1):
        ds = sorted(DATES.index(d) for d in formal_days.get(w, set()))
        counts.append(len(ds))
        if len(ds) > MAX_WORK_DAYS:
            fail("正式工%d 出勤 %d 天 > %d" % (w, len(ds), MAX_WORK_DAYS))
        run = best = 0
        prev = None
        for dd in ds:
            run = run + 1 if (prev is not None and dd == prev + 1) else 1
            best = max(best, run)
            prev = dd
        if best > MAX_RUN:
            fail("正式工%d 连续出勤 %d 天 > %d" % (w, best, MAX_RUN))
    if any(c == 0 for c in counts):
        warn("有 %d 名正式工 30 天内一天未出勤" % sum(1 for c in counts if c == 0))
    nf = len(formal_days)
    nt = len({tid for (tid, _) in temp_slots})
    print("  正式工 %d 人，出勤人天 %d；临时工 %d 个编号，人天 %d"
          % (nf, sum(counts), nt, sum(temp_cell.values())))
    print("  正式工出勤天数 min/mean/max = %d / %.3f / %d；出勤率 %.2f%% ~ %.2f%%（上限 85%%）"
          % (min(counts), sum(counts) / len(counts), max(counts),
             100.0 * min(counts) / N_DAY, 100.0 * max(counts) / N_DAY))
    std = math.sqrt(sum((c - sum(counts) / len(counts)) ** 2 for c in counts) / len(counts))
    print("  出勤率标准差 %.4f（越小越均衡）" % std)
    per_day = defaultdict(int)
    for (d, s), v in temp_cell.items():
        per_day[d] += v
    peak = max(per_day.items(), key=lambda kv: kv[1])
    print("  临时工高峰日 %s（%d 人）" % (peak[0], peak[1]))
    return {"rows": len(body), "formal_person_days": sum(counts),
            "temp_person_days": sum(temp_cell.values()),
            "attend_min": min(counts), "attend_max": max(counts),
            "attend_std": std, "peak_temp_day": peak[0], "peak_temp": peak[1]}


def find_table5_for_cross():
    path = find_file("结果表5.csv")
    if not path:
        return None
    rows = read_csv(path)
    T = [[0] * NS for _ in range(N_DAY)]
    N5 = [[0] * NS for _ in range(N_DAY)]
    seen = 0
    for r in rows[1:]:
        if len(r) < 5 or r[0].strip() != CENTER_SC60:
            continue
        d, s = r[1].strip().replace("-", "/"), r[2].strip()
        if d not in DATES or s not in SHIFT_NAMES:
            continue
        i, j = DATES.index(d), SHIFT_NAMES.index(s)
        N5[i][j] = int(float(r[3]))
        T[i][j] = int(float(r[3])) + int(float(r[4]))
        seen += 1
    if seen != N_DAY * NS:
        return None
    return T, N5


def main(argv=None):
    ap = argparse.ArgumentParser(description="独立校验结果表 5 / 表 6")
    ap.add_argument("--mode", default="backlog", choices=["backlog", "turn8", "cum", "strict"],
                    help="产能口径：backlog=允许积压+日末清零（默认），cum=累计公式，strict=严格逐小时")
    ap.add_argument("--table5", default=None)
    ap.add_argument("--table6", default=None)
    args = ap.parse_args(argv)

    print("=" * 78)
    print("结果表 5 / 表 6 独立校验（口径：%s）" % MODE_CN[args.mode])
    print("=" * 78)
    dem, src = load_demand()
    print("需求曲线来源：%s（%d 个 (中心,日) 组合）" % (src, len(dem)))

    p5 = find_file("结果表5.csv", args.table5)
    if p5 is None:
        print("✗ 找不到结果表 5")
        return 1
    s5 = check_table5(p5, dem, mode=args.mode)

    p6 = find_file("结果表6.csv", args.table6)
    if p6 is None:
        print("\n✗ 找不到结果表 6")
        return 1
    s6 = check_table6(p6)

    print("\n" + "=" * 78)
    print("校验结论")
    print("=" * 78)
    if WARNS:
        print("提示 %d 条：" % len(WARNS))
        for w in WARNS:
            print("  ·", w)
    if FAILS:
        print("✗ 失败 %d 项：" % len(FAILS))
        for f in FAILS[:30]:
            print("  -", f)
        return 1
    print("✓ 表 5 与表 6 全部校验通过")
    print("  表 5：%d 行 / %d 中心 / 总人天数 %d（正式工 %d，临时工 %d）"
          % (s5["rows"], s5["centers"], s5["person_days"], s5["formal"], s5["temp"]))
    print("  表 6：%d 行 / 正式工 %d 人天 / 临时工 %d 人天 / 出勤率 %.2f%%~%.2f%%"
          % (s6["rows"], s6["formal_person_days"], s6["temp_person_days"],
             100.0 * s6["attend_min"] / N_DAY, 100.0 * s6["attend_max"] / N_DAY))
    return 0


if __name__ == "__main__":
    sys.exit(main())
