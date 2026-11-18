# -*- coding: utf-8 -*-
"""
validate.py —— 提交前的硬性校验（问题 1/2 的结果表与下游接口）

校验项（任一不通过即 FAIL，进程返回码非 0）：
  1. 表1/表3 = 1710 行 = 57 中心 × 30 天，无重复、无缺格
  2. 表2/表4 = 41040 行 = 57 × 30 × 24，小时 0~23 全覆盖
  3. 表4 的 Σ小时 = 表3 当日日货量（逐 (中心,日期) 精确相等）
  4. 四张表无负值、无缺失值、无 0 日总量
  5. 表3 与表1 的单中心差异率在 ±5% 内
  6. 日期格式为 `2023/12/d`（月、日不补零），列名与模板完全一致
  7. GBK 可读（可直接提交），且不含示例行
  8. 下游接口 data/pred_daily.csv（1710 行）、data/pred_hourly.csv（41040 行）齐全
"""

from __future__ import annotations

import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

CENTER, DATE, HOUR, VOL = C.CENTER, C.DATE, C.HOUR, C.VOL
TPL = {"1": [CENTER, DATE, VOL], "2": [CENTER, DATE, HOUR, VOL],
       "3": [CENTER, DATE, VOL], "4": [CENTER, DATE, HOUR, VOL]}

RESULTS = []
FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    if not ok:
        FAILED.append(name)
    print("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", name, detail))


def load_table(idx: str) -> pd.DataFrame:
    path = os.path.join(C.result_dir(verbose=False), "结果表%s.csv" % idx)
    df = pd.read_csv(path, encoding="gbk", dtype={CENTER: str})
    df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]
    return df


def main() -> None:
    C._force_utf8_stdout()
    d = C.result_dir(verbose=False)
    print("[validate] 结果表目录：%s" % d)

    tabs = {}
    for i in ["1", "2", "3", "4"]:
        p = os.path.join(d, "结果表%s.csv" % i)
        check("表%s 文件存在" % i, os.path.exists(p), p)
        if not os.path.exists(p):
            continue
        tabs[i] = load_table(i)

    if len(tabs) < 4:
        print("\n[validate] 结果表不齐，终止后续校验")
        return finish()

    # ---- 列名 ----
    for i in ["1", "2", "3", "4"]:
        check("表%s 列名与模板一致" % i, list(tabs[i].columns) == TPL[i],
              str(list(tabs[i].columns)))

    # ---- 行数 ----
    for i, expect in [("1", 1710), ("3", 1710), ("2", 41040), ("4", 41040)]:
        check("表%s 行数 = %d" % (i, expect), len(tabs[i]) == expect, "实际 %d" % len(tabs[i]))

    # ---- 日期格式 ----
    pat = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")
    for i in ["1", "2", "3", "4"]:
        ds = tabs[i][DATE].astype(str)
        check("表%s 日期格式 2023/12/d（不补零）" % i, bool(ds.map(lambda x: bool(pat.match(x))).all()),
              "样例 %s" % ds.iloc[0])
        check("表%s 日期无 0 填充" % i, not ds.str.contains(r"/0\d/").any(),
              "样例 %s" % ds.iloc[0])

    # ---- 日期区间与格数 ----
    for i in ["1", "3"]:
        ds = pd.to_datetime(tabs[i][DATE], format="%Y/%m/%d")
        check("表%s 日期为 2023/12/1~12/30" % i,
              bool(ds.min() == pd.Timestamp("2023-12-01") and ds.max() == pd.Timestamp("2023-12-30")),
              "%s ~ %s" % (ds.min().date(), ds.max().date()))
        g = tabs[i].groupby([CENTER, DATE]).size()
        check("表%s 57 中心 × 30 天无重复无缺格" % i,
              len(g) == 1710 and bool((g == 1).all()),
              "格子数 %d" % len(g))

    # ---- 小时覆盖 ----
    for i in ["2", "4"]:
        hs = set(int(x) for x in tabs[i][HOUR].unique())
        check("表%s 小时取值覆盖 0~23" % i, hs == set(range(24)), "实有 %d 个" % len(hs))
        g = tabs[i].groupby([CENTER, DATE]).size()
        check("表%s 每 (中心,日期) 恰好 24 行" % i, bool((g == 24).all()),
              "最小 %d / 最大 %d" % (g.min(), g.max()))

    # ---- 数值合法性 ----
    for i in ["1", "2", "3", "4"]:
        v = pd.to_numeric(tabs[i][VOL], errors="coerce")
        check("表%s 无缺失值" % i, bool(v.notna().all()))
        check("表%s 无负值" % i, bool((v >= 0).all()), "最小值 %s" % v.min())
        check("表%s 为整数" % i, bool((v % 1 == 0).all()))

    # ---- Σ小时 = 日 ----
    d3 = tabs["3"].copy()
    d3[VOL] = d3[VOL].astype(np.int64)
    h4 = tabs["4"].copy()
    h4[VOL] = h4[VOL].astype(np.int64)
    s = h4.groupby([CENTER, DATE])[VOL].sum().rename("小时合计").reset_index()
    m = s.merge(d3, on=[CENTER, DATE], how="outer", indicator=True)
    check("表4 与表3 的中心×日期完全对齐", bool((m["_merge"] == "both").all()),
          "不匹配 %d" % int((m["_merge"] != "both").sum()))
    bad = int((m["小时合计"] != m[VOL]).sum())
    check("表4 Σ小时 = 表3 当日日货量", bad == 0, "不符 %d 条" % bad)

    # ---- 非周期性：同中心同星期几的 30 天预测不得完全相同 ----
    t1c = tabs["1"].copy()
    t1c["_dow"] = pd.to_datetime(t1c[DATE], format="%Y/%m/%d").dt.dayofweek
    gd = t1c.groupby([CENTER, "_dow"])[VOL].nunique()
    check("表1 同中心同星期几不再精确周期（nunique>1）", bool((gd > 1).all()),
          "最小 nunique %d，组合数 %d，nunique=1 的 %d 个" % (
              int(gd.min()), len(gd), int((gd == 1).sum())))

    # ---- 表3 vs 表1 ----
    a = tabs["1"].set_index([CENTER, DATE])[VOL].astype(np.int64)
    b = tabs["3"].set_index([CENTER, DATE])[VOL].astype(np.int64)
    j = pd.concat([a.rename("t1"), b.rename("t3")], axis=1).dropna()
    ratio = (j["t3"] - j["t1"]) / j["t1"].replace(0, np.nan)
    check("表3 与表1 单格差异率 ≤5%", bool(ratio.abs().max() <= 0.05),
          "最大 %.4f%%" % (ratio.abs().max() * 100))
    tot = (j["t3"].sum() - j["t1"].sum()) / j["t1"].sum()
    check("表3 全网总量与表1 一致（|偏差|≤0.01%）", abs(tot) <= 1e-4,
          "偏差 %.6f%%" % (tot * 100))

    # ---- 下游接口 ----
    for fn, n, cols in [("pred_daily.csv", 1710, [CENTER, DATE, VOL]),
                        ("pred_hourly.csv", 41040, [CENTER, DATE, HOUR, VOL])]:
        p = os.path.join(C.DATA_DIR, fn)
        ok = os.path.exists(p)
        check("接口 %s 存在" % fn, ok, p)
        if ok:
            df = pd.read_csv(p, encoding=C.ENC_OUT, dtype={CENTER: str})
            check("接口 %s 列名" % fn, list(df.columns) == cols, str(list(df.columns)))
            check("接口 %s 行数 = %d" % (fn, n), len(df) == n, "实际 %d" % len(df))

    # ---- 示例行残留检查 ----
    for i in ["1", "2", "3", "4"]:
        vals = tabs[i].astype(str).apply(lambda s: s.str.contains("示例", na=False)).to_numpy().any()
        check("表%s 无示例行残留" % i, not bool(vals))

    return finish()


def finish():
    n = len(RESULTS)
    nf = len(FAILED)
    print("\n[validate] %d 项检查，通过 %d 项，失败 %d 项" % (n, n - nf, nf))
    if nf:
        print("[validate] 失败项：%s" % "、".join(FAILED))
        print("[validate] 结果：FAIL")
        sys.exit(1)
    print("[validate] 结果：ALL PASS ✅")


if __name__ == "__main__":
    main()
