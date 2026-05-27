#!/usr/bin/env python3
"""
삼성전자(005930) 최근 종가를 받아 data.json에 기록.

GitHub Actions에서 평일 18:30 KST (= 09:30 UTC)에 실행되어 자사주
환산 주가 기본값을 자동으로 갱신한다.

다중 소스 폴백 구조:
    1. Naver Finance siseJson (일봉 — 가장 정확)
    2. Naver Finance polling   (실시간 시세)
    3. Stooq CSV
    4. Yahoo Finance           (마지막 폴백 — 클라우드 IP 차단 빈번)

Yahoo는 2026년 들어 GitHub Actions runner IP에 대해 403을 자주
반환하므로 최후 폴백으로만 사용한다.

출력 data.json 스키마:
    {
        "asOf":          "YYYY-MM-DD",
        "currentPrice":  319000,
        "source":        "Naver Finance 005930 daily close"
    }
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data.json"
UA = "Mozilla/5.0 (samsung-bonus-calculator updater)"
TIMEOUT = 20


def _get(url: str, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── 소스 1: Naver Finance 일봉 (siseJson) ────────────────────────────────
def fetch_naver_sise() -> tuple[str, int]:
    today = datetime.now(KST)
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    url = (
        "https://api.finance.naver.com/siseJson.naver"
        f"?symbol=005930&requestType=1&startTime={start}&endTime={end}&timeframe=day"
    )
    raw = _get(url, headers={"Referer": "https://finance.naver.com/"})
    # 응답은 Python literal 형태이지만 strict JSON으로도 파싱 가능 (따옴표가 큰따옴표라면).
    # 안전을 위해 ast.literal_eval 사용.
    import ast

    rows = ast.literal_eval(raw.strip())
    # 첫 행은 헤더, 이후는 [날짜, 시가, 고가, 저가, 종가, 거래량, 외국인소진율]
    if not isinstance(rows, list) or len(rows) < 2:
        raise RuntimeError("Naver siseJson 응답 형식 불일치")
    last = rows[-1]
    date_raw = str(last[0])
    close = int(round(float(last[4])))
    as_of = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
    return as_of, close


# ── 소스 2: Naver Finance 실시간 폴링 ────────────────────────────────────
def fetch_naver_polling() -> tuple[str, int]:
    url = "https://polling.finance.naver.com/api/realtime/domestic/stock/005930"
    raw = _get(url, headers={"Referer": "https://finance.naver.com/"})
    data = json.loads(raw)
    item = data["datas"][0]
    close = int(str(item["closePrice"]).replace(",", ""))
    # time 필드: "YYYYMMDDhhmmss"
    t = data.get("time") or item.get("localTradedAt") or ""
    as_of = (
        f"{t[:4]}-{t[4:6]}-{t[6:8]}"
        if len(t) >= 8 and t[:8].isdigit()
        else datetime.now(KST).strftime("%Y-%m-%d")
    )
    return as_of, close


# ── 소스 3: Stooq CSV ────────────────────────────────────────────────────
def fetch_stooq() -> tuple[str, int]:
    url = "https://stooq.com/q/l/?s=005930.kr&f=sd2t2ohlcv&h&e=csv"
    raw = _get(url)
    lines = [ln for ln in raw.strip().splitlines() if ln]
    if len(lines) < 2:
        raise RuntimeError("Stooq 응답 비어 있음")
    header = [c.strip().lower() for c in lines[0].split(",")]
    values = [c.strip() for c in lines[1].split(",")]
    row = dict(zip(header, values))
    date = row.get("date") or row.get("d")
    close = row.get("close") or row.get("c")
    if not date or not close or close.upper() == "N/D":
        raise RuntimeError(f"Stooq 데이터 무효: {row}")
    return date, int(round(float(close)))


# ── 소스 4: Yahoo Finance (마지막 폴백) ──────────────────────────────────
def fetch_yahoo() -> tuple[str, int]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/005930.KS"
        "?range=5d&interval=1d"
    )
    raw = _get(url)
    payload = json.loads(raw)
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    for i in range(len(closes) - 1, -1, -1):
        if closes[i] is not None:
            as_of = datetime.fromtimestamp(timestamps[i], tz=KST).strftime("%Y-%m-%d")
            return as_of, int(round(closes[i]))
    raise RuntimeError("Yahoo 응답에 유효한 종가가 없습니다.")


SOURCES = [
    ("Naver Finance 005930 daily close",       fetch_naver_sise),
    ("Naver Finance 005930 realtime polling",  fetch_naver_polling),
    ("Stooq 005930.kr daily close",            fetch_stooq),
    ("Yahoo Finance 005930.KS daily close",    fetch_yahoo),
]


def main() -> int:
    errors: list[str] = []
    for source, fn in SOURCES:
        try:
            as_of, price = fn()
            if price <= 0:
                raise RuntimeError(f"비정상 가격: {price}")
            out = {
                "asOf": as_of,
                "currentPrice": price,
                "source": source,
            }
            OUTPUT_PATH.write_text(
                json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[update_data] OK ({source}) asOf={as_of}, currentPrice={price:,}원")
            if errors:
                print(f"[update_data] (선행 소스 실패: {'; '.join(errors)})")
            return 0
        except Exception as exc:  # noqa: BLE001
            msg = f"{source}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            print(f"[update_data] FAIL {msg}", file=sys.stderr)

    print(f"[update_data] 모든 소스 실패: {'; '.join(errors)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
