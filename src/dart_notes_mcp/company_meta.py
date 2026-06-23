"""시장(corp_cls)×업종(induty_code) 회사 메타 캐시 (SQLite).

corpCode.xml에는 시장구분·업종이 없어, 회사별 company.json을 1회 수집해 캐시한다.
이후 induty_code/corp_cls 필터는 런타임 API 호출 0으로 즉시 처리(하이브리드 v1).

비용: 상장사(stock_code 보유) ~2,800개 company.json 호출(일 한도 20,000 내). 1회 적재 후 증분.
비상장(E) 전수 enumeration은 비현실적 → 이름 지정 on-demand(resolve_company)로 보완.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .config import META_DB
from .dart_client import DartClient
from .ksic import name_for

MARKET_NAME = {"Y": "코스피", "K": "코스닥", "N": "코넥스", "E": "비상장"}
MARKET_CODE = {v: k for k, v in MARKET_NAME.items()}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS company_meta (
    corp_code   TEXT PRIMARY KEY,
    corp_name   TEXT,
    stock_code  TEXT,
    corp_cls    TEXT,
    induty_code TEXT,
    induty_name TEXT,
    modify_date TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_cls   ON company_meta(corp_cls);
CREATE INDEX IF NOT EXISTS ix_induty ON company_meta(induty_code);
CREATE INDEX IF NOT EXISTS ix_name  ON company_meta(corp_name);
"""


@dataclass
class Company:
    corp_code: str
    corp_name: str
    stock_code: str
    corp_cls: str
    induty_code: str
    induty_name: str | None

    @property
    def market(self) -> str:
        return MARKET_NAME.get(self.corp_cls, self.corp_cls or "?")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(META_DB)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def status() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM company_meta").fetchone()[0]
        by = c.execute(
            "SELECT corp_cls, COUNT(*) n FROM company_meta GROUP BY corp_cls"
        ).fetchall()
    return {
        "total": total,
        "by_market": {MARKET_NAME.get(r["corp_cls"], r["corp_cls"]): r["n"] for r in by},
        "db": str(META_DB),
    }


def build_meta(
    client: DartClient,
    listed_only: bool = True,
    limit: int | None = None,
    sleep: float = 0.05,
    progress_every: int = 200,
    log=print,
) -> dict:
    """corpCode 전체 → 상장사(stock_code 보유) company.json 수집 → 캐시.

    listed_only=True: stock_code 있는 회사만(코스피/코스닥/코넥스).
    """
    corps = client.corp_code_list()
    if listed_only:
        corps = [c for c in corps if c.get("stock_code")]
    if limit:
        corps = corps[:limit]
    log(f"[build_meta] 대상 {len(corps)}개 회사 company.json 수집 시작")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    ok = err = 0
    with _conn() as conn:
        for i, c in enumerate(corps, 1):
            try:
                info = client.company(c["corp_code"])
                if str(info.get("status")) != "000":
                    err += 1
                    continue
                induty = (info.get("induty_code") or "").strip()
                conn.execute(
                    """INSERT INTO company_meta
                       (corp_code, corp_name, stock_code, corp_cls, induty_code,
                        induty_name, modify_date, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(corp_code) DO UPDATE SET
                        corp_name=excluded.corp_name, stock_code=excluded.stock_code,
                        corp_cls=excluded.corp_cls, induty_code=excluded.induty_code,
                        induty_name=excluded.induty_name, modify_date=excluded.modify_date,
                        updated_at=excluded.updated_at""",
                    (
                        c["corp_code"],
                        info.get("corp_name") or c.get("corp_name"),
                        c.get("stock_code", ""),
                        info.get("corp_cls", ""),
                        induty,
                        name_for(induty),
                        c.get("modify_date", ""),
                        now,
                    ),
                )
                ok += 1
            except Exception as e:  # noqa: BLE001
                err += 1
                if err <= 5:
                    log(f"  [warn] {c.get('corp_name')}: {e}")
            if i % progress_every == 0:
                conn.commit()
                log(f"  ... {i}/{len(corps)} (ok={ok}, err={err})")
            if sleep:
                time.sleep(sleep)
        conn.commit()
    log(f"[build_meta] 완료 ok={ok}, err={err}")
    return {"processed": len(corps), "ok": ok, "err": err}


def _row_to_company(r: sqlite3.Row) -> Company:
    return Company(
        corp_code=r["corp_code"],
        corp_name=r["corp_name"],
        stock_code=r["stock_code"] or "",
        corp_cls=r["corp_cls"] or "",
        induty_code=r["induty_code"] or "",
        induty_name=r["induty_name"],
    )


def query_companies(
    markets: list[str] | None = None,      # ['코스피','코스닥',...] 또는 코드 ['Y','K']
    induty_prefix: str | list[str] | None = None,  # 업종코드 접두(2~5자리)
    induty_contains: str | None = None,    # 업종명 부분일치
    name_contains: str | None = None,
    limit: int | None = None,
) -> list[Company]:
    where, params = [], []
    if markets:
        codes = [MARKET_CODE.get(m, m) for m in markets]
        where.append("corp_cls IN (%s)" % ",".join("?" * len(codes)))
        params += codes
    if induty_prefix:
        prefs = [induty_prefix] if isinstance(induty_prefix, str) else induty_prefix
        where.append("(" + " OR ".join("induty_code LIKE ?" for _ in prefs) + ")")
        params += [f"{p}%" for p in prefs]
    if induty_contains:
        where.append("induty_name LIKE ?")
        params.append(f"%{induty_contains}%")
    if name_contains:
        where.append("corp_name LIKE ?")
        params.append(f"%{name_contains}%")
    sql = "SELECT * FROM company_meta"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY corp_name"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with _conn() as c:
        return [_row_to_company(r) for r in c.execute(sql, params).fetchall()]


def resolve_company(client: DartClient | None, name_or_code: str) -> Company | None:
    """캐시 우선, 없으면(비상장 등) 이름으로 corpCode에서 찾아 live company.json."""
    s = name_or_code.strip()
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM company_meta WHERE corp_code=? OR corp_name=? "
            "ORDER BY (corp_name=?) DESC LIMIT 1",
            (s, s, s),
        ).fetchone()
        if r:
            return _row_to_company(r)
        r = c.execute(
            "SELECT * FROM company_meta WHERE corp_name LIKE ? ORDER BY length(corp_name) LIMIT 1",
            (f"%{s}%",),
        ).fetchone()
        if r:
            return _row_to_company(r)
    if client is None:
        return None
    # 캐시에 없음 → corpCode에서 이름 매칭 후 live 조회(비상장 보완)
    for entry in client.corp_code_list():
        if entry.get("corp_name") == s or (s in (entry.get("corp_name") or "")):
            info = client.company(entry["corp_code"])
            if str(info.get("status")) == "000":
                induty = (info.get("induty_code") or "").strip()
                return Company(
                    corp_code=entry["corp_code"],
                    corp_name=info.get("corp_name", s),
                    stock_code=entry.get("stock_code", ""),
                    corp_cls=info.get("corp_cls", ""),
                    induty_code=induty,
                    induty_name=name_for(induty),
                )
    return None


def list_industries(markets: list[str] | None = None, contains: str | None = None) -> list[dict]:
    """캐시에 실제 존재하는 업종(회사수 포함) — 사용자 필터 선택용."""
    where, params = ["induty_code != ''"], []
    if markets:
        codes = [MARKET_CODE.get(m, m) for m in markets]
        where.append("corp_cls IN (%s)" % ",".join("?" * len(codes)))
        params += codes
    if contains:
        where.append("induty_name LIKE ?")
        params.append(f"%{contains}%")
    sql = (
        "SELECT induty_code, induty_name, COUNT(*) n FROM company_meta WHERE "
        + " AND ".join(where)
        + " GROUP BY induty_code, induty_name ORDER BY n DESC"
    )
    with _conn() as c:
        return [
            {"induty_code": r["induty_code"], "induty_name": r["induty_name"], "count": r["n"]}
            for r in c.execute(sql, params).fetchall()
        ]
