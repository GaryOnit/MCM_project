# -*- coding: utf-8 -*-
"""Minimal pure-python PDF text extractor (no third-party deps).
Parses objects, inflates FlateDecode streams, maps glyph codes via ToUnicode CMaps,
and reconstructs lines using text-positioning operators.
"""
import re, zlib, sys, io, codecs

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PDF = '物流网络分拣中心货量预测及人员排班.pdf'
raw = open(PDF, 'rb').read()


def find_objects(raw):
    objs = {}
    for m in re.finditer(rb'(\d+)\s+(\d+)\s+obj\b', raw):
        num = int(m.group(1))
        start = m.end()
        e = raw.find(b'endobj', start)
        if e < 0:
            e = len(raw)
        objs[num] = raw[start:e]
    return objs


objs = find_objects(raw)


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
        try:
            return zlib.decompressobj().decompress(data)
        except Exception:
            return None


# ---- collect stream payloads
streams = {}
for num, chunk in objs.items():
    if b'stream' in chunk:
        d = inflate(chunk)
        if d:
            streams[num] = d

print('objects:', len(objs), 'streams:', len(streams), file=sys.stderr)


# ---- ToUnicode CMap parsing
def parse_cmap(data):
    txt = data.decode('latin-1')
    cmap = {}

    def hex2uni(h):
        h = h.strip()
        try:
            b = bytes.fromhex(h)
        except ValueError:
            return ''
        # UTF-16BE
        if len(b) % 2:
            b = b + b'\x00'
        try:
            return b.decode('utf-16-be', 'ignore')
        except Exception:
            return ''

    for m in re.finditer(r'beginbfchar(.*?)endbfchar', txt, re.S):
        for mm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', m.group(1)):
            src = int(mm.group(1), 16)
            cmap[src] = hex2uni(mm.group(2))
    for m in re.finditer(r'beginbfrange(.*?)endbfrange', txt, re.S):
        body = m.group(1)
        for mm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', body):
            lo, hi, dst = int(mm.group(1), 16), int(mm.group(2), 16), mm.group(3)
            if len(dst) <= 4:
                base = int(dst, 16)
                for k in range(hi - lo + 1):
                    cmap[lo + k] = chr(base + k) if base + k < 0x110000 else ''
            else:
                pass
        for mm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]', body, re.S):
            lo = int(mm.group(1), 16)
            items = re.findall(r'<([0-9A-Fa-f]+)>', mm.group(3))
            for k, it in enumerate(items):
                cmap[lo + k] = hex2uni(it)
    return cmap


# ---- font: obj num -> (cmap, bytes_per_code)
def font_info(num):
    chunk = objs.get(num, b'')
    m = re.search(rb'/ToUnicode\s+(\d+)\s+0\s+R', chunk)
    cmap = {}
    if m:
        tu = int(m.group(1))
        if tu in streams:
            cmap = parse_cmap(streams[tu])
    two = False
    if re.search(rb'/Subtype\s*/Type0', chunk) or re.search(rb'/Type0', chunk):
        two = True
    return cmap, two


# ---- page: get content + font resource dict
pages = []
for num, chunk in objs.items():
    if re.search(rb'/Type\s*/Page\b', chunk) and not re.search(rb'/Type\s*/Pages\b', chunk):
        pages.append((num, chunk))
pages.sort()
print('pages:', len(pages), file=sys.stderr)


def refs(txt, key):
    out = []
    for m in re.finditer(key.encode() + rb'\s*\[(.*?)\]', txt, re.S):
        out += [int(x) for x in re.findall(rb'(\d+)\s+0\s+R', m.group(1))]
    m = re.search(key.encode() + rb'\s+(\d+)\s+0\s+R', txt)
    if m:
        out.append(int(m.group(1)))
    return out


def resolve_resources(pagechunk):
    # resources may be inline or a ref
    fonts = {}
    m = re.search(rb'/Resources\s+(\d+)\s+0\s+R', pagechunk)
    if m:
        res = objs.get(int(m.group(1)), b'')
    else:
        i = pagechunk.find(b'/Resources')
        res = pagechunk[i:] if i >= 0 else b''
    # font dict
    fm = re.search(rb'/Font\s*<<(.*?)>>', res, re.S)
    if fm:
        for mm in re.finditer(rb'/([A-Za-z0-9#+.\-]+)\s+(\d+)\s+0\s+R', fm.group(1)):
            fonts[mm.group(1).decode('latin-1')] = int(mm.group(2))
    else:
        fm2 = re.search(rb'/Font\s+(\d+)\s+0\s+R', res)
        if fm2:
            fd = objs.get(int(fm2.group(1)), b'')
            for mm in re.finditer(rb'/([A-Za-z0-9#+.\-]+)\s+(\d+)\s+0\s+R', fd):
                fonts[mm.group(1).decode('latin-1')] = int(mm.group(2))
    return fonts


# ---- content stream tokenizer / interpreter
NUM = r'-?\d+\.?\d*'


def unescape_literal(s):
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):
            n = s[i + 1]
            mp = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12,
                  0x28: 0x28, 0x29: 0x29, 0x5C: 0x5C}
            if n in mp:
                out.append(mp[n]); i += 2; continue
            if 0x30 <= n <= 0x37:
                oc = ''
                j = i + 1
                while j < len(s) and len(oc) < 3 and 0x30 <= s[j] <= 0x37:
                    oc += chr(s[j]); j += 1
                out.append(int(oc, 8) & 0xFF); i = j; continue
            if n in (10, 13):
                i += 2
                continue
            out.append(n); i += 2; continue
        out.append(c); i += 1
    return bytes(out)


def decode_str(b, cmap, two):
    if two or len(b) % 2 == 0 and two:
        pass
    out = []
    if two:
        for i in range(0, len(b) - 1, 2):
            code = (b[i] << 8) | b[i + 1]
            out.append(cmap.get(code, ''))
    else:
        for ch in b:
            if ch in cmap:
                out.append(cmap[ch])
            else:
                out.append(cmap.get(ch, chr(ch) if 32 <= ch < 127 else ''))
    return ''.join(out)


def extract_page_content_contents(pagechunk):
    cs = refs(pagechunk, '/Contents')
    data = b''
    for c in cs:
        if c in streams:
            data += streams[c] + b'\n'
    return data


def interpret(content, fonts):
    # tokenize: strings, hexstrings, arrays, names, numbers, operators
    toks = []
    i = 0
    n = len(content)
    while i < n:
        c = content[i:i + 1]
        if c in b' \t\r\n\x00\x0c':
            i += 1; continue
        if c == b'%':
            j = content.find(b'\n', i)
            i = n if j < 0 else j + 1; continue
        if c == b'(':
            depth = 1; j = i + 1; buf = bytearray()
            while j < n and depth > 0:
                ch = content[j:j + 1]
                if ch == b'\\':
                    buf += content[j:j + 2]; j += 2; continue
                if ch == b'(':
                    depth += 1
                elif ch == b')':
                    depth -= 1
                    if depth == 0:
                        j += 1; break
                buf += ch; j += 1
            toks.append(('str', unescape_literal(bytes(buf))))
            i = j; continue
        if c == b'<':
            if content[i:i + 2] == b'<<':
                toks.append(('op', '<<')); i += 2; continue
            j = content.find(b'>', i)
            h = re.sub(rb'[^0-9A-Fa-f]', b'', content[i + 1:j])
            if len(h) % 2:
                h += b'0'
            toks.append(('str', bytes.fromhex(h.decode())))
            i = j + 1; continue
        if c == b'>':
            if content[i:i + 2] == b'>>':
                toks.append(('op', '>>')); i += 2; continue
            i += 1; continue
        if c == b'[':
            toks.append(('op', '[')); i += 1; continue
        if c == b']':
            toks.append(('op', ']')); i += 1; continue
        if c == b'/':
            m = re.match(rb'/([^\s/\[\]<>(){}%]*)', content[i:])
            toks.append(('name', m.group(1).decode('latin-1')))
            i += m.end(); continue
        m = re.match(rb'(\d+\.?\d*|\.\d+|\+\d+\.?\d*|-\d+\.?\d*|[A-Za-z\'"*][A-Za-z0-9\'"*]*)', content[i:])
        if m:
            w = m.group(1)
            if re.fullmatch(rb'[-+0-9.]+', w):
                toks.append(('num', float(w)))
            else:
                toks.append(('op', w.decode('latin-1')))
            i += m.end(); continue
        i += 1
    return toks


def render(toks, fonts):
    lines = []
    cur = ''
    lasty = None
    curfont = None
    stack = []
    tm = [1, 0, 0, 1, 0, 0]
    tlm = [1, 0, 0, 1, 0, 0]
    leading = 0.0
    for kind, val in toks:
        if kind == 'num':
            stack.append(val)
        elif kind == 'name':
            stack.append(('name', val))
        elif kind == 'str':
            stack.append(('str', val))
        elif kind == 'op':
            op = val
            if op == 'Tf' and len(stack) >= 2:
                nm = stack[-2]
                if isinstance(nm, tuple) and nm[0] == 'name':
                    curfont = nm[1]
            elif op == 'Tm' and len(stack) >= 6:
                tm = [float(x) for x in stack[-6:]]
                tlm = list(tm)
            elif op in ('Td', 'TD') and len(stack) >= 2:
                tx, ty = float(stack[-2]), float(stack[-1])
                tlm = [tlm[0], tlm[1], tlm[2], tlm[3], tlm[4] + tx * tlm[0] + ty * tlm[2],
                       tlm[5] + tx * tlm[1] + ty * tlm[3]]
                tm = list(tlm)
                if op == 'TD':
                    leading = -ty
            elif op == 'TL' and stack:
                leading = float(stack[-1])
            elif op == 'T*':
                tlm = [tlm[0], tlm[1], tlm[2], tlm[3], tlm[4] - leading * tlm[2],
                       tlm[5] - leading * tlm[3]]
                tm = list(tlm)
            elif op in ('BT',):
                tm = [1, 0, 0, 1, 0, 0]; tlm = list(tm)
            elif op in ('Tj', "'", '"'):
                if stack and isinstance(stack[-1], tuple) and stack[-1][0] == 'str':
                    s = stack[-1][1]
                    cmap, two = font_info(fonts.get(curfont, -1)) if curfont else ({}, False)
                    text = decode_str(s, cmap, two)
                    if op in ("'", '"'):
                        cur += '\n'
                        lines.append(('pre', cur))
                        cur = ''
                    cur += text
            elif op == 'TJ':
                # gather until '['
                arr = []
                for it in reversed(stack):
                    if isinstance(it, tuple) and it[0] == 'str':
                        arr.append(it[1])
                    elif it == '[':
                        break
                arr.reverse()
                cmap, two = font_info(fonts.get(curfont, -1)) if curfont else ({}, False)
                for s in arr:
                    cur += decode_str(s, cmap, two)
            if op in ('Tj', 'TJ', "'", '"', 'Td', 'TD', 'T*', 'Tm', 'ET', 'BT', 'Tf', 'TL', 'Tc', 'Tw', 'Tz', 'Ts', 're', 'cm', 'q', 'Q', 'Do', 'gs', 'BDC', 'EMC'):
                stack = []
            elif op in ('j', 'J', 'w', 'd', 'i', 'M', 'ri', 'sh'):
                stack = []
            else:
                if op not in ('[', ']', '<<', '>>'):
                    stack = []
        if kind == 'op' and val == 'ET':
            if cur.strip():
                lines.append(('line', cur))
            cur = ''
    if cur.strip():
        lines.append(('line', cur))
    return lines


alltext = []
for pno, (num, chunk) in enumerate(pages, 1):
    fonts = resolve_resources(chunk)
    content = extract_page_content_contents(chunk)
    toks = interpret(content, fonts)
    lines = render(toks, fonts)
    alltext.append(f'\n===== PAGE {pno} =====')
    for k, v in lines:
        if k == 'pre':
            alltext.append(v)
        else:
            alltext.append(v)
    print(f'page {pno}: {len(content)} bytes, {len(fonts)} fonts, {len(lines)} lines', file=sys.stderr)

txt = '\n'.join(alltext)
open('_pdf_text_raw.txt', 'w', encoding='utf-8').write(txt)
print(txt[:3000])
