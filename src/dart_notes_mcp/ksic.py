"""KSIC(한국표준산업분류) 코드 → 업종명 매핑.

DART induty_code는 KSIC 기반(보통 소분류 3자리이나 응답에 따라 자릿수 혼재 가능).
data/ksic/ksic{rev}.csv (컬럼 Industy_code, Industy_name) 사용.
개정판(9/10차) 불일치 대비: 정확일치 실패 시 상위 자릿수로 폴백 탐색.
"""
from __future__ import annotations

import csv
import functools

from .config import KSIC_DIR

DEFAULT_REV = "10"


@functools.lru_cache(maxsize=4)
def _table(rev: str) -> dict[str, str]:
    path = KSIC_DIR / f"ksic{rev}.csv"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f)
        next(r, None)  # header
        for row in r:
            if len(row) >= 2 and row[0]:
                out[row[0].strip()] = row[1].strip()
    return out


def name_for(code: str, rev: str = DEFAULT_REV) -> str | None:
    """induty_code → 업종명. 정확일치 후 상위 자릿수 폴백."""
    if not code:
        return None
    code = code.strip()
    for r in (rev, "09" if rev != "09" else "10"):
        t = _table(r)
        if not t:
            continue
        if code in t:
            return t[code]
        for n in (5, 4, 3, 2):
            if len(code) > n and code[:n] in t:
                return t[code[:n]]
    return None


def major_code(code: str) -> str:
    """중분류(2자리) 키."""
    return (code or "")[:2]


def list_middle_categories(rev: str = DEFAULT_REV) -> list[dict]:
    """중분류(2자리) 목록 — 업종 필터 UX용."""
    t = _table(rev)
    return sorted(
        ({"code": c, "name": n} for c, n in t.items() if len(c) == 2),
        key=lambda x: x["code"],
    )
