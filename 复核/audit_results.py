# -*- coding: utf-8 -*-
"""复核主脚本（可重复运行）：A 格式 + B 一致性 + C 独立仿真 + D 人员约束 + 针对性三点。

用法：
    python 复核/audit_results.py                # 跑当前 结果/结果/结果表1~6.csv
    python 复核/audit_results.py --tag round2   # 输出文件名带版本标记

只读交付文件；所有输出写到 复核/_work/out/ 与 复核/audit_results_<tag>.md。
不 import 交付代码（code/ 下任何模块），仿真与下界均在本文件内独立实现。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "结果", "结果")
TPL = os.path.join(ROOT, "模板备份")
SUB = os.path.join(ROOT, "提交")
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(HERE, "_work", "out")
os.makedirs(OUT, exist_ok=True)

SHIFTS = ["00:00-08:00", "05:00-13:00", "08:00-16:00",
          "12:00-20:00", "14:00-22:00", "16:00-24:00"]
COVER = {s: list(range(st, st + 8)) for s, st in zip(SHIFTS, [0, 5, 8, 12, 14, 16])}
RATE_F, RATE_T = 25, 20
EXPECT_ROWS = {1: 1710, 2: 41040, 3: 1710, 4: 41040, 5: 10260}
DATE_RE = re.compile(r"^2023/12/([1-9]|[12][0-9]|30)$")

CHECKS = []          # (id, 项目, 状态, 证据)
INFO = {}            # 供报告引用的关键数字
BUF = io.StringIO()


def w(*a):
    print(*a, file=BUF)


def chk(cid, name, ok, evidence, level="A"):
    status = "通过" if ok is True else ("不通过" if ok is False else str(ok))
    CHECKS.append({"id": cid, "level": level, "name": name, "status": status,
                   "evidence": evidence})
    w("[%s] %-28s %s | %s" % (cid, name, status, evidence))
    return ok


# ---------------------------------------------------------------- 读表
def decode(path):
    raw = open(path, "rb").read()
    for enc in ("gbk", "utf-8-sig"):
        try:
            return raw.decode(enc), enc, raw
        except UnicodeDecodeError:
            continue
    raise RuntimeError("无法解码 %s" % path)


def load_result(i):
    txt, enc, raw = decode(os.path.join(RES, "结果表%d.csv" % i))
    df = pd.read_csv(io.StringIO(txt), dtype=str, keep_default_na=False)
    df.attrs["enc"] = enc
    df.attrs["txt"] = txt
    df.attrs["md5"] = hashlib.md5(raw).hexdigest()
    df.attrs["bytes"] = len(raw)
    return df


def load_template(i):
    txt, enc, raw = decode(os.path.join(TPL, "结果表%d.csv" % i))
    return pd.read_csv(io.StringIO(txt), dtype=str, keep_default_na=False), enc


def num(s):
    return pd.to_numeric(s, errors="coerce")


def main():
    global RES
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="latest")
    ap.add_argument("--dir", default=RES, help="结果表目录（默认 结果/结果；可传 提交）")
    args = ap.parse_args()
    tag = args.tag
    RES = args.dir

    w("# 复核脚本运行：tag=%s" % tag)
    w("结果目录：%s" % RES)
    w("")

    frames = {i: load_result(i) for i in range(1, 7)}
    INFO["file"] = {i: {"md5": frames[i].attrs["md5"], "bytes": frames[i].attrs["bytes"],
                        "encoding": frames[i].attrs["enc"], "rows": len(frames[i]),
                        "cols": list(frames[i].columns)} for i in frames}
    for i in frames:
        w("表%d md5=%s rows=%d enc=%s cols=%r" % (
            i, frames[i].attrs["md5"], len(frames[i]), frames[i].attrs["enc"],
            list(frames[i].columns)))
    # 提交/ 与 结果/结果/ 双向一致性
    other = SUB if os.path.abspath(RES) == os.path.abspath(os.path.join(ROOT, "结果", "结果")) \
        else os.path.join(ROOT, "结果", "结果")
    sub_same = {}
    for i in frames:
        p = os.path.join(other, "结果表%d.csv" % i)
        sub_same[i] = os.path.exists(p) and hashlib.md5(open(p, "rb").read()).hexdigest() == frames[i].attrs["md5"]
    chk("A0", "两处副本逐字节一致（结果/结果 vs 提交）", all(sub_same.values()),
        "基准目录=%s；另一处=%s；md5 相同：%r" % (
            os.path.relpath(RES, ROOT), os.path.relpath(other, ROOT), sub_same))

    # ---------------- A1 列名/行数/空列/示例行
    ok_all, ev = True, []
    for i in range(1, 7):
        tpl, tenc = load_template(i)
        tpl_cols = [c for c in tpl.columns]
        # 模板列名去掉全空列（模板尾部多两个空列是模板自身的排版）
        tpl_used = [c for c in tpl_cols if not str(c).startswith("Unnamed")]
        got = list(frames[i].columns)
        same = got == tpl_used
        blank = [c for c in got if str(c).startswith("Unnamed")]
        resid = 0
        for c in frames[i].columns:
            resid += int(frames[i][c].astype(str).str.contains("示例|请删除|请提交").sum())
        nrow = len(frames[i])
        exp = EXPECT_ROWS.get(i)
        ev.append("表%d 列名=%s 与模板%s；空列%d；残留示例%d；行数%d%s" % (
            i, got, "一致" if same else "不一致(模板=%r)" % tpl_used, len(blank), resid, nrow,
            "(期望%d)" % exp if exp else "(按实际)"))
        ok_all &= same and not blank and resid == 0 and (exp is None or nrow == exp)
    chk("A1", "列名逐字一致/无空列/无示例行/行数", ok_all, "；".join(ev))

    # 编码
    enc_ok = all(frames[i].attrs["enc"] == "gbk" for i in frames)
    chk("A1b", "六表 GBK 可解码（无 BOM）", enc_ok,
        "解码编码=%r" % {i: frames[i].attrs["enc"] for i in frames})

    # ---------------- A2 日期
    ok_all, ev = True, []
    for i in range(1, 7):
        v = frames[i]["日期"].astype(str)
        bad = int((~v.str.match(DATE_RE)).sum())
        nd = v.nunique()
        pad = int(v.str.match(r"^2023/12/0\d$").sum())
        ev.append("表%d 非法%d 唯一日期%d 补零%d" % (i, bad, nd, pad))
        ok_all &= (bad == 0 and nd == 30 and pad == 0)
    chk("A2", "日期=2023/12/1 形式且∈12/1-12/30", ok_all, "；".join(ev))

    # ---------------- A3 小时
    ok_all, ev = True, []
    for i in (2, 4):
        df = frames[i]
        h = num(df["小时"])
        g = df.groupby(["分拣中心", "日期"]).size()
        good = (h.min() == 0 and h.max() == 23 and int(h.isna().sum()) == 0
                and int(((h % 1) != 0).sum()) == 0 and int((g != 24).sum()) == 0
                and df.duplicated(["分拣中心", "日期", "小时"]).sum() == 0)
        ev.append("表%d 小时∈[%s,%s] 非整数%d 24行缺组%d 重复%d" % (
            i, h.min(), h.max(), int(((h % 1) != 0).sum()), int((g != 24).sum()),
            int(df.duplicated(["分拣中心", "日期", "小时"]).sum())))
        ok_all &= bool(good)
    chk("A3", "表2/表4 小时0-23且每中心日24行", ok_all, "；".join(ev))

    # ---------------- A4 班次
    t5, t6 = frames[5], frames[6]
    u5 = sorted(t5["班次"].unique())
    g5 = t5.groupby(["分拣中心", "日期"]).size()
    ok5 = set(u5) == set(SHIFTS) and int((g5 != 6).sum()) == 0
    u6 = sorted(t6["班次"].unique())
    miss6 = sorted(set(SHIFTS) - set(u6))
    extra6 = sorted(set(u6) - set(SHIFTS))
    chk("A4", "表5 班次=题面6个且每中心日6行", ok5,
        "取值=%r 缺组=%d" % (u5, int((g5 != 6).sum())))
    # 表6 缺班次是否因该格人数为 0
    cnt5 = (num(t5["正式工人数"]) + num(t5["临时工人数"])).groupby(
        [t5["分拣中心"], t5["日期"], t5["班次"]]).sum()
    zero_gap = []
    for s in miss6:
        sub = cnt5.xs("SC60", level=0).xs(s, level=1)
        zero_gap.append("%s 表5同格人数合计=%d" % (s, int(sub.sum())))
    chk("A4b", "表6 缺班次（按实际）是否与表5 同格为0 一致", len(extra6) == 0 and all(
        "合计=0" in z for z in zero_gap),
        "表6 班次=%r；缺失=%r；%s" % (u6, miss6, "；".join(zero_gap) if miss6 else "无缺失"))

    # ---------------- A5 非负整数
    ok_all, ev = True, []
    for i in (1, 2, 3, 4):
        v = num(frames[i]["货量"])
        bad = int(v.isna().sum() + (v < 0).sum() + ((v % 1) != 0).sum())
        ev.append("表%d 货量 min=%s max=%s 异常%d sum=%d" % (i, v.min(), v.max(), bad, int(v.sum())))
        ok_all &= bad == 0
    for c in ("正式工人数", "临时工人数"):
        v = num(t5[c])
        bad = int(v.isna().sum() + (v < 0).sum() + ((v % 1) != 0).sum())
        ev.append("表5.%s min=%s max=%s 异常%d sum=%d" % (c, v.min(), v.max(), bad, int(v.sum())))
        ok_all &= bad == 0
    chk("A5", "货量/人数均为非负整数（无 NaN/小数）", ok_all, "；".join(ev))
    INFO["totals"] = {
        "t1": int(num(frames[1]["货量"]).sum()), "t2": int(num(frames[2]["货量"]).sum()),
        "t3": int(num(frames[3]["货量"]).sum()), "t4": int(num(frames[4]["货量"]).sum()),
        "formal": int(num(t5["正式工人数"]).sum()), "temp": int(num(t5["临时工人数"]).sum()),
        "t6_rows": len(t6)}

    # ---------------- A6 预测的日序列是否退化为"7 天精确周期"
    tt = frames[1].copy()
    tt["v"] = num(tt["货量"])
    tt["wd"] = pd.to_datetime(tt["日期"].str.replace("/", "-")).dt.weekday
    daily = tt.groupby("日期")["v"].sum()
    gwd = tt.groupby(["分拣中心", "wd"])["v"].agg(["nunique", "std"])
    nuniq = int(daily.nunique())
    flat = int((gwd["nunique"] == 1).sum())
    chk("A6", "日预测是否退化为 7 天精确周期（nunique>7）", nuniq > 7,
        "30 天日合计只有 %d 个不同取值；同一中心同一星期几 30 天内取值完全相同的组数=%d/%d（std=0）" % (
            nuniq, flat, len(gwd)))
    INFO["a6"] = {"nunique_daily": nuniq, "flat_centers_weekday": flat, "n_groups": len(gwd)}

    # ---------------- B6 日=Σ小时
    ok_all, ev = True, []
    for nm, d, hh in (("表1=Σ表2", frames[1], frames[2]), ("表3=Σ表4", frames[3], frames[4])):
        a = pd.DataFrame({"货量": num(d["货量"])}).set_index([d["分拣中心"], d["日期"]])
        s = num(hh["货量"]).groupby([hh["分拣中心"], hh["日期"]]).sum()
        j = a.join(s.rename("h"), how="outer")
        diff = (j["货量"].fillna(-1) - j["h"].fillna(-1))
        nz = int((diff != 0).sum())
        ev.append("%s 组数%d 缺失%d 非零差%d 最大|差|=%s" % (
            nm, len(j), int(j.isna().any(axis=1).sum()), nz, diff.abs().max()))
        ok_all &= nz == 0 and int(j.isna().any(axis=1).sum()) == 0
    chk("B6", "表1=表2 逐格24小时和、表3=表4（0误差）", ok_all, "；".join(ev))

    # ---------------- B7 表3 vs 表1
    a = num(frames[1]["货量"]).groupby([frames[1]["分拣中心"], frames[1]["日期"]]).sum()
    b = num(frames[3]["货量"]).groupby([frames[3]["分拣中心"], frames[3]["日期"]]).sum()
    j = pd.DataFrame({"t1": a, "t3": b})
    rel_grid = ((j["t3"] - j["t1"]).abs() / j["t1"]).max()
    rel_tot = abs(j["t3"].sum() / j["t1"].sum() - 1)
    cen = j.groupby(level=0).sum()
    rel_cen = ((cen["t3"] - cen["t1"]).abs() / cen["t1"]).max()
    chk("B7", "表3 与表1 总量差 ≤±5%（且逐格/逐中心）", bool(rel_tot <= 0.05 and rel_cen <= 0.05),
        "总量 %d vs %d，差 %d 件（%.6f%%）；单中心最大差异率 %.4f%%；单格最大 %.4f%%" % (
            j["t1"].sum(), j["t3"].sum(), j["t3"].sum() - j["t1"].sum(),
            rel_tot * 100, rel_cen * 100, rel_grid * 100))
    INFO["b7"] = {"diff": int(j["t3"].sum() - j["t1"].sum()), "rel_tot_pct": rel_tot * 100,
                  "rel_center_max_pct": rel_cen * 100, "rel_grid_max_pct": rel_grid * 100}

    # ---------------- B8 表5 正式工 ≤60
    g = num(t5["正式工人数"]).groupby([t5["分拣中心"], t5["日期"]]).sum()
    chk("B8", "表5 每(中心,日) 正式工合计 ≤60", bool(g.max() <= 60),
        "max=%d min=%d 超限组数=%d" % (g.max(), g.min(), int((g > 60).sum())))
    INFO["b8"] = {"max": int(g.max()), "min": int(g.min()), "over": int((g > 60).sum())}

    # ---------------- B9 表6 vs 表5（SC60）
    t6 = t6.copy()
    t6["kind"] = np.where(t6["出勤员工"].str.startswith("正式工"), "f", "t")
    c6 = t6.groupby(["日期", "班次", "kind"]).size().unstack(fill_value=0)
    tot6 = c6.sum(axis=1)
    s5 = t5[t5["分拣中心"] == "SC60"].copy()
    tot5 = num(s5["正式工人数"]) + num(s5["临时工人数"])
    key5 = pd.Series(tot5.values, index=pd.MultiIndex.from_arrays([s5["日期"], s5["班次"]]))
    jj = pd.DataFrame({"t5": key5, "t6": tot6}).fillna(0)
    d_tot = (jj["t5"] - jj["t6"]).abs().max()
    f5 = pd.Series(num(s5["正式工人数"]).values, index=key5.index)
    t5t = pd.Series(num(s5["临时工人数"]).values, index=key5.index)
    jj2 = pd.DataFrame({"f5": f5, "t5": t5t, "f6": c6.get("f", 0), "t6": c6.get("t", 0)}).fillna(0)
    chk("B9", "表6 SC60 每(日,班次) 总人数 = 表5 同格", bool(d_tot == 0 and len(jj) == 180),
        "对齐组数=%d 最大|差|=%s；拆分不同：表5 正式%d/临时%d vs 表6 正式%d/临时%d（Q3 60 人、Q4 200 人假设不同）" % (
            len(jj), d_tot, jj2["f5"].sum(), jj2["t5"].sum(), jj2["f6"].sum(), jj2["t6"].sum()))
    INFO["b9"] = {"groups": len(jj), "max_diff": float(d_tot),
                  "t5_formal": int(jj2["f5"].sum()), "t5_temp": int(jj2["t5"].sum()),
                  "t6_formal": int(jj2["f6"].sum()), "t6_temp": int(jj2["t6"].sum())}

    # ---------------- C10 全中心流体仿真
    t4 = frames[4]
    Dm = {}
    for c, d, h, v in zip(t4["分拣中心"], t4["日期"], t4["小时"], num(t4["货量"])):
        Dm[(c, d, int(h))] = int(v)
    cap5 = {}
    for c, d, s, nf, nt in zip(t5["分拣中心"], t5["日期"], t5["班次"],
                               num(t5["正式工人数"]).astype(int), num(t5["临时工人数"]).astype(int)):
        for h in COVER[s]:
            cap5[(c, d, h)] = cap5.get((c, d, h), 0) + RATE_F * nf + RATE_T * nt

    def simulate(keys, demand, cap):
        rows = []
        for c, d in keys:
            bl = 0
            peak = 0
            zero_cap_in = []
            for h in range(24):
                bl += demand.get((c, d, h), 0)
                cp = cap.get((c, d, h), 0)
                if cp == 0 and bl > 0:
                    zero_cap_in.append((h, bl))
                bl -= min(bl, cp)
                peak = max(peak, bl)
            rows.append((c, d, bl, peak, len(zero_cap_in)))
        return pd.DataFrame(rows, columns=["中心", "日期", "日末积压", "峰值积压", "零产能小时数"])

    keys = sorted({(c, d) for (c, d, h) in Dm})
    r5 = simulate(keys, Dm, cap5)
    bad5 = r5[r5["日末积压"] > 1]
    chk("C10", "全中心流体仿真：日末积压=0", len(bad5) == 0,
        "1710 组：日末积压 max=%d 非零组=%d；峰值积压 max=%d（中心/日=%s）" % (
            r5["日末积压"].max(), int((r5["日末积压"] > 0).sum()), r5["峰值积压"].max(),
            r5.loc[r5["峰值积压"].idxmax(), ["中心", "日期"]].tolist()))
    if len(bad5):
        w(bad5.sort_values("日末积压", ascending=False).head(20).to_string())
    INFO["c10"] = {"max_end": int(r5["日末积压"].max()), "n_bad": len(bad5),
                   "max_peak": int(r5["峰值积压"].max())}

    # ---------------- C11 零产能小时
    z = r5[r5["零产能小时数"] > 0]
    r5["零产能小时数"].sum()
    tot_zero = int(r5["零产能小时数"].sum())
    chk("C11", "有到货却无人在岗的小时（后续是否清货）", "部分通过",
        "%d/%d 个(中心,日) 存在零产能小时，合计 %d 个小时；但这些组日末积压全部=0（当晚班清货），"
        "最大滞留积压=%d 件；即『当天后来无人清货』不成立，但『大量货量整日等待』成立" % (
            len(z), len(r5), tot_zero, r5["峰值积压"].max()))
    INFO["c11"] = {"center_days": len(z), "hours": tot_zero,
                   "max_peak": int(r5["峰值积压"].max()),
                   "worst": r5.loc[r5["峰值积压"].idxmax(), ["中心", "日期"]].tolist()}

    # ---------------- C12 表6 仿真
    cap6 = {}
    for (d, s), row in c6.iterrows():
        nf, nt = int(row.get("f", 0)), int(row.get("t", 0))
        for h in COVER[s]:
            cap6[("SC60", d, h)] = cap6.get(("SC60", d, h), 0) + RATE_F * nf + RATE_T * nt
    keys6 = sorted({(c, d) for (c, d, h) in Dm if c == "SC60"},
                   key=lambda x: int(x[1].split("/")[-1]))
    r6 = simulate(keys6, Dm, cap6)
    chk("C12", "表6（SC60）流体仿真：日末积压=0", bool(r6["日末积压"].max() <= 1),
        "30 天 日末积压 max=%d 峰值积压 max=%d" % (r6["日末积压"].max(), r6["峰值积压"].max()))

    # ---------------- C13 人天下界（严格下界：只用总量/工时口径，另报组合口径）
    # 表5 口径：每(中心,日) 60 正式工上限；表6 口径：SC60 200 正式工、每人≤25天（月 5000 正式工天）
    W5 = {}
    for (c, d, h), v in Dm.items():
        W5[(c, d)] = W5.get((c, d), 0) + v
    lb5 = 0
    for (c, d), W in W5.items():
        n = int(np.ceil(W / 200.0))              # 全按 25 人效所需人天
        f = min(60, n)
        t = int(np.ceil((W - 200 * f) / 160.0)) if W > 200 * f else 0
        lb5 += f + t
    act5 = int(INFO["totals"]["formal"] + INFO["totals"]["temp"])
    # 表6：SC60
    W6 = [W5[("SC60", d)] for d in [x[1] for x in keys6]]
    n6 = [int(np.ceil(W / 200.0)) for W in W6]
    sum_n6 = sum(n6)
    lb6 = int(np.ceil(1.25 * sum_n6 - 0.25 * min(5000, 30 * 200)))
    act6 = int(len(t6))
    chk("C13", "人天数 vs 可证明下界（表5/表6）", "见证据",
        "表5：下界 %d（按每中心日≤60 正式工、临时工 160/天）实际 %d 人天，超 %+.2f%%；"
        "表6：下界 %d（200 正式工×25 天=5000 正式工天 + 临时工 160/天）实际 %d 人天，超 %+.2f%%" % (
            lb5, act5, 100 * (act5 / lb5 - 1), lb6, act6, 100 * (act6 / lb6 - 1)))
    INFO["c13"] = {"lb5": lb5, "act5": act5, "gap5_pct": 100 * (act5 / lb5 - 1),
                   "lb6": lb6, "act6": act6, "gap6_pct": 100 * (act6 / lb6 - 1),
                   "certified_lb5_exact_vol": int(np.ceil(20143155 / 200.0)),
                   "certified_lb6_exact_vol": int(np.ceil(1.25 * (1850043 / 200.0) - 1250))}
    # 与交付自带下界对照
    p3 = json.load(open(os.path.join(DATA, "p3_stats.json"), encoding="utf-8"))
    chk("C13b", "交付自带 gap 口径是否可采信", "部分通过",
        "p3_stats.json: lb_pure_formal=%d  gap_pure=%.2f%%（该下界=Σceil(日货量/200)，未扣 60 正式工上限，不可达）；"
        "按可达下界 %d 计，实际超 %+.2f%%" % (
            p3["lb_pure_formal"], p3["gap_pure_pct"], lb5, 100 * (act5 / lb5 - 1)))

    # ---------------- D 逐人
    t6["num"] = t6["出勤员工"].str.extract(r"(\d+)$").astype(int)
    t6["prefix"] = t6["出勤员工"].str.replace(r"\d+$", "", regex=True)
    f = t6[t6["prefix"] == "正式工"]
    p = t6[t6["prefix"] == "临时工"]
    days = f.groupby("num")["日期"].nunique()
    chk("D12", "每名正式工出勤 ≤25 天（85%×30）", bool(days.max() <= 25),
        "200 人 出勤天数 min=%d mean=%.3f max=%d std=%.4f" % (
            days.min(), days.mean(), days.max(), days.std(ddof=0)))
    chk("D15", "200 名正式工全部使用 & 出勤率均衡", bool(len(days) == 200),
        "使用人数=%d；出勤率 min=%.2f%% mean=%.2f%% max=%.2f%% std=%.4f（天数口径）" % (
            len(days), days.min() / 30 * 100, days.mean() / 30 * 100, days.max() / 30 * 100,
            days.std(ddof=0)))

    def to_int(s):
        return int(s.split("/")[0]) * 10000 + int(s.split("/")[1]) * 100 + int(s.split("/")[2])

    def max_run(ds):
        ds = sorted(ds)
        best = cur = 1
        for x, y in zip(ds, ds[1:]):
            cur = cur + 1 if y - x == 1 else 1
            best = max(best, cur)
        return best

    runs = f.assign(k=f["日期"].map(to_int)).groupby("num")["k"].apply(lambda s: max_run(list(s)))
    chk("D13", "每名正式工连续出勤 ≤7 天", bool(runs.max() <= 7),
        "最大值=%d；分布=%r" % (runs.max(), dict(runs.value_counts().sort_index())))
    dup = int(t6.duplicated(["出勤员工", "日期"]).sum())
    chk("D14", "每人每天 ≤1 个班次", dup == 0, "同一员工同一天多班行数=%d" % dup)
    pn = sorted(p["num"].unique())
    cont = pn == list(range(1, len(pn) + 1))
    chk("D16", "临时工编号连续且每人每天≤1班", bool(cont),
        "临时工唯一编号=%d 区间=[%d,%d] 连续=%s；人数最多的一天=%d" % (
            len(pn), pn[0], pn[-1], cont, p.groupby("日期").size().max()))
    pdays = p.groupby("num")["日期"].nunique()
    INFO["d"] = {"formal_days": {"min": int(days.min()), "max": int(days.max()),
                                 "mean": float(days.mean()), "std": float(days.std(ddof=0))},
                 "runs_max": int(runs.max()), "temp_ids": len(pn),
                 "temp_days_max": int(pdays.max())}

    # ---------------- P1/P2/P3 针对性三点
    # P2 覆盖空档
    used = [s for s in SHIFTS if any(COVER[s]) and s in u6]
    covered = set()
    for s in used:
        covered |= set(COVER[s])
    holes = sorted(set(range(24)) - covered)
    chk("P2", "表6 只用4个班次时的24小时覆盖", len(holes) == 0,
        "表6 使用的班次=%r；未被任何班次覆盖的小时=%r；表5 同两班人数合计=%s" % (
            used, holes, [int(cnt5.xs("SC60", level=0).xs(s, level=1).sum()) for s in miss6]))

    # P3 极小中心日
    staff_day = pd.DataFrame({
        "people": (num(t5["正式工人数"]) + num(t5["临时工人数"])).values},
        index=pd.MultiIndex.from_arrays([t5["分拣中心"], t5["日期"]]))["people"].groupby(level=[0, 1]).sum()
    small = staff_day[staff_day <= 1].index.tolist()
    worst = None
    for (c, d) in small:
        W = W5[(c, d)]
        bl = 0
        okh = True
        for h in range(24):
            bl += Dm.get((c, d, h), 0)
            cp = cap5.get((c, d, h), 0)
            bl -= min(bl, cp)
        if W > 0:
            worst = (c, d, W, bl)
            break
    if small:
        c0, d0 = small[0]
        W0 = W5[(c0, d0)]
        all_ok = True
        max_end = 0
        worst_hour = 0
        over200 = 0
        for (c, d) in small:
            W = W5[(c, d)]
            if W > 200:
                over200 += 1
            bl = 0
            for h in range(24):
                bl += Dm.get((c, d, h), 0)
                cp = cap5.get((c, d, h), 0)
                bl -= min(bl, cp)
            max_end = max(max_end, bl)
            all_ok &= (bl <= 1)
            worst_hour = max(worst_hour, max(Dm.get((c, d, h), 0) for h in range(24)))
        ev = ("全天只有1人的(中心,日) 共%d 组（如 %s %s：当日货量=%d，1人×8h×25=200 件，%s）；"
              "30 组逐小时仿真 日末积压 max=%d；这些日子单小时最大到货=%d 件；日货量>200 的组数=%d" % (
                  len(small), c0, d0, W0, "够用" if W0 <= 200 else "不够",
                  max_end, worst_hour, over200))
        chk("P3", "极小中心日（1人）容量与Hall可行性", "通过" if (all_ok and over200 == 0) else "不通过", ev)
        INFO["p3_small"] = {"n": len(small), "example": [c0, d0, W0], "max_end": int(max_end),
                            "over200": over200}

    # ---------------- 汇总
    w("\n# 汇总")
    for c in CHECKS:
        w("%-5s %-10s %-40s %s" % (c["id"], c["level"], c["name"], c["status"]))
    npass = sum(1 for c in CHECKS if c["status"] == "通过")
    w("\n通过 %d / %d 项" % (npass, len(CHECKS)))

    payload = {"tag": tag, "checks": CHECKS, "info": INFO,
               "generated_at": pd.Timestamp.now().isoformat(timespec="seconds")}
    with open(os.path.join(OUT, "audit_results_%s.json" % tag), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "audit_results_%s.txt" % tag), "w", encoding="utf-8") as fh:
        fh.write(BUF.getvalue())
    print("OK ->", os.path.join(OUT, "audit_results_%s.json" % tag))
    print("通过 %d / %d" % (npass, len(CHECKS)))
    for c in CHECKS:
        if c["status"] != "通过":
            print("  [%s] %s -> %s" % (c["id"], c["name"], c["status"]))


if __name__ == "__main__":
    main()


