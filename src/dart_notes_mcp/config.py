"""경로·인증키 설정. .env에서 DART_API_KEY를 읽는다."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 패키지 기준 프로젝트 루트: src/dart_notes_mcp/config.py -> 루트
PKG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PKG_DIR.parent.parent

load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = Path(os.environ.get("DART_NOTES_DATA_DIR", PROJECT_ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
KSIC_DIR = DATA_DIR / "ksic"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

META_DB = CACHE_DIR / "company_meta.sqlite"
# rcept_no -> 파싱된 주석 섹션(JSON) 디스크 캐시 (하이브리드 v2 인덱스의 lazy seed)
NOTES_CACHE_DIR = CACHE_DIR / "notes"
NOTES_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_api_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DART_API_KEY가 설정되지 않았습니다. 프로젝트 루트의 .env에 "
            "DART_API_KEY=<40자 인증키> 를 넣으세요 (.env.example 참고)."
        )
    return key
