# -*- coding: utf-8 -*-
"""measure.py —— 统计摘要字数与分页估算（临时工具）"""
import os
import re
import sys

from docx import Document
from docx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(ROOT, '论文',
                   '2024年MathorCupC题_物流网络分拣中心货量预测及人员排班.docx')

doc = Document(DOC)
paras = doc.paragraphs

# 摘要范围：从 "摘　要" 到 "关键词：" 之前
start = next(i for i, p in enumerate(paras)
             if p.text.replace('\u3000', '').strip() == '摘要')
end = next(i for i, p in enumerate(paras) if p.text.startswith('关键词'))
abs_text = ''.join(p.text for p in paras[start + 1:end])
n_abs = len(re.sub(r'\s', '', abs_text))
print('摘要标题段索引：%d，关键词段索引：%d' % (start, end))
print('摘要字数（去空白）：%d' % n_abs)
print('关键词：', paras[end].text)

# 逐段行数估算（正文 37 字/行；表格单独按行）
CPL = 37
total_lines = 0
page_breaks = 0
cur_lines = 0
pages = []
for p in paras:
    if p.paragraph_format.page_break_before:
        pages.append(cur_lines)
        cur_lines = 0
        page_breaks += 1
    n = len(re.sub(r'\s', '', p.text))
    cur_lines += 1 if n == 0 else max(1, -(-n // CPL))
pages.append(cur_lines)

# 表格行按"单元格最多折行数"估算
def tbl_lines(tbl):
    tot = 0
    for row in tbl.rows:
        mx = 1
        for cell in row.cells:
            t = cell.text
            mx = max(mx, max(1, -(-len(re.sub(r'\s', '', t)) // 36)))
        tot += mx
    return tot

# 图占 12 行
extra = tbl_lines(doc.tables[0]) + tbl_lines(doc.tables[1]) + 12
LP_PAGE = 30
print('\n各页起始段落的行数分布：', pages)
print('估算总行数：%d（含表/图追加 %d）' % (sum(pages), extra))
est = sum(max(1, -(-(x) // LP_PAGE)) for x in pages)
est += round(extra / LP_PAGE + 0.5)
print('估算页数：约 %d 页（每页 %d 行）' % (est, LP_PAGE))
print('段落数：%d，表格：%d' % (len(paras), len(doc.tables)))
