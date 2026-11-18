# -*- coding: utf-8 -*-
"""
docx_utils.py —— 数学建模论文 Word 排版样式模块（python-docx 1.2.0）
=====================================================================

设计目标：为「2024 年 MathorCup C 题」论文提供一套**可复用**的排版原语，
后续续写（第四~十章）与全文统稿时统一调用本模块，保证格式完全一致。

硬约束（对应《论文规格.md》§3）
--------------------------------
* 纸张 A4（21.0 cm × 29.7 cm），上下左右页边距均 2.5 cm
* 正文：宋体、小四（12 pt）、行距 1.5 倍、首行缩进 2 字符
* 标题：黑体，一级三号（16 pt）加粗、二级四号（14 pt）、三级小四（12 pt）
* 表格：三线表（顶线 1.5 pt / 表头线 0.75 pt / 底线 1.5 pt，无竖线），
        表题在表上方居中（五号加粗），表内五号（10.5 pt）
* 图题在图下方居中（五号加粗）
* 公式：居中，右侧编号 (1)(2)…
* 页脚居中页码

中文字体必须同时写入 `w:eastAsia`，否则 Word 中会退回默认字体（等线）。

行内标记语法（正文、表头、表体、公式通用）
------------------------------------------
* `$...$`      内部按斜体排（用于数学符号），如 ``$V_{c,d}$``
* `_{...}`     下标，如 ``V_{c,d}``
* `^{...}`     上标，如 ``e^{25}``
以上均为**普通文本 + 字符格式**，不产生 OMML，Word 打开安全。

典型用法
--------
>>> from docx_utils import Paper, CN_BODY, CN_HEAD
>>> p = Paper()
>>> p.h1('一、问题重述')
>>> p.p('电商物流网络由仓库、分拣中心与营业部等节点构成……')
>>> p.formula('$f_{c}$ = (IN$_{c}$ + OUT$_{c}$) / (IN$_{c}$ + OUT$_{c}$)', 2)
>>> p.table('表 1　主要符号说明', ['符号', '含义', '单位'], rows, widths=[3.0, 10.0, 3.0])
>>> p.figure(r'论文/figs/flow.png', '图 1　论文总体技术路线', width_cm=15.5)
>>> p.save(r'论文/xxx.docx')
"""

from __future__ import annotations

import os

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# --------------------------------------------------------------------------
# 全局排版常量
# --------------------------------------------------------------------------
CN_BODY = '宋体'
CN_HEAD = '黑体'
EN_FONT = 'Times New Roman'

PAGE_W, PAGE_H = 21.0, 29.7          # A4，单位 cm
MARGIN = 2.5                          # 页边距，单位 cm
TEXT_W = PAGE_W - 2 * MARGIN          # 版心宽度 16.0 cm

SIZE_BODY = 12.0                      # 小四
SIZE_H1, SIZE_H2, SIZE_H3 = 16.0, 14.0, 12.0   # 三号 / 四号 / 小四
SIZE_TABLE = 10.5                     # 五号
SIZE_NOTE = 9.0                       # 小五

LINE_SPACING = 1.5

ALIGN_MAP = {
    'left': WD_ALIGN_PARAGRAPH.LEFT,
    'center': WD_ALIGN_PARAGRAPH.CENTER,
    'right': WD_ALIGN_PARAGRAPH.RIGHT,
    'justify': WD_ALIGN_PARAGRAPH.JUSTIFY,
}

# OOXML 子元素顺序表（Word 对 tblPr/trPr/tcPr 的子元素顺序敏感，乱序可能被判为损坏）
_TBLPR_ORDER = [
    'tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual', 'tblStyleRowBandSize',
    'tblStyleColBandSize', 'tblW', 'jc', 'tblCellSpacing', 'tblInd',
    'tblBorders', 'shd', 'tblLayout', 'tblCellMar', 'tblLook', 'tblCaption',
    'tblDescription',
]
_TRPR_ORDER = [
    'cnfStyle', 'divId', 'gridBefore', 'gridAfter', 'wBefore', 'wAfter',
    'cantSplit', 'trHeight', 'tblHeader', 'tblCellSpacing', 'jc', 'hidden',
]
_TCPR_ORDER = [
    'cnfStyle', 'tcW', 'gridSpan', 'hMerge', 'vMerge', 'tcBorders', 'shd',
    'noWrap', 'tcMar', 'textDirection', 'tcFitText', 'vAlign', 'hideMark',
]


def _local(tag):
    return tag.split('}')[-1]


def _insert_in_order(parent, el, order):
    """按 OOXML 规定的顺序把 el 插入 parent。"""
    idx = order.index(_local(el.tag))
    for child in list(parent):
        name = _local(child.tag)
        if name in order and order.index(name) > idx:
            child.addprevious(el)
            return
    parent.append(el)


# --------------------------------------------------------------------------
# 字体 / 行内标记
# --------------------------------------------------------------------------
def set_run_font(run, cn=CN_BODY, en=EN_FONT, size=SIZE_BODY,
                 bold=False, italic=False, color=None, underline=False):
    """设置 run 的中西文字体（必须同时写 w:eastAsia，否则 Word 掉字体）。"""
    run.font.name = en
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    run.underline = underline
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    # 清掉主题字体属性，否则主题字体会覆盖显式字体
    for attr in ('w:asciiTheme', 'w:hAnsiTheme', 'w:eastAsiaTheme', 'w:cstheme'):
        if rFonts.get(qn(attr)) is not None:
            del rFonts.attrib[qn(attr)]
    rFonts.set(qn('w:ascii'), en)
    rFonts.set(qn('w:hAnsi'), en)
    rFonts.set(qn('w:eastAsia'), cn)
    rFonts.set(qn('w:cs'), en)
    if color is not None:
        run.font.color.rgb = color


def set_style_font(style, cn=CN_BODY, en=EN_FONT, size=SIZE_BODY, bold=None,
                   color=None):
    """设置样式级字体（用于 Normal / Heading 1~3）。"""
    style.font.name = en
    style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    for attr in ('w:asciiTheme', 'w:hAnsiTheme', 'w:eastAsiaTheme', 'w:cstheme'):
        if rFonts.get(qn(attr)) is not None:
            del rFonts.attrib[qn(attr)]
    rFonts.set(qn('w:ascii'), en)
    rFonts.set(qn('w:hAnsi'), en)
    rFonts.set(qn('w:eastAsia'), cn)
    rFonts.set(qn('w:cs'), en)


def parse_rich(text):
    """把带行内标记的字符串切分为 [(片段, 是否斜体, 上下标)] 。

    * `$...$` 切换斜体
    * `_{...}` 下标，`^{...}` 上标
    """
    if text is None:
        return []
    if text.count('$') % 2 != 0:
        raise ValueError('行内公式标记 $ 未闭合：%r' % (text,))
    segs = []
    buf = []
    italic = False

    def flush():
        if buf:
            segs.append((''.join(buf), italic, None))
            del buf[:]

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '$':
            flush()
            italic = not italic
            i += 1
            continue
        if ch in '^_' and i + 1 < n and text[i + 1] == '{':
            j = text.find('}', i + 2)
            if j != -1:
                flush()
                segs.append((text[i + 2:j], italic, 'sup' if ch == '^' else 'sub'))
                i = j + 1
                continue
        buf.append(ch)
        i += 1
    flush()
    return segs


def add_rich(paragraph, text, size=SIZE_BODY, bold=False, cn=CN_BODY,
             en=EN_FONT, italic_all=False, color=None):
    """把带标记的文本写入段落，返回段落。"""
    for seg, italic, script in parse_rich(text):
        if not seg:
            continue
        run = paragraph.add_run(seg)
        set_run_font(run, cn=cn, en=en, size=size, bold=bold,
                     italic=(italic_all or italic), color=color)
        if script == 'sub':
            run.font.subscript = True
        elif script == 'sup':
            run.font.superscript = True
    return paragraph


def _set_ind_chars(paragraph, first_line_chars=None, left_chars=None,
                   hanging_chars=None):
    """写入 w:firstLineChars 等字符单位缩进，使 Word 中按"字符"显示。"""
    pPr = paragraph._p.get_or_add_pPr()
    ind = pPr.find(qn('w:ind'))
    if ind is None:
        ind = OxmlElement('w:ind')
        pPr.append(ind)
    if first_line_chars is not None:
        ind.set(qn('w:firstLineChars'), str(first_line_chars))
    if left_chars is not None:
        ind.set(qn('w:leftChars'), str(left_chars))
    if hanging_chars is not None:
        ind.set(qn('w:hangingChars'), str(hanging_chars))


# --------------------------------------------------------------------------
# 主体类
# --------------------------------------------------------------------------
class Paper:
    """一篇论文 = 一个 Paper 实例；所有 add_* 方法都作用在同一文档上。"""

    def __init__(self, margins=MARGIN, body_size=SIZE_BODY,
                 line_spacing=LINE_SPACING, page_number=True):
        self.doc = Document()
        self.body_size = body_size
        self.line_spacing = line_spacing
        self.text_width = PAGE_W - 2 * margins
        self._fig_no = 0
        self._tab_no = 0
        self._pending_break = False

        sec = self.doc.sections[0]
        sec.page_width = Cm(PAGE_W)
        sec.page_height = Cm(PAGE_H)
        sec.top_margin = Cm(margins)
        sec.bottom_margin = Cm(margins)
        sec.left_margin = Cm(margins)
        sec.right_margin = Cm(margins)
        sec.header_distance = Cm(1.5)
        sec.footer_distance = Cm(1.5)

        self._setup_styles()
        if page_number:
            self.add_page_number(sec)

    # ---------------- 样式 ----------------
    def _setup_styles(self):
        # 正文
        normal = self.doc.styles['Normal']
        set_style_font(normal, cn=CN_BODY, en=EN_FONT, size=self.body_size)
        pf = normal.paragraph_format
        pf.line_spacing = self.line_spacing
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)

        # 三级标题（保留内置样式以维持大纲级别，便于导航/自动目录）
        spec = {
            'Heading 1': (SIZE_H1, 12, 8),
            'Heading 2': (SIZE_H2, 10, 6),
            'Heading 3': (SIZE_H3, 8, 4),
        }
        for name, (size, before, after) in spec.items():
            st = self.doc.styles[name]
            set_style_font(st, cn=CN_HEAD, en=CN_HEAD, size=size, bold=True,
                           color=RGBColor(0, 0, 0))
            st.font.italic = False
            spf = st.paragraph_format
            spf.space_before = Pt(before)
            spf.space_after = Pt(after)
            spf.line_spacing = self.line_spacing
            spf.keep_with_next = True
            spf.first_line_indent = Pt(0)

    # ---------------- 页脚页码 ----------------
    def add_page_number(self, section):
        footer = section.footer
        footer.is_linked_to_previous = False
        par = footer.paragraphs[0]
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.first_line_indent = Pt(0)
        run = par.add_run()
        set_run_font(run, size=SIZE_TABLE, en=EN_FONT)
        fld_begin = OxmlElement('w:fldChar')
        fld_begin.set(qn('w:fldCharType'), 'begin')
        instr = OxmlElement('w:instrText')
        instr.set(qn('xml:space'), 'preserve')
        instr.text = ' PAGE '
        fld_sep = OxmlElement('w:fldChar')
        fld_sep.set(qn('w:fldCharType'), 'separate')
        txt = OxmlElement('w:t')
        txt.text = '1'
        fld_end = OxmlElement('w:fldChar')
        fld_end.set(qn('w:fldCharType'), 'end')
        for el in (fld_begin, instr, fld_sep, txt, fld_end):
            run._element.append(el)

    # ---------------- 段落 ----------------
    def _new_par(self):
        """新建段落；若挂起了分页请求，则改为"段前分页"，避免空白行。"""
        par = self.doc.add_paragraph()
        if self._pending_break:
            par.paragraph_format.page_break_before = True
            self._pending_break = False
        return par

    def p(self, text='', indent=True, size=None, bold=False, align=None,
          space_before=0, space_after=0, line_spacing=None, cn=CN_BODY,
          en=EN_FONT, italic=False, keep_with_next=False, left_indent=None,
          hanging=None, first_line=None):
        size = size or self.body_size
        par = self._new_par()
        pf = par.paragraph_format
        pf.line_spacing = line_spacing or self.line_spacing
        pf.space_before = Pt(space_before)
        pf.space_after = Pt(space_after)
        pf.keep_with_next = keep_with_next
        if first_line is not None:
            pf.first_line_indent = Pt(first_line)
        elif indent:
            pf.first_line_indent = Pt(size * 2)
            _set_ind_chars(par, first_line_chars=200)
        else:
            pf.first_line_indent = Pt(0)
        if left_indent is not None:
            pf.left_indent = Cm(left_indent)
        if hanging is not None:
            pf.first_line_indent = Cm(-hanging)
            _set_ind_chars(par, hanging_chars=int(hanging / (size * 0.0353)))
        if align:
            par.alignment = ALIGN_MAP[align]
        add_rich(par, text, size=size, bold=bold, cn=cn, en=en,
                 italic_all=italic)
        return par

    def blank(self, size=None):
        return self.p('', indent=False, size=size or self.body_size)

    # ---------------- 标题 ----------------
    def _heading(self, text, level, align=None):
        size = {1: SIZE_H1, 2: SIZE_H2, 3: SIZE_H3}[level]
        par = self.doc.add_paragraph(style='Heading %d' % level)
        if self._pending_break:
            par.paragraph_format.page_break_before = True
            self._pending_break = False
        pf = par.paragraph_format
        pf.first_line_indent = Pt(0)
        pf.left_indent = Cm(0)
        if align:
            par.alignment = ALIGN_MAP[align]
        add_rich(par, text, size=size, bold=True, cn=CN_HEAD, en=CN_HEAD)
        return par

    def h1(self, text, align='center'):
        return self._heading(text, 1, align=align)

    def h2(self, text):
        return self._heading(text, 2, align='left')

    def h3(self, text):
        return self._heading(text, 3, align='left')

    def abstract_title(self, text='摘　要'):
        """摘要标题：黑体四号居中。"""
        par = self._new_par()
        pf = par.paragraph_format
        pf.first_line_indent = Pt(0)
        pf.space_before = Pt(6)
        pf.space_after = Pt(10)
        pf.line_spacing = self.line_spacing
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_rich(par, text, size=SIZE_H2, bold=True, cn=CN_HEAD, en=CN_HEAD)
        return par

    # ---------------- 图 ----------------
    def figure(self, path, caption=None, width_cm=None, note=None):
        if not os.path.exists(path):
            raise FileNotFoundError('图片不存在：%s' % path)
        par = self._new_par()
        pf = par.paragraph_format
        pf.first_line_indent = Pt(0)
        pf.space_before = Pt(6)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.0
        pf.keep_with_next = True
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = par.add_run()
        run.add_picture(path, width=Cm(width_cm or self.text_width))
        if caption:
            self._fig_no += 1
            self.caption(caption, kind='figure')
        if note:
            self.note(note)
        return par

    def caption(self, text, kind='table', size=SIZE_TABLE):
        """表题（表上方）/ 图题（图下方）：五号加粗、居中。"""
        par = self._new_par()
        pf = par.paragraph_format
        pf.first_line_indent = Pt(0)
        pf.line_spacing = 1.0
        if kind == 'table':
            pf.space_before = Pt(8)
            pf.space_after = Pt(3)
            pf.keep_with_next = True
        else:
            pf.space_before = Pt(4)
            pf.space_after = Pt(8)
            pf.keep_with_next = False
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_rich(par, text, size=size, bold=True, cn=CN_BODY, en=EN_FONT)
        return par

    def note(self, text, size=SIZE_NOTE):
        """表下注释：小五、左对齐、无缩进。"""
        par = self._new_par()
        pf = par.paragraph_format
        pf.first_line_indent = Pt(0)
        pf.space_before = Pt(2)
        pf.space_after = Pt(8)
        pf.line_spacing = 1.0
        par.alignment = WD_ALIGN_PARAGRAPH.LEFT
        add_rich(par, text, size=size, cn=CN_BODY, en=EN_FONT)
        return par

    # ---------------- 公式 ----------------
    def formula(self, expr, number=None, size=None):
        """公式居中（居中制表位）、编号右对齐（右制表位）。"""
        size = size or self.body_size
        par = self._new_par()
        pf = par.paragraph_format
        pf.first_line_indent = Pt(0)
        pf.space_before = Pt(6)
        pf.space_after = Pt(6)
        pf.line_spacing = self.line_spacing
        par.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf.tab_stops.add_tab_stop(Cm(self.text_width / 2.0), WD_TAB_ALIGNMENT.CENTER)
        pf.tab_stops.add_tab_stop(Cm(self.text_width), WD_TAB_ALIGNMENT.RIGHT)
        r0 = par.add_run('\t')
        set_run_font(r0, size=size)
        add_rich(par, expr, size=size, italic_all=True)
        if number is not None:
            r1 = par.add_run('\t(%s)' % number)
            set_run_font(r1, size=size)
        return par

    # ---------------- 三线表 ----------------
    @staticmethod
    def _borders_el(edges):
        """edges: [(边名, 线型或None, 线宽/8pt)]"""
        borders = OxmlElement('w:tblBorders')
        for edge, val, sz in edges:
            el = OxmlElement('w:%s' % edge)
            el.set(qn('w:val'), val)
            if val != 'nil':
                el.set(qn('w:sz'), str(sz))
                el.set(qn('w:space'), '0')
                el.set(qn('w:color'), '000000')
            else:
                el.set(qn('w:sz'), '0')
                el.set(qn('w:space'), '0')
            borders.append(el)
        return borders

    def table(self, caption, header, rows, widths=None, note=None,
              font=SIZE_TABLE, header_bold=True, aligns=None,
              row_height=None, top_sz=12, mid_sz=8, bottom_sz=12,
              autofit_header_repeat=True):
        """三线表。

        caption : 表题（写在表上方，居中五号加粗）；给 None 则不写
        header  : 表头列表
        rows    : 二维表体（元素可为 str，支持行内标记）
        widths  : 各列宽度（cm），默认均分版心
        aligns  : 每列对齐（'left'/'center'），默认全部居中
        note    : 表下注释（小五）
        """
        if caption:
            self.caption(caption, kind='table')
        ncol = len(header)
        if widths is None:
            widths = [self.text_width / ncol] * ncol
        if aligns is None:
            aligns = ['center'] * ncol

        tbl = self.doc.add_table(rows=1 + len(rows), cols=ncol)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        # 默认样式名在不同模板中为 "Table Normal" 或 "Normal Table"，取到哪个用哪个
        for style_name in ('Table Normal', 'Normal Table', 'Table Grid'):
            try:
                tbl.style = self.doc.styles[style_name]
                break
            except KeyError:
                continue
        tblPr = tbl._tbl.tblPr

        # 表宽 = 100%
        tblW = tblPr.find(qn('w:tblW'))
        if tblW is None:
            tblW = OxmlElement('w:tblW')
            _insert_in_order(tblPr, tblW, _TBLPR_ORDER)
        tblW.set(qn('w:type'), 'dxa')
        tblW.set(qn('w:w'), str(int(sum(widths) / 2.54 * 1440)))

        # 三线：顶线 / 底线，无竖线、无内横线
        borders = self._borders_el([
            ('top', 'single', top_sz),
            ('left', 'nil', 0),
            ('bottom', 'single', bottom_sz),
            ('right', 'nil', 0),
            ('insideH', 'nil', 0),
            ('insideV', 'nil', 0),
        ])
        old = tblPr.find(qn('w:tblBorders'))
        if old is not None:
            tblPr.remove(old)
        _insert_in_order(tblPr, borders, _TBLPR_ORDER)

        # 固定列宽
        layout = OxmlElement('w:tblLayout')
        layout.set(qn('w:type'), 'fixed')
        _insert_in_order(tblPr, layout, _TBLPR_ORDER)

        # 单元格边距
        mar = OxmlElement('w:tblCellMar')
        for side, w in (('top', 30), ('left', 80), ('bottom', 30), ('right', 80)):
            el = OxmlElement('w:%s' % side)
            el.set(qn('w:w'), str(w))
            el.set(qn('w:type'), 'dxa')
            mar.append(el)
        _insert_in_order(tblPr, mar, _TBLPR_ORDER)

        for i, w in enumerate(widths):
            tbl.columns[i].width = Cm(w)

        # 表头行：整行重复 + 不跨页断行 + 下框线
        hdr_tr = tbl.rows[0]._tr
        trPr = hdr_tr.get_or_add_trPr()
        cant = OxmlElement('w:cantSplit')
        _insert_in_order(trPr, cant, _TRPR_ORDER)
        if autofit_header_repeat:
            th = OxmlElement('w:tblHeader')
            th.set(qn('w:val'), 'true')
            _insert_in_order(trPr, th, _TRPR_ORDER)

        for r_idx, row in enumerate(tbl.rows):
            if row_height:
                row.height = Cm(row_height)
            for c_idx, cell in enumerate(row.cells):
                cell.width = Cm(widths[c_idx])
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                par = cell.paragraphs[0]
                pf = par.paragraph_format
                pf.first_line_indent = Pt(0)
                pf.left_indent = Cm(0)
                pf.space_before = Pt(2)
                pf.space_after = Pt(2)
                pf.line_spacing = 1.0
                par.alignment = ALIGN_MAP[aligns[c_idx]]
                txt = header[c_idx] if r_idx == 0 else rows[r_idx - 1][c_idx]
                add_rich(par, '' if txt is None else str(txt), size=font,
                         bold=(header_bold if r_idx == 0 else False),
                         cn=CN_BODY, en=EN_FONT)
                if r_idx == 0 and mid_sz:
                    self._cell_bottom_border(cell, mid_sz)
        if note:
            self.note(note)
        self._tab_no += 1
        return tbl

    @staticmethod
    def _cell_bottom_border(cell, sz):
        tcPr = cell._tc.get_or_add_tcPr()
        tcB = OxmlElement('w:tcBorders')
        b = OxmlElement('w:bottom')
        b.set(qn('w:val'), 'single')
        b.set(qn('w:sz'), str(sz))
        b.set(qn('w:space'), '0')
        b.set(qn('w:color'), '000000')
        tcB.append(b)
        old = tcPr.find(qn('w:tcBorders'))
        if old is not None:
            tcPr.remove(old)
        _insert_in_order(tcPr, tcB, _TCPR_ORDER)

    # ---------------- 参考文献条目 ----------------
    def reference(self, text, size=None, hanging_cm=0.9):
        """悬挂缩进的参考文献条目。"""
        size = size or SIZE_TABLE
        par = self._new_par()
        pf = par.paragraph_format
        pf.line_spacing = 1.25
        pf.space_before = Pt(2)
        pf.space_after = Pt(2)
        pf.left_indent = Cm(hanging_cm)
        pf.first_line_indent = Cm(-hanging_cm)
        par.alignment = WD_ALIGN_PARAGRAPH.LEFT
        add_rich(par, text, size=size, cn=CN_BODY, en=EN_FONT)
        return par

    # ---------------- 分页 / 保存 ----------------
    def page_break(self):
        """挂起一次分页：由下一个段落以「段前分页」实现，避免产生空行。"""
        self._pending_break = True

    def flush_break(self):
        """若分页请求未被消费（如处于文档末尾），补一个真正的分页符。"""
        if not self._pending_break:
            return
        self._pending_break = False
        par = self.doc.add_paragraph()
        par.paragraph_format.first_line_indent = Pt(0)
        run = par.add_run()
        br = OxmlElement('w:br')
        br.set(qn('w:type'), 'page')
        run._element.append(br)

    def save(self, path):
        self.flush_break()
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        self.doc.save(path)
        return path


# --------------------------------------------------------------------------
# 便捷函数：不建 Paper 也能快速设字体
# --------------------------------------------------------------------------
def quick_font(paragraph, size=SIZE_BODY, bold=False, cn=CN_BODY):
    for run in paragraph.runs:
        set_run_font(run, cn=cn, size=size, bold=bold)
    return paragraph


if __name__ == '__main__':
    # 冒烟测试：生成一个最小样张，检查字体/三线表/公式/页码是否正常
    p = Paper()
    p.h1('一、冒烟测试')
    p.p('中文宋体小四，首行缩进两字符；行内符号 $V_{c,d}$ 与上标 $e^{25}$。')
    p.formula('$f_{c}$ = (IN$_{c}$ + OUT$_{c}$) / (IN$_{c}$ + OUT$_{c}$)', 1)
    p.table('表 1　三线表自检', ['符号', '含义', '单位'],
            [['$V_{c,d}$', '日货量', '件'], ['$e_{25}$', '正式工人效', '件/(人·时)']],
            widths=[3.5, 9.0, 3.5])
    p.figure(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), '论文', 'figs', 'flow.png'),
        '图 1　测试图')
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       '论文', '_smoke.docx')
    p.save(out)
    print('OK', out)
