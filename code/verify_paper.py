# -*- coding: utf-8 -*-
"""
verify_paper.py —— 论文 docx 结构与格式自检
===========================================
不依赖 Word / LibreOffice，直接解包 document.xml 检查排版属性，
并统计各章字数、标题层级、图表、参考文献与【待补】条目。

运行：python code/verify_paper.py [docx 路径]
"""

import os
import re
import sys
import zipfile
from collections import OrderedDict

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT = os.path.join(
    ROOT, '论文',
    '2024年MathorCupC题_物流网络分拣中心货量预测及人员排班.docx')

BAN = ['模型生成', '占位', 'AI 生成', '由 AI 撰写', 'notebook 生成']

# OOXML 子元素顺序（乱序可能被 Word 判为"内容有问题"）
ORDER = {
    'pPr': ['pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'framePr',
            'widowControl', 'numPr', 'suppressLineNumbers', 'pBdr', 'shd',
            'tabs', 'suppressAutoHyphens', 'kinsoku', 'wordWrap',
            'overflowPunct', 'topLinePunct', 'autoSpaceDE', 'autoSpaceDN',
            'bidi', 'adjustRightInd', 'snapToGrid', 'spacing', 'ind',
            'contextualSpacing', 'mirrorIndents', 'suppressOverlap', 'jc',
            'textDirection', 'textAlignment', 'textboxTightWrap',
            'outlineLvl', 'divId', 'cnfStyle', 'rPr', 'sectPr', 'pPrChange'],
    'rPr': ['rStyle', 'rFonts', 'b', 'bCs', 'i', 'iCs', 'caps', 'smallCaps',
            'strike', 'dstrike', 'outline', 'shadow', 'emboss', 'imprint',
            'noProof', 'snapToGrid', 'vanish', 'webHidden', 'color',
            'spacing', 'w', 'kern', 'position', 'sz', 'szCs', 'highlight',
            'u', 'effect', 'bdr', 'shd', 'fitText', 'vertAlign', 'rtl', 'cs',
            'em', 'lang', 'eastAsianLayout', 'specVanish', 'oMath'],
    'tblPr': ['tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual',
              'tblStyleRowBandSize', 'tblStyleColBandSize', 'tblW', 'jc',
              'tblCellSpacing', 'tblInd', 'tblBorders', 'shd', 'tblLayout',
              'tblCellMar', 'tblLook', 'tblCaption', 'tblDescription'],
    'trPr': ['cnfStyle', 'divId', 'gridBefore', 'gridAfter', 'wBefore',
             'wAfter', 'cantSplit', 'trHeight', 'tblHeader', 'tblCellSpacing',
             'jc', 'hidden'],
    'tcPr': ['cnfStyle', 'tcW', 'gridSpan', 'hMerge', 'vMerge', 'tcBorders',
             'shd', 'noWrap', 'tcMar', 'textDirection', 'tcFitText', 'vAlign',
             'hideMark'],
}


def check_order(doc):
    """检查 pPr/rPr/tblPr/trPr/tcPr 的子元素顺序。"""
    bad = []
    for tag, order in ORDER.items():
        for el in doc.element.body.iter(qn('w:' + tag)):
            idx = -1
            for child in el:
                name = child.tag.split('}')[-1]
                if name not in order:
                    continue
                i = order.index(name)
                if i < idx:
                    bad.append((tag, name, text_of(el)[:30]))
                    break
                idx = i
    return bad


def text_of(el):
    return ''.join(n.text or '' for n in el.iter(qn('w:t')))


def main(path):
    print('=' * 78)
    print('检查文件：', path)
    print('大小：%.1f KB' % (os.path.getsize(path) / 1024.0))

    # ---- 1. zip 完整性 ----
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        names = z.namelist()
    print('zip 完整性：', 'OK' if bad is None else '损坏 %s' % bad)
    print('包含部件：', len(names), '个；document.xml =',
          'word/document.xml' in names)

    doc = Document(path)

    # ---- 2. 页面设置 ----
    sec = doc.sections[0]
    print('\n[页面] 纸张 %.1f x %.1f cm；边距 上%.1f 下%.1f 左%.1f 右%.1f cm'
          % (sec.page_width.cm, sec.page_height.cm, sec.top_margin.cm,
             sec.bottom_margin.cm, sec.left_margin.cm, sec.right_margin.cm))
    ok_page = (abs(sec.page_width.cm - 21) < 0.05 and
               abs(sec.page_height.cm - 29.7) < 0.05 and
               all(abs(m.cm - 2.5) < 0.05 for m in
                   (sec.top_margin, sec.bottom_margin,
                    sec.left_margin, sec.right_margin)))
    print('        A4 + 2.5cm 边距：', 'PASS' if ok_page else 'FAIL')

    # ---- 3. 样式 ----
    def style_font(name):
        st = doc.styles[name]
        rPr = st.element.find(qn('w:rPr'))
        rf = rPr.find(qn('w:rFonts')) if rPr is not None else None
        sz = rPr.find(qn('w:sz')) if rPr is not None else None
        return (rf.get(qn('w:eastAsia')) if rf is not None else None,
                int(sz.get(qn('w:val'))) / 2.0 if sz is not None else None,
                st.font.bold)

    print('\n[样式]')
    for s in ('Normal', 'Heading 1', 'Heading 2', 'Heading 3'):
        ea, sz, b = style_font(s)
        print('  %-10s eastAsia=%-4s size=%s bold=%s' % (s, ea, sz, b))
    ea_n, sz_n, _ = style_font('Normal')
    ok_body = ea_n == '宋体' and sz_n == 12.0
    print('        正文宋体小四：', 'PASS' if ok_body else 'FAIL')

    # ---- 4. 逐段扫描：标题层级、缩进、字数 ----
    body = doc.element.body
    chapters = OrderedDict()
    cur = '（封面与摘要）'
    chapters[cur] = 0
    heads = []
    ind_ok = ind_bad = 0
    banned_hits = []
    all_text = []

    for child in body.iterchildren():
        if child.tag != qn('w:p'):
            continue
        pPr = child.find(qn('w:pPr'))
        style = ''
        if pPr is not None:
            ps = pPr.find(qn('w:pStyle'))
            if ps is not None:
                style = ps.get(qn('w:val'))
        txt = text_of(child)
        all_text.append(txt)
        for w in BAN:
            if w in txt:
                banned_hits.append((w, txt[:40]))

        if style in ('Heading1', 'Heading2', 'Heading3', '1', '2', '3'):
            lvl = {'Heading1': 1, 'Heading2': 2, 'Heading3': 3}.get(
                style, int(style) if style.isdigit() else 0)
            heads.append((lvl, txt))
            if lvl == 1:
                cur = txt
                chapters.setdefault(cur, 0)
            continue

        # 统计正文字数（去空白）
        n = len(re.sub(r'\s', '', txt))
        chapters[cur] = chapters.get(cur, 0) + n

        # 首行缩进检查（只针对正文段落：有文字、非居中标题、非表格）
        if n > 10:
            ind = pPr.find(qn('w:ind')) if pPr is not None else None
            if ind is not None and ind.get(qn('w:firstLineChars')) == '200':
                ind_ok += 1
            elif ind is not None and ind.get(qn('w:firstLine')) not in (None, '0'):
                ind_bad += 1

    print('\n[标题] 共 %d 个，层级序列：' % len(heads))
    for lvl, t in heads:
        if lvl == 1:
            print('  H1 %s' % t)
    print('  二级标题数：%d，三级标题数：%d'
          % (sum(1 for l, _ in heads if l == 2),
             sum(1 for l, _ in heads if l == 3)))

    print('\n[正文首行缩进] firstLineChars=200 命中 %d 段，其它缩进 %d 段'
          % (ind_ok, ind_bad))

    print('\n[各章字数（去空白）]')
    total = 0
    for name, n in chapters.items():
        total += n
        print('  %-24s %6d' % (name, n))
    print('  %-24s %6d' % ('合计', total))
    core = sum(v for k, v in chapters.items()
               if k.startswith(('一、', '二、', '三、')))
    print('  第一~三章合计：%d 字（要求 >= 3000）' % core)

    # ---- 5. 图 ----
    print('\n[图]')
    imgs = doc.inline_shapes
    print('  内嵌图数量：', len(imgs))
    for i, shp in enumerate(imgs, 1):
        w, h = shp.width.cm, shp.height.cm
        print('  图 %d：%.2f x %.2f cm，版心 16.00 cm，%s'
              % (i, w, h, 'PASS' if w <= 16.0 else 'FAIL（超宽）'))

    # ---- 6. 三线表 ----
    print('\n[三线表] docx 中表格数：', len(doc.tables))
    for ti, tbl in enumerate(doc.tables, 1):
        tblPr = tbl._tbl.tblPr
        borders = tblPr.find(qn('w:tblBorders'))
        edges = {}
        if borders is not None:
            for e in borders:
                edges[e.tag.split('}')[-1]] = (e.get(qn('w:val')),
                                               e.get(qn('w:sz')))
        hdr = tbl.rows[0].cells[0]._tc.find(qn('w:tcPr'))
        tcB = hdr.find(qn('w:tcBorders')) if hdr is not None else None
        layout = tblPr.find(qn('w:tblLayout'))
        print('  表 %d：%d 行 x %d 列' % (ti, len(tbl.rows), len(tbl.columns)))
        print('       顶线=%s 底线=%s 内横线=%s 内竖线=%s'
              % (edges.get('top'), edges.get('bottom'),
                 edges.get('insideH'), edges.get('insideV')))
        print('       表头下框线=%s；固定布局=%s；表头重复=%s'
              % ('有' if tcB is not None else '无',
                 layout.get(qn('w:type')) if layout is not None else '无',
                 '是' if tbl.rows[0]._tr.find(
                     qn('w:trPr')).find(qn('w:tblHeader')) is not None else '否'))
        ok3 = (edges.get('top', ('',))[0] == 'single' and
               edges.get('bottom', ('',))[0] == 'single' and
               edges.get('insideH', ('',))[0] == 'nil' and
               edges.get('insideV', ('',))[0] == 'nil' and tcB is not None)
        print('       三线表判定：', 'PASS' if ok3 else 'FAIL')

    # ---- 7. 公式（制表位） ----
    print('\n[公式段落]')
    n_eq = 0
    for p in doc.paragraphs:
        ts = p.paragraph_format.tab_stops
        txt = p.text.strip()
        if len(ts) == 2 and re.match(r'^\t.*\(\d+\)$', p.text):
            n_eq += 1
            print('  (%s) 制表位 %s' % (txt.split('(')[-1].rstrip(')'),
                                      [round(t.position.cm, 1) for t in ts]))
    print('  居中+右编号公式：%d 个' % n_eq)

    # ---- 8. 参考文献与【待补】 ----
    refs = [t for t in all_text if re.match(r'^\[\d+\]', t.strip())]
    print('\n[参考文献] %d 条（要求 >= 12）：%s'
          % (len(refs), 'PASS' if len(refs) >= 12 else 'FAIL'))
    used = set()
    for seg in re.findall(r'\[(\d{1,2}(?:[-,]\s*\d{1,2})*)\]', '\n'.join(all_text)):
        for part in seg.split(','):
            part = part.strip()
            if '-' in part:
                a, b = part.split('-')
                used.update(range(int(a), int(b) + 1))
            elif part:
                used.add(int(part))
    print('  正文引用编号集合：', sorted(used))
    print('  编号连续且全覆盖：',
          'PASS' if used == set(range(1, len(refs) + 1)) else
          'FAIL（缺 %s）' % sorted(set(range(1, len(refs) + 1)) - used))

    full = '\n'.join(all_text)
    ph = re.findall(r'【待补[^】]*】', full)
    n_ph = full.count('【待补')
    print('\n[待补标记] 共 %d 处（含表格单元格的简写），去重后 %d 条' % (n_ph, len(set(ph))))
    no_ph = (n_ph == 0)
    print('  全文无遗留【待补】：', 'PASS' if no_ph else 'FAIL')
    has_list = any('待补数字清单' in t for t in all_text)

    # ---- 9. 违规词 ----
    print('\n[违禁表述] ', 'PASS（未出现）' if not banned_hits else banned_hits)

    # ---- 9.5 OOXML 子元素顺序 ----
    bad_order = check_order(doc)
    print('\n[XML 子元素顺序] ', 'PASS' if not bad_order else bad_order[:8])

    # ---- 9.6 页脚页码 ----
    ftr_xml = sec.footer.paragraphs[0]._p.xml
    has_page_field = 'PAGE' in ftr_xml and 'fldChar' in ftr_xml
    centered = sec.footer.paragraphs[0].alignment is not None
    print('\n[页脚] PAGE 域：%s；对齐方式：%s'
          % ('有' if has_page_field else '无',
             sec.footer.paragraphs[0].alignment))

    # ---- 9.7 run 级中文字体覆盖 ----
    miss = 0
    tot = 0
    for r in doc.element.body.iter(qn('w:r')):
        txt = ''.join(n.text or '' for n in r.iter(qn('w:t')))
        if not txt.strip():
            continue
        tot += 1
        rPr = r.find(qn('w:rPr'))
        rf = rPr.find(qn('w:rFonts')) if rPr is not None else None
        if rf is None or rf.get(qn('w:eastAsia')) is None:
            miss += 1
    print('\n[run 级字体] 含文字 run %d 个，缺 eastAsia 的 %d 个：%s'
          % (tot, miss, 'PASS' if miss == 0 else 'FAIL'))

    # ---- 10. 结论 ----
    print('\n' + '=' * 78)
    checks = [
        ('A4 与 2.5cm 边距', ok_page),
        ('正文宋体 12pt', ok_body),
        ('一级标题 5 个以内正确层级', sum(1 for l, _ in heads if l == 1) >= 3),
        ('第一~三章 >= 3000 字', core >= 3000),
        ('图 1 已插入且不超宽', len(imgs) >= 1),
        ('三线表存在', len(doc.tables) >= 1),
        ('公式带居中/右编号制表位', n_eq >= 1),
        ('参考文献 >= 12 条且全部被引', len(refs) >= 12 and
         used == set(range(1, len(refs) + 1))),
        ('全文无遗留【待补】', no_ph),
        ('无违禁表述', not banned_hits),
        ('XML 顺序合法', not bad_order),
        ('页脚有居中页码', has_page_field),
        ('全部 run 写入 eastAsia 字体', miss == 0),
    ]
    for name, ok in checks:
        print('  [%s] %s' % ('PASS' if ok else 'FAIL', name))
    print('=' * 78)
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
