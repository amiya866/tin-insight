#!/usr/bin/env python3
"""Build a static market-sentiment snapshot (social.json) for the tin dashboard.

The Cloudflare Worker /api/social live-searches Douyin for "沪锡" sentiment.
When the Worker is unreachable (common from mainland networks), the page falls
back to this static file so the sentiment board never goes blank. The content
is extracted from the latest committed DATA.social embedded in index.html.

Payload shape mirrors worker/src/social.mjs buildSocialPayload().
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUT = ROOT / "social.json"


def extract_data_object(text: str) -> dict:
    """Parse the whole `const DATA = {...}` object embedded in index.html."""
    marker = "const DATA="
    start = text.index(marker) + len(marker)
    i = start
    depth = 0
    in_string = False
    escape = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
        i += 1
    if depth != 0:
        raise SystemExit("index.html: DATA 对象未闭合，无法提取 social")
    return json.loads(text[start : i + 1])


def main() -> None:
    text = INDEX.read_text(encoding="utf-8")
    data = extract_data_object(text)
    items = data.get("social") or []
    if not isinstance(items, list) or not items:
        raise SystemExit("index.html: DATA.social 为空，无法生成快照")

    payload = {
        "updated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "source": "CI 静态快照（抖音“沪锡”检索缓存 · Worker 不可达时的回退层）",
        "commodity": "tin",
        "items": items,
        "sources": {
            "douyin": {"ok": False, "count": len(items), "optional": False},
        },
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps({
        "ok": True,
        "updated_at": payload["updated_at"],
        "items": len(items),
        "sample": [item["title"] for item in items[:3]],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
