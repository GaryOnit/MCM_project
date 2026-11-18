# -*- coding: utf-8 -*-
import re, zlib, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
raw = open('物流网络分拣中心货量预测及人员排班.pdf','rb').read()
print('size', len(raw), 'header', raw[:9])
streams = re.findall(rb'stream\r?\n(.*?)endstream', raw, re.S)
print('streams', len(streams))
out = []
for s in streams:
    try:
        d = zlib.decompress(s)
    except Exception:
        continue
    if b'BT' not in d and b'Tj' not in d and b'TJ' not in d:
        continue
    txt = []
    for m in re.finditer(rb'\((?:[^()\\]|\\.)*\)|<([0-9A-Fa-f\s]+)>\s*Tj|TJ', d):
        pass
    # crude: collect literal strings
    parts = re.findall(rb'\(((?:[^()\\]|\\.){1,200})\)', d)
    for p in parts:
        txt.append(p)
    if txt:
        out.append(b' '.join(txt))
    if len(out) >= 3:
        break
joined = b'\n'.join(out)[:4000]
print('LITERAL_SAMPLE:')
print(joined.decode('latin-1', 'replace')[:1200])
# check for CID / ToUnicode
print('has ToUnicode:', b'ToUnicode' in raw, '| has Identity-H:', b'Identity-H' in raw, '| fonts:', len(re.findall(rb'/Type\s*/Font', raw)))
