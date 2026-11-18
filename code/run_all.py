# -*- coding: utf-8 -*-
"""
run_all.py —— 一键跑通 Phase A（数据侧）+ Phase B（问题 1/2）

流程
----
  common     数据加载/清洗/体检 → data/*.csv + data_quality.md
  eda        EDA 指标 + 绘图数据包 + eda_report.md
  plot_figs  9 张 EDA 图（需要 matplotlib 的系统 python）
  backtest   四模型回测 → 选主模型 → model_choice.json
  p1_daily   问题 1 日预测 → 结果表1
  p1_hourly  问题 1 小时分配（含方案回测）→ 结果表2
  p2_adjust  问题 2 线路修正 → 结果表3、结果表4 + 下游接口
  plots      4 张 Phase B 图（需要 matplotlib）
  validate   54 项硬性校验

用法
----
    python code/run_all.py                 # 全跑
    python code/run_all.py --from backtest # 从某步开始
    python code/run_all.py --only p2_adjust,validate

说明
----
* 数据/建模脚本用当前解释器（3.12，带 pandas）；
* 绘图脚本自动寻找带 matplotlib 的 python（本机为 Python 3.8 的 `python`）；
* 每步独立子进程，失败立即停止并打印原因。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = os.path.join(ROOT, "code")
DATA = os.path.join(ROOT, "data")

STEPS = [
    ("common", "common.py", "pandas", "数据加载清洗、中间表、data_quality.md"),
    ("eda", "eda.py", "pandas", "EDA 指标、绘图数据包、eda_report.md"),
    ("plot_figs", "plot_figs.py", "mpl", "9 张 EDA 图（fig01~fig09）"),
    ("backtest", "backtest.py", "pandas", "四模型回测、选主模型"),
    ("p1_daily", "p1_daily.py", "pandas", "问题1 日预测 → 表1"),
    ("p1_hourly", "p1_hourly.py", "pandas", "问题1 小时分配 → 表2"),
    ("hourly_sens", "hourly_sens.py", "pandas", "小时占比口径敏感性（不改表1~4）"),
    ("p2_adjust", "p2_adjust.py", "pandas", "问题2 线路修正 → 表3/表4 + 接口"),
    ("plots", "plots.py", "mpl", "4 张 Phase B 图（fig10~fig13）"),
    ("validate", "validate.py", "pandas", "硬性校验（55 项）"),
    ("p3_staffing", "p3_staffing.py", "pandas", "问题3 班次人数（Hall 条件）→ 表5"),
    ("p4_roster", "p4_roster.py", "pandas", "问题4 SC60 逐人排班 → 表6"),
    ("validate_schedule", "validate_schedule.py", "pandas", "排班侧逐小时/逐人校验"),
]


# --------------------------------------------------------------------------- #
def force_utf8() -> None:
    for st in (sys.stdout, sys.stderr):
        try:
            if hasattr(st, "reconfigure"):
                st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def has_module(py: str, mod: str) -> bool:
    try:
        r = subprocess.run([py, "-c", "import %s" % mod],
                           capture_output=True, text=True, timeout=90)
        return r.returncode == 0
    except Exception:
        return False


def find_mpl_python() -> str:
    """找一个 import matplotlib 成功的解释器。"""
    cands = [os.environ.get("MPL_PYTHON"), shutil.which("python"),
             shutil.which("python3"), sys.executable]
    seen = set()
    for c in cands:
        if not c or c in seen or not os.path.exists(c):
            continue
        seen.add(c)
        if has_module(c, "matplotlib"):
            return c
    raise SystemExit("找不到带 matplotlib 的解释器；请设置环境变量 MPL_PYTHON 指向它。")


def run_step(name: str, script: str, kind: str, desc: str, mpl_py: str | None) -> float:
    py = mpl_py if kind == "mpl" else sys.executable
    path = os.path.join(CODE, script)
    if not os.path.exists(path):
        raise SystemExit("缺少脚本：%s" % path)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    print("\n" + "=" * 78)
    print(">>> %-10s %s" % (name, desc))
    print("    %s %s" % (py, os.path.join("code", script)))
    print("=" * 78)
    t0 = time.time()
    r = subprocess.run([py, path], cwd=ROOT, env=env)
    dt = time.time() - t0
    if r.returncode != 0:
        raise SystemExit("步骤 %s 失败（exit=%d），已停止。" % (name, r.returncode))
    print("<<< %-10s 完成，用时 %.1f 秒" % (name, dt))
    return dt


def summary() -> None:
    """打印关键产出摘要。"""
    print("\n" + "=" * 78)
    print("产出摘要")
    print("=" * 78)
    mc = os.path.join(DATA, "model_choice.json")
    if os.path.exists(mc):
        with open(mc, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        print("主模型      ：%s（k=%d，星期因子=%s，趋势因子=%s）" % (
            cfg.get("model"), cfg.get("k", -1), cfg.get("weekday"), cfg.get("trend")))
        print("验证期 WAPE ：%.2f%%（常态日 %.2f%%）" % (
            cfg.get("valid_WAPE", 0) * 100, cfg.get("valid_WAPE_ex", 0) * 100))
        h = cfg.get("hourly", {})
        if h:
            print("小时方案    ：%s（验证 WAPE %.2f%%）" % (h.get("name"), h.get("valid_WAPE", 0) * 100))

    for fn in ["backtest_results.csv", "hourly_backtest.csv", "factor_table.csv",
               "line_changes.csv", "pred_daily.csv", "pred_hourly.csv"]:
        p = os.path.join(DATA, fn)
        print("data/%-24s %s" % (fn, "OK" if os.path.exists(p) else "缺失"))

    # 结果表位置
    from common import result_dir  # noqa: E402
    d = result_dir(verbose=False)
    print("结果表目录  ：%s" % d)
    for i in [1, 2, 3, 4, 5, 6]:
        p = os.path.join(d, "结果表%d.csv" % i)
        print("  结果表%d.csv  %s" % (i, "OK" if os.path.exists(p) else "缺失"))
    figs = os.path.join(ROOT, "论文", "figs")
    n = len([x for x in os.listdir(figs) if x.endswith(".png")]) if os.path.isdir(figs) else 0
    print("论文配图    ：%d 张（论文/figs/）" % n)


def main() -> None:
    force_utf8()
    args = sys.argv[1:]
    only = None
    start = None
    if "--only" in args:
        only = set(args[args.index("--only") + 1].split(","))
    if "--from" in args:
        start = args[args.index("--from") + 1]

    steps = STEPS
    if start:
        names = [s[0] for s in STEPS]
        if start not in names:
            raise SystemExit("未知步骤 %s，可选：%s" % (start, ", ".join(names)))
        steps = STEPS[names.index(start):]
    if only:
        steps = [s for s in STEPS if s[0] in only]

    mpl_py = find_mpl_python() if any(s[2] == "mpl" for s in steps) else None
    print("[run_all] 工作目录：%s" % ROOT)
    print("[run_all] pandas 解释器：%s" % sys.executable)
    if mpl_py:
        print("[run_all] 绘图解释器：%s" % mpl_py)
    print("[run_all] 计划执行：%s" % " → ".join(s[0] for s in steps))

    t0 = time.time()
    total = 0.0
    for name, script, kind, desc in steps:
        total += run_step(name, script, kind, desc, mpl_py)
    print("\n[run_all] 全部步骤完成，总用时 %.1f 秒" % (time.time() - t0))
    summary()


if __name__ == "__main__":
    main()

