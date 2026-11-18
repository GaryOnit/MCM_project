# -*- coding: utf-8 -*-
"""final_numbers.py —— 排班定稿后，一次性算出第七~九章需回填的全部数字。"""
import collections
import csv
import json
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data')
R = os.path.join(ROOT, '结果', '结果')


def rd(path, enc='gbk'):
    with open(path, encoding=enc) as f:
        return list(csv.DictReader(f))


# ---------------- 表 5 ----------------
t5 = rd(os.path.join(R, '结果表5.csv'))
SH = ['00:00-08:00', '05:00-13:00', '08:00-16:00',
      '12:00-20:00', '14:22', '16:00-24:00']
SH = ['00:00-08:00', '05:00-13:00', '08:00-16:00',
      '12:00-20:00', '14:00-22:00', '16:00-24:00']
tot = form = temp = 0
by_d = collections.Counter()
by_d_temp = collections.Counter()
by_s = collections.Counter()
by_s_zero = collections.Counter()
by_cd = {}
for r in t5:
    f = int(float(r['正式工人数']))
    m = int(float(r['临时工人数']))
    tot += f + m
    form += f
    temp += m
    by_d[r['日期']] += f + m
    by_d_temp[r['日期']] += m
    by_s[r['班次']] += f + m
    by_cd[(r['分拣中心'], r['日期'])] = by_cd.get((r['分拣中心'], r['日期']), 0) + f + m
zero = collections.Counter()
for r in t5:
    if int(float(r['正式工人数'])) + int(float(r['临时工人数'])) == 0:
        zero[r['班次']] += 1

print('表5 行数 %d；总人天 %d（正式 %d %.2f%%，临时 %d %.2f%%）'
      % (len(t5), tot, form, form / tot * 100, temp, temp / tot * 100))
print('日均 %.1f；逐日 %d~%d；人天最多日 %s；临时工峰值 %s（%d）'
      % (tot / 30, min(by_d.values()), max(by_d.values()),
         max(by_d, key=by_d.get), max(by_d_temp, key=by_d_temp.get),
         max(by_d_temp.values())))
print('班次结构：')
for s in SH:
    print('  %s %6d 行 %6d 占比 %5.2f%% 为0的中心日 %4d 平均人数 %5.2f'
          % ('', 0, by_s[s], by_s[s] / tot * 100, zero[s], by_s[s] / 1710))

# 人效
dem = rd(os.path.join(D, 'pred_hourly.csv'), 'utf-8-sig')
D3 = collections.defaultdict(float)
for r in dem:
    D3[(r['分拣中心'], r['日期'])] += float(r['货量'])
eff_cd = []
daily_vol = collections.Counter()
for (c, d), n in by_cd.items():
    v = D3[(c, d)]
    daily_vol[d] += v
    if n:
        eff_cd.append(v / (8.0 * n))
eff_daily = [daily_vol[d] / (8.0 * by_d[d]) for d in by_d]
print('人效 全网 %.3f；日层面 %.3f ± %.3f；中心日 %.3f ± %.3f（min %.3f max %.3f，达25的 %d 个）'
      % (sum(daily_vol.values()) / (8.0 * tot), st.mean(eff_daily), st.stdev(eff_daily),
         st.mean(eff_cd), st.stdev(eff_cd), min(eff_cd), max(eff_cd),
         sum(1 for x in eff_cd if x >= 24.999)))
lb = sum(daily_vol.values()) / (8.0 * 25)
print('下界 %.0f；倍数 %.3f；gap %.2f%%' % (lb, tot / lb, (tot / lb - 1) * 100))

# ---------------- 表 6 ----------------
t6 = rd(os.path.join(R, '结果表6.csv'))
cnt = collections.Counter()
days = collections.defaultdict(set)
temp6 = collections.Counter()
for r in t6:
    emp = r['出勤员工']
    key = (r['日期'], r['班次'])
    cnt[key] += 1
    days[emp].add(r['日期'])
    if emp.startswith('临时'):
        temp6[r['日期']] += 1
formal_days = [len(v) for k, v in days.items() if k.startswith('正式')]
daily_person = collections.Counter()
for (d, s), n in cnt.items():
    daily_person[d] += n
print('\n表6 行数 %d；正式工 %d 人天、临时工 %d 人天'
      % (len(t6), sum(formal_days), len(t6) - sum(formal_days)))
print('出勤率 min/mean/max = %.2f%% / %.2f%% / %.2f%%'
      % (min(formal_days) / 30 * 100, st.mean(formal_days) / 30 * 100,
         max(formal_days) / 30 * 100))
# 连续出勤
def max_run(s):
    ds = sorted(s, key=lambda x: tuple(int(t) for t in x.split('/')))
    best = cur = 1
    prev = None
    for d in ds:
        if prev is None:
            cur = 1
        else:
            y, m, dd = (int(t) for t in d.split('/'))
            py, pm, pd = (int(t) for t in prev.split('/'))
            cur = cur + 1 if (d != prev and (m == pm and dd == pd + 1)) else 1
        best = max(best, cur)
        prev = d
    return best
runs = [max_run(v) for k, v in days.items() if k.startswith('正式')]
print('连续出勤最大 %d 天（200 人中）' % max(runs))
# 每天正式/临时人数
per_day_formal = collections.Counter()
for (d, s), n in cnt.items():
    pass
fd = collections.Counter()
td = collections.Counter()
for r in t6:
    if r['出勤员工'].startswith('正式'):
        fd[r['日期']] += 1
    else:
        td[r['日期']] += 1
print('每天正式工 %d~%d（均值 %.1f）；临时工 %d~%d（均值 %.1f）；临时高峰 %s（%d）'
      % (min(fd.values()), max(fd.values()), st.mean(list(fd.values())),
         min(td.values()), max(td.values()), st.mean(list(td.values())),
         max(td, key=td.get), max(td.values())))

# ---------------- 9.1 分中心误差 & 四段 WAPE ----------------
bp = json.load(open(os.path.join(D, 'backtest_payload.json'), encoding='utf-8'))
pw = bp.get('per_center_wape') or {}
model = 'A10' if 'A10' in str(list(pw.values())[0]) else None
print('\nper_center_wape 类型：', type(pw).__name__, '样例：', list(pw.items())[:2])
pred = bp['pred']
actual = bp['actual']
dates = bp['dates']
mkey = [k for k in pred if 'A10' in k]
if mkey:
    p = pred[mkey[0]]
    # 四段
    seg = [(0, 7), (7, 14), (14, 21), (21, 30)]
    for a, b in seg:
        num = sum(abs(pp - aa) for pp, aa in zip(p[a:b], actual[a:b]))
        den = sum(actual[a:b])
        print('段 %s~%s WAPE %.2f%%' % (dates[a], dates[b - 1], num / den * 100))
    num = sum(abs(pp - aa) for pp, aa in zip(p, actual))
    print('全期 WAPE %.2f%%' % (num / sum(actual) * 100))
    # 分中心
    kc = bp.get('per_center_wape') or {}
    if isinstance(kc, dict):
        sub = kc.get(mkey[0]) if mkey[0] in kc else kc
        if isinstance(sub, dict):
            items = sorted(sub.items(), key=lambda kv: -kv[1])
            print('最差 5 中心：', [(k, round(v * 100, 2)) for k, v in items[:5]])
            print('中位 WAPE：%.2f%%' % (st.median(sub.values()) * 100))

# ---------------- 9.3 / 表14 ----------------
fs = rd(os.path.join(D, 'factor_sensitivity.csv'), 'utf-8-sig')
print('\nfactor_sensitivity：')
for r in fs:
    print('  ', r)
hb = rd(os.path.join(D, 'hourly_backtest.csv'), 'utf-8-sig')
print('hourly_backtest：')
for r in hb:
    print('  %-28s 天数 %s WAPE %.2f%% MAPE %.2f%%'
          % (r['方案'], r['估计用天数'], float(r['WAPE']) * 100, float(r['MAPE']) * 100))
