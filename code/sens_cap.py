# -*- coding: utf-8 -*-
"""
sens_cap.py —— 问题三「正式工上限」灵敏度：把每中心 60 人放宽到 80 / 100 人
==========================================================================
调用 p3_staffing 的同一求解器（solve_day_backlog），只改 formal_cap，
逐 (中心, 日) 重解 1710 个小整数规划，统计总人天数与正式工/临时工结构。

输出：data/sens_formal_cap.csv
"""
import os
import sys
import csv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import p3_staffing as p3  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'sens_formal_cap.csv')


def main():
    demand, meta = p3.load_demand('pred')
    centers = meta['centers']
    print('需求：%d 中心 × %d 天，总货量 %.0f'
          % (meta['n_center'], p3.N_DAY, meta['total_volume']))

    lower = 0.0
    for c in centers:
        for k in range(p3.N_DAY):
            lower += sum(demand[(c, k)]) / (8.0 * 25.0)
    print('日总量工时下界 = %.0f' % lower)

    rows = []
    for cap in (60, 80, 100):
        tot = form = temp = 0
        bad = 0
        for c in centers:
            for k in range(p3.N_DAY):
                R = demand[(c, k)]
                x, y, _ = p3.solve_day_backlog(R, formal_cap=cap, do_balance=False)
                ok, _ = p3.verify_day_hall(R, x, y)
                if not ok:
                    bad += 1
                tot += sum(x) + sum(y)
                form += sum(x)
                temp += sum(y)
        rows.append({'正式工上限': cap, '总人天数': tot, '正式工人天': form,
                     '临时工人天': temp,
                     '正式工占比': round(form / tot * 100, 2),
                     '相对下界': round(tot / lower, 3),
                     '人效': round(meta['total_volume'] / (8.0 * tot), 2),
                     '未通过校验数': bad})
        print('cap=%3d → 总人天数 %6d（正式 %6d / 临时 %6d，正式占比 %.2f%%，'
              '下界倍数 %.3f，人效 %.2f，未通过 %d）'
              % (cap, tot, form, temp, form / tot * 100, tot / lower,
                 meta['total_volume'] / (8.0 * tot), bad))

    with open(OUT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('已写出：', OUT)


if __name__ == '__main__':
    main()
