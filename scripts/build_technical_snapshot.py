#!/usr/bin/env python3
"""Build a static four-frame technical snapshot (technical.json) for the tin dashboard.

Runs in GitHub Actions (network to Sina/Zhiji is reliable there). The page uses
this file as a fallback when the Cloudflare Worker /api/technical is unreachable
(e.g. workers.dev resets from mainland networks) so the four-frame analysis and
daily K chart stay current for all visitors.

Payload shape mirrors worker/src/technical.mjs buildTechnicalPayload().
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
OUT = Path(__file__).resolve().parent.parent / "technical.json"

SINA_MINUTE_URL = (
    "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/=/"
    "InnerFuturesNewService.getFewMinLine"
)
SINA_DAILY_URL = (
    "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/=/"
    "InnerFuturesNewService.getDailyKLine"
)
ZHIJI_KLINE_URL = "https://zhiji-ai.xyz/guan/api/kline"
SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Tin Dashboard GitHub Actions",
}


# ------------------------------------------------------------------ fetching
def fetch_sina(freq: str, limit: int) -> list[dict]:
    url = SINA_MINUTE_URL + "?" + urlencode({"symbol": "SN0", "type": freq})
    last_error: Exception | None = None
    for attempt in range(3):  # 新浪对 CI 出口 IP 间歇性 SSL 超时，退避重试
        try:
            request = Request(url, headers=SINA_HEADERS)
            with urlopen(request, timeout=40) as response:
                text = response.read().decode("utf-8", errors="replace")
            return parse_jsonp_bars(text)[-limit:]
        except Exception as error:  # noqa: BLE001
            last_error = error
            time.sleep(4 * (attempt + 1))
    raise last_error


def fetch_zhiji_minute(freq: str, limit: int, key: str) -> list[dict]:
    """知几分钟 K（freq=15/60，ifind 源）。注意：15min/60min 字样会被静默降级成日线，必须用 15/60。"""
    query = urlencode({"symbol": "SN", "freq": freq, "cont": "1", "limit": str(limit), "key": key})
    request = Request(
        ZHIJI_KLINE_URL + "?" + query,
        headers={"User-Agent": "Tin Dashboard GitHub Actions", "X-Guan-Key": key},
    )
    with urlopen(request, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw = payload.get("bars") or payload.get("data") or []
    bars = [bar for bar in (normalize_bar(item) for item in raw) if bar]
    bars.sort(key=lambda bar: bar["time"])
    if len(bars) < 20 or ":" not in str(bars[-1]["time"]):
        raise RuntimeError(f"Zhiji {freq}min kline unusable ({len(bars)} bars)")
    return bars[-limit:]


def fetch_sina_daily(limit: int) -> list[dict]:
    url = SINA_DAILY_URL + "?" + urlencode({"symbol": "SN0"})
    request = Request(url, headers=SINA_HEADERS)
    with urlopen(request, timeout=40) as response:
        text = response.read().decode("utf-8", errors="replace")
    return parse_jsonp_bars(text)[-limit:]


def fetch_zhiji_daily(limit: int, key: str) -> list[dict]:
    query = urlencode({"symbol": "SN", "freq": "D", "cont": "1", "limit": str(limit), "key": key})
    request = Request(
        ZHIJI_KLINE_URL + "?" + query,
        headers={"User-Agent": "Tin Dashboard GitHub Actions", "X-Guan-Key": key},
    )
    with urlopen(request, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw = payload.get("bars") or payload.get("data") or []
    bars = [bar for bar in (normalize_bar(item) for item in raw) if bar]
    bars.sort(key=lambda bar: bar["time"])
    if len(bars) < 20:
        raise RuntimeError(f"Zhiji daily kline returned only {len(bars)} bars")
    return bars[-limit:]


def parse_jsonp_bars(text: str) -> list[dict]:
    start = text.index("=(")
    end = text.rindex(");")
    raw = json.loads(text[start + 2 : end])
    bars = [bar for bar in (normalize_bar(item) for item in raw) if bar]
    bars.sort(key=lambda bar: bar["time"])
    if len(bars) < 20:
        raise RuntimeError(f"Sina returned only {len(bars)} bars")
    return bars


def normalize_bar(item: dict) -> dict | None:
    time = str(
        item.get("time") or item.get("date") or item.get("datetime")
        or item.get("trade_date") or item.get("d") or ""
    )
    def num(*names):
        for name in names:
            if item.get(name) is not None:
                try:
                    return float(item[name])
                except (TypeError, ValueError):
                    return None
        return None
    o, h, l, c = num("open", "o"), num("high", "h"), num("low", "l"), num("close", "c")
    if not time or None in (o, h, l, c):
        return None
    return {"time": time, "open": o, "high": h, "low": l, "close": c,
            "volume": num("volume", "v")}


# ---------------------------------------------------------------- indicators
def moving_average(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    acc = 0.0
    for i, value in enumerate(values):
        acc += value
        if i >= period:
            acc -= values[i - period]
        if i >= period - 1:
            out[i] = acc / period
    return out


def ema(values: list[float], period: int) -> list[float]:
    factor = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * factor + out[-1] * (1 - factor))
    return out


def macd(values: list[float]) -> tuple[list[float], list[float], list[float]]:
    fast, slow = ema(values, 12), ema(values, 26)
    dif = [f - s for f, s in zip(fast, slow)]
    dea = ema(dif, 9)
    return dif, dea, [(d - e) * 2 for d, e in zip(dif, dea)]


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains = losses = 0.0
    for i in range(len(values) - period, len(values)):
        change = values[i] - values[i - 1]
        if change > 0:
            gains += change
        else:
            losses -= change
    if not losses:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def display_number(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{round(value):,}"


def tech_card(frame: str, bars: list[dict]) -> dict:
    closes = [bar["close"] for bar in bars]
    window = bars[-20:]
    ma5 = moving_average(closes, 5)[-1]
    ma20 = moving_average(closes, 20)[-1]
    dif, dea, hist = macd(closes)
    price = closes[-1]
    last_rsi = rsi(closes)
    range_low = min(bar["low"] for bar in window)
    range_high = max(bar["high"] for bar in window)
    position = 0.5 if range_high == range_low else (price - range_low) / (range_high - range_low)
    structure = "上沿附近" if position >= 0.8 else ("下沿附近" if position <= 0.2 else "区间内部")
    status, tone = "震荡", "neutral"
    if ma5 and ma20 and price > ma5 and price > ma20 and hist[-1] >= 0:
        status, tone = "偏多", "up"
    elif ma5 and ma20 and price < ma5 and price < ma20 and hist[-1] <= 0:
        status, tone = "偏空", "down"
    detail = (
        f"道氏/均线：MA5 {display_number(ma5)}、MA20 {display_number(ma20)}"
        f"；MACD DIF {display_number(dif[-1])} / DEA {display_number(dea[-1])}"
        f"；RSI14 {'—' if last_rsi is None else f'{last_rsi:.1f}'}"
        f"；缠论简化结构位于20根区间{structure}"
        f"；江恩区间 {display_number(range_low)}–{display_number(range_high)}。"
    )
    return {"frame": frame, "status": status, "tone": tone, "price": price, "detail": detail}


def kline_payload(bars: list[dict]) -> dict:
    closes = [bar["close"] for bar in bars]
    mas = {f"MA{p}": moving_average(closes, p) for p in (5, 10, 20, 60, 288)}
    return {
        "labels": [bar["time"] for bar in bars],
        "candles": [{"o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"]} for b in bars],
        "mas": mas,
    }


# ---------------------------------------------------------------------- main
def main() -> None:
    errors: dict[str, str] = {}
    tech: list[dict] = []
    key = os.environ.get("ZHIJI_API_KEY", "").strip()

    for freq, frame in (("15", "小级别｜15 分钟"), ("60", "中级别｜60 分钟")):
        try:
            tech.append(tech_card(frame, fetch_sina(freq, 320)))
        except Exception as error:  # noqa: BLE001
            errors[f"{freq}min-sina"] = str(error)[:200]
            if key:  # 新浪挂了 → 知几分钟 K 兜底
                try:
                    tech.append(tech_card(frame, fetch_zhiji_minute(freq, 320, key)))
                    errors.pop(f"{freq}min-sina")
                    errors[f"{freq}min"] = "新浪失败，已用知几兜底"
                except Exception as error2:  # noqa: BLE001
                    errors[f"{freq}min-zhiji"] = str(error2)[:200]

    daily_bars: list[dict] | None = None
    if key:
        try:
            daily_bars = fetch_zhiji_daily(320, key)
        except Exception as error:  # noqa: BLE001
            errors["D-zhiji"] = str(error)[:200]
    if daily_bars is None:
        try:
            daily_bars = fetch_sina_daily(320)
        except Exception as error:  # noqa: BLE001
            errors["D-sina"] = str(error)[:200]

    if daily_bars is None:
        if not tech:
            raise SystemExit(f"all sources failed: {errors}")
        daily_bars = None
    else:
        tech.append(tech_card("大级别｜日线", daily_bars))

    # 保留最近一次成功的框架：本次缺的小级别用仓库里已提交的旧快照补位，避免页面掉级别
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
            have = {item["frame"] for item in tech}
            for old_card in previous.get("tech") or []:
                if old_card.get("frame") not in have:
                    tech.insert(0 if "15" in old_card["frame"] else min(1, len(tech)), old_card)
                    errors[f"reused-{old_card['frame']}"] = f"沿用 {previous.get('updated_at', '?')} 快照"
            tech.sort(key=lambda item: ("15" not in item["frame"], "60" not in item["frame"]))
        except Exception:  # noqa: BLE001
            pass

    payload = {
        "updated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "source": "沪锡｜新浪 15/60 分钟 K + 日 K；GitHub Actions 静态快照（Worker 不可达时的回退层）",
        "commodity": "tin",
        "tech": tech,
        "kline": kline_payload(daily_bars) if daily_bars else None,
        "errors": errors,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "ok": bool(tech),
        "updated_at": payload["updated_at"],
        "frames": [item["frame"] for item in tech],
        "prices": [item["price"] for item in tech],
        "kline_last": payload["kline"]["labels"][-1] if payload["kline"] else None,
        "errors": errors,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
