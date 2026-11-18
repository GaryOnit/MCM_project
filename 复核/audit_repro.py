# -*- coding: utf-8 -*-
"""F 部分：从零复现（在 复核/_work/repro/ 的隔离副本里跑，绝不改动交付目录）。

流程：
 1. 新建隔离目录，复制 code/（去 __pycache__）、附件/附件/、结果/结果/（仅作对比基线）；
 2. 依次运行 run_all.py --only common,backtest,p1_daily,p1_hourly,p2_adjust,validate
    再运行 p3_staffing.py --source pred、p4_roster.py、validate_schedule.py；
 3. 记录每步 returncode / 耗时 / stderr 尾部；
 4. 对比新生成结果表与交付表的 md5 与逐格差异。

用法：python 复核/audit_repro.py [--skip-run]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.join(HERE, "_work", "repro")
OUT = os.path.join(HERE, "_work", "out")
os.makedirs(OUT, exist_ok=True)
PY = sys.executable
BUF = io.StringIO()
RESULT = {}


def w(*a):
    print(*a, file=BUF)
    print(*a)


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def prepare():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    shutil.copytree(os.path.join(ROOT, "code"), os.path.join(WORK, "code"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(os.path.join(ROOT, "附件"), os.path.join(WORK, "附件"))
    shutil.copytree(os.path.join(ROOT, "结果"), os.path.join(WORK, "结果"))
    os.makedirs(os.path.join(WORK, "data"), exist_ok=True)
    w("[repro] 隔离目录：%s" % WORK)


def run(step, args, timeout=3600):
    t0 = time.time()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("MPL_PYTHON",):
        env.pop(k, None)
    try:
        r = subprocess.run([PY] + args, cwd=WORK, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        dt = time.time() - t0
        out, err = r.stdout or "", r.stderr or ""
        ok = r.returncode == 0
    except subprocess.TimeoutExpired as e:
        dt = time.time() - t0
        out, err, ok = "", "TIMEOUT", False
    w("\n=== %s  (%s)  exit=%s  %.1fs" % (step, " ".join(args), 0 if ok else 1, dt))
    if err.strip():
        w("--- stderr tail ---")
        w("\n".join(err.strip().splitlines()[-8:]))
    w("--- stdout tail ---")
    w("\n".join((out or "").strip().splitlines()[-12:]))
    RESULT[step] = {"args": args, "ok": ok, "seconds": round(dt, 1),
                    "stderr_tail": "\n".join(err.strip().splitlines()[-8:]) if err else ""}
    return ok


def compare():
    w("\n# 结果表对比（隔离副本 vs 交付目录 提交/ 与 结果/结果/）")
    cmp = {}
    import pandas as pd
    for i in range(1, 7):
        a = os.path.join(WORK, "结果", "结果", "结果表%d.csv" % i)
        if not os.path.exists(a):
            w("  表%d 未生成（缺失）" % i)
            cmp[i] = {"exists": False}
            continue
        da = pd.read_csv(a, encoding="gbk", dtype=str)
        rec = {"rows_new": len(da)}
        for label, d in (("提交", os.path.join(ROOT, "提交")),
                         ("结果", os.path.join(ROOT, "结果", "结果"))):
            b = os.path.join(d, "结果表%d.csv" % i)
            if not os.path.exists(b):
                rec[label] = {"exists": False}
                continue
            same = md5(a) == md5(b)
            db = pd.read_csv(b, encoding="gbk", dtype=str)
            eq = da.shape == db.shape and bool((da.values == db.values).all())
            n_diff = -1 if da.shape != db.shape else int((da.values != db.values).any(axis=1).sum())
            rec[label] = {"rows": len(db), "same_md5": bool(same), "same_cells": eq,
                          "diff_rows": n_diff}
            w("  表%d vs %-4s 行数 %d vs %d；md5同=%s；逐格同=%s；差异行=%d" % (
                i, label, len(da), len(db), same, eq, n_diff))
        cmp[i] = rec
    RESULT["compare"] = cmp
    return cmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-run", action="store_true")
    ap.add_argument("--tag", default="round1")
    args = ap.parse_args()
    w("# F. 从零复现（隔离副本）")
    w("解释器：%s" % PY)
    w("工作目录：%s" % ROOT)
    if not args.skip_run:
        prepare()
        run("run_all", ["code/run_all.py", "--only",
                        "common,backtest,p1_daily,p1_hourly,p2_adjust,validate"])
        run("p3_staffing", ["code/p3_staffing.py", "--source", "pred"])
        run("p4_roster", ["code/p4_roster.py"])
        run("validate_schedule", ["code/validate_schedule.py"])
    compare()
    # 静态检查
    w("\n# F18 静态检查")
    bad_abs, bad_enc, vendor = [], [], []
    for dirpath, _, files in os.walk(os.path.join(ROOT, "code")):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            s = open(p, encoding="utf-8", errors="replace").read()
            for i, line in enumerate(s.splitlines(), 1):
                if ("C:\\" in line or "D:\\" in line) and "http" not in line:
                    bad_abs.append("%s:%d: %s" % (fn, i, line.strip()[:100]))
                if "_vendor" in line:
                    vendor.append("%s:%d" % (fn, i))
            if "encoding='gbk'" in s or 'encoding="gbk"' in s:
                pass
    w("  硬编码绝对路径：%d 处" % len(bad_abs))
    for x in bad_abs[:10]:
        w("    " + x)
    w("  _vendor 依赖：%d 处" % len(vendor))
    RESULT["static"] = {"abs_paths": bad_abs, "vendor": vendor}
    with open(os.path.join(OUT, "audit_repro_%s.txt" % args.tag), "w", encoding="utf-8") as f:
        f.write(BUF.getvalue())
    with open(os.path.join(OUT, "audit_repro_%s.json" % args.tag), "w", encoding="utf-8") as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=1)
    print("OK ->", os.path.join(OUT, "audit_repro_%s.json" % args.tag))


if __name__ == "__main__":
    main()
