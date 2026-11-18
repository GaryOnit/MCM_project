# -*- coding: utf-8 -*-
"""PDF text extraction v2: group glyphs by position, mark undecodable (CJK-subset)
glyphs with placeholder so the ASCII/number skeleton can be verified against a
candidate transcription."""
import re, zlib, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
raw = open('物流网络分拣中心货量预测及人员排班.pdf', 'rb').read()

objs = {}
for m in re.finditer(rb'(\d+)\s+(\d+)\s+obj\b', raw):
    s = m.end(); e = raw.find(b'endobj', s); objs[int(m.group(1))] = raw[s:e]


def inflate(chunk):
    i = chunk.find(b'stream')
    if i < 0:
        return None
    j = i + 6
    while j < len(chunk) and chunk[j] in (13, 10):
        j += 1
    k = chunk.rfind(b'endstream')
    data = chunk[j:k] if k > j else chunk[j:]
    try:
        return zlib.decompress(data)
    except Exception:
        return None


streams = {n: d for n, c in objs.items() if b'stream' in c for d in [inflate(c)] if d}


def parse_cmap(data):
    txt = data.decode('latin-1')
    cmap = {}

    def hex2uni(h):
        b = bytes.fromhex(h)
        if len(b) % 2:
            b += b'\x00'
        return b.decode('utf-16-be', 'ignore')

    for m in re.finditer(r'beginbfchar(.*?)endbfchar', txt, re.S):
        for mm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', m.group(1)):
            cmap[int(mm.group(1), 16)] = hex2uni(mm.group(2))
    for m in re.finditer(r'beginbfrange(.*?)endbfrange', txt, re.S):
        for mm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', m.group(1)):
            lo, hi, dst = int(mm.group(1), 16), int(mm.group(2), 16), mm.group(3)
            base = int(dst, 16)
            for k in range(hi - lo + 1):
                cmap[lo + k] = chr(base + k)
    return cmap


fonts = {}
for num, chunk in objs.items():
    if re.search(rb'/Type\s*/Font', chunk):
        tu = re.search(rb'/ToUnicode\s+(\d+)\s+0\s+R', chunk)
        cm = parse_cmap(streams[int(tu.group(1))]) if tu and int(tu.group(1)) in streams else {}
        fonts[num] = cm

pages = [(n, c) for n, c in objs.items()
         if re.search(rb'/Type\s*/Page\b', c) and not re.search(rb'/Type\s*/Pages\b', c)]
pages.sort()


def resolve_fonts(pagechunk):
    m = re.search(rb'/Resources\s+(\d+)\s+0\s+R', pagechunk)
    res = objs.get(int(m.group(1)), b'') if m else pagechunk
    out = {}
    fm = re.search(rb'/Font\s*<<(.*?)>>', res, re.S)
    if fm:
        for mm in re.finditer(rb'/([A-Za-z0-9#+.\-]+)\s+(\d+)\s+0\s+R', fm.group(1)):
            out[mm.group(1).decode('latin-1')] = int(mm.group(2))
    else:
        fm2 = re.search(rb'/Font\s+(\d+)\s+0\s+R', res)
        if fm2:
            fd = objs.get(int(fm2.group(1)), b'')
            for mm in re.finditer(rb'/([A-Za-z0-9#+.\-]+)\s+(\d+)\s+0\s+R', fd):
                out[mm.group(1).decode('latin-1')] = int(mm.group(2))
    return out


NUMRE = re.compile(rb'(\d+\.?\d*|\.\d+|[A-Za-z\'"*][A-Za-z0-9\'"*]*|/[^\s/\[\]<>(){}%]*|<<|>>|[\[\]])')


def tokenize(c):
    toks = []
    i, n = 0, len(c)
    while i < n:
        ch = c[i:i + 1]
        if ch in b' \t\r\n\x00\x0c':
            i += 1; continue
        if ch == b'%':
            j = c.find(b'\n', i); i = n if j < 0 else j + 1; continue
        if ch == b'(':
            depth, j, buf = 1, i + 1, bytearray()
            while j < n and depth > 0:
                x = c[j:j + 1]
                if x == b'\\':
                    buf += c[j:j + 2]; j += 2; continue
                if x == b'(':
                    depth += 1
                elif x == b')':
                    depth -= 1
                    if depth == 0:
                        j += 1; break
                buf += x; j += 1
            toks.append(('s', unescape(bytes(buf))))
            i = j; continue
        if ch == b'<':
            if c[i:i + 2] == b'<<':
                toks.append(('o', '<<')); i += 2; continue
            j = c.find(b'>', i)
            h = re.sub(rb'[^0-9A-Fa-f]', b'', c[i + 1:j])
            if len(h) % 2:
                h += b'0'
            toks.append(('s', bytes.fromhex(h.decode())))
            i = j + 1; continue
        if ch == b'>':
            if c[i:i + 2] == b'>>':
                toks.append(('o', '>>')); i += 2; continue
            i += 1; continue
        if ch in b'[]':
            toks.append(('o', ch.decode())); i += 1; continue
        m = NUMRE.match(c, i)
        if m:
            w = m.group(1)
            if re.fullmatch(rb'[-+]?[0-9.]+', w):
                toks.append(('n', float(w)))
            elif w.startswith(b'/'):
                toks.append(('nm', w[1:].decode('latin-1')))
            else:
                toks.append(('o', w.decode('latin-1')))
            i = m.end(); continue
        i += 1
    return toks


def unescape(s):
    out = bytearray(); i = 0
    mp = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12, 0x28: 0x28, 0x29: 0x29, 0x5C: 0x5C}
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):
            nx = s[i + 1]
            if nx in mp:
                out.append(mp[nx]); i += 2; continue
            if 0x30 <= nx <= 0x37:
                oc = ''; j = i + 1
                while j < len(s) and len(oc) < 3 and 0x30 <= s[j] <= 0x37:
                    oc += chr(s[j]); j += 1
                out.append(int(oc, 8) & 0xFF); i = j; continue
            i += 2; continue
        out.append(c); i += 1
    return bytes(out)


def page_glyphs(pagechunk, fonts_map):
    m = re.search(rb'/Contents\s*\[(.*?)\]', pagechunk, re.S)
    cnums = [int(x) for x in re.findall(rb'(\d+)\s+0\s+R', m.group(1))] if m else []
    if not cnums:
        m2 = re.search(rb'/Contents\s+(\d+)\s+0\s+R', pagechunk)
        if m2:
            cnums = [int(m2.group(1))]
    content = b''.join(streams.get(c, b'') + b'\n' for c in cnums)
    toks = tokenize(content)
    fn = resolve_fonts(pagechunk)
    glyphs = []
    stack = []
    tm, tlm = [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0]
    cur, leading, fs = None, 0.0, 10.0
    for kind, val in toks:
        if kind in ('n', 's', 'nm'):
            stack.append((kind, val))
            continue
        if kind != 'o':
            continue
        op = val
        if op == 'Tf':
            for k, v in reversed(stack):
                if k == 'nm':
                    cur = v; break
            nums = [v for k, v in stack if k == 'n']
            if nums:
                fs = nums[-1]
        elif op == 'Tm':
            nums = [v for k, v in stack if k == 'n']
            if len(nums) >= 6:
                tm = nums[-6:]; tlm = list(tm)
        elif op in ('Td', 'TD'):
            nums = [v for k, v in stack if k == 'n']
            if len(nums) >= 2:
                tx, ty = nums[-2], nums[-1]
                tlm = [tlm[0], tlm[1], tlm[2], tlm[3],
                       tlm[4] + tx * tlm[0] + ty * tlm[2], tlm[5] + tx * tlm[1] + ty * tlm[3]]
                tm = list(tlm)
                if op == 'TD':
                    leading = -ty
        elif op == 'TL':
            nums = [v for k, v in stack if k == 'n']
            if nums:
                leading = nums[-1]
        elif op == 'T*':
            tlm = [tlm[0], tlm[1], tlm[2], tlm[3], tlm[4] - leading * tlm[2], tlm[5] - leading * tlm[3]]
            tm = list(tlm)
        elif op == 'BT':
            tm = [1, 0, 0, 1, 0, 0]; tlm = list(tm)
        elif op in ('Tj', 'TJ', "'", '"'):
            strs = [v for k, v in stack if k == 's']
            cmap = fonts.get(fonts_map.get(cur, -1), {})
            x, y = tm[4], tm[5]
            for s in strs:
                for b in s:
                    if b in cmap and cmap[b].strip():
                        glyphs.append((y, x, cmap[b]))
                    else:
                        glyphs.append((y, x, '\u25a1'))
                    x += fs * 0.5
            if op in ("'", '"'):
                tlm = [tlm[0], tlm[1], tlm[2], tlm[3], tlm[4] - leading * tlm[2], tlm[5] - leading * tlm[3]]
                tm = list(tlm)
        if op not in ('[', ']', '<<', '>>'):
            stack = []
    return glyphs


out = []
for pno, (num, chunk) in enumerate(pages, 1):
    glyphs = page_glyphs(chunk, resolve_fonts(chunk))
    # group into lines by rounded y
    glyphs.sort(key=lambda g: (-round(g[0], 1), g[1]))
    lines = []
    for y, x, ch in glyphs:
        if lines and abs(lines[-1][0] - y) < 2.5:
            lines[-1][1].append((x, ch))
        else:
            lines.append((y, [(x, ch)]))
    out.append(f'\n===== PAGE {pno}  (glyphs={len(glyphs)}) =====')
    for y, items in lines:
        items.sort(key=lambda t: t[0])
        txt = ''.join(c for _, c in items)
        out.append(f'[y={y:7.1f}] {txt}')
    nbox = sum(1 for g in glyphs if g[2] == '\u25a1')
    out.append(f'-- page {pno}: {len(glyphs)} glyphs, {nbox} undecodable')

txt = '\n'.join(out)
open('_pdf_text_skeleton.txt', 'w', encoding='utf-8').write(txt)
print(txt)
