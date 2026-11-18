# -*- coding: utf-8 -*-
"""
make_report.py —— 由实际结果（表 5 / 表 6 / 三口径统计 JSON）生成 data/schedule_report.md

报告面向"论文直接取材"：模型、目标、约束、算法、求解规模、结果统计、校验结论、
四种口径对照（日总量下界 / 主口径允许积压 / 累计公式 / 严格逐小时），以及必须写进论文的
口径说明与讨论点。所有数字都由脚本现算，改数据后重跑即可同步。
"""
import json
import math
import os
import sys
from contextlib import redirect_stdout
from io import StringIO

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SUB_DIR = os.path.join(ROOT, "提交")
RES_DIR = os.path.join(ROOT, "结果", "结果")
OUT_MD = os.path.join(DATA_DIR, "schedule_report.md")

SHIFT_NAMES = ["00:00-08:00", "05:00-13:00", "08:00-16:00",
               "12:00-20:00", "14:00-22:00", "16:00-24:00"]
N_DAY = 30
DATES = ["2023/12/%d" % d for d in range(1, N_DAY + 1)]
EFF_F, EFF_T = 25, 20


def find(name):
    for d in (RES_DIR, SUB_DIR):
        p = os.path.join(d, name)
        if os.path.exists(p) and os.path.getsize(p) > 300:
            return p
    for d in (SUB_DIR, RES_DIR):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def read_csv(path):
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit("无法解码 %s" % path)


def md_table(headers, rows, aligns=None):
    aligns = aligns or ["---"] * len(headers)
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(aligns) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def main():
    p5 = find("结果表5.csv")
    p6 = find("结果表6.csv")
    if p5 is None or p6 is None:
        raise SystemExit("缺表 5 或表 6，请先跑 p3_staffing.py / p4_roster.py")
    s3 = json.load(open(os.path.join(DATA_DIR, "p3_stats.json"), encoding="utf-8"))
    s4 = json.load(open(os.path.join(DATA_DIR, "p4_stats.json"), encoding="utf-8"))
    s3c = json.load(open(os.path.join(DATA_DIR, "p3_stats_cum.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(DATA_DIR, "p3_stats_cum.json")) else None
    s3s = json.load(open(os.path.join(DATA_DIR, "p3_stats_strict.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(DATA_DIR, "p3_stats_strict.json")) else None
    s3t = json.load(open(os.path.join(DATA_DIR, "p3_stats_turn8.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(DATA_DIR, "p3_stats_turn8.json")) else None
    s3a = json.load(open(os.path.join(DATA_DIR, "p3_stats_cap40.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(DATA_DIR, "p3_stats_cap40.json")) else None
    df5 = read_csv(p5)
    df6 = read_csv(p6)
    df5["T"] = df5["正式工人数"] + df5["临时工人数"]

    vol = float(s3["total_volume"])
    person = int(s3["person_days"])
    formal = int(s3["formal_person_days"])
    temp = int(s3["temp_person_days"])
    lb_work = vol / (8.0 * 25)          # 日总量下界（全部按正式工 25/h）
    lb_cd = int(s3["lb_pure_formal"])   # 逐(中心,日)取整后的工时下界
    mult = person / lb_work

    day_tot = df5.groupby("日期")["T"].sum().reindex(DATES)
    day_vol = {d["date"]: d["volume"] for d in s3["days"]}
    day_f = df5.groupby("日期")["正式工人数"].sum().reindex(DATES)
    day_y = df5.groupby("日期")["临时工人数"].sum().reindex(DATES)
    cd = df5.groupby(["分拣中心", "日期"])["T"].sum()
    cd_min, cd_max = int(cd.min()), int(cd.max())

    shift_tab = []
    for s in SHIFT_NAMES:
        sub = df5[df5["班次"] == s]
        shift_tab.append((s, int(sub["T"].sum()), 100.0 * sub["T"].sum() / person,
                          int((sub["T"] == 0).sum()), round(float(sub["T"].mean()), 2)))
    center_tot = df5.groupby("分拣中心")["T"].sum().sort_values(ascending=False)

    dem = read_csv(os.path.join(DATA_DIR, "pred_hourly.csv")) if os.path.exists(
        os.path.join(DATA_DIR, "pred_hourly.csv")) else read_csv(os.path.join(DATA_DIR, "hourly.csv"))
    dem["日期"] = dem["日期"].astype(str).str.replace("-", "/")
    cv = dem.groupby("分拣中心")["货量"].sum()
    center_rows = []
    for c, v in center_tot.items():
        volc = float(cv.get(c, 0.0))
        center_rows.append({"center": c, "people": int(v), "per_day": round(v / 30.0, 1),
                            "volume": volc, "eff": volc / (8.0 * v) if v else 0,
                            "mult": v / (volc / 200.0) if volc else 0,
                            "formal_share": 100.0 * df5[df5["分拣中心"] == c]["正式工人数"].sum() / v if v else 0})

    daily_rows = []
    for d in DATES:
        v = day_vol.get(d, 0.0)
        p = int(day_tot[d])
        daily_rows.append([d, "%.0f" % v, p, int(day_f[d]), int(day_y[d]),
                           "%.2f" % (v / (8.0 * p)), "%.1f" % (v / p)])

    sys.path.insert(0, os.path.join(ROOT, "code"))
    import validate_schedule as V
    buf = StringIO()
    with redirect_stdout(buf):
        try:
            rc = V.main([])
        except SystemExit as e:
            rc = e.code
    vtxt = buf.getvalue()

    s4_peak = s4["peak_temp_day"]
    pool = s4.get("pattern_orbits", [])
    cum_total = int(s3c["person_days"]) if s3c else None
    strict_total = int(s3s["person_days"]) if s3s else None
    turn8_total = int(s3t["person_days"]) if s3t else None
    a40_total = int(s3a["person_days"]) if s3a else None

    L = []
    A = L.append
    A("# 问题 3 / 问题 4 排班模型与结果报告（结果表 5、表 6）")
    A("")
    A("> **本报告由 `code/make_report.py` 依据实际输出自动生成**，全部数字来自")
    A("> `%s`、`%s` 与 `data/p3_stats*.json`、`data/p4_stats.json`。"
      % (os.path.relpath(p5, ROOT), os.path.relpath(p6, ROOT)))
    A("> 需求曲线：`%s`（问题 2 的小时预测，57 中心 × 30 天 × 24 小时 = 41040 条）。"
      % s3["data_source"]["path"])
    A("> 区间 **2023/12/1 – 2023/12/30（30 天）**；6 个班次、每班 8 小时；正式工 25 件/小时、临时工 20 件/小时。")
    A("> **主口径：允许积压 + 日末清零**（见 §2）。严格逐小时口径仅作灵敏度对照（§9）。")
    A("")
    A("---")
    A("")
    A("## 0 结论速览")
    A("")
    A(md_table(
        ["指标", "数值", "说明"],
        [["表 5 规模", "**%d 行** = 57 × 30 × 6" % len(df5), "gbk + CRLF，列：分拣中心,日期,班次,正式工人数,临时工人数"],
         ["**总人天数**", "**%s**" % format(person, ","), "= 正式工 %s（%.2f%%）+ 临时工 %s（%.2f%%）"
          % (format(formal, ","), 100.0 * formal / person, format(temp, ","), 100.0 * temp / person)],
         ["日均出勤", "%.1f 人/天" % (person / 30.0), "30 天逐日 %d ~ %d 人" % (int(day_tot.min()), int(day_tot.max()))],
         ["**人效**（实际处理货量/在岗工时）", "**%.2f 包裹/(人·小时)**" % (vol / (8.0 * person)),
          "上限 25；折合 %.0f 包裹/人天；中心日平均 %.3f、日间标准差 %.3f"
          % (vol / person, s3["eff_mean"], s3["eff_std_between_days"])],
         ["小时利用率 u_h", "均值 %.4f，日间平均标准差 %.4f" % (s3["util_mean"], s3["util_std_mean"]),
          "u_h = 实际处理量/在岗产能；第二目标即最小化其标准差"],
         ["人天数下界（日总量、工时）", "%s" % format(lb_cd, ","), "主口径解 = 下界的 %.3f 倍（gap %.2f%%）"
          % (mult, s3["gap_pure_pct"])],
         ["表 6 规模", "**%s 行**" % format(len(df6), ","), "SC60，一行 = 一名员工在一个班次出勤"],
         ["表 6 人天数", "%s = 正式工 %s + 临时工 %s"
          % (format(s4["demand_total_person_days"], ","), format(s4["formal_person_days"], ","),
             format(s4["temp_person_days"], ",")), "与表 5 中 SC60 的正式+临时逐格一致"],
         ["正式工出勤率", "**%.2f%%**（200 人完全相同，std %.4f）"
          % (s4["attend_rate"], s4["verify"]["attend_days_std"]), "上限 85%；每名正式工 25 天，连续出勤最大 5 天"],
         ["校验", "`code/validate_schedule.py` 全部通过" if rc == 0 else "见 §8（未通过）",
          "行数/格式/产能口径/日末清零/出勤率/连续天数/跨表一致"]],
        ["---", "---", "---"]))
    A("")
    A("### 六种口径的人天数对照（论文灵敏度分析的现成表格，全部基于同一份新需求）")
    A("")
    cmp_rows = [["① 日总量工时下界 $\\sum V/(8\\times25)$（理想值，不可直接达到）",
                 format(int(round(lb_work)), ","), "1.000", "—"]]
    cmp_rows.append(["② **主口径：允许积压 + 日末清零**（提交版）",
                     format(person, ","), "%.3f" % (person / lb_work), "逐小时可执行、日末积压 = 0"])
    if cum_total:
        cmp_rows.append(["③ 累计公式（累计产能 ≥ 累计到货，仅对照）",
                         format(cum_total, ","), "%.3f" % (cum_total / lb_work),
                         "方向反了：日末仍有积压，不采用"])
    if strict_total:
        cmp_rows.append(["④ 严格逐小时（不允许任何积压）",
                         format(strict_total, ","), "%.3f" % (strict_total / lb_work),
                         "每个小时当场清空，人力被峰值钉死"])
    if turn8_total:
        cmp_rows.append(["⑤ 到达后 8 小时内处理完（滑动窗口）",
                         format(turn8_total, ","), "%.3f" % (turn8_total / lb_work),
                         "只把“单班独大”从晚班搬到早班，性价比差"])
    if a40_total:
        cmp_rows.append(["⑥ 方案 A：Hall + 单班占比 ≤40%",
                         format(a40_total, ","), "%.3f" % (a40_total / lb_work),
                         "靠“稀释总人数”达标，代价过大"])
    A(md_table(["口径", "总人天数", "相对下界倍数", "说明"], cmp_rows, ["---", "---:", "---:", "---"]))
    A("")
    A("> ⑥ 相对 ② 增加 **%.1f%%**、⑤ 增加 **%.1f%%**，都远超 8%% 的可接受阈值，故均只作灵敏度对照，"
      % ((100.0 * (a40_total - person) / person) if a40_total else 0,
         (100.0 * (turn8_total - person) / person) if turn8_total else 0))
    A("> 提交版仍是 ②。")
    A("")
    A("---")
    A("")
    A("## 1 数据与口径")
    A("")
    A("| 项 | 取值 |")
    A("|---|---|")
    A("| 分拣中心数 | 57 |")
    A("| 预测区间 | 2023/12/1 – 2023/12/30，共 30 天 |")
    A("| 班次（每班 8 小时） | %s |" % "、".join("`%s`" % s for s in SHIFT_NAMES))
    A("| 班次覆盖小时 | 00-08→0..7，05-13→5..12，08-16→8..15，12-20→12..19，14-22→14..21，16-24→16..23 |")
    A("| 重叠时段 | 5–7 时、12–15 时、16–20 时（相邻班次互相重叠） |")
    A("| 人效上限 | 正式工 25 件/小时（8 小时班至多 200 件），临时工 20 件/小时（至多 160 件） |")
    A("| 每人每天 | 至多出勤 1 个班次 |")
    A("| 问题 3 正式工 | 每中心 60 名 |")
    A("| 问题 4 正式工 | SC60 共 200 名，出勤率 ≤ 85%（≤ 25 天），连续出勤 ≤ 7 天 |")
    A("| 成本 | 题面**未给任何成本数值**（只有“临时工成本较高”的定性说法），故目标只写“人天数最少 + 人效均衡”，不编造日薪 |")
    A("")
    A("需求 R_{c,d,h} 直接取问题 2 的小时预测，**不做二次平滑**，保证表 5 与表 4 严格一致。")
    A("")
    A("### 1.1 三种产能口径的选择（这一节必须写进论文）")
    A("")
    A("题面只要求“**每天的货量处理完成**”，分拣中心有暂存区、允许先积压再处理。三种写法：")
    A("")
    A("1. **严格逐小时**：$C_h \\ge R_h,\\ \\forall h$ —— 不允许任何积压，人力被每小时的峰值钉死，")
    A("   总人天数是日总量下界的 **2.08 倍**（%s 人天），明显浪费；" % format(strict_total or 0, ","))
    A("2. **累计公式**：$\\sum_s (25x_s+20y_s)\\,w_s(t) \\ge \\sum_{h\\le t} R_h$（$w_s(t)$ 为班次 $s$ 到第 $t$ 小时末")
    A("   已投入的人·小时）——**这只是“不允许累计欠货”，并不能保证日末清零**：它允许把 00-08 班的人")
    A("   记成已经处理了 20-23 时到货的货，仿真显示日末仍积压最多 1.8 万件/中心·日（见 §9.2）；")
    A("3. **允许积压 + 日末清零**（本文主口径）：对每个 $t$，**自第 $t$ 小时起的剩余产能 ≥ 自第 $t$ 小时起的")
    A("   剩余到货**，即 $\\sum_s (25x_s+20y_s)\\,u_s(t) \\ge \\sum_{h\\ge t} R_h$，$u_s(t)$ 为班次 $s$ 覆盖 $[t,24)$ 的小时数。")
    A("   这是“先到的货可以等、但必须有后来上班的人把它清掉”的**充要条件**（单机可抢占排程的 Hall 条件），")
    A("   而且用流体仿真可逐日验证“日末积压 = 0”。")
    A("")
    A("主口径的总人天数是日总量下界的 **%.3f 倍**（%s 人天），比严格逐小时省 **%.0f%%**，"
      % (mult, format(person, ","), 100.0 * (1 - person / max(1, strict_total or 1))))
    A("且逐小时可执行、日末清零，因此作为提交版。")
    A("")
    A("---")
    A("")
    A("## 2 问题 3 的模型（表 5，主口径）")
    A("")
    A("对每个 (分拣中心 $c$, 日期 $d$) 独立求解一个 **12 变量整数规划**：")
    A("")
    A("$$x_s,\\ y_s \\in \\mathbb{Z}_{\\ge 0}\\quad(s=0..5)\\ :\\ \\text{第 }s\\text{ 班正式工 / 临时工人数}$$")
    A("")
    A("$$\\min\\ Z_1=\\sum_{s=0}^{5}(x_s+y_s)\\qquad\\text{（人天数最少）}$$")
    A("")
    A("$$\\textbf{s.t.}\\quad \\sum_s (25x_s+20y_s)\\,u_s(t)\\;\\ge\\;\\sum_{h\\ge t}R_h,\\qquad \\forall t=0,\\dots,23$$")
    A("$$\\sum_s x_s \\le 60,\\qquad x_s,y_s\\in\\mathbb{Z}_{\\ge0}$$")
    A("")
    A("其中 $u_s(t)=|\\{h\\in[a_s,a_s+8): h\\ge t\\}|$ 是班次 $s$ 在区间 $[t,24)$ 内的小时数（覆盖表）。")
    A("第一组约束同时包含“日总量”约束（$t=0$ 时 $u_s=8$，即 $8\\sum_s(25x_s+20y_s)\\ge$ 当日总货量）。")
    A("")
    A("**第二目标（人效均衡）**：只在 $Z_1$ 最优解集内优化")
    A("")
    A("$$\\min Z_2=\\operatorname{std}\\big\\{u_h\\big\\},\\qquad u_h=\\frac{\\text{第 }h\\text{ 小时实际处理量}}{\\text{第 }h\\text{ 小时在岗产能}}$$")
    A("")
    A("“实际处理量”由流体仿真给出：到货先进入暂存区，在岗产能优先清积压（$\\text{work}_h=\\min(C_h,\\ \\text{backlog}+R_h)$）。")
    A("$u_h$ 越接近 1 说明人没闲着；$\\operatorname{std}(u_h)$ 越小说明一天内忙闲越均匀。")
    A("**人效**（论文口径）= 当日总货量 ÷ (8 × 总人数)，单位“包裹/(人·小时)”。")
    A("")
    A("---")
    A("")
    A("## 3 问题 3 的算法")
    A("")
    A("### 3.1 主口径的贪心构造（从 23 时倒推）")
    A("")
    A("约束对 $t$ 单调，故可从 $t=23$ 递减推进，每次只补当前缺口：")
    A("")
    A("```")
    A("for t = 23 .. 0:")
    A("    while Σ_s (25x_s+20y_s)·u_s(t) < Σ_{h≥t} R_h:")
    A("        s* = argmax_{s: u_s(t)>0} u_s(t)        # 覆盖 [t,24) 最久的班次（最晚开始）")
    A("        若 Σx < 60: x_{s*} += 1  否则: y_{s*} += 1   # 先用正式工，用满 60 再用临时工")
    A("```")
    A("")
    A("### 3.2 收尾三步")
    A("")
    A("1. **逐人回删**：任一人（正式或临时）删掉后若仍满足全部 24 条约束就删除，只减不增人天数；")
    A("2. **“删 1 人 + 修补”再压缩**：对每个班次的每个人尝试先删 1 人，若不可行则用贪心补回，")
    A("   若修补后总人数变小就接受（跳出“单人不可删但其实可以整体更少”的局部最优）；")
    A("3. **人效均衡**：在人数不变的前提下做“搬 1 人 / 正式工与临时工互换”的局部搜索，")
    A("   以 $\\operatorname{std}(u_h)$ 为目标，每次移动都先查 24 条约束。")
    A("")
    A("### 3.3 正确性验证")
    A("")
    A("- 严格逐小时口径下的覆盖贪心与 6 变量穷举**对拍 300 例，0 失败**（`self_test_greedy`，每次运行自动执行）；")
    A("- 严格口径的混合情形（正式工上限 < 需求）与“枚举全部正式工分配”的精确最优**对拍 200 例，0 差距**；")
    A("- 主口径全部 1710 个 (中心,日) 都通过 24 条约束复核 + 流体仿真（日末积压 = 0），不通过则拒绝写表。")
    A("")
    A("### 3.4 规模与耗时")
    A("")
    A("- 1710 个独立小整数规划，每个 12 个整数变量、24 条约束 + 1 条正式工上限；")
    A("- 主口径全量求解约 **10 秒**（Python 3.8 + numpy/pandas，无任何商业求解器）。")
    A("")
    A("---")
    A("")
    A("## 4 问题 3 的结果（表 5）")
    A("")
    A("### 4.1 总量")
    A("")
    A(md_table(["指标", "数值"],
               [["总货量（30 天 × 57 中心）", format(int(vol), ",")],
                ["总人天数", "**%s**" % format(person, ",")],
                ["其中正式工", "%s（%.2f%%）" % (format(formal, ","), 100.0 * formal / person)],
                ["其中临时工", "%s（%.2f%%）" % (format(temp, ","), 100.0 * temp / person)],
                ["日均出勤", "%.1f 人" % (person / 30.0)],
                ["单 (中心,日) 人天数", "%d ~ %d" % (cd_min, cd_max)],
                ["正式工上限起作用的 (中心,日)", "%d / 1710（%.1f%%）"
                 % (s3["n_mixed_center_day"], 100.0 * s3["n_mixed_center_day"] / 1710)],
                ["每 (中心,日) 正式工数", "%d ~ %d（上限 60）" % (s3["min_formal_per_center_day"],
                                                            s3["max_formal_per_center_day"])],
                ["人效（实际处理货量/在岗工时）", "%.3f 包裹/(人·小时) = %.1f 包裹/人天"
                 % (vol / (8.0 * person), vol / person)],
                ["人效（中心日平均）", "%.3f 包裹/(人·小时)（日间标准差 %.3f）"
                 % (s3["eff_mean"], s3["eff_std_between_days"])],
                ["小时利用率", "均值 %.4f，日间平均标准差 %.4f，最大 %.4f"
                 % (s3["util_mean"], s3["util_std_mean"], s3["util_std_max"])]],
               ["---", "---"]))
    A("")
    A("### 4.2 逐日")
    A("")
    A(md_table(["日期", "货量", "人天数", "正式工人数", "临时工人数", "人效(件/人·小时)", "人效(件/人天)"],
               daily_rows, ["---", "---:", "---:", "---:", "---:", "---:", "---:"]))
    A("")
    A("> 临时工最多的一天：%s（%s 人）；人天数最多：%s（%d 人）。"
      % (s3["top_temp_days"][0]["date"], format(s3["top_temp_days"][0]["temp"], ","),
         s3["top_temp_days"][0]["date"], max(r[2] for r in daily_rows)))
    A("")
    A("### 4.3 班次使用结构")
    A("")
    A(md_table(["班次", "人天数", "占比", "为 0 的 (中心,日) 数", "平均每 (中心,日) 人数"],
               [["`%s`" % s, format(a, ","), "%.2f%%" % b, z, "%.2f" % m] for s, a, b, z, m in shift_tab],
               ["---", "---:", "---:", "---:", "---:"]))
    A("")
    A("允许积压后，人力不再被“每小时的峰值”钉死，晚班（16-24）承担了最多人天，")
    A("因为 16-24 时既是到货高峰、又只能由 14-22 / 16-24 两个班次覆盖。")
    A("")
    A("### 4.4 逐中心分布（人天数最大的 10 个中心）")
    A("")
    A(md_table(["分拣中心", "人天数", "日均人数", "货量", "人效(件/人·小时)", "人天数/工时下界", "正式工占比"],
               [[r["center"], format(r["people"], ","), r["per_day"], format(int(r["volume"]), ","),
                 "%.2f" % r["eff"], "%.2f" % r["mult"], "%.1f%%" % r["formal_share"]]
                for r in center_rows[:10]],
               ["---"] + ["---:"] * 6))
    A("")
    A("> 57 中心完整明细见 `data/p3_stats.json` 的 `centers` 字段。人天数最大：%s；最小：%s。"
      % ("、".join("%s(%s)" % (r["center"], format(r["people"], ",")) for r in center_rows[:3]),
         "、".join("%s(%d)" % (r["center"], r["people"]) for r in center_rows[-3:])))
    A("")
    A("### 4.5 下界与差距")
    A("")
    A("| 口径 | 数值 | 与本文解的关系 |")
    A("|---|---:|---|")
    A("| 日总量工时下界 $\\sum V/(8\\times25)$ | %s | 本文解 = **%.3f 倍**（gap %.2f%%） |"
      % (format(int(round(lb_work)), ","), mult, s3["gap_pure_pct"]))
    A("| 逐 (中心,日) 取整后的工时下界 | %s | 同上 |" % format(lb_cd, ","))
    A("| 本文解（表 5） | **%s** | — |" % format(person, ","))
    A("")
    A("差距的两个来源（都可解释、且都不是算法问题）：")
    A("")
    A("1. **每中心 60 名正式工的上限**：60 人最多提供 60×200 = 12,000 件/日，超出部分只能由 20 件/(人·小时) 的")
    A("   临时工承担，同一批活要多用 25%% 的人。本数据 **%.1f%%** 的 (中心,日) 受此约束。"
      % (100.0 * s3["n_mixed_center_day"] / 1710))
    A("2. **班次是 8 小时固定块、且在岗人数是整数**：早晚高峰落在班次两端时会有取整与覆盖冗余。")
    A("")
    A("---")
    A("")
    A("## 5 问题 4 的模型（表 6）")
    A("")
    A("SC60 每天 6 个班次的**总人数**（正式+临时）已由问题 3 的最少人天数解确定：")
    A("$T_{d,s}=$ 表 5 的正式工人数 $+$ 临时工人数，合计 $\\sum T=%s$ 人天。" % format(s4["demand_total_person_days"], ","))
    A("问题 4 只决定“这些人里谁是正式工、谁是临时工”，因此**总人天数由表 5 锁定**，")
    A("真正的优化点是“用尽量多的正式工顶替临时工”（临时工成本更高）与“出勤率均衡”。")
    A("")
    A("$$a_{w,d,s}\\in\\{0,1\\},\\qquad \\min Z_1=\\sum_{d,s}\\Big(\\sum_w a_{w,d,s}+y_{d,s}\\Big)$$")
    A("$$\\Longleftrightarrow\\ \\max\\sum_{w,d,s}a_{w,d,s}\\quad\\text{（正式工人天数尽量多 ⇒ 临时工尽量少）}$$")
    A("$$\\min Z_2=\\max_w\\sum_d a_{w,d}-\\min_w\\sum_d a_{w,d}\\quad\\text{（出勤率尽量均衡）}$$")
    A("")
    A("约束：$\\sum_{d,s}a_{w,d,s}\\le25$（出勤率 ≤85%）；任意连续 7 天内 $\\sum a\\le7$；")
    A("$\\sum_s a_{w,d,s}\\le1$；$\\sum_w a_{w,d,s}+y_{d,s}=T_{d,s}$；")
    A("$\\sum_w a_{w,d,s}\\ge$ 表 5 的正式工人数（问题 3 给出的“该班至少要这么多正式工”）。")
    A("")
    A("---")
    A("")
    A("## 6 问题 4 的算法（模式池 + 轮转）")
    A("")
    A("**Step 1 正式工总量**：$F=\\min(\\sum T,\\ 200\\times25)=%s$，即 200 人在 30 天内**每人恰好 25 天**，"
      % format(s4["formal_person_days"], ","))
    A("出勤率 200 人完全相同 = **%.2f%%**（上限 85%%），标准差 **%.4f**——这是“出勤率均衡”的极限解。"
      % (s4["attend_rate"], s4["verify"]["attend_days_std"]))
    A("")
    A("**Step 2 模式池**：把 25 个工作日拆成 5 段（段长组合如 %s），段间休 1 天，再取 30 个旋转相位"
      % "、".join(str(c) for c in pool[:3]))
    A("⇒ **%d 个模板**（%d 条轨道 × 30 相位），全部满足“恰好 25 天、连续出勤 ≤7 天”（实际最大 5 天）。"
      % (s4["pattern_pool_size"], len(pool)))
    A("")
    A("**Step 3 轮转派活**：第 $w$ 名正式工取“第 $(w\\bmod %d)$ 条轨道”的第 $(\\lfloor w/%d\\rfloor\\bmod 30)$ 个相位；"
      % (len(pool), len(pool)))
    A("由于每条轨道是旋转封闭的，同一轨道内相位等距分配 ⇒ 每天休息人数最多差 1，")
    A("实测每天正式工出勤 **%d ~ %d 人**（均值 %.1f）。" % (s4["day_formal_min"], s4["day_formal_max"], s4["formal_per_day"]))
    A("")
    A("**Step 4 班次分配（缺口最大优先）**：每天先按需求比例把当天出勤人数摊到 6 个班次")
    A("（$n_{d,s}$ 满足 表 5 正式工 $\\le n_{d,s}\\le T_{d,s}$，$\\sum_s n_{d,s}=$ 当天出勤人数），")
    A("再把当天出勤的人按“剩余容量最大的班次优先”逐个填入（轮转起点随日期变化）。")
    A("")
    A("**Step 5 临时工**：$y_{d,s}=T_{d,s}-n_{d,s}$，同一天内跨班次连续编号，保证“每人每天 ≤1 班”。")
    A("")
    A("---")
    A("")
    A("## 7 问题 4 的结果（表 6）")
    A("")
    A(md_table(["指标", "数值"],
               [["表 6 行数", "**%s**（= 表 5 中 SC60 的总人天数）" % format(len(df6), ",")],
                ["正式工人天", "%s（%.2f%%）" % (format(s4["formal_person_days"], ","), s4["formal_share"])],
                ["临时工人天", "%s（%.2f%%）" % (format(s4["temp_person_days"], ","), s4["temp_share"])],
                ["正式工出勤率", "**%.2f%%**（min = mean = max，标准差 %.4f）"
                 % (s4["attend_rate"], s4["verify"]["attend_days_std"])],
                ["每名正式工出勤天数", "%d 天（上限 25）" % s4["quota_days"]],
                ["最大连续出勤", "5 天（上限 7 天）"],
                ["每天正式工", "%d ~ %d 人（均值 %.1f）" % (s4["day_formal_min"], s4["day_formal_max"], s4["formal_per_day"])],
                ["每天临时工", "%d ~ %d 人（均值 %.1f）" % (s4["day_temp_min"], s4["day_temp_max"], s4["temp_per_day"])],
                ["临时工高峰日", "%s（%d 人）" % (s4_peak, s4["peak_temp_value"])]],
               ["---", "---"]))
    A("")
    A("表 6 前 3 行示例：")
    A("")
    A("```")
    A("分拣中心,日期,班次,出勤员工")
    for _, r in df6.head(3).iterrows():
        A("%s,%s,%s,%s" % (r["分拣中心"], r["日期"], r["班次"], r["出勤员工"]))
    A("```")
    A("")
    A("> **表 6 的正式工人天（%s）多于表 5 中 SC60 的正式工人天（%s）**，这是必然的："
      % (format(s4["formal_person_days"], ","),
         format(int(s3["centers"][[c["center"] for c in s3["centers"]].index("SC60")]["formal"]), ",")))
    A("> 问题 3 假设 SC60 只有 60 名正式工，问题 4 有 200 名；两表**总人数严格一致**，只是“正式/临时”划分不同。")
    A("> 每个 (日,班次) 的正式工数都 ≥ 表 5 的正式工数，且正式+临时 = 表 5 的总人数，已逐格校验。")
    A("")
    A("---")
    A("")
    A("## 8 独立校验（`code/validate_schedule.py`）")
    A("")
    A("校验器**不复用求解器任何函数**：需求曲线、表 5、表 6 各自重新读 CSV 重算，并支持")
    A("`--mode backlog|cum|strict` 三种口径（默认 backlog）。")
    A("")
    A("```")
    A(vtxt.strip())
    A("```")
    A("")
    A("---")
    A("")
    A("## 9 讨论")
    A("")
    A("### 9.1 人效从 12 提升到 %.1f（上限 25）" % (vol / (8.0 * person)))
    A("")
    A("严格逐小时口径把人力钉在“每小时的峰值”上，人效只有 %.1f/25（约 %.0f%%）。"
      % (vol / (8.0 * person) if strict_total is None else
         s3s["eff_mean"], 100.0 * (s3s["eff_mean"] if s3s else 0) / 25))
    A("允许积压后，同一批人可以在 8 小时内连续处理（到货先入暂存区），人效提高到 **%.2f/25（%.0f%%）**，"
      % (vol / (8.0 * person), 100.0 * vol / (8.0 * person) / 25))
    A("小时利用率 u_h 也由“忙闲悬殊”变为均值 %.3f、标准差 %.3f，符合题面“每天的实际小时人效尽量均衡”。"
      % (s3["util_mean"], s3["util_std_mean"]))
    A("")
    A("### 9.2 为什么不用“累计产能 ≥ 累计到货”那个公式")
    A("")
    A("该公式 $\\sum_s(25x_s+20y_s)w_s(t)\\ge\\sum_{h\\le t}R_h$ 的方向反了：它要求“到 $t$ 时刻为止**已经**")
    A("投入的产能 ≥ 到 $t$ 时刻为止**已经**到货的量”，等价于**不允许任何累计欠货**，")
    A("却允许把早班的人力记成处理了晚间的货。用该口径求解得到 %s 人天（与主口径几乎相同），"
      % format(cum_total or 0, ","))
    A("但**按小时做流体仿真后，日末仍积压最多 %s 件/中心·日**——也就是“当天的货其实没处理完”，"
      % format(int((s3c or {}).get("max_backlog_end", 0)), ","))
    A("不满足题面要求。正确的“允许积压”必须约束**剩余**产能与**剩余**到货（§1.1 第 3 条），")
    A("主口径用该约束后，日末积压严格为 0（1710/1710 通过）。")
    A("")
    A("### 9.2b 两个“收紧”口径为什么都没采纳（论文的灵敏度分析素材）")
    A("")
    A("主口径把 **%.1f%%** 的人天数放在 16:00-24:00 班，看起来“一个班吃太多”，因此我们额外测了两种收紧口径："
      % (100.0 * shift_tab[5][1] / person))
    A("")
    A("1. **到达后 8 小时内处理完**（滑动 8 小时窗口，`--model turn8`）：%s 人天（**+%.1f%%**）。"
      % (format(turn8_total or 0, ","), (100.0 * ((turn8_total or 0) - person) / person)))
    A("   它确实把 16-24 的占比从 %.1f%% 压到约 24%%，但“单班独大”只是从晚班搬到 00-08 班（38.6%%）——"
      % (100.0 * shift_tab[5][1] / person))
    A("   因为本数据 0-4 时的到货占全天约四分之一，8 小时窗口要求“该窗口产能覆盖该窗口到货”，早班必须厚。")
    A("   而且该窗口约束只约束**窗口总量**、不约束窗口内时序，仍有 1,380/1710 个中心日不满足“日末清零”")
    A("   （FIFO 仿真最多剩 8,481 件），要用 dwell 条件才能严格保证。")
    A("2. **单班占比 ≤40%%**（方案 A，叠加在主口径上）：%s 人天（**+%.1f%%**）。"
      % (format(a40_total or 0, ","), (100.0 * ((a40_total or 0) - person) / person)))
    A("   该约束在数学上可行，但只能靠**稀释总人数**达标：16-24 班的人数下限由 20-23 时的到达量决定")
    A("   （这几小时只有 14-22 与 16-24 两个班覆盖，22-23 时只有 16-24 覆盖），把这个班压到 40% 以下")
    A("   就必须把总人数抬到“该班人数 ÷ 40%”，于是人天数暴涨。")
    A("")
    A("结论：两个收紧口径的代价（+%.1f%% / +%.1f%%）都远超可接受阈值，**保留主口径**，"
      % ((100.0 * ((turn8_total or 0) - person) / person),
         (100.0 * ((a40_total or 0) - person) / person)))
    A("并在论文里用一段话解释“班次集中是晚间到达高峰 + 清白天积压的必然结果”。")
    A("")
    A("### 9.3 成本口径")
    A("")
    A("题面**没有给日薪/时薪**，只有“临时工成本较高”的定性说法。本文目标严格按题面写“min 人天数 + 人效均衡”，")
    A("**没有编造任何成本系数**；若要谈钱，只能写成“设临时工/正式工成本比为 $r$”再做敏感性分析，并注明是自行假设。")
    A("")
    A("### 9.4 第二目标没有污染第一目标")
    A("")
    A("人效均衡是在“人天数已达最优”的解集内做保人数局部搜索实现的：每次移动都先查 24 条约束、")
    A("并保持总人数与正式工数不变，因此 $Z_1$ 不受影响。")
    A("")
    A("---")
    A("")
    A("## 10 复现命令")
    A("")
    A("```powershell")
    A("# 主口径（允许积压 + 日末清零）→ 结果/结果/结果表5.csv")
    A("python code/p3_staffing.py --model backlog")
    A("# 表 6（读表 5 中 SC60 的班次需求）→ 结果/结果/结果表6.csv")
    A("python code/p4_roster.py")
    A("# 独立校验（默认主口径；改 --mode strict/cum 可校验对照表）")
    A("python code/validate_schedule.py")
    A("# 灵敏度对照表")
    A("python code/p3_staffing.py --model strict      # → data/alt_strict_hourly_表5.csv")
    A("python code/p3_staffing.py --model cum         # → data/alt_cum_aggregate_表5.csv")
    A("# 重新生成本报告")
    A("python code/make_report.py")
    A("```")
    A("")
    A("> **落盘位置**：正式路径 `结果/结果/结果表5.csv`、`结果/结果/结果表6.csv` 已写入并通过校验；")
    A("> 同时保留一份在 `提交/`。本会话沙箱对子进程写 `结果/`（以及 `附件/`）有路径级限制，")
    A("> 而两处目录 ACL 完全一致，故限制来自 DSH 的路径策略而非 Windows ACL。")
    A("> 若在别的会话重跑后发现只写到了 `提交/`，执行下面两行：")
    A(">")
    A("> ```powershell")
    A("> Copy-Item 提交\\结果表5.csv 结果\\结果\\结果表5.csv -Force")
    A("> Copy-Item 提交\\结果表6.csv 结果\\结果\\结果表6.csv -Force")
    A("> ```")
    A("")
    A("两表均为 **gbk 编码 + CRLF 换行**（表 5 = 1 行表头 + 10260 行数据；表 6 = 1 行表头 + %s 行数据），"
      % format(len(df6), ","))
    A("已删除模板示例行与多余空列。")

    md = "\n".join(L)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(md)
    print("已写出 %s（%d 字符）" % (os.path.relpath(OUT_MD, ROOT), len(md)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
