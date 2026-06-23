"""인덱스 빌드 CLI.

  python -m dart_notes_mcp.index_build --year 2024              # 전체(열거→fetch→적재)
  python -m dart_notes_mcp.index_build --year 2024 --enumerate-only
  python -m dart_notes_mcp.index_build --year 2024 --load-only  # fetch 생략, 캐시→DB
"""
from __future__ import annotations

import argparse
import time

from .dart_client import DartClient
from .config import get_api_key
from .index_db import status
from .indexer import enumerate_filings, fetch_all, load_to_db


def main() -> None:
    ap = argparse.ArgumentParser(description="DART 사업보고서 주석 인덱스 빌드")
    ap.add_argument("--year", type=int, required=True, help="사업연도(FY). 예: 2024")
    ap.add_argument("--end-de", default=None, help="열거 종료일 YYYYMMDD(기본 오늘)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--enumerate-only", action="store_true")
    ap.add_argument("--load-only", action="store_true", help="fetch 생략, 캐시에서 DB 적재만")
    args = ap.parse_args()

    end_de = args.end_de or time.strftime("%Y%m%d")
    t0 = time.time()
    with DartClient(get_api_key()) as c:
        rcepts = enumerate_filings(c, args.year, end_de)
        print(f"[enumerate] FY{args.year} 사업보고서 {len(rcepts)}개사 ({time.time()-t0:.1f}s)")
        if args.enumerate_only:
            return
        if not args.load_only:
            fetch_all(c, rcepts, workers=args.workers)
        load_to_db(rcepts, args.year)
    print(f"[done] {time.time()-t0:.1f}s")
    print("status:", status())


if __name__ == "__main__":
    main()
