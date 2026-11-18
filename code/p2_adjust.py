# -*- coding: utf-8 -*-
"""
p2_adjust.py —— 问题 2：线路增减 → 中心级修正因子 → 结果表 3 / 表 4

一、输入
--------
附件3：过去 90 天 134 条有向线路的**日均货量** F（全网流入=流出=18977，平衡）
附件4：未来 30 天开通的 122 条线路（= 保留 120 + 新开 2）

二、线路变化的处理（假设见 data/assumptions.md）
----
* 关闭线 a→b（14 条）：a 的**发出总量不变**，该线货量按「a 其余仍在开通的发出线路」的货量
  占比重新分摊 → 这些目的地 b' 的流入增加、b 的流入减少；若 a 已无其他发出线路，
  则该货量在 a 的流出与 b 的流入两侧同时消失。
* 新开线 a→b（2 条）：流量按「a 的发出线路均值」与「b 的接收线路均值」的平均估计，
  同时加到 a 的流出与 b 的流入。
* 上述规则天然保持全网流入总量 = 流出总量（平衡不被破坏）。

三、中心修正因子
----------------
    ΔL_c = (Δ流入_c + Δ流出_c) / 2        # 线路承载的日均处理量变化
    f_raw = 1 + ΔL_c / V_c                # V_c = 表1 该中心 30 天日均
    f = clip(f_raw, 0.95, 1.05)           # 线路仅占中心货量 2.7%，超过 ±5% 不可信
    f ← f × λ，λ = Σ V_c / Σ(V_c·f)       # 全网总量守恒（与表1 一致）

四、输出
--------
结果表3.csv / 结果表4.csv
data/pred_daily.csv   （= 表3，1710 行，给排班 Worker）
data/pred_hourly.csv  （= 表4，41040 行，含 0 值小时）
data/factor_table.csv / line_changes.csv / factor_sensitivity.csv / factor_payload.json
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import models as M

F_CAP = 0.05          # 修正因子截断幅度（±5%）
CENTER, DATE, HOUR, VOL = C.CENTER, C.DATE, C.HOUR, C.VOL


# --------------------------------------------------------------------------- #
def build_flow(routes: pd.DataFrame):
    """附件3 → 线路字典与中心流入/流出汇总。"""
    F = {(a, b): float(v) for a, b, v in zip(routes["始发"], routes["到达"], routes[VOL])}
    out_lines, in_lines = {}, {}
    for (a, b), v in F.items():
        out_lines.setdefault(a, []).append((b, v))
        in_lines.setdefault(b, []).append((a, v))
    return F, out_lines, in_lines


def adjust(verbose: bool = True):
    routes = C.load_routes()          # 附件3，已带 在附件4 标记
    opens = C.load_route_open()       # 附件4
    F, out_lines, in_lines = build_flow(routes)

    p3 = set(F.keys())
    p4 = set(zip(opens["始发"], opens["到达"]))
    closed = sorted(p3 - p4)
    new = sorted(p4 - p3)

    centers = sorted(C.load_daily()[C.CENTER].unique().tolist(), key=C.center_rank)
    din = {c: 0.0 for c in centers}
    dout = {c: 0.0 for c in centers}
    notes = []

    # ---- 关闭线路 ----
    for a, b in closed:
        v = F[(a, b)]
        rest = [(b2, v2) for (b2, v2) in out_lines.get(a, []) if (a, b2) in p4]
        if rest:
            tot = sum(v2 for _, v2 in rest)
            din[b] -= v
            for b2, v2 in rest:
                din[b2] += v * v2 / tot
            notes.append((a, b, v, "关闭", "在 %s 其余 %d 条开通线路间按货量占比分摊" % (a, len(rest))))
        else:
            din[b] -= v
            dout[a] -= v
            notes.append((a, b, v, "关闭", "%s 无其他开通的发出线路，该货量在两侧消失" % a))

    # ---- 新开线路 ----
    for a, b in new:
        om = np.mean([v for _, v in out_lines[a]]) if out_lines.get(a) else np.nan
        im = np.mean([v for _, v in in_lines[b]]) if in_lines.get(b) else np.nan
        cand = [x for x in (om, im) if np.isfinite(x)]
        v_new = float(np.mean(cand)) if cand else float(np.mean(list(F.values())))
        dout[a] += v_new
        din[b] += v_new
        notes.append((a, b, v_new, "新开", "按两端中心同类线路均值估计（发出侧均值 %s，接收侧均值 %s）"
                      % ("%.2f" % om if np.isfinite(om) else "无", "%.2f" % im if np.isfinite(im) else "无")))

    # ---- 基线（表1 的 30 天日均）----
    base_path = os.path.join(C.DATA_DIR, "pred_daily_base.csv")
    if not os.path.exists(base_path):
        raise SystemExit("缺少 %s，请先运行 code/p1_daily.py" % base_path)
    base = pd.read_csv(base_path, encoding=C.ENC_OUT)
    base[C.CENTER] = base[C.CENTER].astype(str)
    v_base = base.groupby(C.CENTER)[VOL].mean()

    # ---- 因子 ----
    tab = pd.DataFrame({"分拣中心": centers})
    tab["流入_附件3"] = [sum(v for _, v in in_lines.get(c, [])) for c in centers]
    tab["流出_附件3"] = [sum(v for _, v in out_lines.get(c, [])) for c in centers]
    tab["Δ流入"] = [din.get(c, 0.0) for c in centers]
    tab["Δ流出"] = [dout.get(c, 0.0) for c in centers]
    tab["Δ线路货量"] = (tab["Δ流入"] + tab["Δ流出"]) / 2.0
    tab["基线日均"] = tab["分拣中心"].map(v_base)
    tab["f_raw"] = 1.0 + tab["Δ线路货量"] / tab["基线日均"]
    tab["f_capped"] = tab["f_raw"].clip(1 - F_CAP, 1 + F_CAP)
    n_cap = int((tab["f_capped"] != tab["f_raw"]).sum())

    lam = float((tab["基线日均"] * tab["f_capped"]).sum() / tab["基线日均"].sum())
    tab["f"] = tab["f_capped"] / lam
    tab = tab.sort_values("Δ线路货量", key=lambda s: s.abs(), ascending=False)

    if verbose:
        print("[p2] 关闭线路 %d 条，新开线路 %d 条，保留 %d 条" % (len(closed), len(new), len(p3 & p4)))
        print("[p2] 线路侧净变化：ΣΔ流入=%+.1f，ΣΔ流出=%+.1f（应相等）" % (tab["Δ流入"].sum(), tab["Δ流出"].sum()))
        print("[p2] f 范围 [%.6f, %.6f]，中位 %.6f；被 ±%.0f%% 截断的中心 %d 个；守恒系数 λ=%.8f" % (
            tab["f"].min(), tab["f"].max(), tab["f"].median(), F_CAP * 100, n_cap, lam))
        print("[p2] 修正幅度 |>0.1%%| 的中心数：%d / %d" % (
            int(((tab["f"] - 1).abs() > 0.001).sum()), len(tab)))

    return tab, notes, closed, new, lam, n_cap


# --------------------------------------------------------------------------- #
def load_share() -> pd.DataFrame | dict:
    """读取 p1_hourly 选定的小时占比（固定占比或按星期几）。"""
    cfg_path = os.path.join(C.DATA_DIR, "model_choice.json")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    h = cfg.get("hourly", {})
    if h.get("by_weekday"):
        p = os.path.join(C.DATA_DIR, "hour_share_by_weekday.csv")
        if os.path.exists(p):
            df = pd.read_csv(p, encoding=C.ENC_OUT)
            out = {}
            for k, g in df.groupby("星期几"):
                g = g.set_index(C.CENTER).drop(columns=["星期几"])
                g.columns = [int(c) for c in g.columns]
                out[int(k)] = g
            return out
    df = pd.read_csv(os.path.join(C.DATA_DIR, "hour_share.csv"),
                     encoding=C.ENC_OUT, index_col=0)
    df.columns = [int(c) for c in df.columns]
    return df


def main() -> None:
    C._force_utf8_stdout()
    tab, notes, closed, new, lam, n_cap = adjust()

    # ---- 表3 ----
    base = pd.read_csv(os.path.join(C.DATA_DIR, "pred_daily_base.csv"), encoding=C.ENC_OUT)
    base[C.CENTER] = base[C.CENTER].astype(str)
    fmap = dict(zip(tab["分拣中心"], tab["f"]))
    b = base.copy()
    b["f"] = b[C.CENTER].map(fmap).fillna(1.0)
    # 逐格乘因子并取整；再用「四舍五入后仍满足 |差异|≤5%」的上下界夹一次，
    # 保证小中心也不会因为取整把差异率顶到 5% 以上。
    raw = b[VOL].to_numpy(dtype=float) * b["f"].to_numpy(dtype=float)
    val = np.rint(raw)
    lo = np.ceil(b[VOL].to_numpy(dtype=float) * (1 - F_CAP))
    hi = np.floor(b[VOL].to_numpy(dtype=float) * (1 + F_CAP))
    val = np.clip(val, lo, hi)
    b["货量_表3"] = val.astype(np.int64)
    b["货量_表3"] = b["货量_表3"].clip(lower=1)

    t3 = b[[C.CENTER, DATE, "货量_表3"]].rename(columns={"货量_表3": VOL})
    C.write_result_table(t3, 3, [C.CENTER, DATE, VOL])
    t3.to_csv(os.path.join(C.DATA_DIR, "pred_daily.csv"), index=False, encoding=C.ENC_OUT)

    # ---- 表4 ----
    share = load_share()
    dates = list(dict.fromkeys(t3[DATE].tolist()))
    wide = t3.pivot(index=C.CENTER, columns=C.DATE, values=VOL)
    wide = wide.reindex(sorted(wide.index, key=C.center_rank))[dates]
    long4 = M.split_daily_to_hourly(wide, share, dates)
    long4[C.CENTER] = long4[C.CENTER].astype(str)
    C.write_result_table(long4, 4, [C.CENTER, DATE, HOUR, VOL])
    long4.to_csv(os.path.join(C.DATA_DIR, "pred_hourly.csv"), index=False, encoding=C.ENC_OUT)

    # ---- 明细表 ----
    tab2 = tab.copy()
    tab2["表1合计"] = tab2["分拣中心"].map(base.groupby(C.CENTER)[VOL].sum())
    tab2["表3合计"] = tab2["分拣中心"].map(t3.groupby(C.CENTER)[VOL].sum())
    tab2["差异率"] = tab2["表3合计"] / tab2["表1合计"] - 1
    tab2.to_csv(os.path.join(C.DATA_DIR, "factor_table.csv"), index=False, encoding=C.ENC_OUT)

    lc = pd.DataFrame(notes, columns=["始发", "到达", "线路货量", "变化", "处理说明"])
    lc = lc.sort_values(["变化", "线路货量"], ascending=[True, False])
    lc.to_csv(os.path.join(C.DATA_DIR, "line_changes.csv"), index=False, encoding=C.ENC_OUT)

    # 敏感性：f ≡ 1 的对照
    sens = pd.DataFrame({
        "口径": ["表1（f≡1）", "表3（线路修正）"],
        "全网合计": [int(base[VOL].sum()), int(t3[VOL].sum())],
        "日均": [float(base[VOL].mean()), float(t3[VOL].mean())],
        "单中心最大差异率": [0.0, float(tab2["差异率"].abs().max())],
        "有结构变化的中心数": [0, int((tab2["Δ线路货量"].abs() > 1e-9).sum())],
    })
    sens["相对表1"] = sens["全网合计"] / int(base[VOL].sum()) - 1
    sens.to_csv(os.path.join(C.DATA_DIR, "factor_sensitivity.csv"),
                index=False, encoding=C.ENC_OUT)

    # ---- 绘图 payload ----
    top = tab2.head(12)
    payload = {
        "f": [float(x) for x in tab2["f"].tolist()],
        "centers": [str(x) for x in tab2["分拣中心"].tolist()],
        "delta": [float(x) for x in tab2["Δ线路货量"].tolist()],
        "top_centers": [str(x) for x in top["分拣中心"].tolist()],
        "top_delta": [float(x) for x in top["Δ线路货量"].tolist()],
        "top_f": [float(x) for x in top["f"].tolist()],
        "lam": lam, "cap": F_CAP, "n_cap": n_cap,
        "closed": len(closed), "new": len(new),
        "net_delta": float(tab2["Δ线路货量"].sum()),
        "route_share": float(tab2["流入_附件3"].sum() /
                             (base[VOL].sum() / max(base[DATE].nunique(), 1))),
    }
    with open(os.path.join(C.DATA_DIR, "factor_payload.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    # ---- 控制台摘要 ----
    print("[p2] 表3 合计 %s（表1 %s，比值 %.8f）" % (
        format(int(t3[VOL].sum()), ","), format(int(base[VOL].sum()), ","),
        t3[VOL].sum() / base[VOL].sum()))
    print("[p2] 单中心最大差异率 %.4f%%，有结构变化的中心 %d / %d" % (
        tab2["差异率"].abs().max() * 100,
        int((tab2["Δ线路货量"].abs() > 1e-9).sum()), len(tab2)))
    print("[p2] 表4 行数 %d（应为 %d）" % (len(long4), 57 * 30 * 24))

    chk = long4.groupby([C.CENTER, DATE])[VOL].sum().rename("小时合计").reset_index()
    m = chk.merge(t3, on=[C.CENTER, DATE])
    print("[p2] 表4 日合计不符的 (中心,日期) 数：%d" % int((m["小时合计"] != m[VOL]).sum()))
    print("[p2] 已写出 表3、表4、data/pred_daily.csv、data/pred_hourly.csv、"
          "factor_table.csv、line_changes.csv、factor_sensitivity.csv")


if __name__ == "__main__":
    main()
