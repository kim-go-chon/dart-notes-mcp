"""주석 전문 인덱스 DB (SQLite + FTS5 trigram).

note_section: 회사별 주석 섹션 원문(title/body/tables).
note_fts    : 정규화 blob의 trigram FTS(한국어 부분문자열 검색용 후보 좁히기).
검색 = FTS5로 후보 좁힘 → topics.match_topic으로 정밀 필터(정밀도는 온디맨드와 동일).
"""
from __future__ import annotations

import sqlite3

from .config import CACHE_DIR

INDEX_DB = CACHE_DIR / "notes_index.sqlite"

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS filing (
  rcept_no TEXT PRIMARY KEY, corp_code TEXT, corp_name TEXT, year INTEGER,
  report_nm TEXT, rcept_dt TEXT, corp_cls TEXT, induty_code TEXT, induty_name TEXT,
  n_sections INTEGER, indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_filing_year ON filing(year);
CREATE INDEX IF NOT EXISTS ix_filing_corp ON filing(corp_code);

CREATE TABLE IF NOT EXISTS note_section (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rcept_no TEXT, corp_code TEXT, corp_name TEXT, year INTEGER,
  corp_cls TEXT, induty_code TEXT, induty_name TEXT,
  fs_div TEXT, note_no INTEGER, title TEXT, body TEXT, tables_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_ns_rcept ON note_section(rcept_no);
CREATE INDEX IF NOT EXISTS ix_ns_year ON note_section(year);
CREATE INDEX IF NOT EXISTS ix_ns_cls ON note_section(corp_cls);

CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(blob, tokenize='trigram');
"""


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(INDEX_DB)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def status() -> dict:
    with connect() as c:
        f = c.execute("SELECT COUNT(*) FROM filing").fetchone()[0]
        s = c.execute("SELECT COUNT(*) FROM note_section").fetchone()[0]
        yrs = c.execute(
            "SELECT year, COUNT(*) n FROM filing GROUP BY year ORDER BY year"
        ).fetchall()
        mk = c.execute(
            "SELECT corp_cls, COUNT(DISTINCT corp_code) n FROM filing GROUP BY corp_cls"
        ).fetchall()
    return {
        "filings": f,
        "sections": s,
        "by_year": {r["year"]: r["n"] for r in yrs},
        "by_market": {r["corp_cls"]: r["n"] for r in mk},
        "db": str(INDEX_DB),
    }
