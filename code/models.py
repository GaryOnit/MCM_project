# -*- coding: utf-8 -*-
"""
models.py —— 预测模型库（问题 1/2 共用，被 backtest.py 与 p1_daily.py 导入）

提供 4 个模型：
    A1 朴素均值        naive_mean
    A2 加权移动平均    wma
    A4 Holt-Winters    holt_winters          （加法模型，周期 7，手写 numpy 递推）
    A9 分解式稳健 WMA  decomp               （水平 × 星期因子 × 趋势因子，主模型）

以及回测指标 WAPE / MAPE / RMSE、事件日剔除掩码、小时占比与最大余数取整。

设计原则
--------
* 所有模型只依赖「预测起点之前」的数据，禁止未来信息泄漏；
* 事件日（大促、节假日、IQR/3σ 异常）在估计「水平」与「星期因子」时剔除，
  但不从数据集中删除，预测值本身仍按因子放大；
* 取整用「最大余数法」，保证 Σ小时 = 日预测、Σ日 ≠ 被四舍五入破坏。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import common as C

CENTER, DATE, VOL, HOUR = C.CENTER, C.DATE, C.VOL, C.HOUR


# --------------------------------------------------------------------------- #
# 0. 掩码与基础工具
# --------------------------------------------------------------------------- #
def event_dates() -> pd.DatetimeIndex:
    """题设事件窗口内的日期（大促/节假日）。"""
    days = []
    for s, e in C.EVENT_WINDOWS.values():
        days.extend(pd.date_range(s, e, freq="D"))
    return pd.DatetimeIndex(sorted(set(days)))


def build_mask(daily: pd.DataFrame) -> pd.Series:
    """
    (中心,日期) → 是否应剔除（用于水平/因子估计）。
    规则：事件窗口内的日期，或该 (中心,日期) 被 IQR/3σ 标记为异常。
    """
    ev = event_dates()
    bad = daily["异常标记"].fillna("").astype(str) != ""
    in_ev = daily[DATE].isin(ev)
    return (bad | in_ev).rename("剔除")


def wide_matrix(daily: pd.DataFrame) -> pd.DataFrame:
    """中心 × 日期 的货量宽表（行=中心，列=日期）。"""
    m = daily.pivot_table(index=CENTER, columns=DATE, values=VOL, aggfunc="mean")
    return m.sort_index(key=lambda idx: idx.map(C.center_rank))


def mask_matrix(daily: pd.DataFrame) -> pd.DataFrame:
    """中心 × 日期 的剔除掩码宽表（True=剔除）。"""
    d = daily.copy()
    d["_m"] = build_mask(daily).to_numpy()
    m = d.pivot_table(index=CENTER, columns=DATE, values="_m", aggfunc="max")
    return m.reindex(wide_matrix(daily).index)[wide_matrix(daily).columns].fillna(False).astype(bool)


# --------------------------------------------------------------------------- #
# 1. 指标
# --------------------------------------------------------------------------- #
def metrics(y_true, y_pred) -> dict:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    err = p - y
    denom = np.maximum(y, 1.0)
    return {
        "WAPE": float(np.abs(err).sum() / max(np.abs(y).sum(), 1e-9)),
        "MAPE": float(np.mean(np.abs(err) / denom)),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "n": int(len(y)),
    }


# --------------------------------------------------------------------------- #
# 2. A1 朴素均值
# --------------------------------------------------------------------------- #
def naive_mean(train: pd.DataFrame) -> pd.Series:
    """全历史均值（含大促，故意保留朴素做法作为基线）。"""
    return train.mean(axis=1)


# --------------------------------------------------------------------------- #
# 3. A2 线性加权移动平均
# --------------------------------------------------------------------------- #
def wma(train: pd.DataFrame, k: int = 21) -> pd.Series:
    """最近 k 天的线性加权平均（越近权重越大），含大促日（朴素基线）。"""
    sub = train.iloc[:, -k:]
    w = np.arange(1, sub.shape[1] + 1, dtype=float)
    w = w / w.sum()
    return pd.Series(sub.to_numpy() @ w, index=sub.index)


# --------------------------------------------------------------------------- #
# 4. A4 Holt-Winters 加法模型（周期 7）
# --------------------------------------------------------------------------- #
def _hw_one(y: np.ndarray, horizon: int, period: int = 7,
            alpha: float = 0.25, beta: float = 0.02, gamma: float = 0.25) -> np.ndarray:
    """单序列 Holt-Winters 加法模型；返回未来 horizon 步预测。"""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2 * period + 1:
        return np.repeat(y.mean(), horizon)

    s1 = float(np.mean(y[:period]))
    s2 = float(np.mean(y[period:2 * period]))
    level = s2
    trend = (s2 - s1) / period
    season = [float(y[i] - s1) for i in range(period)]

    for t in range(period, n):
        idx = t % period
        pred = level + trend + season[idx]
        err = y[t] - pred
        new_level = level + trend + alpha * err
        new_trend = trend + alpha * beta * err
        season[idx] = season[idx] + gamma * (1 - alpha) * err
        level, trend = new_level, new_trend

    out = np.empty(horizon, dtype=float)
    for h in range(horizon):
        t = n + h
        out[h] = level + (h + 1) * trend + season[t % period]
    return out


def holt_winters(train: pd.DataFrame, horizon: int, **kw) -> pd.DataFrame:
    """对每个中心拟合 HW，返回 中心 × h 的预测矩阵。"""
    cols = ["h%d" % (i + 1) for i in range(horizon)]
    rows = {}
    for c in train.index:
        rows[c] = _hw_one(train.loc[c].to_numpy(), horizon, **kw)
    return pd.DataFrame.from_dict(rows, orient="index", columns=cols)


# --------------------------------------------------------------------------- #
# 5. A9 分解式稳健加权移动平均（主模型）
# --------------------------------------------------------------------------- #
def global_trend_slope(train: pd.DataFrame, mask: pd.DataFrame) -> float:
    """在全网日合计上拟合 log 线性趋势（剔除掩码日），返回每日对数斜率。"""
    keep = (~mask).sum(axis=0) > 0
    tot = train.where(~mask).sum(axis=0)
    ok = keep & (tot > 0)
    if ok.sum() < 10:
        return 0.0
    x = np.arange(train.shape[1], dtype=float)[ok.to_numpy()]
    y = np.log(tot.to_numpy()[ok.to_numpy()])
    slope = float(np.polyfit(x, y, 1)[0])
    return slope


def weekday_factors(train: pd.DataFrame, mask: pd.DataFrame,
                    shrink: float = 4.0) -> pd.DataFrame:
    """
    星期因子（7 列，行=中心，每行均值归一为 1）。

    * 单中心因子 = 该中心某星期几的非事件日均值 / 该中心非事件日总均值；
    * 与全网因子做 shrink 倍收缩：W = (n*W_c + m*W_g)/(n+m)，m=shrink；
    * 最后按行归一化，保证 Σ_dow W = 7（不改变水平）。
    """
    dates = train.columns
    dow = dates.dayofweek.to_numpy()
    clean = train.where(~mask)
    tot = clean.sum(axis=0)                      # 全网当日合计（NaN=全被剔除）
    valid_day = tot.notna()

    gl = []
    for k in range(7):
        sel = (dow == k) & valid_day.to_numpy()
        gl.append(float(tot.to_numpy()[sel].mean()) if sel.any() else np.nan)
    gl = np.array(gl)
    gl = gl / np.nanmean(gl)

    W = np.zeros((train.shape[0], 7))
    for i in range(train.shape[0]):
        vals = clean.iloc[i].to_numpy()
        row = np.full(7, np.nan)
        for k in range(7):
            sel = (dow == k) & ~np.isnan(vals)
            if sel.any():
                row[k] = float(np.mean(vals[sel]))
        overall = np.nanmean(row)
        if not np.isfinite(overall) or overall <= 0:
            W[i] = gl
            continue
        wc = row / overall
        n = np.array([((dow == k) & ~np.isnan(vals)).sum() for k in range(7)], dtype=float)
        num = n * np.nan_to_num(wc, nan=1.0) + shrink * gl
        W[i] = num / (n + shrink)
    W = np.where(np.isfinite(W), W, 1.0)
    W = W / W.mean(axis=1, keepdims=True)
    return pd.DataFrame(W, index=train.index, columns=list(range(7)))


def robust_level(train: pd.DataFrame, mask: pd.DataFrame, k: int = 28,
                 weight_mode: str = "linear") -> pd.Series:
    """
    水平项：最近 k 个自然日的加权稳健均值（逐中心剔除掩码日）。

    weight_mode='linear' → 越近权重越大（1..k 归一）；
                 'mean'   → 等权。
    """
    sub = train.iloc[:, -k:]
    msub = mask.iloc[:, -k:]
    vals = sub.where(~msub).to_numpy()          # NaN = 剔除
    w = np.arange(1, sub.shape[1] + 1, dtype=float)
    if weight_mode == "mean":
        w = np.ones_like(w)
    w = w / w.sum()

    out = np.empty(vals.shape[0])
    for i in range(vals.shape[0]):
        v = vals[i]
        ok = ~np.isnan(v)
        if not ok.any():
            out[i] = np.nanmean(train.iloc[i].to_numpy())
        else:
            ww = w[ok]
            out[i] = float(np.sum(v[ok] * ww) / ww.sum())
    return pd.Series(out, index=train.index)


def weekly_growth(train: pd.DataFrame, weeks: int = 8, clip: float = 0.015,
                  shrink: float = 0.5, min_points: int = 4,
                  r2_min: float = 0.15, cv_max: float = 0.40,
                  trim: float = 0.25):
    """
    周增长率 g_c（每周，小数），用于 A10 的漂移项 (1+g_c)^(h/7)。

    做法
    ----
    1. 取训练集最后 weeks×7 天，按 7 天一段切成 weeks 个「周合计」；
    2. 先剔除偏离中位数超过 trim（默认 ±25%）的周（大促周/假期周），
       剩下的点做 **Theil-Sen**（两两斜率的中位数）对数线性回归，抗单点污染；
    3. g_raw = exp(斜率) - 1，截断到 ±clip（默认 ±1.5%/周）；
    4. 若可用点 < min_points、R² < r2_min、或周合计变异系数 CV > cv_max，
       判为「拟合不稳」，把 g 向全网中位数收缩：g = (1-shrink)·g + shrink·g_net。

    返回
    ----
    (g: Series[中心], info: DataFrame[分拣中心, g_raw, g_clip, r2, cv, n_used, unstable, g_final, 是否收缩])
    """
    sub = train.iloc[:, -weeks * 7:]
    n = sub.shape[1]
    blocks, idx = [], []
    for i in range(0, n - 6, 7):
        blocks.append(sub.to_numpy()[:, i:i + 7].sum(axis=1))
        idx.append(i // 7)
    W = np.vstack(blocks).T                     # 中心 × 周数
    idx = np.asarray(idx, dtype=float)

    rows = []
    g_raw = np.full(len(train.index), np.nan)
    for i, c in enumerate(train.index):
        w = W[i].astype(float)
        med = float(np.median(w))
        if not np.isfinite(med) or med <= 0:
            g_raw[i] = 0.0
            rows.append((c, 0.0, 0.0, 0.0, 1.0, 0, True, 0.0, True))
            continue
        keep = np.abs(w / med - 1.0) <= trim
        k_idx = idx[keep]
        k_y = np.log(np.maximum(w[keep], 1e-9))
        n_used = int(keep.sum())
        cv = float(np.std(w) / med)

        if n_used >= 2:
            sl = [(k_y[j] - k_y[i]) / (k_idx[j] - k_idx[i])
                  for i in range(n_used) for j in range(i + 1, n_used)]
            slope_ts = float(np.median(sl))
        else:
            slope_ts = 0.0

        # OLS 的 R²（仅用于稳定性判据）
        if n_used >= 3 and np.std(k_y) > 1e-12:
            b, a = np.polyfit(k_idx, k_y, 1)
            pred = a + b * k_idx
            ss_res = float(((k_y - pred) ** 2).sum())
            ss_tot = float(((k_y - k_y.mean()) ** 2).sum())
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        else:
            r2 = 0.0

        g = float(np.exp(slope_ts) - 1.0)
        g_raw[i] = g
        unstable = bool(n_used < min_points or r2 < r2_min or cv > cv_max)
        rows.append((c, g, float(np.clip(g, -clip, clip)), float(r2), cv,
                     n_used, unstable, np.nan, False))

    info = pd.DataFrame(rows, columns=["分拣中心", "g_raw", "g_clip", "r2", "cv",
                                       "n_used", "unstable", "g_final", "是否收缩"])
    g_net = float(np.median(g_raw[np.isfinite(g_raw)])) if np.isfinite(g_raw).any() else 0.0
    g_net = float(np.clip(g_net, -clip, clip))

    g_final = info["g_clip"].to_numpy(dtype=float).copy()
    shrunk = info["unstable"].to_numpy()
    g_final[shrunk] = (1 - shrink) * g_final[shrunk] + shrink * g_net
    info["g_final"] = g_final
    info["是否收缩"] = shrunk
    info.attrs["g_net"] = g_net
    info.attrs["clip"] = clip
    return pd.Series(g_final, index=train.index, name="g"), info


def decomp(train: pd.DataFrame, mask: pd.DataFrame, horizon_dates: pd.DatetimeIndex,
           k: int = 28, shrink: float = 4.0, use_weekday: bool = True,
           use_trend: bool = True, horizon: int | None = None,
           growth: pd.Series | None = None) -> pd.DataFrame:
    """
    分解式稳健加权移动平均（A9 / A10）：

        A9  : ŷ(c,d) = L_c(k) × s_c(dow) × T(d)
        A10 : ŷ(c,d) = L_c(k) × s_c(dow) × T(d) × (1+g_c)^(h_d/7)

    h_d = 预测日距**预测起点**（horizon_dates[0]）的天数；growth 为每周增长率（小数）。
    growth=None 时退化为 A9（预测会呈精确 7 天周期）。
    """
    h = len(horizon_dates) if horizon is None else horizon
    L = robust_level(train, mask, k=k)
    W = weekday_factors(train, mask, shrink=shrink) if use_weekday else None
    slope = global_trend_slope(train, mask) if use_trend else 0.0

    origin = pd.Timestamp(horizon_dates[0])       # 预测起点（漂移基准）
    g_vec = None if growth is None else growth.reindex(train.index).fillna(0.0).to_numpy(dtype=float)

    anchor = train.columns[-1]                    # 历史最后一天（趋势因子基准）
    preds = np.zeros((train.shape[0], h), dtype=float)
    for j, d in enumerate(horizon_dates[:h]):
        step = (pd.Timestamp(d) - pd.Timestamp(anchor)).days
        trend = float(np.exp(slope * step)) if use_trend else 1.0
        w = W[d.dayofweek].to_numpy() if use_weekday else 1.0
        drift = 1.0 if g_vec is None else np.power(1.0 + g_vec, (pd.Timestamp(d) - origin).days / 7.0)
        preds[:, j] = L.to_numpy() * w * trend * drift

    preds = np.where(np.isfinite(preds), preds, 0.0)
    cols = ["h%d" % (i + 1) for i in range(h)]
    return pd.DataFrame(preds, index=train.index, columns=cols)


# --------------------------------------------------------------------------- #
# 6. 取整与小时拆分
# --------------------------------------------------------------------------- #
def largest_remainder(total: int, weights) -> np.ndarray:
    """
    最大余数法：把整数 total 按 weights 拆成整数，且 Σ 结果 = total。
    weights 会被归一化；负数权重按 0 处理。
    """
    w = np.asarray(weights, dtype=float).copy()
    w[~np.isfinite(w)] = 0.0
    w[w < 0] = 0.0
    s = w.sum()
    if s <= 0:
        w = np.ones_like(w)
        s = w.sum()
    raw = w / s * float(total)
    base = np.floor(raw).astype(int)
    rest = int(total) - int(base.sum())
    if rest > 0:
        frac = raw - base
        order = np.argsort(-frac)
        for i in order[:rest]:
            base[i] += 1
    elif rest < 0:                                  # 理论上不会发生
        order = np.argsort(base - raw)
        for i in order[:abs(rest)]:
            if base[i] > 0:
                base[i] -= 1
    return base


def hourly_share(hourly: pd.DataFrame, shrink: float = 0.0,
                 by_weekday: bool = False, days=None) -> pd.DataFrame | dict:
    """
    计算中心 × 24 的小时占比（每行和=1）。

    shrink: 向全网平均占比收缩的强度（0=不收缩，0.5=各占一半）
    by_weekday: True → 返回 {dow: DataFrame}；False → 单一 DataFrame
    """
    h = hourly
    if days is not None:
        h = h[h[DATE].isin(list(days))]

    net = (h.groupby(HOUR)[VOL].sum() / h.groupby(HOUR)[VOL].sum().sum()).to_numpy()
    net = np.where(net > 0, net, 1.0 / 24)

    def one(sub: pd.DataFrame) -> pd.DataFrame:
        tab = sub.pivot_table(index=CENTER, columns=HOUR, values=VOL, aggfunc="sum")
        tab = tab.reindex(columns=list(range(24))).fillna(0.0)
        m = tab.to_numpy()
        tot = m.sum(axis=1, keepdims=True)
        tot[tot <= 0] = 1.0
        share = m / tot
        if shrink > 0:
            share = (1 - shrink) * share + shrink * net[None, :]
        share = share / share.sum(axis=1, keepdims=True)
        return pd.DataFrame(share, index=tab.index, columns=list(range(24)))

    if not by_weekday:
        return one(h)

    out = {}
    for k in range(7):
        sub = h[h[DATE].dt.dayofweek == k]
        out[k] = one(sub) if len(sub) else one(h)
    return out


def split_daily_to_hourly(daily_pred: pd.DataFrame, share: pd.DataFrame | dict,
                          dates: list) -> pd.DataFrame:
    """
    日预测 → 小时预测（整数，且 Σ小时 = 当日日预测）。

    daily_pred: index=中心, columns=日期(str/date)，值=日预测整数
    share: DataFrame(中心×24) 或 {dow: DataFrame}
    返回长表：分拣中心, 日期, 小时, 货量
    """
    rows = []
    for d in dates:
        ts = pd.Timestamp(d)
        sh = share[ts.dayofweek] if isinstance(share, dict) else share
        for c in daily_pred.index:
            tot = int(round(float(daily_pred.loc[c, d])))
            w = sh.loc[c].to_numpy() if c in sh.index else np.ones(24) / 24
            vals = largest_remainder(tot, w)
            for hh in range(24):
                rows.append((c, d, hh, int(vals[hh])))
    return pd.DataFrame(rows, columns=[CENTER, DATE, HOUR, VOL])
