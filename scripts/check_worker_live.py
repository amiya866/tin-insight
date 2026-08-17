#!/usr/bin/env python3
"""Smoke-test the public Worker policy localization and remote social MCP."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


BASE_URL = "https://tin-insight-api.wangziquan-tin.workers.dev"


def get_json(path: str) -> dict:
    request = urllib.request.Request(
        BASE_URL + path,
        headers={"User-Agent": "Tin Insight GitHub Actions Smoke Test"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            if response.status != 200:
                raise RuntimeError(f"{path} returned HTTP {response.status}")
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} returned HTTP {error.code}: {body}") from error


def has_chinese(value: object) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in str(value or ""))


def main() -> None:
    health = get_json("/health")
    if not health.get("ok") or not health.get("ai_configured") or not health.get("social_configured"):
        raise RuntimeError(f"Worker health is not ready: {health}")

    policy = get_json("/api/policy?smoke=github")
    items = policy.get("items") or []
    ai_source = (policy.get("sources") or {}).get("WORKERS AI 中文摘要") or {}
    if not items or not ai_source.get("ok"):
        raise RuntimeError(f"Policy AI source failed: {ai_source}")
    if not all(has_chinese(item.get("title_zh")) and has_chinese(item.get("summary_zh")) for item in items):
        raise RuntimeError("Policy feed contains an item without a Chinese title or summary")
    if any("RSS 摘要未提供更多细节" in str(item.get("summary_zh") or "") for item in items):
        raise RuntimeError("Policy feed still contains the deprecated generic RSS placeholder")
    macro_items = [item for item in items if str(item.get("category") or "").startswith("MACRO")]
    if any(str(item.get("title_zh") or "").startswith("锡产业动态｜") for item in macro_items):
        raise RuntimeError("A macro event is still mislabeled as a tin-industry update")

    technical_diag = {}
    try:
        technical = get_json("/api/technical?smoke=github-v3")
        technical_diag = {
            "updated_at": technical.get("updated_at"),
            "errors": technical.get("errors") or {},
            "frames": [item.get("frame") for item in technical.get("tech") or []],
            "kline_last": (technical.get("kline") or {}).get("labels", [None])[-1],
        }
    except Exception as error:  # noqa: BLE001 - diagnostics only, never fail the step
        technical_diag = {"fetch_error": str(error)[:300]}
    print("TECHNICAL_DIAG " + json.dumps(technical_diag, ensure_ascii=False))

    social = get_json("/api/social?smoke=github-v2")
    social_sources = social.get("sources") or {}
    for platform in ("小红书", "抖音"):
        status = social_sources.get(platform) or {}
        if not status.get("ok") or int(status.get("count") or 0) <= 0:
            raise RuntimeError(f"{platform} remote MCP source failed: {status}")

    sample = [
        {"title_zh": item["title_zh"], "summary_zh": item["summary_zh"]}
        for item in items[:2]
    ]
    print(json.dumps({
        "ok": True,
        "policy_count": len(items),
        "policy_sample": sample,
        "social_sources": social_sources,
        "social_count": len(social.get("items") or []),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
