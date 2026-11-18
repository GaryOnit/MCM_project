# -*- coding: utf-8 -*-
"""dump_text.py —— 把 docx 正文导出为纯文本，便于校对（临时工具）"""
import os
import sys

from docx import Document
from docx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(ROOT, '论文',
                   '2024年MathorCupC题_物流网络分拣中心货量预测及人员排班.docx')
OUT = os.path.join(ROOT, '论文', '_dump.txt')

doc = Document(DOC)
lines = []
for child in doc.element.body.iterchildren():
    tag = child.tag.split('}')[-1]
    if tag == 'p':
        pPr = child.find(qn('w:pPr'))
        style = ''
        if pPr is not None:
            ps = pPr.find(qn('w:pStyle'))
            style = ps.get(qn('w:val')) if ps is not None else ''
        txt = ''.join(n.text or '' for n in child.iter(qn('w:t')))
        if 'Heading' in style:
            jc = pPr.find(qn('w:jc'))
            lines.append('\n' + ('  ' * (int(style[-1]) - 1)) +
                         '[%s] %s' % (style, txt))
        elif 'page_break_before' in (child.xml[:400]):
            lines.append('\n---- 分页 ----')
            lines.append(txt)
        else:
            lines.append(txt)
    elif tag == 'tbl':
        lines.append('<<表格>>')
        for tr in child.iter(qn('w:tr')):
            cells = []
            for tc in tr.iter(qn('w:tc')):
                cells.append(''.join(n.text or '' for n in tc.iter(qn('w:t'))))
            lines.append('  | ' + ' | '.join(cells))
        lines.append('<<表格结束>>')

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('已导出：', OUT, sum(len(x) for x in lines), '字符')
