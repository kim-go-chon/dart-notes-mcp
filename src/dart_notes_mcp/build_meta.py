"""메타 캐시 구축 CLI.

  python -m dart_notes_mcp.build_meta [--limit N]

상장사(코스피/코스닥/코넥스) 시장×업종 메타를 1회 수집해 SQLite에 캐시한다.
이후 search_company_notes의 시장/업종 필터가 런타임 API 호출 0으로 동작한다.
"""
from __future__ import annotations

import argparse

from .company_meta import build_meta, status
from .config import get_api_key
from .dart_client import DartClient


def main() -> None:
    ap = argparse.ArgumentParser(description="DART 시장×업종 메타 캐시 구축")
    ap.add_argument("--limit", type=int, default=None, help="테스트용 일부만 수집")
    ap.add_argument("--sleep", type=float, default=0.05, help="호출 간 대기(초)")
    args = ap.parse_args()

    with DartClient(get_api_key()) as client:
        res = build_meta(client, limit=args.limit, sleep=args.sleep)
    print("결과:", res)
    print("현황:", status())


if __name__ == "__main__":
    main()
