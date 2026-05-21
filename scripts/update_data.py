#!/usr/bin/env python3
"""
삼성전자(005930) 최근 종가를 Yahoo Finance에서 받아 data.json에 기록.

GitHub Actions에서 평일 18:30 KST (= 09:30 UTC)에 실행되어 자사주
환산 주가 기본값을 자동으로 갱신한다.

출력 data.json 스키마:
    {
        "asOf":          "YYYY-MM-DD",   # KST 거래일
        "currentPrice":  276000,         # 원
        "source":        "Yahoo Finance 005930.KS daily close"
    }
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/005930.KS"
    "?range=5d&interval=1d"
)
KST = timezone(timedelta(hours=9))
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data.json"


def fetch() -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(URL, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_close(payload: dict) -> tuple[str, int]:
    result = payload["chart"]["result"][0]
    timestamps: list[int] = result["timestamp"]
    closes: list[float | None] = result["indicators"]["quote"][0]["close"]

    for i in range(len(closes) - 1, -1, -1):
        if closes[i] is not None:
            as_of = datetime.fromtimestamp(timestamps[i], tz=KST).strftime("%Y-%m-%d")
            return as_of, int(round(closes[i]))

    raise RuntimeError("Yahoo Finance 응답에 유효한 종가가 없습니다.")


def main() -> int:
    try:
        payload = fetch()
        as_of, price = latest_close(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[update_data] 실패: {exc}", file=sys.stderr)
        return 1

    out = {
        "asOf": as_of,
        "currentPrice": price,
        "source": "Yahoo Finance 005930.KS daily close",
    }
    OUTPUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[update_data] asOf={as_of}, currentPrice={price:,}원")
    return 0


if __name__ == "__main__":
    sys.exit(main())
