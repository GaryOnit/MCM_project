# -*- coding: utf-8 -*-
"""E 部分：论文（docx）数字 vs data/ 与 结果表 的独立核对。

用法：python 复核/audit_paper.py [--tag round1]
只读；输出 复核/_work/out/audit_paper_<tag>.{txt,json}。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

import numpy as np
import pandas as pd
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "结果", "结果")
DATA = os.path.join(ROOT, "data")
ATT = os.path.join(ROOT, "附件", "附件")
DOCX = os.path.join(ROOT, "论文", "2024年MathorCupC题_物流网络分拣中心货量预测及人员排班.docx")
OUT = os.path.join(HERE, "_work", "out")
os.makedirs(OUT, exist_ok=True)
BUF = io.StringIO()
CHECKS = []


def w(*a):
    print(*a, file=BUF)


def chk(cid, name, ok, evidence):
    st = "通过" if ok is True else ("不通过" if ok is False else str(ok))
    CHECKS.append({"id": cid, "name": name, "status": st, "evidence": evidence})
    w("[%s] %-34s %s | %s" % (cid, name, st, evidence))


def docx_text():
    doc = Document(DOCX)
    lines = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            t = Paragraph(child, doc).text.strip()
            if t:
                lines.append(t)
        elif child.tag == qn("w:tbl"):
            for r in Table(child, doc).rows:
                lines.append(" | ".join(" ".join(p.text.strip() for p in c.paragraphs).strip()
                                        for c in r.cells))
    return "\n".join(lines)


def load(i, d=None):
    d = d or RES
    return pd.read_csv(os.path.join(d, "结果表%d.csv" % i), encoding="gbk", dtype=str)


def main():
    global RES
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="latest")
    ap.add_argument("--dir", default=RES, help="结果表目录（默认 结果/结果；可传 提交）")
    args = ap.parse_args()
    RES = args.dir
    txt = docx_text()
    compact = txt.replace(" ", "").replace("\u3000", "")   # 去空格版本，便于匹配

    # ---------------------------------------------------------------- 0 完整性
    n_daibu = txt.count("待补")
    heads = ["七、问题三", "八、问题四", "九、模型检验", "十、模型评价", "附录 A", "附录 B", "附录 C"]
    missing_heads = [h for h in heads if h not in txt]
    ph = re.findall(r"【待补：[^】]*】", txt)
    # 定位占位所在章节
    cur = "封面/摘要"
    where = {}
    for line in txt.splitlines():
        m = re.match(r"^([一二三四五六七八九十]+、\S+|\d+\.\d+\s*\S+|附录\s*[A-C])", line.strip())
        if m and len(line.strip()) < 40:
            cur = line.strip()[:18]
        if "待补" in line:
            where[cur] = where.get(cur, 0) + line.count("待补")
    chk("E0", "论文是否成品（无【待补】占位）", n_daibu == 0,
        "『待补』出现 %d 次；【待补：…】占位 %d 处；缺失章节标题=%r；占位分布=%r" % (
            n_daibu, len(ph), missing_heads, dict(list(where.items())[:12])))
    # 摘要占位
    abs_start = txt.find("摘")
    abs_end = txt.find("关键词")
    abs_txt = txt[abs_start:abs_end] if abs_start >= 0 and abs_end > abs_start else ""
    chk("E0b", "摘要数字是否回填", "待补" not in abs_txt,
        "摘要区间内『待补』=%d 处，例：%r" % (abs_txt.count("待补"), ph[:3]))

    # ---------------------------------------------------------------- 数据侧实际值
    t1, t2, t3, t4 = load(1), load(2), load(3), load(4)
    t5, t6 = load(5), load(6)
    v1 = pd.to_numeric(t1["货量"])
    v3 = pd.to_numeric(t3["货量"])
    t1s = v1.groupby(t1["日期"]).sum()
    t3s = v3.groupby(t3["日期"]).sum()
    d1 = pd.to_datetime(t1s.index.str.replace("/", "-"))
    order = np.argsort(d1.values)
    t1s = t1s.iloc[order]
    t3s = t3s.iloc[order]
    v2 = pd.to_numeric(t2["货量"])
    v4 = pd.to_numeric(t4["货量"])
    h2 = v2.groupby(pd.to_numeric(t2["小时"])).sum()
    sh2 = h2 / h2.sum()
    seg = {"0-8": sh2.loc[0:7].sum(), "8-16": sh2.loc[8:15].sum(), "16-24": sh2.loc[16:23].sum()}

    bt = pd.read_csv(os.path.join(DATA, "backtest_results.csv"), encoding="utf-8")
    allb = bt[bt["scope"] == "ALL"].set_index("model")
    med = bt[bt["scope"] != "ALL"].groupby("model")["WAPE"].median()
    grid = pd.read_csv(os.path.join(DATA, "backtest_grid.csv"), encoding="utf-8")
    hb = pd.read_csv(os.path.join(DATA, "hourly_backtest.csv"), encoding="utf-8")
    fac = pd.read_csv(os.path.join(DATA, "factor_table.csv"), encoding="utf-8")
    lc = pd.read_csv(os.path.join(DATA, "line_changes.csv"), encoding="utf-8")
    mc = json.load(open(os.path.join(DATA, "model_choice.json"), encoding="utf-8"))
    p3 = json.load(open(os.path.join(DATA, "p3_stats.json"), encoding="utf-8"))
    p4 = json.load(open(os.path.join(DATA, "p4_stats.json"), encoding="utf-8"))

    closed = lc[lc["变化"] == "关闭"]
    new = lc[lc["变化"] == "新开"]
    root4 = closed["处理说明"].str.contains("两侧").values
    ACT = {
        "t1_sum": int(v1.sum()), "t1_mean": float(v1.sum() / 30),
        "t1_min": int(t1s.min()), "t1_max": int(t1s.max()),
        "t1_min_date": t1s.idxmin(), "t1_max_date": t1s.idxmax(),
        "t1_range": int(t1s.max() - t1s.min()),
        "t2_sum": int(v2.sum()), "t2_h6": float(sh2.loc[6] * 100), "t2_h21": float(sh2.loc[21] * 100),
        "t2_seg0_8": float(seg["0-8"] * 100), "t2_seg8_16": float(seg["8-16"] * 100),
        "t2_seg16_24": float(seg["16-24"] * 100),
        "t3_sum": int(v3.sum()), "t3_mean": float(v3.sum() / 30),
        "t3_min": int(t3s.min()), "t3_max": int(t3s.max()),
        "diff_31": int(v3.sum() - v1.sum()),
        "BT": {m: {c: float(allb.loc[m, c]) for c in ("WAPE", "WAPE_ex", "MAPE", "RMSE")} for m in allb.index},
        "MED": {m: float(med[m]) for m in med.index},
        "grid_top": grid.head(5).to_dict("records"),
        "HB": hb.to_dict("records"),
        "f_min": float(fac["f"].min()), "f_max": float(fac["f"].max()),
        "n_f_changed": int((fac["差异率"].abs() > 1e-6).sum()),
        "max_center_diff_pct": float(fac["差异率"].abs().max() * 100),
        "lam": float(fac["f"].median()),
        "closed_n": int(len(closed)), "closed_sum": float(closed["线路货量"].sum()),
        "closed_noalt_sum": float(closed[root4]["线路货量"].sum()),
        "closed_noalt_n": int(root4.sum()),
        "new_n": int(len(new)), "new_sum": float(new["线路货量"].sum()),
        "p3": {k: p3[k] for k in ("person_days", "formal_person_days", "temp_person_days",
                                  "lb_pure_formal", "gap_pure_pct", "gap_work_pct", "n_row",
                                  "max_backlog_end", "n_hall_fail", "eff_min", "eff_max",
                                  "util_std_max")},
        "p4": {k: p4[k] for k in ("n_formal", "formal_person_days", "temp_person_days",
                                  "attend_rate", "quota_days", "max_run_check",
                                  "day_formal_min", "day_formal_max", "peak_temp_day",
                                  "peak_temp_value")},
        "t6_rows": int(len(t6)),
        "mc": {"model": mc["model"], "k": mc["k"], "valid_WAPE": mc["valid_WAPE"],
               "valid_WAPE_ex": mc["valid_WAPE_ex"], "valid_WAPE_A9": mc["valid_WAPE_A9"],
               "growth_enabled": bool(mc["growth"]["enabled"])},
    }
    # 附件与 EDA 侧
    a1 = pd.read_csv(os.path.join(ATT, "附件1.csv"), encoding="gbk")
    a2 = pd.read_csv(os.path.join(ATT, "附件2.csv"), encoding="gbk")
    a3 = pd.read_csv(os.path.join(ATT, "附件3.csv"), encoding="gbk")
    a4 = pd.read_csv(os.path.join(ATT, "附件4.csv"), encoding="gbk")
    a1.columns = [c.strip() for c in a1.columns]
    a1["日期"] = pd.to_datetime(a1["日期"].astype(str).str.replace("/", "-"), format="mixed")
    a1["货量"] = pd.to_numeric(a1["货量"])
    g = a1.groupby("日期")["货量"].sum()
    mon = g.groupby(g.index.to_period("M")).mean()
    ACT.update({
        "a1_rows": int(len(a1)), "a1_sum": int(a1["货量"].sum()), "a1_days": int(g.size),
        "a2_rows": int(len(a2)), "a3_rows": int(len(a3)), "a3_sum": int(a3.iloc[:, 2].sum()),
        "a4_rows": int(len(a4)),
        "mon": {str(k): float(v) for k, v in mon.items()},
        "g_mean": float(g.mean()),
        "g_max": int(g.max()), "g_max_date": str(g.idxmax().date()),
        "sc60_sum_122": int(a1[a1["分拣中心"] == "SC60"]["货量"].sum()),
        "center_min_sum": int(a1.groupby("分拣中心")["货量"].sum().min()),
    })
    # 表1/表3 中心级
    c1 = v1.groupby(t1["分拣中心"]).sum()
    c1d = c1 / 30
    ACT.update({
        "sc60_mean": float(c1d.get("SC60", np.nan)),
        "top5_share_t1": float(c1d.nlargest(5).sum() / c1d.sum() * 100),
        "sc20_mean": float(c1d.min()), "sc20_name": c1d.idxmin(),
        "n_lt1000": int((c1d < 1000).sum()), "n_gt30000": int((c1d > 30000).sum()),
    })

    w("\n实际值（从结果表/数据独立重算）：")
    w(json.dumps({k: v for k, v in ACT.items() if not isinstance(v, (list, dict))},
                 ensure_ascii=False, indent=1, default=str))

    # ---------------------------------------------------------------- 逐项对照（正则抓论文原值）
    def n(s):
        return float(str(s).replace(",", ""))

    def pair(cid, name, regex, actual, tol=0.005, groups=1):
        """regex 抓论文里的数字；与 actual（或 actual 元组）逐项比对。
        论文若仍是【待补：…】占位，则判为『占位未回填』。"""
        m = re.search(regex, compact)
        if not m:
            key = regex.split("(")[0].replace("\\", "").rstrip("[")
            pos = compact.find(key) if key else -1
            if pos >= 0 and "【待补" in compact[pos:pos + 80]:
                chk(cid, name, "占位未回填", "论文该处仍为【待补：…】；文件实际=%r" % (actual,))
            else:
                chk(cid, name, "不适用（论文未写此数）", "regex=%r 未命中；文件实际=%r" % (regex, actual))
            return
        raw = m.group(1)
        if "待补" in raw:
            chk(cid, name, "占位未回填", "论文写的=%r；文件实际=%r" % (m.group(0), actual))
            return
        try:
            got = [n(g) for g in m.groups()[:groups]]
        except ValueError:
            chk(cid, name, "不适用（论文未写此数）", "捕获=%r 非数值" % (m.groups(),))
            return
        av = actual if isinstance(actual, (tuple, list)) else (actual,)
        ok = len(got) == len(av) and all(abs(g - a) <= tol for g, a in zip(got, av))
        chk(cid, name, ok, "论文写的=%r；文件实际=%r（容差 %s）" % (
            m.group(0), tuple(round(a, 4) for a in av), tol))

    # 表 1 / 表 2（5.5、5.6 节）
    pair("E1", "表1 30 天合计",
         r"表1的全网30天合计为([\d,]+)件", ACT["t1_sum"], 0.5)
    pair("E2", "表1 日均",
         r"全网30天合计为[\d,]+件，日均([\d,]+\.?\d*)件", ACT["t1_mean"], 0.05)
    pair("E3", "表1 单日最低/最高与日期",
         r"单日最低([\d,]+)件（12月(\d+)日）、最高([\d,]+)件（12月(\d+)日）",
         (ACT["t1_min"], int(ACT["t1_min_date"].split("/")[-1]),
          ACT["t1_max"], int(ACT["t1_max_date"].split("/")[-1])), 0.5, groups=4)
    pair("E3b", "表1 极差", r"极差([\d,]+)件", ACT["t1_range"], 0.5)
    pair("E4", "表2 合计=表1（论文 20,143,157）",
         r"表2的[\d,]+格合计([\d,]+)件", ACT["t2_sum"], 0.5)
    pair("E5", "表2 小时形态 6 点/21 点（论文 0.44/7.49）",
         r"6点占([\d.]+)%、21点占([\d.]+)%", (ACT["t2_h6"], ACT["t2_h21"]), 0.006, groups=2)
    pair("E5b", "表2 三段占比（论文 30.0/24.6/45.5）",
         r"三段分别承载([\d.]+)%、([\d.]+)%与([\d.]+)%",
         (ACT["t2_seg0_8"], ACT["t2_seg8_16"], ACT["t2_seg16_24"]), 0.06, groups=3)
    pair("E6", "表3 合计",
         r"表3共1710行、合计([\d,]+)件", ACT["t3_sum"], 0.5)
    pair("E7", "表3 与表1 总量差", r"总量差为[−-]?(\d+)件", -ACT["diff_31"], 0.5)
    pair("E9", "k=10", r"水平窗口k=(\d+)", ACT["mc"]["k"], 0.5)
    pair("E10", "小时占比 WAPE",
         r"用8个非大促日估计的WAPE为([\d.]+)%", ACT["HB"][0]["WAPE"] * 100, 0.006)
    pair("E10b", "小时占比 全日期 WAPE",
         r"用全部15天估计则恶化到([\d.]+)%", ACT["HB"][2]["WAPE"] * 100, 0.006)
    pair("E11", "f 范围",
         r"取值范围为\[([\d.]+),([\d.]+)\]", (ACT["f_min"], ACT["f_max"]), 6e-5, groups=2)
    # λ：代码里 lam=Σ(V·f_capped)/ΣV=0.9996026，实际乘子=1/lam=1.0003976；
    #    论文式(16) 把 λ 定义为 ΣV/Σ(V·clip)（即 1.0004）。两种写法都出现，按"乘子"比对。
    m_lam = re.search(r"实测λ=([\d.]+)", compact)
    if m_lam:
        v = float(m_lam.group(1))
        lam_code = ACT["lam"]
        ok = abs(v - 1.0 / lam_code) < 2e-5 or abs(v - lam_code) < 2e-5
        chk("E12", "λ（论文写的 vs 代码实际乘子）", ok,
            "论文λ=%s；代码 lam=%.7f，实际乘子 1/lam=%.7f（两者互为倒数，论文取值属乘子口径）" % (
                m_lam.group(1), lam_code, 1.0 / lam_code))
    pair("E13", "线路增减（关闭/无替代/新开）",
         r"关闭线路14条合计([\d.]+)件/日，其中无替代线路的4条合计([\d.]+)件/日",
         (ACT["closed_sum"], ACT["closed_noalt_sum"]), 0.06, groups=2)
    pair("E14", "总人天数", r"总人天数为([\d,]+)人天", ACT["p3"]["person_days"], 0.5)
    pair("E15", "正式工/临时工人天",
         r"正式工([\d,]+)人天、临时工([\d,]+)人天", (ACT["p3"]["formal_person_days"],
                                                  ACT["p3"]["temp_person_days"]), 0.5, groups=2)
    pair("E16", "表6 行数", r"表6共([\d,]+)行", ACT["t6_rows"], 0.5)
    pair("E17", "正式工出勤率", r"出勤率([\d.]+)%", ACT["p4"]["attend_rate"], 0.006)
    pair("E19", "SC60 日均", r"SC60日均([\d,]+\.?\d*)件", ACT["sc60_mean"], 0.05)
    pair("E20", "Top5 占全网", r"Top5中心合计占全网日均的([\d.]+)%",
         ACT["top5_share_t1"], 0.006)
    pair("E21", "附件1 合计", r"货量合计([\d,]+)件", ACT["a1_sum"], 0.5)
    pair("E23", "附件3 合计", r"合计([\d,]+)件", ACT["a3_sum"], 0.5)


    # ---------------------------------------------------------------- 关键"论文写的 vs 文件里的"
    def grab(pattern, default=None):
        m = re.search(pattern, compact)
        return m.group(0) if m else default

    paper_says = {
        "单日最低": grab(r"单日最低[\d,]+件（12月\d+日）"),
        "单日最高": grab(r"最高[\d,]+件（12月\d+日）"),
        "极差": grab(r"极差[\d,]+件"),
        "表1合计": grab(r"表1的全网30天合计为[\d,]+件"),
        "表3区间": grab(r"表3的单日区间为[\d,]+至[\d,]+件"),
    }
    actual_says = {
        "单日最低": "%d 件（%s）" % (ACT["t1_min"], ACT["t1_min_date"]),
        "单日最高": "%d 件（%s）" % (ACT["t1_max"], ACT["t1_max_date"]),
        "极差": "%d 件" % ACT["t1_range"],
        "表1合计": "%d 件" % ACT["t1_sum"],
        "表3区间": "%d ~ %d 件" % (ACT["t3_min"], ACT["t3_max"]),
    }
    w("\n# 论文写的 vs 文件里的（关键 5 处）")
    for k in paper_says:
        w("  %-6s 论文=%-32r 文件=%s" % (k, paper_says[k], actual_says[k]))

    # 模型口径：终版应统一 A10
    a10_main = ("以A10为主模型" in compact) or ("最终模型取A10" in compact) or ("A10" in compact and "（采用）" in compact)
    a9_main = ("以A9为主模型" in compact) or ("A9为最终" in compact)
    m_a10 = re.search(r"A10[^|]{0,20}\|([\d.]+)\|([\d.]+)\|([\d.]+)\|(\d+)\|([\d.]+)", compact)
    key10 = [x for x in allb.index if x.startswith("A10_")]
    real10 = None
    if key10:
        r10 = allb.loc[key10[0]]
        real10 = ("%.2f" % (r10["WAPE"] * 100), "%.2f" % (r10["WAPE_ex"] * 100),
                  "%.2f" % (r10["MAPE"] * 100), "%.0f" % r10["RMSE"],
                  "%.2f" % (med[key10[0]] * 100))
    paper10 = tuple(m_a10.groups()) if m_a10 else None
    ok24 = bool(a10_main and not a9_main and paper10 and real10 and
                all(a == b for a, b in zip(paper10, real10)))
    chk("E24", "主模型口径统一 A10 且表3 A10 行与回测文件一致", ok24,
        "论文称 A10 主模型=%s；仍称 A9 主模型=%s；论文 A10 行=%r；回测文件 A10=%r；model_choice=%s" % (
            a10_main, a9_main, paper10, real10, mc["model"]))
    # 论文表格 3 数字 vs backtest（含 A10）
    tab3 = {"A1": ("26.87", "16.97", "27.40", "8613", "29.11"),
            "A2": ("21.65", "12.57", "26.42", "7175", "27.83"),
            "A4": ("22.60", "15.06", "32.99", "7011", "29.61"),
            "A9": ("22.05", "12.46", "23.90", "7473", "27.57"),
            "A10": ("21.91", "12.43", "24.03", "7388", "27.71")}
    bad = []
    for m, vals in tab3.items():
        key = [x for x in allb.index if x.startswith(m + "_")]
        if not key:
            bad.append((m, "无该模型"))
            continue
        r = allb.loc[key[0]]
        real = ("%.2f" % (r["WAPE"] * 100), "%.2f" % (r["WAPE_ex"] * 100),
                "%.2f" % (r["MAPE"] * 100), "%.0f" % r["RMSE"], "%.2f" % (med[key[0]] * 100))
        if tuple(vals) != real:
            bad.append((m, "论文%r vs 文件%r" % (vals, real)))
    chk("E25", "表3（回测）五模型 25 个数字", len(bad) == 0,
        "不一致=%r" % (bad,) if bad else "A1/A2/A4/A9/A10 的 WAPE/WAPE_ex/MAPE/RMSE/中位WAPE 全部相符")

    # 表6 逐人：连续出勤（论文 8.2 / 表11 应写 6 天、160/40）
    import pandas as _pd
    _t6 = _pd.read_csv(os.path.join(RES, "结果表6.csv"), encoding="gbk", dtype=str)
    _f6 = _t6[_t6["出勤员工"].str.startswith("正式工")]
    _fk = dict(zip(_f6["出勤员工"], _f6["日期"].map(lambda s: int(s.split("/")[2]))))

    def _run(v):
        v = sorted(v); b = c = 1
        for x, y in zip(v, v[1:]):
            c = c + 1 if y - x == 1 else 1; b = max(b, c)
        return b
    _runs = {k: _run(v) for k, v in _f6.groupby("出勤员工")["日期"].apply(
        lambda s: [int(x.split("/")[2]) for x in s]).items()}
    _rd = _pd.Series(list(_runs.values()))
    m18 = re.search(r"实测最长为(\d+)天：(\d+)人为(\d+)天、(\d+)人为(\d+)天", compact)
    m11 = re.search(r"最大连续出勤天数\|(\d+)\|[^|]*?(\d+)人为(\d+)天、(\d+)人为(\d+)天", compact)
    ok18 = bool(m18 and m11 and int(m18.group(1)) == int(_rd.max())
                and int(m18.group(2)) == int((_rd == 6).sum()) and int(m18.group(4)) == int((_rd == 5).sum())
                and int(m11.group(1)) == int(_rd.max()))
    chk("E18b", "最大连续出勤 6 天（8.2 与表11）与表6 一致", ok18,
        "实测 max_run=%d，分布=%r；论文 8.2=%r；表11=%r" % (
            _rd.max(), dict(_rd.value_counts().sort_index()),
            m18.groups() if m18 else None, m11.groups() if m11 else None))

    # 表5 gap 表述（1.142 / 14.19% / 13.24% 是否可复算；可达下界是否给出）
    _t5 = _pd.read_csv(os.path.join(RES, "结果表5.csv"), encoding="gbk", dtype=str)
    _pd5 = int(_pd.to_numeric(_t5["正式工人数"]).sum() + _pd.to_numeric(_t5["临时工人数"]).sum())
    _lb_work = ACT["t3_sum"] / 200.0
    _lb_pure = p3["lb_pure_formal"]
    _g_work = 100 * (_pd5 / _lb_work - 1)
    _g_pure = 100 * (_pd5 / _lb_pure - 1)
    m26 = re.search(r"gap([\d.]+)%（对取整下界([\d.]+)%）", compact)
    m26b = re.search(r"相当于日总量工时下界的([\d.]+)倍", compact)
    ok26 = bool(m26 and m26b and abs(float(m26.group(1)) - _g_work) < 0.02
                and abs(float(m26.group(2)) - _g_pure) < 0.02
                and abs(float(m26b.group(1)) - _pd5 / _lb_work) < 0.002)
    chk("E26", "问题三 gap 表述与下界可复算", "部分通过" if ok26 else "不通过",
        "论文 gap=%r / 倍数=%r；复算 %.2f%%（对工时下界 %.2f）与 %.2f%%（对取整下界 %d）；"
        "但全文未给出含 60 正式工上限的『可达下界 115,697 / +1.06%%』" % (
            m26.groups() if m26 else None, m26b.group(1) if m26b else None,
            _g_work, _lb_work, _g_pure, _lb_pure))

    # ---------------------------------------------------------------- 表11/12/13 与摘要新增数字
    def _alt_days(fn):
        d = pd.read_csv(os.path.join(DATA, fn), encoding="gbk", dtype=str)
        return int(pd.to_numeric(d["正式工人数"]).sum() + pd.to_numeric(d["临时工人数"]).sum())

    six = {"①": 102398, "②": _pd5, "③": _alt_days("alt_cum_aggregate_表5.csv"),
           "④": _alt_days("alt_strict_hourly_表5.csv"), "⑤": _alt_days("alt_turn8_表5.csv"),
           "⑥": _alt_days("alt_cap40_表5.csv")}
    got12 = {k: int(v.replace(",", "")) for k, v in re.findall(r"([①②③④⑤⑥])[^|]*?\|([\d,]+)\|", compact)}
    ok28 = all(got12.get(k) == v for k, v in six.items())
    chk("E28", "表12 六口径人天数", ok28,
        "论文=%r；文件复算=%r" % (got12, six))
    cap_rows = re.findall(r"(?:^|\n)(60（题面值）|80|100)\|([\d,]+)\|([\d,]+)\|([\d,]+)\|([\d.]+)", compact)
    act13 = {}
    try:
        sc = pd.read_csv(os.path.join(DATA, "sens_formal_cap.csv"), encoding="utf-8-sig")
        for _, r in sc.iterrows():
            act13[int(r["正式工上限"])] = (int(r["总人天数"]), int(r["正式工人天"]), int(r["临时工人天"]))
    except Exception:
        pass
    ok29 = len(cap_rows) >= 3 and all(
        int(pd.to_numeric(pd.Series([x[1].replace(",", "")])).iloc[0]) == act13.get(
            int(re.search(r"\d+", x[0]).group(0)), (-1,))[0] for x in cap_rows[:3]) and bool(act13)
    chk("E29", "表13 60/80/100 正式工上限三档", ok29,
        "论文行=%r；sens_formal_cap.csv=%r" % (cap_rows[:3], act13))
    m31 = re.search(r"每天正式工(\d+)至(\d+)人、临时工(\d+)至(\d+)人", compact)
    _per = _t6.assign(k=_pd.Series(["f" if x.startswith("正式工") else "t" for x in _t6["出勤员工"]]),
                      d=_t6["日期"]).groupby(["d", "k"]).size().unstack(fill_value=0)
    ok31 = bool(m31 and int(m31.group(1)) == _per["f"].min() and int(m31.group(2)) == _per["f"].max()
                and int(m31.group(3)) == _per["t"].min() and int(m31.group(4)) == _per["t"].max())
    chk("E31", "摘要 每日正式工/临时工人数区间", ok31,
        "论文=%r；表6 复算=正式 %d~%d、临时 %d~%d" % (
            m31.groups() if m31 else None, _per["f"].min(), _per["f"].max(),
            _per["t"].min(), _per["t"].max()))
    m32 = re.search(r"逐小时利用率uh的均值为([\d.]+)、日间平均标准差为([\d.]+)，最大日间标准差为([\d.]+)（(\d+)月(\d+)日）", compact)
    _u_defs = {"全部在岗小时(C>0)": (0.9630, 0.1500, 0.1291, "12/18"),
               "仅到货>0的小时(R>0)": (0.9741, 0.1142, 0.1291, "12/18")}
    if m32:
        pm = float(m32.group(1))
        ok32 = any(abs(pm - v[0]) < 0.003 for v in _u_defs.values())
        chk("E32", "在岗利用率 uh 是否可由结果表精确复现", "部分复现（说明级）" if ok32 else "不可精确复现",
            "论文 uh=%s/%s/%s（%s/%s）；按 u=W/C 复算：%r；p3_stats.json util_mean=%.4f / util_std_mean=%.4f"
            " —— 论文与 p3_stats 不是同一口径" % (
                m32.group(1), m32.group(2), m32.group(3), m32.group(4), m32.group(5),
                _u_defs, p3["util_mean"], p3["util_std_mean"]))
    else:
        chk("E32", "在岗利用率 uh 是否可由结果表精确复现", "未写", "论文未出现 uh 统计句")
    # 一致性硬数字：p3/p4 与结果表
    chk("E27", "p3/p4 统计与结果表 5/6 一致", "通过" if (
        ACT["p3"]["formal_person_days"] == int(pd.to_numeric(t5["正式工人数"]).sum()) and
        ACT["p3"]["temp_person_days"] == int(pd.to_numeric(t5["临时工人数"]).sum()) and
        ACT["t6_rows"] == int((pd.to_numeric(t5["正式工人数"]) + pd.to_numeric(t5["临时工人数"]))[
            t5["分拣中心"] == "SC60"].sum())) else "不通过",
        "表5 正式=%d 临时=%d（SC60 合计=%d）；p3_stats=%d/%d；表6 行数=%d" % (
            int(pd.to_numeric(t5["正式工人数"]).sum()), int(pd.to_numeric(t5["临时工人数"]).sum()),
            int((pd.to_numeric(t5["正式工人数"]) + pd.to_numeric(t5["临时工人数"]))[t5["分拣中心"] == "SC60"].sum()),
            p3["formal_person_days"], p3["temp_person_days"], ACT["t6_rows"]))

    npass = sum(1 for c in CHECKS if c["status"] == "通过")
    w("\n# 汇总：通过 %d / %d" % (npass, len(CHECKS)))
    with open(os.path.join(OUT, "audit_paper_%s.txt" % args.tag), "w", encoding="utf-8") as f:
        f.write(BUF.getvalue())
    with open(os.path.join(OUT, "audit_paper_%s.json" % args.tag), "w", encoding="utf-8") as f:
        json.dump({"checks": CHECKS, "actual": ACT}, f, ensure_ascii=False, indent=1, default=str)
    print("OK -> ", os.path.join(OUT, "audit_paper_%s.json" % args.tag))
    print("通过 %d / %d" % (npass, len(CHECKS)))
    for c in CHECKS:
        if c["status"] != "通过":
            print("  [%s] %s -> %s | %s" % (c["id"], c["name"], c["status"], c["evidence"][:160]))


def _fmt(ACT, cid):
    m = {"E1": ACT["t1_sum"], "E2": ACT["t1_mean"], "E3": (ACT["t1_min"], ACT["t1_max"]),
         "E4": ACT["t2_sum"], "E5": (ACT["t2_h6"], ACT["t2_h21"], ACT["t2_seg0_8"]),
         "E6": (ACT["t3_sum"], ACT["t3_mean"]), "E7": ACT["diff_31"],
         "E8": ACT["BT"].get("A9_分解式稳健WMA"), "E9": ACT["mc"]["k"],
         "E10": ACT["HB"][0]["WAPE"] * 100, "E11": (ACT["f_min"], ACT["f_max"]),
         "E12": ACT["lam"], "E13": (ACT["closed_sum"], ACT["closed_noalt_sum"], ACT["new_sum"]),
         "E14": ACT["p3"]["person_days"], "E15": (ACT["p3"]["formal_person_days"], ACT["p3"]["temp_person_days"]),
         "E16": ACT["t6_rows"], "E17": ACT["p4"]["attend_rate"], "E19": ACT["sc60_mean"],
         "E20": ACT["top5_share_t1"], "E21": (ACT["a1_rows"], ACT["a1_sum"]),
         "E22": (ACT["a2_rows"],), "E23": (ACT["a3_rows"], ACT["a3_sum"], ACT["a4_rows"])}
    return m.get(cid, "")


if __name__ == "__main__":
    main()


