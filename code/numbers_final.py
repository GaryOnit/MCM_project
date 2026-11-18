# -*- coding: utf-8 -*-
"""
numbers_final.py —— 从 data/ 的最终产物重算第五、六章需要的全部数字
（结果/结果/ 下的四张表仍是旧版，权威数据在 data/pred_*.csv 与 factor_table.csv）
"""
import collections
import csv
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data')


def rd(name, enc='utf-8-sig'):
    with open(os.path.join(D, name), encoding=enc) as f:
        return list(csv.DictReader(f))


def dkey(s):
    y, m, d = s.replace('-', '/').split('/')
    return (int(y), int(m), int(d))


def daily_stats(name):
    rows = rd(name)
    by_c = collections.defaultdict(dict)
    by_d = collections.defaultdict(int)
    for r in rows:
        c, d, v = r['分拣中心'], r['日期'].replace('-', '/'), int(float(r['货量']))
        by_c[c][d] = v
        by_d[d] += v
    tot = sum(by_d.values())
    cmean = {c: sum(v.values()) / len(v) for c, v in by_c.items()}
    top5 = sum(sorted(cmean.values(), reverse=True)[:5])
    ds = sorted(by_d.items(), key=lambda kv: dkey(kv[0]))
    print('\n== %s ==' % name)
    print('行 %d；合计 %s；日均 %.1f；最小日 %s=%s；最大日 %s=%s'
          % (len(rows), format(tot, ','), tot / 30, ds[0][0], format(ds[0][1], ','),
             ds[-1][0], format(ds[-1][1], ',')))
    print('Top5 占比 %.2f%%；最大中心 %.1f（%s）；最小中心 %.1f（%s）'
          % (top5 / (tot / 30) * 100, max(cmean.values()),
             max(cmean, key=cmean.get), min(cmean.values()),
             min(cmean, key=cmean.get)))
    print('日均<1000 的中心 %d 个；>30000 的 %d 个'
          % (sum(1 for v in cmean.values() if v < 1000),
             sum(1 for v in cmean.values() if v > 30000)))
    return tot, cmean, by_d


def hourly_stats(name, daily_name):
    rows = rd(name)
    by_d = collections.defaultdict(dict)
    for r in rd(daily_name):
        by_d[r['日期'].replace('-', '/')][r['分拣中心']] = int(float(r['货量']))
    hs = collections.defaultdict(int)
    byhour = collections.defaultdict(int)
    tot = 0
    for r in rows:
        k = (r['分拣中心'], r['日期'].replace('-', '/'))
        h = int(r['小时'])
        v = int(float(r['货量']))
        hs[k] += v
        byhour[h] += v
        tot += v
    diff = sum(abs(hs[k] - by_d[d][c]) for (c, d) in hs
               for _ in [0]) if False else 0
    diff = 0
    for (c, d), v in hs.items():
        diff += abs(v - by_d[d][c])
    print('\n== %s ==' % name)
    print('行 %d；合计 %s；Σ小时与日逐格绝对差 %d' % (len(rows), format(tot, ','), diff))
    sh = {h: byhour[h] / tot * 100 for h in range(24)}
    print('6 点 %.2f%%；21 点 %.2f%%；0 点 %.2f%%；三段 %.1f/%.1f/%.1f'
          % (sh[6], sh[21], sh[0], sum(sh[h] for h in range(8)),
             sum(sh[h] for h in range(8, 16)), sum(sh[h] for h in range(16, 24))))
    return tot


def factor_stats():
    rows = rd('factor_table.csv')
    f = [float(r['f']) for r in rows]
    diff = [float(r['差异率']) for r in rows]
    ch = [r for r in rows if abs(float(r['Δ线路货量'])) > 1e-6]
    tv1 = sum(int(float(r['表1合计'])) for r in rows)
    tv3 = sum(int(float(r['表3合计'])) for r in rows)
    print('\n== factor_table.csv ==')
    print('f 范围 [%.4f, %.4f]；中位 %.4f；有变化中心 %d；总量 %s vs %s（差 %d，比 %.7f）'
          % (min(f), max(f), st.median(f), len(ch), format(tv1, ','),
             format(tv3, ','), tv3 - tv1, tv3 / tv1))
    print('最大差异率 %.4f%%；最小 %.4f%%' % (max(diff) * 100, min(diff) * 100))
    ch.sort(key=lambda r: float(r['f']))
    print('18 行明细：')
    for r in ch:
        print("  ['%s', '%+.1f', '%+.1f', '%+.1f', '%.4f', '%.4f', '%+.2f'],"
              % (r['分拣中心'], float(r['Δ流入']), float(r['Δ流出']),
                 float(r['Δ线路货量']), float(r['f_raw']), float(r['f']),
                 float(r['差异率']) * 100))
    sc61 = [r for r in rows if r['分拣中心'] == 'SC61'][0]
    print('SC61: f_raw %.4f, 基线日均 %.1f' % (float(sc61['f_raw']), float(sc61['基线日均'])))


def backtest_stats():
    rows = rd('backtest_results.csv')
    order = ['A1_朴素均值', 'A2_加权移动平均21', 'A4_HoltWinters',
             'A9_分解式稳健WMA', 'A10_漂移A9']
    allr = {r['model']: r for r in rows if r['scope'] == 'ALL'}
    per = collections.defaultdict(list)
    for r in rows:
        if r['scope'] != 'ALL':
            per[r['model']].append(float(r['WAPE']))
    print('\n== backtest_results.csv ==')
    for m in order:
        r = allr[m]
        print('%-18s WAPE %.2f  WAPE_ex %.2f  MAPE %.2f  RMSE %.0f  中位 %.2f'
              % (m, float(r['WAPE']) * 100, float(r['WAPE_ex']) * 100,
                 float(r['MAPE']) * 100, float(r['RMSE']),
                 st.median(per[m]) * 100))


if __name__ == '__main__':
    daily_stats('pred_daily_base.csv')
    daily_stats('pred_daily.csv')
    hourly_stats('pred_hourly_base.csv', 'pred_daily_base.csv')
    hourly_stats('pred_hourly.csv', 'pred_daily.csv')
    factor_stats()
    backtest_stats()
