# -*- coding: utf-8 -*-
"""tin-insight DATA 块降级刷新：zhiji series 配额耗尽期使用。
数据源：
  - 本地缓存镜像 D:\\Kimi\\金属总网\\网站构建\\db\\数据缓存_v1.db（zhiji 指标日更快照）
  - westmetall.com（LME 官方日报镜像，锡价 3M 结算 + LME 锡库存，逐年表）
合并策略：与 index.html 内嵌 DATA 现有序列反向提取后取并集，同日冲突以新源为准；
缓存比 DATA 旧的指标自动保留 DATA 较新部分。warehouse 三地仓单无降级源，保持不动。
用法：python scripts/refresh_data_fallback.py
"""
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DB = r"D:\Kimi\金属总网\网站构建\db\数据缓存_v1.db"
COLORS = ["#f4b942", "#3dd6b6", "#6e9fff", "#ff758f", "#a989ff", "#ff9f43"]

# 指标 -> (缓存ID, DATA chart key, 类型)
CACHE_MAP = {
    "shfe_stock": ("FU00015998", "shfe_stock", "seasonal"),
    "social_stock": ("ID01517441", "social_stock", "seasonal"),
    "tin_ore_import_myanmar": ("CM0000451826", "myanmar", "seasonal"),
    "tin_ore_import_drc": ("a10099501", "drc", "seasonal"),
    "indonesia_export": ("ID01593795", "indo_export", "seasonal"),
    "malaysia_export": ("ID01659306", "malaysia_export", "seasonal"),
    "indonesia_exchange": ("FU00082529", None, "lag"),
}


def curl(url):
    out = subprocess.run(["curl", "-sL", "--max-time", "30", "-H", "User-Agent: Mozilla/5.0", url],
                         capture_output=True, timeout=40)
    return out.stdout.decode("utf-8", errors="replace")


def cache_series(ind_id):
    con = sqlite3.connect(CACHE_DB)
    rows = con.execute(
        "SELECT date, value FROM series_points WHERE ind_id=? ORDER BY date", (ind_id,)).fetchall()
    meta = con.execute(
        "SELECT name, unit, source, last_date FROM series_meta WHERE ind_id=?", (ind_id,)).fetchone()
    con.close()
    return [(d[:10], float(v)) for d, v in rows if v is not None], meta


def westmetall_tin():
    """逐年抓 LME 锡日报表：[date, cash结算, 3M, 库存]。返回 (price3m_series, stock_series)。"""
    price, stock = {}, {}
    for year in range(2021, 2027):
        t = curl(f"https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Sn_cash&year={year}")
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
            cells = [re.sub(r"<[^>]+>|\s+", " ", c).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(cells) < 4 or not re.match(r"\d{2}\. \w+ \d{4}", cells[0]):
                continue
            day = pd_to_iso(cells[0])
            if not day:
                continue
            try:
                p3m = float(cells[2].replace(",", ""))
                st = float(cells[3].replace(",", ""))
                price[day] = p3m
                stock[day] = st
            except ValueError:
                continue
    return sorted(price.items()), sorted(stock.items())


MONTHS = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
          "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12}


def pd_to_iso(s):
    m = re.match(r"(\d{2})\. (\w+) (\d{4})", s)
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


# ---- 与 refresh_zhiji_data.py 相同的图表构造函数 ----

def seasonal_chart(series, years=5):
    if not series:
        return {"labels": [], "datasets": []}
    available = sorted({int(day[:4]) for day, _ in series if int(day[:4]) >= 2021})[-years:]
    labels = sorted({day[5:] for day, _ in series if int(day[:4]) in available})
    datasets = []
    maximum = max(available)
    for index, year in enumerate(available):
        values = {day[5:]: value for day, value in series if int(day[:4]) == year}
        color = COLORS[index % len(COLORS)]
        datasets.append({
            "label": str(year),
            "data": [values.get(label) for label in labels],
            "borderColor": color,
            "backgroundColor": color + "18",
            "borderWidth": 2.7 if year == maximum else 1.35,
        })
    return {"labels": labels, "datasets": datasets}


def continuous_chart(series_map, limit=260):
    labels = sorted({day for series in series_map.values() for day, _ in series})
    if limit:
        labels = labels[-limit:]
    datasets = []
    for index, (name, series) in enumerate(series_map.items()):
        values = dict(series)
        color = COLORS[index % len(COLORS)]
        datasets.append({
            "label": name,
            "data": [values.get(day) for day in labels],
            "borderColor": color,
            "backgroundColor": color + "18",
            "borderWidth": 2.1,
        })
    return {"labels": labels, "datasets": datasets}


def forward_sum(left, right):
    left_map, right_map = dict(left), dict(right)
    left_value = right_value = None
    result = []
    for day in sorted(set(left_map) | set(right_map)):
        if day in left_map:
            left_value = left_map[day]
        if day in right_map:
            right_value = right_map[day]
        if left_value is not None and right_value is not None:
            result.append((day, left_value + right_value))
    return result


def lag_observation_rows(series, lags=(0, 1, 10, 30)):
    if not series:
        return []
    current = series[-1][1]
    rows = []
    for lag in lags:
        if len(series) <= lag:
            continue
        day, value = series[-1 - lag]
        rows.append({
            "label": "T" if lag == 0 else f"T-{lag}",
            "date": day,
            "value": value,
            "currentMinusReference": current - value,
        })
    return rows


def latest(series):
    return [series[-1][0], series[-1][1]] if series else [None, None]


# ---- 从现有 DATA 反向提取序列 ----

def unseasonal(chart):
    out = {}
    for ds in chart.get("datasets") or []:
        year = ds.get("label", "")
        if not year.isdigit():
            continue
        for lab, val in zip(chart.get("labels") or [], ds.get("data") or []):
            if val is not None:
                out[f"{year}-{lab}"] = float(val)
    return out


def uncontinuous(chart):
    labels = chart.get("labels") or []
    out = {}
    for ds in chart.get("datasets") or []:
        name = ds.get("label")
        out[name] = {lab: float(v) for lab, v in zip(labels, ds.get("data") or []) if v is not None}
    return out


def merge(old, new):
    """并集；同日以新源为准。"""
    m = dict(old)
    m.update(new)
    return sorted(m.items())


def meta_obj(ind_id, name, unit, org, last_date, source_note):
    return {"id": ind_id, "source": source_note, "name": name, "unit": unit,
            "frequency": "日", "organization": org, "dataLatest": last_date}


def main():
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    prefix = "const DATA="
    suffix = ";\nconst STATIC_HOST="
    start = text.index(prefix) + len(prefix)
    end = text.index(suffix, start)
    data = json.loads(text[start:end])
    charts = data.setdefault("charts", {})
    latest_data = data.setdefault("latest", {})
    source_meta = data.setdefault("sourceMeta", {})

    report = []

    # ---- 缓存镜像指标 ----
    for label, (ind_id, chart_key, kind) in CACHE_MAP.items():
        series, meta = cache_series(ind_id)
        if not series:
            report.append(f"{label}: 缓存无数据，跳过")
            continue
        old = {}
        if kind == "seasonal" and chart_key in charts:
            old = unseasonal(charts[chart_key])
        merged = merge(old, dict(series))
        if kind == "seasonal":
            charts[chart_key] = seasonal_chart(merged)
            latest_data_key = {"shfe_stock": "shfe_stock", "social_stock": "social_stock",
                               "tin_ore_import_myanmar": "tin_ore_import_myanmar",
                               "tin_ore_import_drc": "tin_ore_import_drc",
                               "indonesia_export": "indo_export",
                               "malaysia_export": "malaysia_export"}[label]
            latest_data[latest_data_key] = latest(merged)
        else:  # indonesia_exchange
            old_rows = (data.get("indonesiaExchange") or {}).get("rows") or []
            old = {r["date"]: float(r["value"]) for r in old_rows if r.get("value") is not None}
            merged = merge(old, dict(series))
            data["indonesiaExchange"] = {
                "meta": meta_obj(ind_id, meta[0], meta[1], "ICDX", merged[-1][0],
                                 "缓存镜像(zhiji/ICDX)"),
                "rows": lag_observation_rows(merged),
            }
        if kind == "seasonal":
            source_meta_key = {"shfe_stock": "shfeStock", "social_stock": "socialStock",
                               "tin_ore_import_myanmar": "tinOreImportMyanmar",
                               "tin_ore_import_drc": "tinOreImportDrc",
                               "indonesia_export": "indonesiaExport",
                               "malaysia_export": "malaysiaExport"}[label]
            source_meta[source_meta_key] = meta_obj(ind_id, meta[0], meta[1], meta[2],
                                                    merged[-1][0], "缓存镜像(zhiji)")
        report.append(f"{label}: -> {merged[-1][0]} ({len(merged)} 点)")

    # ---- westmetall：LME 锡价(3M结算) + LME 锡库存 ----
    try:
        lme_price, lme_stock = westmetall_tin()
    except Exception as e:
        print("westmetall 抓取失败:", e)
        lme_price, lme_stock = [], []
    if lme_price:
        old = unseasonal(charts.get("overview_lme", {}))
        merged = merge(old, dict(lme_price))
        charts["overview_lme"] = seasonal_chart(merged)
        latest_data["lme"] = latest(merged)
        source_meta["lmePrice"] = meta_obj("westmetall", "LME 锡 3M 结算价", "美元/吨",
                                           "LME/westmetall", merged[-1][0], "westmetall 直采")
        report.append(f"lme_price: -> {merged[-1][0]}")
    if lme_stock:
        old = unseasonal(charts.get("lme_stock", {}))
        merged = merge(old, dict(lme_stock))
        charts["lme_stock"] = seasonal_chart(merged)
        latest_data["lme_stock"] = latest(merged)
        source_meta["lmeStock"] = meta_obj("westmetall", "LME 锡库存", "吨",
                                           "LME/westmetall", merged[-1][0], "westmetall 直采")
        report.append(f"lme_stock: -> {merged[-1][0]}")
    # 全球显性库存 = SHFE + LME 前填相加
    shfe_map = dict()
    if "shfe_stock" in charts:
        shfe_map = unseasonal(charts["shfe_stock"])
    lme_map = dict()
    if lme_stock:
        lme_map = dict(merge(unseasonal(charts.get("lme_stock", {})), dict(lme_stock)))
    if shfe_map and lme_map:
        gs = forward_sum(sorted(shfe_map.items()), sorted(lme_map.items()))
        charts["overview_global_stock"] = seasonal_chart(gs)
        latest_data["global_stock"] = latest(gs)
        report.append(f"global_stock: -> {gs[-1][0]}")

    # ---- TC / 冶炼利润（连续图）----
    tc_y, my = cache_series("ID01538256")
    tc_j, mj = cache_series("ID01538257")
    if tc_y or tc_j:
        old = uncontinuous(charts.get("cost_tc", {}))
        name_y, name_j = "云南 40% 锡精矿加工费", "江西 60% 锡精矿加工费"
        m_y = merge(old.get(name_y, {}), dict(tc_y))
        m_j = merge(old.get(name_j, {}), dict(tc_j))
        charts["cost_tc"] = continuous_chart({name_y: m_y, name_j: m_j})
        if m_y:
            latest_data["tc_yunnan"] = latest(m_y)
        if m_j:
            latest_data["tc_jiangxi"] = latest(m_j)
        source_meta["tcYunnan"] = meta_obj("ID01538256", my[0], my[1], my[2], m_y[-1][0], "缓存镜像(zhiji)")
        source_meta["tcJiangxi"] = meta_obj("ID01538257", mj[0], mj[1], mj[2], m_j[-1][0], "缓存镜像(zhiji)")
        report.append(f"cost_tc: -> {m_y[-1][0]}")
    prof, pm = cache_series("ID02105841")
    if prof:
        name = "冶炼锡毛利（日度）"
        old = uncontinuous(charts.get("cost_profit", {}))
        m_p = merge(old.get(name, {}), dict(prof))
        charts["cost_profit"] = continuous_chart({name: m_p})
        latest_data["smelting_profit"] = latest(m_p)
        source_meta["smeltingProfit"] = meta_obj("ID02105841", pm[0], pm[1], pm[2], m_p[-1][0], "缓存镜像(zhiji)")
        report.append(f"cost_profit: -> {m_p[-1][0]}")

    out = text[:start] + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + text[end:]
    (ROOT / "index.html").write_text(out, encoding="utf-8", newline="")
    print("\n".join(report))
    print(f"index.html 已更新 ({len(out)/1e3:.0f} KB)")


if __name__ == "__main__":
    sys.exit(main())
