# -*- coding: utf-8 -*-
"""Build gid->unicode maps from embedded TrueType subsets and test the
hypothesis that PDF character codes equal glyph ids."""
import re, zlib, struct, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
raw = open('物流网络分拣中心货量预测及人员排班.pdf', 'rb').read()
objs = {}
for m in re.finditer(rb'(\d+)\s+(\d+)\s+obj\b', raw):
    s = m.end(); e = raw.find(b'endobj', s); objs[int(m.group(1))] = raw[s:e]


def inf(c):
    i = c.find(b'stream'); j = i + 6
    while c[j] in (13, 10):
        j += 1
    k = c.rfind(b'endstream')
    try:
        return zlib.decompress(c[j:k])
    except Exception:
        return None


def ttf_tables(data):
    tag = data[:4]
    if len(data) < 12:
        return None
    numTables = struct.unpack('>H', data[4:6])[0]
    tabs = {}
    for i in range(numTables):
        off = 12 + 16 * i
        if off + 16 > len(data):
            break
        name = data[off:off + 4].decode('latin-1')
        o, l = struct.unpack('>II', data[off + 8:off + 16])
        tabs[name] = (o, l)
    return tabs


def parse_cmap(data, tabs):
    if 'cmap' not in tabs:
        return {}
    base = tabs['cmap'][0]
    n = struct.unpack('>H', data[base + 2:base + 4])[0]
    best = {}
    for i in range(n):
        rec = base + 4 + 8 * i
        pid, eid, off = struct.unpack('>HHI', data[rec:rec + 8])
        sub = base + off
        fmt = struct.unpack('>H', data[sub:sub + 2])[0]
        m = {}
        if fmt == 4:
            segX2 = struct.unpack('>H', data[sub + 6:sub + 8])[0]
            seg = segX2 // 2
            endC = sub + 14
            startC = endC + segX2 + 2
            idD = startC + segX2
            idR = idD + segX2
            for s in range(seg):
                e = struct.unpack('>H', data[endC + 2 * s:endC + 2 * s + 2])[0]
                st = struct.unpack('>H', data[startC + 2 * s:startC + 2 * s + 2])[0]
                delta = struct.unpack('>h', data[idD + 2 * s:idD + 2 * s + 2])[0]
                ro = struct.unpack('>H', data[idR + 2 * s:idR + 2 * s + 2])[0]
                if st == 0xFFFF:
                    continue
                for c in range(st, e + 1):
                    if ro == 0:
                        g = (c + delta) & 0xFFFF
                    else:
                        addr = idR + 2 * s + ro + 2 * (c - st)
                        if addr + 2 > len(data):
                            continue
                        g = struct.unpack('>H', data[addr:addr + 2])[0]
                        if g:
                            g = (g + delta) & 0xFFFF
                    if g:
                        m[c] = g
        elif fmt == 12:
            ngroups = struct.unpack('>I', data[sub + 12:sub + 16])[0]
            for k in range(ngroups):
                g = sub + 16 + 12 * k
                a, b, gg = struct.unpack('>III', data[g:g + 12])
                for c in range(a, min(b, a + 4000) + 1):
                    m[c] = gg + (c - a)
        elif fmt == 6:
            first = struct.unpack('>H', data[sub + 6:sub + 8])[0]
            cnt = struct.unpack('>H', data[sub + 8:sub + 10])[0]
            for k in range(cnt):
                g = struct.unpack('>H', data[sub + 10 + 2 * k:sub + 12 + 2 * k])[0]
                if g:
                    m[first + k] = g
        if len(m) > len(best):
            best = m
    return best


def num_glyphs(data, tabs):
    if 'maxp' not in tabs:
        return 0
    o = tabs['maxp'][0]
    return struct.unpack('>H', data[o + 4:o + 6])[0]


fonts = {}
for num, chunk in objs.items():
    if re.search(rb'/Type\s*/Font', chunk):
        bf = re.search(rb'/BaseFont\s*/([^\s/>]+)', chunk)
        fd = re.search(rb'/FontDescriptor\s+(\d+)\s+0\s+R', chunk)
        if not (bf and fd):
            continue
        desc = objs.get(int(fd.group(1)), b'')
        ff = re.search(rb'/FontFile2\s+(\d+)\s+0\s+R', desc)
        if not ff:
            continue
        data = inf(objs.get(int(ff.group(1)), b''))
        tabs = ttf_tables(data)
        cm = parse_cmap(data, tabs)
        ng = num_glyphs(data, tabs)
        inv = {}
        for u, g in cm.items():
            if g not in inv:
                inv[g] = chr(u)
        fonts[num] = dict(name=bf.group(1).decode('latin-1'), ng=ng, uni2gid=cm, gid2uni=inv)
        print(f"font obj {num}: {fonts[num]['name']:35s} numGlyphs={ng:4d} cmap={len(cm):4d}")

# hypothesis test: YaHei (obj 11) ToUnicode says 0x21->'2', 0x24->'年', 0x3c->'物'
y = fonts.get(11)
if y:
    for code, expect in [(0x21, '2'), (0x24, '年'), (0x3C, '物'), (0x25, '第')]:
        print(f'  code 0x{code:02x} expect {expect!r} -> gid2uni[{code}]={y["gid2uni"].get(code)!r}  '
              f'uni2gid[{expect!r}]={y["uni2gid"].get(ord(expect))}')

# check FangSong subs: does code range 33..255 look like gid range?
for n in (15, 19, 34):
    f = fonts.get(n)
    if f:
        gids = sorted(f['gid2uni'])[:12]
        print(f'font {n} {f["name"]}: min gid {gids[:6]} ... max {max(f["gid2uni"])}')
