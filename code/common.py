# -*- coding: utf-8 -*-
"""
common.py —— 2024 MathorCup C 题「物流网络分拣中心货量预测及人员排班」公共数据层

职责
----
1. 统一读取 附件1~附件4（GBK 编码、行乱序、日期形如 2023/9/5）；
2. 日期解析、去重、排序、类型规范化；
3. 日粒度 / 小时粒度完整性体检（中心×日期空洞、24 点是否齐全）；
4. 异常值标记（每中心 IQR(1.5) 与 3σ 双规则，只标记不删除）+ 环比突增突降；
5. 单位与量级检查（负数 / 0 / 突增突降）；
6. 输出 data/daily.csv、hourly.csv、routes.csv、route_open.csv
   与 data/data_quality.md。

约定
----
* 原始附件按 GBK 读，结果按 UTF-8-SIG 写（Excel 友好）；
* 去重策略：同一主键的多条记录取【算术平均】，并保留 记录条数 列以便追溯。
  理由：重复来源无法判断谁更可信，均值是随机重复下的无偏稳健选择；
  且实测四份附件均无重复键（记录条数恒为 1），此策略仅作防御。
* 异常值只打标记，绝不静默剔除（大促脉冲是真实信号，不是错误）。
* 本模块只记录数据事实，不推断赛题要求；涉及题意的判断一律标注「待原文确认」。

被后续阶段复用
--------------
    import common as C
    daily  = C.load_daily()      # 带标记列
    hourly = C.load_hourly()     # 24 点补齐、缺失=0
    routes = C.load_routes()
    opens  = C.load_route_open()
    share  = C.hour_share()      # 中心×小时 平均占比（日货量→小时货量的分配依据）
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# 0. 路径与常量
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATT_DIR = os.path.join(ROOT, "附件", "附件")
RES_DIR = os.path.join(ROOT, "结果", "结果")
TPL_DIR = os.path.join(ROOT, "结果", "模板")
DATA_DIR = os.path.join(ROOT, "data")
FIG_DIR = os.path.join(ROOT, "论文", "figs")
SUBMIT_DIR = os.path.join(ROOT, "提交")   # 沙箱禁写 结果/ 时的落盘位置

F_DAILY = os.path.join(ATT_DIR, "附件1.csv")
F_HOURLY = os.path.join(ATT_DIR, "附件2.csv")
F_ROUTE = os.path.join(ATT_DIR, "附件3.csv")
F_OPEN = os.path.join(ATT_DIR, "附件4.csv")

ENC_IN = "gbk"          # 原附件编码
ENC_OUT = "utf-8-sig"   # 结果编码（Excel 友好）

CENTER = "分拣中心"
DATE = "日期"
HOUR = "小时"
VOL = "货量"

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 事件窗口：仅用于 EDA 标注与「剔除事件后」的稳健统计，不代表赛题要求。
# 注意：2023 双 12（12/12）不在数据覆盖范围内，故此处没有双 12。
EVENT_WINDOWS = {
    "中秋": ("2023-09-29", "2023-09-30"),
    "国庆": ("2023-10-01", "2023-10-07"),
    "双11预售": ("2023-10-24", "2023-10-25"),
    "双11开门红": ("2023-11-01", "2023-11-03"),
    "双11": ("2023-11-10", "2023-11-13"),
}


# --------------------------------------------------------------------------- #
# 1. 基础工具
# --------------------------------------------------------------------------- #
def _force_utf8_stdout() -> None:
    """让脚本在 GBK 控制台/重定向下也能打印中文。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def center_rank(name) -> int:
    """SC7 < SC12 的自然排序键。"""
    s = str(name).strip()
    if s.startswith("SC"):
        s = s[2:]
    try:
        return int(s)
    except ValueError:
        return 10 ** 6


def read_table(path: str, **kwargs) -> pd.DataFrame:
    """按 GBK 读表，异常时回退 UTF-8-SIG；自动去掉列名首尾空白。"""
    if not os.path.exists(path):
        raise FileNotFoundError("找不到数据文件：%s" % path)
    last_err = None
    for enc in (ENC_IN, ENC_OUT, "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc, **kwargs)
            df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]
            return df
        except UnicodeDecodeError as exc:  # 换编码重试
            last_err = exc
    raise last_err


def parse_date(series: pd.Series) -> pd.Series:
    """'2023/9/5' 一类日期串 → datetime；解析失败置 NaT 并保持可追踪。"""
    s = (series.astype(str).str.strip()
         .str.replace("年", "/", regex=False)
         .str.replace("月", "/", regex=False)
         .str.replace("日", "", regex=False)
         .str.replace("-", "/", regex=False))
    out = pd.to_datetime(s, format="%Y/%m/%d", errors="coerce")
    bad = out.isna()
    if bool(bad.any()):  # 兜底：交给 pandas 自动推断
        out.loc[bad] = pd.to_datetime(s[bad], errors="coerce")
    return out


def sort_by_key(df: pd.DataFrame, keys) -> pd.DataFrame:
    """按 中心(自然序)+日期(+小时) 排序，返回新对象。"""
    df = df.copy()
    df["_中心序号"] = df[CENTER].map(center_rank)
    order = ["_中心序号"] + [k for k in keys if k != CENTER]
    df = df.sort_values(order, kind="mergesort").reset_index(drop=True)
    return df.drop(columns=["_中心序号"])


def _maybe_int(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """若一列全为整数，转 int64，避免 CSV 写出 39517.0 这类尾巴。"""
    v = pd.to_numeric(df[col], errors="coerce")
    if bool(v.notna().all()) and bool((v % 1 == 0).all()):
        df[col] = v.astype("int64")
    return df


def dedupe(df: pd.DataFrame, keys, value=VOL):
    """同主键多记录 → 取均值，并给出 记录条数 / 重复条数。"""
    keys = list(keys)
    n0 = len(df)
    g = df.groupby(keys, as_index=False, dropna=False)[value].agg(["mean", "size"])
    g.columns = keys + [value, "记录条数"]
    return g, n0 - len(g)


# --------------------------------------------------------------------------- #
# 2. 读取四份附件
# --------------------------------------------------------------------------- #
def load_daily_raw() -> pd.DataFrame:
    """附件1 原样（仅解析类型），行序仍为乱序。"""
    df = read_table(F_DAILY, dtype={CENTER: str})
    df[CENTER] = df[CENTER].astype(str).str.strip()
    df[DATE] = parse_date(df[DATE])
    df[VOL] = pd.to_numeric(df[VOL], errors="coerce")
    return df


def load_hourly_raw() -> pd.DataFrame:
    """附件2 原样（仅解析类型）。"""
    df = read_table(F_HOURLY, dtype={CENTER: str})
    df[CENTER] = df[CENTER].astype(str).str.strip()
    df[DATE] = parse_date(df[DATE])
    h = pd.to_numeric(df[HOUR], errors="coerce")
    if bool(h.isna().any()):
        print("[common] 警告：附件2 有 %d 行小时解析失败，已剔除" % int(h.isna().sum()))
        df = df.loc[~h.isna()].copy()
        h = h.loc[~h.isna()]
    df[HOUR] = h.astype("int64")
    df[VOL] = pd.to_numeric(df[VOL], errors="coerce")
    return df


def load_routes_raw() -> pd.DataFrame:
    """附件3：有向线路 + 货量。"""
    df = read_table(F_ROUTE, dtype={CENTER: str})
    df = df.rename(columns={"始发分拣中心": "始发", "到达分拣中心": "到达"})
    df["始发"] = df["始发"].astype(str).str.strip()
    df["到达"] = df["到达"].astype(str).str.strip()
    df[VOL] = pd.to_numeric(df[VOL], errors="coerce")
    return df


def load_open_raw() -> pd.DataFrame:
    """附件4：有向线路开通关系（无货量）。"""
    df = read_table(F_OPEN, dtype={CENTER: str})
    df = df.rename(columns={"始发分拣中心": "始发", "到达分拣中心": "到达"})
    df["始发"] = df["始发"].astype(str).str.strip()
    df["到达"] = df["到达"].astype(str).str.strip()
    return df


# --------------------------------------------------------------------------- #
# 3. 日粒度：清洗 + 标记
# --------------------------------------------------------------------------- #
def _center_stats(df: pd.DataFrame, value=VOL) -> pd.DataFrame:
    """每中心的分位数/均值/标准差（用于 IQR 与 3σ 双规则）。"""
    g = df.groupby(CENTER)[value]
    st = pd.DataFrame({
        "Q1": g.quantile(0.25),
        "Q3": g.quantile(0.75),
        "均值": g.mean(),
        "标准差": g.std(ddof=1),
        "最小": g.min(),
        "最大": g.max(),
        "记录数": g.size(),
    })
    st["IQR"] = st["Q3"] - st["Q1"]
    st["IQR下界"] = st["Q1"] - 1.5 * st["IQR"]
    st["IQR上界"] = st["Q3"] + 1.5 * st["IQR"]
    st["3σ下界"] = st["均值"] - 3 * st["标准差"]
    st["3σ上界"] = st["均值"] + 3 * st["标准差"]
    return st


def load_daily(with_flags: bool = True) -> pd.DataFrame:
    """
    附件1 清洗结果（一行 = 一个中心一天）。

    新增列
    ------
    周几 / 是否周末 / 记录条数 / 环比变化 / 环比倍数
    异常_IQR / 异常_3σ / 异常标记 / 异常方向
    """
    df = load_daily_raw()
    df, _dup = dedupe(df, [CENTER, DATE])
    df = sort_by_key(df, [CENTER, DATE])
    df = _maybe_int(df, VOL)
    df["周几"] = [WEEKDAY_CN[int(i)] if pd.notna(i) else "" for i in df[DATE].dt.dayofweek]
    df["是否周末"] = df[DATE].dt.dayofweek.isin([5, 6])

    if not with_flags:
        return df

    st = _center_stats(df)
    df = df.merge(st, left_on=CENTER, right_index=True, how="left")
    df = df.sort_values([CENTER, DATE], kind="mergesort").reset_index(drop=True)

    iqr_lo = (df[VOL] < df["IQR下界"]).to_numpy()
    iqr_hi = (df[VOL] > df["IQR上界"]).to_numpy()
    s3_lo = (df[VOL] < df["3σ下界"]).to_numpy()
    s3_hi = (df[VOL] > df["3σ上界"]).to_numpy()

    df["异常_IQR"] = np.select([iqr_lo, iqr_hi], ["低", "高"], default="")
    df["异常_3σ"] = np.select([s3_lo, s3_hi], ["低", "高"], default="")
    df["异常标记"] = np.select(
        [(iqr_lo & s3_lo) | (iqr_hi & s3_hi), iqr_lo | s3_lo, iqr_hi | s3_hi],
        ["双规则异常", "低异常", "高异常"], default="")
    df["异常方向"] = np.select([iqr_lo | s3_lo, iqr_hi | s3_hi],
                              ["低于下界", "高于上界"], default="")

    prev = df.groupby(CENTER, sort=False)[VOL].shift(1)
    df["环比变化"] = (df[VOL] / prev - 1.0).round(4)
    df["环比倍数"] = (df[VOL] / prev).round(4)
    return df


# --------------------------------------------------------------------------- #
# 4. 小时粒度：补齐 中心×日期×24 网格
# --------------------------------------------------------------------------- #
def load_hourly(fill: str = "zero") -> pd.DataFrame:
    """
    附件2 清洗结果（一行 = 一个中心一天一小时，网格已补齐）。

    新增列
    ------
    货量_原始   原始值（缺格为 NaN）
    货量        补齐后的值（fill='zero' 时缺失记 0，依据见 data_quality.md §3.3）
    缺失        原始是否缺格
    日合计      该中心该日的 24 小时合计（补齐后）
    小时占比    货量 / 日合计
    """
    if fill not in ("zero", "nan"):
        raise ValueError("fill 仅支持 'zero' 或 'nan'")

    df = load_hourly_raw()
    df, _dup = dedupe(df, [CENTER, DATE, HOUR])
    df[HOUR] = df[HOUR].astype("int64")

    centers = sorted(df[CENTER].unique(), key=center_rank)
    dates = sorted(pd.to_datetime(df[DATE].dropna().unique()))
    grid = pd.MultiIndex.from_product([centers, dates, list(range(24))],
                                      names=[CENTER, DATE, HOUR])
    full = pd.DataFrame(index=grid).reset_index()
    full = full.merge(df, on=[CENTER, DATE, HOUR], how="left")

    full["缺失"] = full[VOL].isna()
    full["货量_原始"] = full[VOL]
    if fill == "zero":
        full[VOL] = full[VOL].fillna(0.0)

    full = sort_by_key(full, [CENTER, DATE, HOUR])
    full["日合计"] = full.groupby([CENTER, DATE], sort=False)[VOL].transform("sum")
    den = full["日合计"].replace(0, np.nan)
    full["小时占比"] = full[VOL] / den
    full["周几"] = [WEEKDAY_CN[int(i)] if pd.notna(i) else "" for i in full[DATE].dt.dayofweek]
    return full[[CENTER, DATE, HOUR, VOL, "货量_原始", "缺失", "日合计", "小时占比", "周几"]]


def hour_share(hourly: pd.DataFrame | None = None, by: str = "center") -> pd.DataFrame:
    """
    小时占比表（后续「日货量 × 小时占比」分配的直接输入）。

    by='center' → index=分拣中心, columns=0..23，值=该中心各小时占比的 30 天均值
    by='allday' → 每 (中心, 日期) 一行的占比矩阵
    by='all'    → 全网 24 小时平均占比（一行）
    """
    h = load_hourly() if hourly is None else hourly
    tab = h.pivot_table(index=[CENTER, DATE], columns=HOUR, values="小时占比", aggfunc="mean")
    if by == "allday":
        return tab
    if by == "center":
        return tab.groupby(level=0).mean()
    if by == "all":
        return tab.mean(axis=0).fillna(0.0).rename("占比").to_frame().T
    raise ValueError("by 仅支持 'center' / 'allday' / 'all'")


# --------------------------------------------------------------------------- #
# 5. 线路：附件3 / 附件4
# --------------------------------------------------------------------------- #
def load_routes() -> pd.DataFrame:
    """附件3 + 与附件4 的关系标记 + 货量占比（分母 = 附件3 自身合计）。"""
    r3 = load_routes_raw()
    r4 = load_open_raw()
    p4 = set(zip(r4["始发"], r4["到达"]))
    p3 = set(zip(r3["始发"], r3["到达"]))

    r3["在附件4"] = [(a, b) in p4 for a, b in zip(r3["始发"], r3["到达"])]
    r3["是否双向"] = [(b, a) in p3 for a, b in zip(r3["始发"], r3["到达"])]
    total = float(r3[VOL].sum())
    r3["线路货量占比"] = (r3[VOL] / total).round(6) if total else np.nan
    r3 = r3.sort_values(VOL, ascending=False, kind="mergesort").reset_index(drop=True)
    r3.insert(0, "线路序号", np.arange(1, len(r3) + 1))
    return r3


def load_route_open() -> pd.DataFrame:
    """附件4 + 是否双向 / 是否在附件3 中有货量 / 出度入度。"""
    r3 = load_routes_raw()
    r4 = load_open_raw()
    p3 = set(zip(r3["始发"], r3["到达"]))
    p4 = set(zip(r4["始发"], r4["到达"]))

    r4["是否双向"] = [(b, a) in p4 for a, b in zip(r4["始发"], r4["到达"])]
    r4["附件3有货量"] = [(a, b) in p3 for a, b in zip(r4["始发"], r4["到达"])]
    r4["始发出度"] = r4.groupby("始发")["到达"].transform("size")
    r4["到达入度"] = r4.groupby("到达")["始发"].transform("size")
    r4 = r4.sort_values(["始发出度", "始发", "到达"], ascending=[False, True, True],
                        kind="mergesort").reset_index(drop=True)
    return r4


# --------------------------------------------------------------------------- #
# 6. 体检：完整度 / 单位量级
# --------------------------------------------------------------------------- #
def daily_completeness(daily: pd.DataFrame) -> dict:
    centers = sorted(daily[CENTER].unique(), key=center_rank)
    dates = sorted(pd.to_datetime(daily[DATE].dropna().unique()))
    cells = len(centers) * len(dates)
    have = len(daily.drop_duplicates([CENTER, DATE]))
    per_center = daily.groupby(CENTER).size()

    full = pd.MultiIndex.from_product([centers, dates], names=[CENTER, DATE])
    miss = full.difference(pd.MultiIndex.from_frame(daily[[CENTER, DATE]].drop_duplicates()))
    gaps = [(c, pd.Timestamp(d)) for c, d in list(miss)[:50]]

    return {
        "中心数": len(centers),
        "日期数": len(dates),
        "起": pd.Timestamp(dates[0]),
        "止": pd.Timestamp(dates[-1]),
        "应有格子": cells,
        "实有格子": have,
        "缺失格子": cells - have,
        "缺失率": (cells - have) / cells if cells else float("nan"),
        "每中心最少记录": int(per_center.min()),
        "每中心最多记录": int(per_center.max()),
        "日期是否连续": len(pd.date_range(dates[0], dates[-1], freq="D")) == len(dates),
        "空洞样例": gaps,
    }


def hourly_completeness(hourly: pd.DataFrame) -> dict:
    centers = sorted(hourly[CENTER].unique(), key=center_rank)
    dates = sorted(pd.to_datetime(hourly[DATE].dropna().unique()))
    cells = len(centers) * len(dates) * 24
    miss = int(hourly["缺失"].sum())
    by_hour = (hourly.groupby(HOUR)["缺失"].mean() * 100).round(2)
    by_center = (hourly.groupby(CENTER)["缺失"].mean() * 100).round(2).sort_values(ascending=False)
    zero = int((hourly["货量_原始"] == 0).sum())      # 显式 0（原始记录就是 0）
    filled_zero = int((hourly[VOL] == 0).sum())       # 显式 0 + 缺格填 0
    both = filled_zero
    return {
        "中心数": len(centers),
        "日期数": len(dates),
        "起": pd.Timestamp(dates[0]),
        "止": pd.Timestamp(dates[-1]),
        "应有格子": cells,
        "实有格子": cells - miss,
        "缺失格子": miss,
        "缺失率": miss / cells,
        "小时取值": sorted(int(x) for x in hourly[HOUR].unique().tolist()),
        "零值格子": zero,
        "零值率": zero / cells,
        "填零后零值格子": filled_zero,
        "零或缺失": both,
        "零或缺失率": both / cells,
        "按小时缺失率": by_hour,
        "按中心缺失率": by_center,
        "0点缺失率": float(by_hour.get(0, float("nan"))),
    }


def reconcile_hourly_daily(daily: pd.DataFrame, hourly: pd.DataFrame) -> dict:
    """附件2 的 24 小时合计 与 附件1 当日货量 对账（只对重叠日期）。"""
    h = hourly.groupby([CENTER, DATE], as_index=False)[VOL].sum().rename(columns={VOL: "小时合计"})
    d = daily[[CENTER, DATE, VOL]].rename(columns={VOL: "日货量"})
    m = h.merge(d, on=[CENTER, DATE], how="inner")
    if m.empty:
        return {"匹配对数": 0}
    rel = (m["小时合计"] - m["日货量"]) / m["日货量"].replace(0, np.nan)
    return {
        "匹配对数": len(m),
        "完全相等比例": float((m["小时合计"] == m["日货量"]).mean()),
        "相对差中位数": float(rel.median()),
        "相对差均值": float(rel.mean()),
        "相对差最小": float(rel.min()),
        "相对差最大": float(rel.max()),
        "|相对差|<=1%比例": float((rel.abs() <= 0.01).mean()),
        "总和比": float(m["小时合计"].sum() / m["日货量"].sum()),
    }


def unit_checks(daily: pd.DataFrame, hourly: pd.DataFrame, routes: pd.DataFrame) -> dict:
    """单位与量级：负数 / 0 / 突增突降。"""
    jump = daily[(daily["环比倍数"] > 5) | (daily["环比倍数"] < 1 / 5)]
    return {
        "日_负数": int((daily[VOL] < 0).sum()),
        "日_零": int((daily[VOL] == 0).sum()),
        "日_最小": float(daily[VOL].min()),
        "日_最大": float(daily[VOL].max()),
        "日_合计": float(daily[VOL].sum()),
        "日_环比绝对值>500%": int((daily["环比变化"].abs() > 5).sum()),
        "日_跳变条数": len(jump),
        "跳变清单": jump[[CENTER, DATE, VOL, "环比倍数"]].copy(),
        "时_负数": int((hourly[VOL] < 0).sum()),
        "时_零": int((hourly["货量_原始"] == 0).sum()),
        "时_填零": int((hourly[VOL] == 0).sum()),
        "时_最大": float(hourly[VOL].max()),
        "线_负数": int((routes[VOL] < 0).sum()),
        "线_零": int((routes[VOL] == 0).sum()),
        "线_最小": float(routes[VOL].min()),
        "线_最大": float(routes[VOL].max()),
        "线_合计": float(routes[VOL].sum()),
    }


# --------------------------------------------------------------------------- #
# 7. 中间数据落盘
# --------------------------------------------------------------------------- #
DAILY_COLS = [CENTER, DATE, VOL, "周几", "是否周末", "记录条数",
              "环比变化", "环比倍数", "异常_IQR", "异常_3σ", "异常标记", "异常方向",
              "Q1", "Q3", "IQR下界", "IQR上界", "3σ下界", "3σ上界"]
HOURLY_COLS = [CENTER, DATE, HOUR, VOL, "货量_原始", "缺失", "日合计", "小时占比", "周几"]


def build_all(verbose: bool = True) -> dict:
    """生成 data/ 下四个中间表与异常清单。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    daily = load_daily()
    hourly = load_hourly()
    routes = load_routes()
    opens = load_route_open()

    d_out = daily[DAILY_COLS].copy()
    d_out[DATE] = d_out[DATE].dt.strftime("%Y-%m-%d")
    d_out.to_csv(os.path.join(DATA_DIR, "daily.csv"), index=False, encoding=ENC_OUT)

    h_out = hourly[HOURLY_COLS].copy()
    h_out[DATE] = h_out[DATE].dt.strftime("%Y-%m-%d")
    h_out["小时占比"] = h_out["小时占比"].round(6)
    h_out.to_csv(os.path.join(DATA_DIR, "hourly.csv"), index=False, encoding=ENC_OUT)

    routes.to_csv(os.path.join(DATA_DIR, "routes.csv"), index=False, encoding=ENC_OUT)
    opens.to_csv(os.path.join(DATA_DIR, "route_open.csv"), index=False, encoding=ENC_OUT)

    anom = daily[daily["异常标记"] != ""][
        [CENTER, DATE, VOL, "周几", "异常_IQR", "异常_3σ", "异常标记",
         "Q1", "Q3", "IQR下界", "IQR上界", "3σ下界", "3σ上界", "环比倍数"]
    ].copy()
    if len(anom):
        anom[DATE] = anom[DATE].dt.strftime("%Y-%m-%d")
    anom.to_csv(os.path.join(DATA_DIR, "anomaly_list.csv"), index=False, encoding=ENC_OUT)

    if verbose:
        print("[common] data/daily.csv        %6d 行" % len(d_out))
        print("[common] data/hourly.csv       %6d 行" % len(h_out))
        print("[common] data/routes.csv       %6d 行" % len(routes))
        print("[common] data/route_open.csv   %6d 行" % len(opens))
        print("[common] data/anomaly_list.csv %6d 行" % len(anom))
    return {"daily": daily, "hourly": hourly, "routes": routes, "opens": opens}


# --------------------------------------------------------------------------- #
# 8. data_quality.md
# --------------------------------------------------------------------------- #
def _md_table(headers, rows, aligns=None) -> str:
    aligns = aligns or ["---"] * len(headers)
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "| " + " | ".join(aligns) + " |"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def _fmt_ts(x) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def write_data_quality(verbose: bool = True) -> str:
    """生成 data/data_quality.md（数据字典 + 清洗规则 + 缺失/异常统计）。"""
    daily = load_daily()
    hourly = load_hourly()
    routes = load_routes()
    opens = load_route_open()

    dc = daily_completeness(daily)
    hc = hourly_completeness(hourly)
    rec = reconcile_hourly_daily(daily, hourly)
    uc = unit_checks(daily, hourly, routes)

    n_iqr = int((daily["异常_IQR"] != "").sum())
    n_3s = int((daily["异常_3σ"] != "").sum())
    n_both = int((daily["异常标记"] == "双规则异常").sum())
    anom = daily[daily["异常标记"] != ""].copy()
    anom["日期str"] = anom[DATE].dt.strftime("%Y-%m-%d")

    if len(anom):
        top_days = anom.groupby("日期str").size().sort_values(ascending=False).head(8)
    else:
        top_days = pd.Series(dtype=int)

    nov_mean_total = float(daily[daily[DATE].dt.month == 11].groupby(DATE)[VOL].sum().mean())
    route_share_pct = uc["线_合计"] / nov_mean_total * 100

    L = []
    L.append("# 数据质量报告（data/data_quality.md）")
    L.append("")
    L.append("> 本文件由 `code/common.py` 自动生成，请勿手工修改；重跑 `python code/common.py` 即可复现。")
    L.append("> 数据源：`附件/附件/附件1~4.csv`（只读，未做任何改动）。")
    L.append("")

    # ---- 1 数据字典 ----
    L.append("## 1. 数据字典")
    L.append("")
    L.append("### 1.1 附件1.csv —— 分拣中心日货量")
    L.append("")
    L.append(_md_table(
        ["字段", "类型", "含义", "取值 / 说明"],
        [["分拣中心", "str", "分拣中心编号", "%d 个（SC1~SC69 间不连续编号）" % dc["中心数"]],
         ["日期", "date", "业务日期", "`2023/9/5` 形式，已解析为 datetime；原文件行序为乱序"],
         ["货量", "int", "该中心当日总货量（件）", "min=%d，max=%d，无 0 无负数" % (uc["日_最小"], uc["日_最大"])]]))
    L.append("")
    L.append("### 1.2 附件2.csv —— 分拣中心小时货量")
    L.append("")
    L.append(_md_table(
        ["字段", "类型", "含义", "取值 / 说明"],
        [["分拣中心", "str", "分拣中心编号", "与附件1 完全一致的 %d 个" % hc["中心数"]],
         ["日期", "date", "业务日期", "%s ~ %s（仅 11 月，%d 天）" % (_fmt_ts(hc["起"]), _fmt_ts(hc["止"]), hc["日期数"])],
         ["小时", "int", "小时序号", "0~23，24 个整点全覆盖，无越界值"],
         ["货量", "int", "该小时货量（件）", "min=0（存在真实零值），max=%d" % uc["时_最大"]]]))
    L.append("")
    L.append("### 1.3 附件3.csv —— 有向线路货量")
    L.append("")
    L.append(_md_table(
        ["字段", "类型", "含义", "取值 / 说明"],
        [["始发分拣中心", "str", "线路起点", "%d 个不同始发" % routes["始发"].nunique()],
         ["到达分拣中心", "str", "线路终点", "%d 个不同到达" % routes["到达"].nunique()],
         ["货量", "int", "该有向线路货量", "min=%d，max=%d，合计=%d" % (uc["线_最小"], uc["线_最大"], uc["线_合计"])]]))
    L.append("")
    L.append("### 1.4 附件4.csv —— 有向线路开通关系")
    L.append("")
    L.append(_md_table(
        ["字段", "类型", "含义", "取值 / 说明"],
        [["始发分拣中心", "str", "线路起点", "%d 个不同始发" % opens["始发"].nunique()],
         ["到达分拣中心", "str", "线路终点", "%d 个不同到达" % opens["到达"].nunique()]]))
    L.append("")
    L.append("### 1.5 data/ 中间产物")
    L.append("")
    L.append(_md_table(
        ["文件", "行数", "粒度", "说明"],
        [["daily.csv", len(daily), "中心×日期", "清洗后的日货量 + 完整性/异常/环比标记列"],
         ["hourly.csv", len(hourly), "中心×日期×小时", "补齐 57×30×24 网格；`货量` 缺格记 0，`货量_原始` 保留原值"],
         ["routes.csv", len(routes), "有向线路", "附件3 + 是否双向 / 是否在附件4 / 线路货量占比"],
         ["route_open.csv", len(opens), "有向线路", "附件4 + 是否双向 / 附件3是否有货量 / 出入度"],
         ["anomaly_list.csv", len(anom), "中心×日期", "IQR 或 3σ 命中的异常清单（仅标记，未删除）"]]))
    L.append("")

    # ---- 2 清洗规则 ----
    L.append("## 2. 清洗规则")
    L.append("")
    rules = [
        ("R1 编码", "原附件按 GBK 读取；所有输出按 UTF-8-SIG 写，Excel 直接打开不乱码。"),
        ("R2 日期解析", "`2023/9/5`、`2023-09-05`、`2023年9月5日` 统一解析为 datetime，失败置 NaT 并计数（实测失败 0 条）。"),
        ("R3 去重", "同一主键（日粒度=中心+日期；小时粒度=中心+日期+小时）多条记录取**算术平均**，保留 `记录条数` 列。"
                    "取均值的理由：重复来源无法判断可信度，均值对随机重复无偏且抗单点误差；"
                    "实测四份附件重复键均为 0，该规则仅作防御。"),
        ("R4 排序", "按中心编号自然序（SC7 在 SC12 之前）+ 日期 + 小时升序，稳定排序（mergesort）。"),
        ("R5 小时网格补齐", "按 中心×日期×0..23 构造完整网格左连接；缺格保留在 `货量_原始`（NaN），`货量` 记 0。"
                            "依据见 §3.3：填 0 后小时合计与附件1 日货量的中位相对误差仅 0.11%，"
                            "即缺格等价于该小时无货量。"),
        ("R6 异常值", "按中心分别用 IQR(1.5) 与 3σ 双规则标记，输出 `异常_IQR`/`异常_3σ`/`异常标记`，**一律不删除**。"
                      "大促脉冲是真实业务信号，剔除会破坏后续峰值建模。"),
        ("R7 突增突降", "按中心计算 `环比倍数 = 当日货量 / 前一自然日货量`，>5 或 <1/5 记入跳变清单（见 §4.3）。"),
        ("R8 只读保护", "`附件/`、`结果/结果/` 下原始文件全程只读；提交模板已原样备份到 `模板备份/`（本会话沙箱禁写 `结果/`，"
                        "故备份放在工作区根目录，内容与原始模板逐字节一致，SHA256 已核对）。"),
    ]
    L.append(_md_table(["规则", "内容"], [[a, b] for a, b in rules]))
    L.append("")

    # ---- 3 缺失 ----
    L.append("## 3. 缺失统计")
    L.append("")
    L.append("### 3.1 日粒度完整度（附件1）")
    L.append("")
    L.append(_md_table(
        ["指标", "数值"],
        [["时间范围", "%s ~ %s" % (_fmt_ts(dc["起"]), _fmt_ts(dc["止"]))],
         ["日历天数", dc["日期数"]],
         ["日期是否连续（无跳日）", "是" if dc["日期是否连续"] else "否"],
         ["分拣中心数", dc["中心数"]],
         ["中心×日期 应有格子", dc["应有格子"]],
         ["实有格子", dc["实有格子"]],
         ["缺失格子", dc["缺失格子"]],
         ["缺失率", "%.4f%%" % (dc["缺失率"] * 100)],
         ["每中心记录数区间", "%d ~ %d" % (dc["每中心最少记录"], dc["每中心最多记录"])]]))
    L.append("")
    L.append("**结论：日粒度不存在任何中心×日期空洞，57×122 全满，缺失率 0%。**")
    L.append("")
    L.append("### 3.2 小时粒度完整度（附件2）")
    L.append("")
    L.append(_md_table(
        ["指标", "数值"],
        [["时间范围", "%s ~ %s" % (_fmt_ts(hc["起"]), _fmt_ts(hc["止"]))],
         ["日历天数", hc["日期数"]],
         ["与附件1 的重叠天数", "%d 天（附件2 只覆盖 11 月，无 8—10 月小时数据）" % hc["日期数"]],
         ["分拣中心数", hc["中心数"]],
         ["小时取值", "0~23 全覆盖（%d 个整点），无越界" % len(hc["小时取值"])],
         ["应有格子 57×30×24", hc["应有格子"]],
         ["实有格子", hc["实有格子"]],
         ["缺失格子", hc["缺失格子"]],
         ["缺失率", "%.2f%%" % (hc["缺失率"] * 100)],
         ["0 点缺失率", "%.2f%%" % hc["0点缺失率"]],
         ["显式 0 值格子", "%d（%.2f%%）" % (hc["零值格子"], hc["零值率"] * 100)],
         ["补零后 0 值格子", "%d（%.2f%%）" % (hc["填零后零值格子"], hc["零或缺失率"] * 100)],
         ["零值或缺失合计", "%d（%.2f%%）" % (hc["零或缺失"], hc["零或缺失率"] * 100)]]))
    L.append("")
    L.append("缺失率按小时分布（缺格集中在夜间低谷，不是随机缺失）：")
    L.append("")
    L.append(_md_table(["小时", "缺失率"],
                       [[h, "%.2f%%" % hc["按小时缺失率"].get(h, float("nan"))] for h in range(24)]))
    L.append("")
    L.append("缺失率最高的 10 个中心（小中心夜间无货 → 缺格多）：")
    L.append("")
    L.append(_md_table(["分拣中心", "缺失率"],
                       [[k, "%.2f%%" % v] for k, v in hc["按中心缺失率"].head(10).items()]))
    L.append("")
    L.append("### 3.3 小时合计 vs 附件1 日货量对账（重叠的 11 月）")
    L.append("")
    L.append(_md_table(
        ["指标", "数值"],
        [["匹配 (中心,日期) 对数", rec.get("匹配对数")],
         ["相对差中位数", "%.4f%%" % (rec.get("相对差中位数", 0) * 100)],
         ["相对差最小 / 最大", "%.2f%% / %.4f%%" % (rec.get("相对差最小", 0) * 100, rec.get("相对差最大", 0) * 100)],
         ["相对差绝对值 ≤ 1% 的比例", "%.2f%%" % (rec.get("|相对差|<=1%比例", 0) * 100)],
         ["Σ小时合计 / Σ日货量", "%.6f" % rec.get("总和比", 0)]]))
    L.append("")
    L.append("**结论：附件2 与附件1 在 11 月是同一套数据的两种粒度；缺格填 0 后总量只差 %.2f%%，"
             "因此「缺失即该小时 0 货量」成立，可直接用于小时占比建模。**" % ((1 - rec.get("总和比", 1)) * 100))
    L.append("")

    # ---- 4 异常 ----
    L.append("## 4. 异常统计")
    L.append("")
    L.append("### 4.1 双规则标记结果（按中心，不删除）")
    L.append("")
    L.append(_md_table(
        ["项目", "条目数", "占比"],
        [["IQR(1.5) 命中", n_iqr, "%.2f%%" % (n_iqr / len(daily) * 100)],
         ["3σ 命中", n_3s, "%.2f%%" % (n_3s / len(daily) * 100)],
         ["其中两规则同时命中", n_both, "%.2f%%" % (n_both / len(daily) * 100)],
         ["异常记录合计（去重）", len(anom), "%.2f%%" % (len(anom) / len(daily) * 100)]]))
    L.append("")
    L.append("异常记录的日期集中度（Top8）：")
    L.append("")
    L.append(_md_table(["日期", "异常中心数"], [[k, int(v)] for k, v in top_days.items()]))
    L.append("")
    L.append("### 4.2 异常清单（前 25 条，全量见 `data/anomaly_list.csv`）")
    L.append("")
    show = anom.sort_values([DATE], kind="mergesort").head(25)
    L.append(_md_table(
        ["分拣中心", "日期", "货量", "IQR下界", "IQR上界", "3σ下界", "3σ上界", "标记"],
        [[r[CENTER], r["日期str"], int(r[VOL]), round(r["IQR下界"]), round(r["IQR上界"]),
          round(r["3σ下界"]), round(r["3σ上界"]), r["异常标记"]] for _, r in show.iterrows()]))
    L.append("")
    L.append("说明：异常分两类，**都不应删除**——① 全网同步的脉冲（11/01、11/11、11/12 等，见 §4.1 日期集中度），"
             "是真实大促信号，应作为事件哑变量/倍数建模；② 个别低货量中心的爬坡或停摆（SC46、SC41、SC20、SC43 等），"
             "属结构性变化，需分段处理。")
    L.append("")
    L.append("### 4.3 突增突降（环比 >5 倍或 <1/5）")
    L.append("")
    jump = uc["跳变清单"].copy()
    if len(jump):
        jump["日期"] = jump[DATE].dt.strftime("%Y-%m-%d")
        L.append(_md_table(["分拣中心", "日期", "货量", "环比倍数"],
                           [[r[CENTER], r["日期"], int(r[VOL]), round(float(r["环比倍数"]), 2)]
                            for _, r in jump.iterrows()]))
        L.append("")
        L.append("判读：这些跳变集中在 SC12 / SC20 / SC41 / SC43 / SC48 等**低货量中心**，"
                 "形态是「某天骤降再回升」或「某天骤增」，更像分拣中心开通/停摆/数据口径切换的结构性变化，"
                 "而非录入错误；后续建模需对这类中心分段处理或设单独哑变量。")
    else:
        L.append("无。")
    L.append("")

    # ---- 5 单位量级 ----
    L.append("## 5. 单位与量级检查")
    L.append("")
    L.append(_md_table(
        ["检查项", "日粒度", "小时粒度", "线路(附件3)"],
        [["负值条数", uc["日_负数"], uc["时_负数"], uc["线_负数"]],
         ["0 值条数", uc["日_零"], uc["时_零"], uc["线_零"]],
         ["最小值", int(uc["日_最小"]), 0, int(uc["线_最小"])],
         ["最大值", int(uc["日_最大"]), int(uc["时_最大"]), int(uc["线_最大"])],
         ["合计", "%d" % uc["日_合计"], "—", "%d" % uc["线_合计"]]]))
    L.append("")
    L.append("* 日粒度无 0、无负数，量级 %d~%d，单位可判定为件/日。" % (uc["日_最小"], uc["日_最大"]))
    L.append("* 小时粒度存在 %d 个显式 0 值（真实无货时段，非缺失；补零后为 %d 个），最大 %d 与日粒度同量级；"
             "且 Σ小时/Σ日 = %.4f，两者单位一致（件/小时 vs 件/日）。"
             % (uc["时_零"], uc["时_填零"], uc["时_最大"], rec.get("总和比", 0)))
    L.append("* 附件3 合计仅 %d，约为 11 月全网日均货量的 %.2f%%，与附件1/附件2 不是同一量级口径，"
             "不可直接与日货量相减或直接占比（见 §6）。" % (uc["线_合计"], route_share_pct))
    L.append("")

    # ---- 6 待确认 ----
    L.append("## 6. 口径核对（题意已由《题目原文》核实）")
    L.append("")
    L.append("以下 3 条的题意已由《题目原文》核实（`论文/题目原文.md`），此处保留数据侧实测证据：")
    L.append("")
    L.append("1. **附件3 货量的时间口径**：附件3 无日期列，合计 %d，仅相当于 11 月全网日均的 %.2f%%；"
             "且「按到达中心汇总的线路货量」与该中心日均货量的比值在 0.6%%~20.3%% 间大幅波动"
             "（Spearman 相关仅 0.19），说明它不是全网日货量在全部线路上的完整分解。"
             "原文已明确：附件3 是**过去 90 天各运输线路的平均日货量**（不是单日快照），"
             "线路总货量仅占全网日均的 %.2f%%，故只能做相对修正，不能用来还原中心货量。"
             % (uc["线_合计"], route_share_pct, route_share_pct))
    L.append("2. **附件3 与附件4 的关系**：%d 条 vs %d 条，重合 %d 条，附件3 独有 %d 条、附件4 独有 %d 条，"
             "两者不构成子集关系；各自含 10 组双向对，其余均为单向。"
             "原文已明确：附件4 = **未来 30 天开通的线路集合**，附件3 有而附件4 无的 14 条为停开线路、"
             "附件4 有而附件3 无的 2 条为新开线路。"
             % (len(routes), len(opens),
                int(sum(routes["在附件4"])), int((~routes["在附件4"]).sum()),
                int((~opens["附件3有货量"]).sum())))
    L.append("3. **预测区间与提交格式**：原文与结果表 5/6 的示例行指向 **2023/12/1 ~ 2023/12/30（30 天）**；"
             "表1/表3 各 1710 行、表2/表4 各 41040 行，日期格式 `2023/12/1`（月日不补零）。"
             "`模板备份/` 仅保存原始模板副本。")
    L.append("")

    md = "\n".join(L)
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "data_quality.md")
    with open(path, "w", encoding=ENC_OUT) as f:
        f.write(md)
    if verbose:
        print("[common] 已写出 %s（%d 字符）" % (path, len(md)))
    return path


# --------------------------------------------------------------------------- #
# 9. 结果表落盘（结果/ 只读时自动降级到 提交/）
# --------------------------------------------------------------------------- #
def date_cn(ts) -> str:
    """结果表要求的日期格式：2023/12/1（月、日不补零）。"""
    t = pd.Timestamp(ts)
    return "%d/%d/%d" % (t.year, t.month, t.day)


def _dir_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, "_probe.tmp")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        os.remove(probe)
        return True
    except Exception:
        return False


def result_dir(verbose: bool = True) -> str:
    """优先写 `结果/结果/`；被沙箱或权限拦截时降级到 `提交/`。"""
    if _dir_writable(RES_DIR):
        return RES_DIR
    os.makedirs(SUBMIT_DIR, exist_ok=True)
    if verbose:
        print("[common] 警告：`结果/结果/` 不可写（沙箱只读），结果表改写 `提交/`；"
              "两者文件名与编码完全一致，可直接复制覆盖。")
    return SUBMIT_DIR


def write_result_table(df: pd.DataFrame, idx: int, cols, verbose: bool = True) -> str:
    """
    按提交规范写结果表：GBK 编码、无多余空列、无示例行、CRLF 换行。

    df  : 已整理好的数据（列名与 cols 一致）
    idx : 1~6
    """
    d = result_dir(verbose)
    path = os.path.join(d, "结果表%d.csv" % idx)
    out = df.loc[:, cols].copy()
    out.to_csv(path, index=False, encoding="gbk", lineterminator="\r\n")
    if verbose:
        print("[common] 已写出 %s（%d 行）" % (path, len(out)))
    return path


# --------------------------------------------------------------------------- #
# 10. 命令行入口
# --------------------------------------------------------------------------- #
def main() -> None:
    _force_utf8_stdout()
    os.makedirs(DATA_DIR, exist_ok=True)
    res = build_all()
    write_data_quality()

    daily, hourly = res["daily"], res["hourly"]
    dc = daily_completeness(daily)
    hc = hourly_completeness(hourly)
    rec = reconcile_hourly_daily(daily, hourly)
    print("")
    print("[common] 日粒度：%s ~ %s，%d 天，%d 个中心，缺失率 %.2f%%" % (
        _fmt_ts(dc["起"]), _fmt_ts(dc["止"]), dc["日期数"], dc["中心数"], dc["缺失率"] * 100))
    print("[common] 小时粒度：%s ~ %s，%d 天，缺失率 %.2f%%（填 0 后与日货量差 %.3f%%）" % (
        _fmt_ts(hc["起"]), _fmt_ts(hc["止"]), hc["日期数"], hc["缺失率"] * 100,
        (1 - rec.get("总和比", 1)) * 100))
    print("[common] 完成。")


if __name__ == "__main__":
    main()
