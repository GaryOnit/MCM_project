# -*- coding: utf-8 -*-
"""calc_stats.py —— 统计第四~六章所需的表1~表4 数字（可重复运行）"""
import os
import csv
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, '结果', '结果')


def read_csv(path, enc='gbk'):
    with open(path, encoding=enc) as f:
        return list(csv.DictReader(f))


def load_daily(name):
    rows = read_csv(os.path.join(RES, name))
    by_center = collections.defaultdict(dict)
    by_date = collections.defaultdict(int)
    for r in rows:
        c, d, v = r['分拣中心'], r['日期'], int(float(r['货量']))
        by_center[c][d] = v
        by_date[d] += v
    return by_center, by_date


for name in ('结果表1.csv', '结果表3.csv'):
    bc, bd = load_daily(name)
    tot = sum(bd.values())
    cmean = {c: sum(v.values()) / len(v) for c, v in bc.items()}
    top5 = sorted(cmean.values(), reverse=True)[:5]
    print('%s 合计=%d 日均=%.1f 最小日=%d 最大日=%d'
          % (name, tot, tot / 30.0, min(bd.values()), max(bd.values())))
    print('   Top5 中心日均占比=%.2f%%  中心日均最大=%.1f 最小=%.1f'
          % (sum(top5) / (tot / 30) * 100, max(cmean.values()), min(cmean.values())))
    print('   日均<1000 的中心数=%d；日均>30000 的中心数=%d'
          % (sum(1 for v in cmean.values() if v < 1000),
             sum(1 for v in cmean.values() if v > 30000)))

for name_d, name_h in (('结果表1.csv', '结果表2.csv'),
                       ('结果表3.csv', '结果表4.csv')):
    bc, _ = load_daily(name_d)
    day = {(c, d): v for c, dv in bc.items() for d, v in dv.items()}
    hs = collections.defaultdict(int)
    byhour = collections.defaultdict(int)
    tot = 0
    for r in read_csv(os.path.join(RES, name_h)):
        k = (r['分拣中心'], r['日期'])
        h = int(r['小时'])
        v = int(float(r['货量']))
        hs[k] += v
        byhour[h] += v
        tot += v
    diff = sum(abs(hs[k] - v) for k, v in day.items())
    print('%s 合计=%d；Σ小时-日 逐格绝对差=%d；最大单格=%d'
          % (name_h, tot, diff, max(byhour.values())))
    prof = {h: byhour[h] / tot * 100 for h in range(24)}
    print('   全网小时占比：6点=%.2f%% 21点=%.2f%% 0点=%.2f%% 12点=%.2f%%'
          % (prof[6], prof[21], prof[0], prof[12]))
    print('   三段占比：0-8=%.1f%% 8-16=%.1f%% 16-24=%.1f%%'
          % (sum(prof[h] for h in range(0, 8)),
             sum(prof[h] for h in range(8, 16)),
             sum(prof[h] for h in range(16, 24))))

# 中心级小时占比的离散度（用 hour_share.csv）
path = os.path.join(ROOT, 'data', 'hour_share.csv')
rows = read_csv(path, 'utf-8-sig')
keys = list(rows[0].keys())[1:]
shares = {r[list(r.keys())[0]]: [float(r[k]) for k in keys] for r in rows}
import statistics as st
vals = [v for s in shares.values() for v in s]
print('\nhour_share: 中心=%d 小时=%d；单格占比 min=%.4f max=%.4f；'
      '每中心和=%.4f~%.4f'
      % (len(shares), len(keys), min(vals), max(vals),
         min(sum(s) for s in shares.values()),
         max(sum(s) for s in shares.values())))
peak = collections.Counter()
for c, s in shares.items():
    peak[max(range(24), key=lambda i: s[i])] += 1
print('   各中心高峰小时分布(前5):', peak.most_common(5))
