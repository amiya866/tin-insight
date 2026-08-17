import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://zhiji-ai.xyz/commodity/api/series"
COLORS = ["#f4b942", "#3dd6b6", "#6e9fff", "#ff758f", "#a989ff", "#ff9f43"]
INDICATORS = {
    "lme_price": "FU00015894",
    "shfe_stock": "FU00015998",
    "lme_stock": "FU00015899",
    "social_stock": "ID01517441",
    # 2026-07-30 起：进口总量图改主数据库“矿端平衡”总进口（金属吨）口径，
    # 由 _tin_pages_update 脚本注入，知几 SMM 金属量系列无权限返回空，勿再从此刷新覆盖
    "tin_ore_import_myanmar": "CM0000451826",
    "tin_ore_import_drc": "a10099501",
    "indonesia_export": "ID01593795",
    "malaysia_export": "ID01659306",
    "tc_yunnan": "ID01538256",
    "tc_jiangxi": "ID01538257",
    "smelting_profit": "ID02105841",
    "warehouse_singapore": "ID00302752",
    "warehouse_hong_kong": "FU00094556",
    "warehouse_port_klang": "ID00302749",
    "indonesia_exchange": "FU00082529",
}


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_series(indicator_id, key):
    query = urlencode({
        "id": indicator_id,
        "start": "2021-01-01",
        "end": date.today().isoformat(),
    })
    request = Request(API_URL + "?" + query, headers={
        "User-Agent": "Tin Dashboard GitHub Actions",
        "X-Data-Key": key,
    })
    with urlopen(request, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    points = {}
    for item in payload.get("points") or []:
        day = str(item.get("date") or "")[:10]
        value = number(item.get("value"))
        if len(day) == 10 and value is not None:
            points[day] = value
    meta = {
        "id": indicator_id,
        "source": "数据接口",
        "name": payload.get("name"),
        "unit": payload.get("unit"),
        "frequency": payload.get("frequency"),
        "organization": payload.get("src_org"),
        "dataLatest": payload.get("data_latest"),
    }
    return sorted(points.items()), meta


def latest(series):
    return [series[-1][0], series[-1][1]] if series else [None, None]


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


def warehouse_row(name, series):
    if not series:
        return None
    return {
        "name": name,
        "latest": series[-1][1],
        "d5": series[-1][1] - series[-6][1] if len(series) >= 6 else None,
        "d20": series[-1][1] - series[-21][1] if len(series) >= 21 else None,
        "date": series[-1][0],
    }


def lag_observation_rows(series, lags=(0, 1, 10, 30)):
    """Build T-n rows from valid observations, retaining observed zero-volume days."""
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


key = os.environ.get("ZHIJI_API_KEY", "").strip()
if not key:
    print("ZHIJI_API_KEY is not configured; keeping embedded fallback data")
    raise SystemExit(0)

series = {}
meta = {}
for label, indicator_id in INDICATORS.items():
    try:
        series[label], meta[label] = fetch_series(indicator_id, key)
    except Exception as exc:
        print(f"Zhiji refresh failed for {label}: {type(exc).__name__}")
        series[label], meta[label] = [], {"id": indicator_id, "source": "数据接口", "error": type(exc).__name__}

path = Path("index.html")
text = path.read_text(encoding="utf-8")
prefix = "const DATA="
suffix = ";\nconst STATIC_HOST="
start = text.index(prefix) + len(prefix)
end = text.index(suffix, start)
data = json.loads(text[start:end])
charts = data.setdefault("charts", {})
latest_data = data.setdefault("latest", {})

if series["lme_price"]:
    charts["overview_lme"] = seasonal_chart(series["lme_price"])
    latest_data["lme"] = latest(series["lme_price"])
if series["shfe_stock"]:
    charts["shfe_stock"] = seasonal_chart(series["shfe_stock"])
    latest_data["shfe_stock"] = latest(series["shfe_stock"])
if series["lme_stock"]:
    charts["lme_stock"] = seasonal_chart(series["lme_stock"])
    latest_data["lme_stock"] = latest(series["lme_stock"])
if series["social_stock"]:
    charts["social_stock"] = seasonal_chart(series["social_stock"])
    latest_data["social_stock"] = latest(series["social_stock"])
# tin_ore_import_total 不再由知几刷新（金属吨口径由主数据库注入，见 INDICATORS 注释）
if series["tin_ore_import_myanmar"]:
    charts["myanmar"] = seasonal_chart(series["tin_ore_import_myanmar"])
    latest_data["tin_ore_import_myanmar"] = latest(series["tin_ore_import_myanmar"])
if series["tin_ore_import_drc"]:
    charts["drc"] = seasonal_chart(series["tin_ore_import_drc"])
    latest_data["tin_ore_import_drc"] = latest(series["tin_ore_import_drc"])
if series["indonesia_export"]:
    charts["indo_export"] = seasonal_chart(series["indonesia_export"])
    latest_data["indo_export"] = latest(series["indonesia_export"])
if series["malaysia_export"]:
    charts["malaysia_export"] = seasonal_chart(series["malaysia_export"])
    latest_data["malaysia_export"] = latest(series["malaysia_export"])
if series["shfe_stock"] and series["lme_stock"]:
    global_stock = forward_sum(series["shfe_stock"], series["lme_stock"])
    charts["overview_global_stock"] = seasonal_chart(global_stock)
    latest_data["global_stock"] = latest(global_stock)
if series["tc_yunnan"] or series["tc_jiangxi"]:
    charts["cost_tc"] = continuous_chart({
        "云南 40% 锡精矿加工费": series["tc_yunnan"],
        "江西 60% 锡精矿加工费": series["tc_jiangxi"],
    })
    if series["tc_yunnan"]:
        latest_data["tc_yunnan"] = latest(series["tc_yunnan"])
    if series["tc_jiangxi"]:
        latest_data["tc_jiangxi"] = latest(series["tc_jiangxi"])
if series["smelting_profit"]:
    charts["cost_profit"] = continuous_chart({
        "冶炼锡毛利（日度）": series["smelting_profit"],
    })
    latest_data["smelting_profit"] = latest(series["smelting_profit"])

warehouses = [
    warehouse_row("新加坡", series["warehouse_singapore"]),
    warehouse_row("中国香港", series["warehouse_hong_kong"]),
    warehouse_row("巴生", series["warehouse_port_klang"]),
]
if any(warehouses):
    data["warehouse"] = [row for row in warehouses if row]

if series["indonesia_exchange"]:
    data["indonesiaExchange"] = {
        "meta": meta["indonesia_exchange"],
        "rows": lag_observation_rows(series["indonesia_exchange"]),
    }

source_meta = data.setdefault("sourceMeta", {})
source_meta.update({
    "lmePrice": meta["lme_price"],
    "shfeStock": meta["shfe_stock"],
    "lmeStock": meta["lme_stock"],
    "socialStock": meta["social_stock"],
    "tinOreImportMyanmar": meta["tin_ore_import_myanmar"],
    "tinOreImportDrc": meta["tin_ore_import_drc"],
    "indonesiaExport": meta["indonesia_export"],
    "malaysiaExport": meta["malaysia_export"],
    "tcYunnan": meta["tc_yunnan"],
    "tcJiangxi": meta["tc_jiangxi"],
    "smeltingProfit": meta["smelting_profit"],
    "indonesiaExchange": meta["indonesia_exchange"],
    "warehouses": {
        "新加坡": meta["warehouse_singapore"],
        "中国香港": meta["warehouse_hong_kong"],
        "巴生": meta["warehouse_port_klang"],
    },
})

encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
path.write_text(text[:start] + encoded + text[end:], encoding="utf-8")
print(json.dumps({
    "lme": latest_data.get("lme"),
    "global_stock": latest_data.get("global_stock"),
    "social_stock": latest_data.get("social_stock"),
    "tin_ore_import_total": latest_data.get("tin_ore_import_total"),
    "tin_ore_import_myanmar": latest_data.get("tin_ore_import_myanmar"),
    "tin_ore_import_drc": latest_data.get("tin_ore_import_drc"),
    "indonesia_export": latest_data.get("indo_export"),
    "malaysia_export": latest_data.get("malaysia_export"),
    "tc_yunnan": latest_data.get("tc_yunnan"),
    "indonesia_exchange": data.get("indonesiaExchange"),
    "warehouses": data.get("warehouse"),
}, ensure_ascii=False))
