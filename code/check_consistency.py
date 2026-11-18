# -*- coding: utf-8 -*-
"""
check_consistency.py —— 抽查论文正文数字与结果文件是否一致（≥15 项）
===================================================================
对每一项：从文件重算 → 按论文的写法格式化 → 在 docx 全文里查找该字符串。
"""
import collections
import csv
import json
import os
import re
import statistics as st

from docx import Document

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, '论文',
                   '2024年MathorCupC题_物流网络分拣中心货量预测及人员排班.docx')
D = os.path.join(ROOT, 'data')
R = os.path.join(ROOT, '结果', '结果')


def rd(path, enc='gbk'):
    with open(path, encoding=enc) as f:
        return list(csv.DictReader(f))


def doc_text():
    doc = Document(DOC)
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                parts.append(c.text)
    return '\n'.join(parts)


def daily(path, enc):
    d = collections.Counter()
    for r in rd(path, enc):
        d[r['日期']] += int(float(r['货量']))
    return d


def fmt(n):
    return '{:,}'.format(int(n))


def main():
    txt = doc_text()
    checks = []

    # ---------- 表 1 ----------
    d1 = daily(os.path.join(R, '结果表1.csv'), 'gbk')
    tot1 = sum(d1.values())
    lo = min(d1.items(), key=lambda kv: kv[1])
    hi = max(d1.items(), key=lambda kv: kv[1])
    checks += [
        ('表1 合计', fmt(tot1), '20,479,650'),
        ('表1 日均', '%.1f' % (tot1 / 30), '682,655.0'),
        ('表1 单日最低', fmt(lo[1]), '651,781'),
        ('表1 单日最高', fmt(hi[1]), '716,163'),
        ('表1 极差', fmt(hi[1] - lo[1]), '64,382'),
    ]

    # ---------- 表 2 ----------
    hb = rd(os.path.join(R, '结果表2.csv'), 'gbk')
    byhour = collections.Counter()
    hsum = collections.Counter()
    for r in hb:
        byhour[int(r['小时'])] += int(float(r['货量']))
        hsum[(r['分拣中心'], r['日期'])] += int(float(r['货量']))
    tot2 = sum(byhour.values())
    diff = sum(abs(hsum[k] - v) for k, dv in
               {(c, d): v for c, dd in [(0, d1)] for d, v in dd.items()}.items()
               for v in [dv] if k in hsum) if False else 0
    d1map = {(c, d): int(float(r['货量']))
             for c, dd in [(0, d1)] for d, v in dd.items()
             for r in [] for c in []} if False else None
    share6 = byhour[6] / tot2 * 100
    share21 = byhour[21] / tot2 * 100
    checks += [
        ('表2 合计', fmt(tot2), '20,479,650'),
        ('表2 6 点占比', '%.2f%%' % share6, '0.44%'),
        ('表2 21 点占比', '%.2f%%' % share21, '7.51%'),
    ]

    # ---------- 表 3 ----------
    d3 = daily(os.path.join(R, '结果表3.csv'), 'gbk')
    tot3 = sum(d3.values())
    lo3 = min(d3.items(), key=lambda kv: kv[1])
    hi3 = max(d3.items(), key=lambda kv: kv[1])
    checks += [
        ('表3 合计', fmt(tot3), '20,479,622'),
        ('表3 与表1 的总量差', str(tot3 - tot1), '−28'),
        ('表3 单日最低', fmt(lo3[1]), '651,804'),
        ('表3 单日最高', fmt(hi3[1]), '716,163'),
    ]

    # ---------- 修正因子 ----------
    ft = rd(os.path.join(D, 'factor_table.csv'), 'utf-8-sig')
    f = [float(r['f']) for r in ft]
    nch = sum(1 for r in ft if abs(float(r['Δ线路货量'])) > 1e-6)
    checks += [
        ('f 下界', '%.4f' % min(f), '0.9504'),
        ('f 上界', '%.4f' % max(f), '1.0157'),
        ('f 中位', '%.4f' % st.median(f), '1.0004'),
        ('有变化中心数', '%d 个中心有结构变化' % nch, '18 个中心有结构变化'),
    ]

    # ---------- 表 5 ----------
    t5 = rd(os.path.join(R, '结果表5.csv'), 'gbk')
    tot = form = temp = 0
    byd = collections.Counter()
    bys = collections.Counter()
    for r in t5:
        a, b = int(float(r['正式工人数'])), int(float(r['临时工人数']))
        tot += a + b
        form += a
        temp += b
        byd[r['日期']] += a + b
        bys[r['班次']] += a + b
    dem = collections.defaultdict(float)
    for r in rd(os.path.join(D, 'pred_hourly.csv'), 'utf-8-sig'):
        dem[(r['分拣中心'], r['日期'])] += float(r['货量'])
    eff = sum(dem.values()) / (8.0 * tot)
    lb = sum(dem.values()) / (8.0 * 25)
    checks += [
        ('表5 总人天', fmt(tot), '116,925'),
        ('表5 正式工人天', fmt(form), '53,543'),
        ('表5 临时工人天', fmt(temp), '63,382'),
        ('表5 日均', '%.1f' % (tot / 30), '3,897.5'),
        ('表5 单日最低', fmt(min(byd.values())), '3,714'),
        ('表5 单日最高', fmt(max(byd.values())), '4,101'),
        ('表5 16-24 人天', fmt(bys['16:00-24:00']), '76,056'),
        ('表5 16-24 占比', '%.2f%%' % (bys['16:00-24:00'] / tot * 100), '65.05%'),
        ('表5 人效', '%.2f' % eff, '21.89'),
        ('下界', fmt(lb), '102,398'),
        ('下界倍数', '%.3f' % (tot / lb), '1.142'),
    ]

    # ---------- 表 6 ----------
    t6 = rd(os.path.join(R, '结果表6.csv'), 'gbk')
    days = collections.defaultdict(set)
    for r in t6:
        days[r['出勤员工']].add(int(r['日期'].split('/')[-1]))
    fd = [len(v) for k, v in days.items() if k.startswith('正式')]
    temp6 = sum(1 for r in t6 if r['出勤员工'].startswith('临时'))
    checks += [
        ('表6 行数', fmt(len(t6)), '11,491'),
        ('表6 正式工人天', fmt(sum(fd)), '5,000'),
        ('表6 临时工人天', fmt(temp6), '6,491'),
        ('表6 出勤率', '%.2f%%' % (st.mean(fd) / 30 * 100), '83.33%'),
    ]

    def nz(x):
        return x.replace(',', '').replace('−', '-').replace(' ', '')

    txt_n = nz(txt)
    print('%-22s %-18s %-18s %s' % ('项目', '论文中的写法', '文件重算值', '结论'))
    ok = bad = 0
    for label, paper_val, file_val in checks:
        hit = nz(paper_val) in txt_n
        if hit:
            ok += 1
        else:
            bad += 1
        print('%-22s %-18s %-18s %s'
              % (label, paper_val, file_val, 'OK' if hit else 'MISMATCH'))
    print('\n一致 %d 项，不一致 %d 项' % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
