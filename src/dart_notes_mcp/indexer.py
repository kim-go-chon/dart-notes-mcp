"""사업연도(FY) 전체 사업보고서 인덱싱.

흐름: 열거(list.json A001 전수 페이지네이션) → fetch+parse(캐시, 병렬) → DB+FTS 적재.
정밀도 엔진(topics)은 검색 시 그대로 재사용 — 인덱스는 '받아오는 비용'만 1회로 끝낸다.
"""
from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from .config import META_DB, get_api_key
from .dart_client import DartClient, Disclosure
from .index_db import connect
from .ksic import name_for
from .search import _cache_path, get_sections
from .topics import _key


def _windows(bgn: str, end: str, days: int = 80) -> list[tuple[str, str]]:
    """corp_code 없는 list 조회는 3개월 제한 → 80일 윈도우로 분할."""
    d0 = datetime.strptime(bgn, "%Y%m%d")
    d1 = datetime.strptime(end, "%Y%m%d")
    out, cur = [], d0
    while cur <= d1:
        nxt = min(cur + timedelta(days=days - 1), d1)
        out.append((cur.strftime("%Y%m%d"), nxt.strftime("%Y%m%d")))
        cur = nxt + timedelta(days=1)
    return out


def enumerate_filings(client: DartClient, year: int, end_de: str, log=print) -> list[Disclosure]:
    """FY{year} 사업보고서 전수 열거(정정 시 최신 1건만). 3개월 윈도우 순회."""
    bgn = f"{year + 1}0101"
    by_corp: dict[str, Disclosure] = {}
    for w_bgn, w_end in _windows(bgn, end_de):
        ds = client.list_disclosures(
            corp_code=None, bgn_de=w_bgn, end_de=w_end,
            pblntf_ty="A", pblntf_detail_ty="A001",
        )
        cand = [d for d in ds if "사업보고서" in d.report_nm and f"({year}." in d.report_nm]
        for d in cand:
            if d.corp_code not in by_corp or d.rcept_dt > by_corp[d.corp_code].rcept_dt:
                by_corp[d.corp_code] = d
        log(f"  window {w_bgn}~{w_end}: +{len(cand)} (누적 {len(by_corp)})")
    return list(by_corp.values())


def fetch_all(client: DartClient, rcepts: list[Disclosure], workers: int = 8, log=print) -> dict:
    """document.xml fetch+parse(캐시) 병렬. 캐시 존재 시 즉시 skip."""
    done = {"n": 0, "err": 0}
    total = len(rcepts)

    def work(d: Disclosure):
        try:
            get_sections(client, d.rcept_no)  # 캐시 hit이면 즉시 반환
            return True
        except Exception:  # noqa: BLE001
            done["err"] += 1
            return False

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, d) for d in rcepts]
        for _ in as_completed(futs):
            done["n"] += 1
            if done["n"] % 100 == 0:
                log(f"  fetch {done['n']}/{total} (err={done['err']})")
    log(f"[fetch] 완료 {done['n']}/{total} (err={done['err']})")
    return done


def load_to_db(rcepts: list[Disclosure], year: int, log=print) -> dict:
    """캐시된 파싱결과 → note_section + note_fts + filing 적재(단일 스레드)."""
    metacon = sqlite3.connect(META_DB)
    metacon.row_factory = sqlite3.Row

    def meta(code: str):
        return metacon.execute(
            "SELECT corp_cls,induty_code,induty_name FROM company_meta WHERE corp_code=?", (code,)
        ).fetchone()

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    loaded = sec_cnt = skipped = 0
    with connect() as db:
        for d in rcepts:
            rc = d.rcept_no
            p = _cache_path(rc)
            if not p.exists():
                skipped += 1
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            secs = data.get("sections", []) if isinstance(data, dict) else data
            m = meta(d.corp_code)
            cls = (m["corp_cls"] if m else "") or ""
            ind = (m["induty_code"] if m else "") or ""
            indn = (m["induty_name"] if m else None) or name_for(ind)

            # 재적재 시 기존 행/FTS 정리
            old = [r[0] for r in db.execute("SELECT id FROM note_section WHERE rcept_no=?", (rc,))]
            for oid in old:
                db.execute("DELETE FROM note_fts WHERE rowid=?", (oid,))
            db.execute("DELETE FROM note_section WHERE rcept_no=?", (rc,))

            for s in secs:
                tables = s.get("tables_md", []) or []
                cur = db.execute(
                    "INSERT INTO note_section(rcept_no,corp_code,corp_name,year,corp_cls,"
                    "induty_code,induty_name,fs_div,note_no,title,body,tables_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rc, d.corp_code, d.corp_name, year, cls, ind, indn,
                     s.get("fs_div"), s.get("note_no"), s.get("title") or "",
                     s.get("body") or "", json.dumps(tables, ensure_ascii=False)),
                )
                blob = _key((s.get("title") or "") + " " + (s.get("body") or "") + " " + " ".join(tables))
                db.execute("INSERT INTO note_fts(rowid,blob) VALUES(?,?)", (cur.lastrowid, blob))
                sec_cnt += 1
            db.execute(
                "INSERT OR REPLACE INTO filing(rcept_no,corp_code,corp_name,year,report_nm,"
                "rcept_dt,corp_cls,induty_code,induty_name,n_sections,indexed_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (rc, d.corp_code, d.corp_name, year, d.report_nm, d.rcept_dt, cls, ind, indn, len(secs), now),
            )
            loaded += 1
            if loaded % 200 == 0:
                db.commit()
                log(f"  load {loaded}/{len(rcepts)} (sections={sec_cnt})")
        db.commit()
    log(f"[load] 완료 filings={loaded} sections={sec_cnt} skipped={skipped}")
    return {"loaded": loaded, "sections": sec_cnt, "skipped": skipped}
