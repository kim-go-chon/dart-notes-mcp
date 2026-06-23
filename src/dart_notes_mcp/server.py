"""DART 주석 정밀검색 MCP 서버 (FastMCP / stdio).

도구:
  search_company_notes  — 시장×업종×토픽으로 여러 회사 주석을 정밀검색(핵심)
  get_company_note      — 단일 회사의 특정 토픽 주석 전문(표 포함)
  list_note_topics      — 등록된 정밀 토픽(규칙) 목록
  list_industries       — 캐시에 존재하는 업종(회사수) — 필터 선택용
  resolve_company_info  — 회사명/코드 → 시장·업종 메타
  meta_status           — 메타 캐시 현황
  build_company_meta    — (관리) 시장×업종 메타 캐시 구축/갱신(상장사, 수분 소요)
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import company_meta, index_db, index_search, search as search_mod, topics
from .config import get_api_key
from .dart_client import DartClient

mcp = FastMCP("dart-notes")

_client: DartClient | None = None


def _get_client() -> DartClient:
    global _client
    if _client is None:
        _client = DartClient(get_api_key())
    return _client


@mcp.tool()
def search_company_notes(
    topic: str,
    market: list[str] | None = None,
    industry_code: list[str] | None = None,
    industry_name: str | None = None,
    year: int = 2024,
    companies: list[str] | None = None,
    max_companies: int = 12,
) -> dict:
    """여러 회사의 재무제표 주석에서 특정 회계이슈를 '정밀' 검색한다.

    유사 키워드 난잡검색을 막기 위해 토픽별 규칙(주제 동의어 AND + 관점 facet +
    발행자/우연출현 차단)으로 매칭한다. 노이즈를 낼 바엔 비매칭(precision 우선).

    Args:
        topic: 회계이슈. 등록 토픽키(예: 'supplier_finance','convertible_bond_holder')
               또는 자유어(예: '공급자금융약정', '전환사채 취득자 회계처리'). 자유어는
               intent 라우팅 또는 전 토큰 AND로 처리. `list_note_topics`로 등록규칙 확인.
        market: ['코스피','코스닥','코넥스','비상장'] 중 택(코드 'Y','K','N','E'도 허용).
        industry_code: KSIC 업종코드 접두 리스트(예: ['26','27'] 또는 ['264']).
        industry_name: 업종명 부분일치(예: '반도체').
        year: 사업연도(귀속). 기본 2024. 예: 공급자금융약정은 2024 최초적용.
        companies: 회사명/고유번호 직접 지정(필터보다 우선, 비상장 포함 가능).
        max_companies: 조회 상한(API 호출수 보호). 기본 12.

    Returns:
        회사별 매칭 주석 섹션(제목·연결/별도·신뢰도·매칭사유·본문발췌·표).
        해당 연도가 인덱싱돼 있으면 인덱스(즉시·전수)로, 아니면 온디맨드로 검색.
    """
    # 특정 회사 지정이 없고 해당 연도가 인덱싱돼 있으면 인덱스 사용(즉시·API콜 0·전수)
    if not companies:
        n = index_search.year_indexed(year)
        if n:
            res = index_search.search_index(
                topic, markets=market, induty_prefix=industry_code,
                induty_contains=industry_name, year=year, max_companies=max_companies,
            )
            res["index_filings"] = n
            return res
    return search_mod.search_notes(
        _get_client(),
        topic=topic,
        markets=market,
        induty_prefix=industry_code,
        induty_contains=industry_name,
        year=year,
        companies=companies,
        max_companies=max_companies,
    )


@mcp.tool()
def get_company_note(company: str, topic: str, year: int = 2024) -> dict:
    """단일 회사의 특정 토픽 주석 '전문'(본문+표 전체)을 가져온다.

    Args:
        company: 회사명 또는 고유번호.
        topic: 회계이슈(등록 토픽키 또는 자유어).
        year: 사업연도. 기본 2024.
    """
    return search_mod.get_company_note(_get_client(), company=company, topic=topic, year=year)


@mcp.tool()
def list_note_topics() -> list[dict]:
    """등록된 정밀 토픽 규칙 목록(주제어·관점 facet·scope). 자유어도 가능하지만,
    반복 이슈는 규칙 등록 시 정밀도가 가장 높다."""
    return topics.list_topics()


@mcp.tool()
def list_industries(market: list[str] | None = None, contains: str | None = None) -> list[dict]:
    """메타 캐시에 실제 존재하는 업종(회사수 포함). 업종 필터값 선택에 사용.

    Args:
        market: 시장 필터(['코스피','코스닥' ...]).
        contains: 업종명 부분일치(예: '반도체','의약').
    """
    return company_meta.list_industries(markets=market, contains=contains)


@mcp.tool()
def resolve_company_info(name_or_code: str) -> dict:
    """회사명/고유번호 → 시장·업종 메타."""
    c = company_meta.resolve_company(_get_client(), name_or_code)
    if not c:
        return {"error": f"회사를 찾지 못함: {name_or_code}"}
    return {
        "corp_code": c.corp_code,
        "corp_name": c.corp_name,
        "stock_code": c.stock_code,
        "market": c.market,
        "induty_code": c.induty_code,
        "induty_name": c.induty_name,
    }


@mcp.tool()
def meta_status() -> dict:
    """시장×업종 메타 캐시 현황(시장별 회사수)."""
    return company_meta.status()


@mcp.tool()
def index_status() -> dict:
    """주석 전문 인덱스 현황(연도별 보고서 수·섹션 수). 인덱싱된 연도는 검색이
    즉시·전수로 동작한다. 인덱싱은 CLI `python -m dart_notes_mcp.index_build --year YYYY`."""
    return index_db.status()


@mcp.tool()
def build_company_meta(limit: int | None = None) -> dict:
    """(관리) 상장사 시장×업종 메타 캐시를 구축/갱신한다. 상장사 ~2,800개
    company.json 수집으로 수분 소요. 보통은 CLI `python -m dart_notes_mcp.build_meta`
    로 1회 실행 권장. limit로 일부만 테스트 가능."""
    return company_meta.build_meta(_get_client(), limit=limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
