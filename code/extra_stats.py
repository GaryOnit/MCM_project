# -*- coding: utf-8 -*-
"""
extra_stats.py —— 论文表 13 与正文要用的三个补充统计（不改任何结果表）

1. 正式工上限 60 / 80 / 100 三档的人天数（主口径 Hall，其余不变）→ 同时刷新 data/sens_formal_cap.csv
2. 口径③（到期累计）在当前需求下的"日末最大积压"
3. u_h 的"日间最大标准差"（30 天里各日 u_h 标准差的最大值）
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "code"))
import p3_staffing as p3

DATA_DIR = os.path.join(ROOT, "data")
RES_DIR = os.path.join(ROOT, "结果", "结果")
SUB_DIR = os.path.join(ROOT, "提交")


def read_csv(path):
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit("无法解码 %s" % path)


def main():
    demand, meta = p3.load_demand("auto")
    centers = meta["centers"]
    vol = float(meta["total_volume"])
    lb = vol / (8.0 * p3.EFF_F)          # 总量工时下界
    lb_cd = sum(p3.cdiv(float(np.sum(demand[(c, k)])), p3.EFF_F * 8)
                for c in centers for k in range(p3.N_DAY))
    print("需求曲线：%s  合计 %.0f  总量下界 %.0f（逐中心日取整 %.0f）"
          % (meta["path"], vol, lb, lb_cd))

    # ---------------- 1) 正式工上限 60/80/100
    rows = []
    print("\n[1] 正式工上限敏感性（主口径 Hall）")
    for cap in (60, 80, 100):
        tf = tt = 0
        nfail = 0
        effs = []
        for c in centers:
            for k in range(p3.N_DAY):
                R = demand[(c, k)]
                x, y, info = p3.solve_day_backlog(R, formal_cap=cap)
                ok, _ = p3.verify_day_hall(R, x, y)
                if not ok:
                    nfail += 1
                tf += sum(x)
                tt += sum(y)
                effs.append(info["eff"])
        tot = tf + tt
        rows.append({"cap": cap, "total": tot, "formal": tf, "temp": tt,
                     "formal_pct": 100.0 * tf / tot, "mult": tot / lb,
                     "eff": vol / (8.0 * tot), "eff_cd": float(np.mean(effs)),
                     "nfail": nfail})
        print("  上限 %3d：总人天 %s（正式 %s / 临时 %s，正式占比 %.2f%%），"
              "= 下界的 %.4f 倍，人效 %.3f 件/(人·小时)，Hall 未通过 %d"
              % (cap, format(tot, ","), format(tf, ","), format(tt, ","),
                 100.0 * tf / tot, tot / lb, vol / (8.0 * tot), nfail))
    out = pd.DataFrame([{
        "正式工上限": r["cap"], "总人天数": r["total"], "正式工人天": r["formal"],
        "临时工人天": r["temp"], "正式工占比": round(r["formal_pct"], 2),
        "相对下界": round(r["mult"], 3), "人效": round(r["eff"], 2),
        "未通过校验数": r["nfail"],
    } for r in rows])
    p = os.path.join(DATA_DIR, "sens_formal_cap.csv")
    out.to_csv(p, index=False, encoding="utf-8-sig")
    print("  已刷新 %s（基于新需求 Σ=%.0f）" % (os.path.relpath(p, ROOT), vol))

    # ---------------- 2) 口径③ 的日末最大积压
    sc = json.load(open(os.path.join(DATA_DIR, "p3_stats_cum.json"), encoding="utf-8"))
    print("\n[2] 口径③（到期累计）：Σ=%.0f 时总人天 %s，日末最大积压 %s 件/中心·日"
          % (sc["total_volume"], format(sc["person_days"], ","),
             format(int(sc["max_backlog_end"]), ",")))

    # ---------------- 3) u_h 的日间最大标准差
    t5 = read_csv(os.path.join(RES_DIR, "结果表5.csv"))
    t5["T"] = t5["正式工人数"] + t5["临时工人数"]
    by_day = defaultdict(list)
    cell = {}
    for c, d, s, x, y in zip(t5["分拣中心"], t5["日期"], t5["班次"],
                             t5["正式工人数"], t5["临时工人数"]):
        cell[(c, str(d), str(s))] = (int(x), int(y))
    for c in centers:
        for k in range(p3.N_DAY):
            d = p3.DATES[k]
            xs = [0] * p3.NS
            ys = [0] * p3.NS
            for si, sname in enumerate(p3.SHIFT_NAMES):
                v = cell.get((c, d, sname))
                if v:
                    xs[si], ys[si] = v
            work, backlog, cap = p3.simulate_work(demand[(c, k)], xs, ys)
            for h in range(24):
                if cap[h] > 0 and work[h] > 1e-9:
                    by_day[d].append(work[h] / cap[h])
    stds = {d: float(np.std(by_day[d])) for d in p3.DATES}
    dmax = max(stds, key=lambda d: stds[d])
    dmin = min(stds, key=lambda d: stds[d])
    allu = [u for d in p3.DATES for u in by_day[d]]
    print("\n[3] u_h：全网汇总均值 %.4f、std %.4f；30 天逐日 std 的最大值 %.4f（%s），最小 %.4f（%s）"
          % (float(np.mean(allu)), float(np.std(allu)), stds[dmax], dmax, stds[dmin], dmin))
    print("     逐日 u_h 均值范围 %.4f ~ %.4f"
          % (min(float(np.mean(by_day[d])) for d in p3.DATES),
             max(float(np.mean(by_day[d])) for d in p3.DATES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
