# -*- coding: utf-8 -*-
"""tin-insight DATA 补丁（2026-09-19）：缓存镜像(zhiji) 配额死、社库/SHFE/lme03 停在 9/04/9/01，
改从 Mysteel锡线下数据.xlsx 延长到 9/18，并重算 overview_global_stock。
幂等：与 DATA 现有序列取并集，同日以新源为准，只前进不回落。
用法：python scripts/_patch_mysteel_20260919.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from refresh_data_fallback import (  # noqa: E402
    forward_sum, latest, merge, meta_obj, seasonal_chart, unseasonal,
)
from refresh_data_excel import MYSTEEL, sheet_series  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    import openpyxl
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    prefix = "const DATA="
    suffix = ";\nconst STATIC_HOST="
    start = text.index(prefix) + len(prefix)
    end = text.index(suffix, start)
    data = json.loads(text[start:end])
    charts, latest_data, source_meta = data["charts"], data["latest"], data["sourceMeta"]
    report = []

    wb = openpyxl.load_workbook(MYSTEEL, read_only=True, data_only=True)

    # 社库 ← Mysteel 锡锭社会库存（A=日期, G=总计，周度）
    ser = sheet_series(wb["锡锭社会库存"], 1, 7, min_row=2, nd=0)
    if ser:
        merged = merge(unseasonal(charts["social_stock"]), dict(ser))
        charts["social_stock"] = seasonal_chart(merged)
        latest_data["social_stock"] = latest(merged)
        source_meta["socialStock"] = meta_obj(
            "mysteel-excel", "Mysteel 锡锭社会库存", "吨", "Mysteel",
            merged[-1][0], "Mysteel锡线下数据.xlsx（zhiji 配额期直读）")
        report.append(f"social_stock: -> {merged[-1][0]} ({len(merged)} 点)")

    # SHFE 库存 ← Mysteel SHFE库存（A=日期, B:D=沪+粤+苏，周度合计）
    ws = wb["SHFE库存"]
    rows = []
    for r in ws.iter_rows(min_row=5, values_only=True):
        dt = r[0]
        parts = [v for v in r[1:4] if isinstance(v, (int, float))]
        if hasattr(dt, "year") and parts:
            rows.append((dt.strftime("%Y-%m-%d"), float(sum(parts))))
    if rows:
        merged = merge(unseasonal(charts["shfe_stock"]), dict(rows))
        charts["shfe_stock"] = seasonal_chart(merged)
        latest_data["shfe_stock"] = latest(merged)
        source_meta["shfeStock"] = meta_obj(
            "mysteel-excel", "SHFE 锡库存", "吨", "Mysteel/SHFE",
            merged[-1][0], "Mysteel锡线下数据.xlsx（zhiji 配额期直读）")
        report.append(f"shfe_stock: -> {merged[-1][0]} ({len(merged)} 点)")

    # lme03 ← Mysteel 进出口盈亏（A=日期, C=LME升贴水 美元/吨，日度）
    ser = sheet_series(wb["进出口盈亏"], 1, 3, min_row=2, nd=2)
    if ser:
        merged = merge(unseasonal(charts["lme03"]), dict(ser))
        charts["lme03"] = seasonal_chart(merged)
        latest_data["lme03"] = latest(merged)
        source_meta["lme03"] = meta_obj(
            "mysteel-excel", "LME 锡 0-3 升贴水", "美元/吨", "Mysteel",
            merged[-1][0], "Mysteel锡线下数据.xlsx 进出口盈亏（zhiji 配额期直读）")
        report.append(f"lme03: -> {merged[-1][0]} ({len(merged)} 点)")

    # 重算全球显性库存 = 最新 SHFE + LME 前填相加
    shfe_map = unseasonal(charts["shfe_stock"])
    lme_map = unseasonal(charts["lme_stock"])
    if shfe_map and lme_map:
        gs = forward_sum(sorted(shfe_map.items()), sorted(lme_map.items()))
        charts["overview_global_stock"] = seasonal_chart(gs)
        latest_data["global_stock"] = latest(gs)
        report.append(f"global_stock: -> {gs[-1][0]} ({gs[-1][1]:.0f} 吨)")

    out = text[:start] + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + text[end:]
    (ROOT / "index.html").write_text(out, encoding="utf-8", newline="")
    print("\n".join(report))
    print(f"index.html 已更新 ({len(out)/1e3:.0f} KB)")


if __name__ == "__main__":
    main()
