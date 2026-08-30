# -*- coding: utf-8 -*-
"""刷新 index.html 内嵌 DATA 的 同业/下游日成交（overview_trade + latest.trade_*）。
数据源 = Mysteel锡线下数据.xlsx「贸易商日度交易量」（用户手动导出，CI 跑不到，需本地手动执行）。
用法: python scripts/refresh_trade_volume.py
2026-08-30 建：zhiji 配额 outage 期间该序列停在 8/21 之前，改从本地 Excel 直读。"""
import json
import re
from pathlib import Path

import openpyxl

BASE = Path(__file__).parent.parent
EXCEL = Path(r"D:\拷贝文件\E\永安\周报数据更新\Mysteel锡线下数据.xlsx")
SHEET = "贸易商日度交易量"

wb = openpyxl.load_workbook(EXCEL, data_only=True, read_only=True)
ws = wb[SHEET]
rows = [r for r in ws.iter_rows(values_only=True)
        if r and hasattr(r[0], "strftime") and r[1] is not None and r[2] is not None]
wb.close()
rows.sort(key=lambda r: r[0])
labels = [r[0].strftime("%Y-%m-%d") for r in rows]
peer = [float(r[1]) for r in rows]
down = [float(r[2]) for r in rows]
print(f"Excel 序列: {labels[0]} ~ {labels[-1]}, 共 {len(labels)} 点")

html = (BASE / "index.html").read_text(encoding="utf-8")
m = re.search(r"const DATA=(\{.*?\});\s*\nconst STATIC_HOST", html, re.S)
data = json.loads(m.group(1))
tr = data["charts"]["overview_trade"]
tr["labels"] = labels
tr["datasets"][0]["data"] = peer
tr["datasets"][1]["data"] = down
data["latest"]["trade_peer"] = [labels[-1], peer[-1]]
data["latest"]["trade_downstream"] = [labels[-1], down[-1]]
new_html = html[: m.start(1)] + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + html[m.end(1):]
(BASE / "index.html").write_text(new_html, encoding="utf-8")
print("index.html 已更新: latest trade =", labels[-1], peer[-1], down[-1])
