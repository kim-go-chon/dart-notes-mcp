"""검색 파이프라인 오프라인 검증 (FakeClient, 네트워크/키 불필요).

search_notes / get_company_note의 보고서탐색·추출·캐시·랭킹·결과스키마를 검증.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dart_notes_mcp import search as search_mod  # noqa: E402
from dart_notes_mcp.company_meta import Company  # noqa: E402
from dart_notes_mcp.config import NOTES_CACHE_DIR  # noqa: E402
from dart_notes_mcp.dart_client import Disclosure  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


DOC_SFA = """<html><body>
<p>연결재무제표에 대한 주석</p>
<p>1. 일반사항</p><p>...</p>
<p>2. 공급자금융약정</p>
<p>당사는 금융제공자와 공급자금융약정(역팩토링)을 체결하고 있으며 연장지급 조건과 한도약정 사용 현황은 다음과 같습니다.</p>
<table><tr><td>구분</td><td>기말</td></tr><tr><td>공급자금융약정 부채</td><td>700</td></tr></table>
</body></html>"""

DOC_NONE = """<html><body>
<p>연결재무제표에 대한 주석</p>
<p>1. 차입금</p><p>금융약정과 미사용 약정한도는 다음과 같습니다.</p>
</body></html>"""

# corp_code -> (rcept_no, html)
FIXTURES = {
    "00000001": ("20250301000001", DOC_SFA),
    "00000002": ("20250301000002", DOC_NONE),
}
COMPANIES = {
    "회사A": Company("00000001", "회사A", "000001", "Y", "264", "유선 통신장비 제조업"),
    "회사C": Company("00000002", "회사C", "000002", "K", "264", "유선 통신장비 제조업"),
}


class FakeClient:
    def list_disclosures(self, corp_code, bgn_de, end_de, pblntf_ty="A", **kw):
        rcept, _ = FIXTURES[corp_code]
        return [Disclosure(corp_code, "회사", rcept, "사업보고서 (2024.12)", "20250301")]

    def document_files(self, rcept_no):
        for cc, (rc, html) in FIXTURES.items():
            if rc == rcept_no:
                return [("doc.xml", html)]
        return []


def _clean_cache():
    for cc, (rc, _) in FIXTURES.items():
        p = NOTES_CACHE_DIR / f"{rc}.json"
        if p.exists():
            p.unlink()


def main():
    _clean_cache()
    # resolve_company를 캐시 대신 픽스처로
    search_mod.resolve_company = lambda client, name: COMPANIES.get(name)

    client = FakeClient()

    print("[1] search_notes — 정밀검색 + 랭킹 + 스키마")
    res = search_mod.search_notes(
        client, topic="공급자금융약정",
        companies=["회사A", "회사C"], year=2024,
    )
    check(res["rule_key"] == "supplier_finance", "토픽 규칙 supplier_finance")
    check(res["companies_considered"] == 2, "2개사 조회")
    check(res["companies_with_hits"] == 1, f"히트 1개사 (got {res['companies_with_hits']})")
    if res["results"]:
        r0 = res["results"][0]
        check(r0["corp_name"] == "회사A", "히트 회사 = 회사A")
        check(r0["market"] == "코스피", "시장 라벨 = 코스피")
        check(r0["viewer_url"].startswith("https://dart.fss.or.kr"), "DART 뷰어 링크 존재")
        sec = r0["sections"][0]
        check(sec["title"].startswith("공급자금융약정"), "매칭 섹션 제목")
        check(sec["confidence"] == "high", f"신뢰도 high (got {sec['confidence']})")
        check(sec.get("tables_md") and "700" in sec["tables_md"][0], "표 포함")
    else:
        check(False, "결과 없음(예상과 다름)")

    print("[2] 캐시 생성 확인")
    check((NOTES_CACHE_DIR / "20250301000001.json").exists(), "파싱결과 디스크 캐시 생성")

    print("[3] get_company_note — 전문")
    note = search_mod.get_company_note(client, company="회사A", topic="공급자금융약정", year=2024)
    check(note["matched_count"] == 1, f"매칭 1건 (got {note.get('matched_count')})")
    check("700" in (note["matched_sections"][0]["tables_md"][0]), "전문 표 포함")

    print("[4] 음성 — 회사C 단독 검색은 0건")
    res2 = search_mod.search_notes(client, topic="공급자금융약정", companies=["회사C"], year=2024)
    check(res2["companies_with_hits"] == 0, "회사C 0건(노이즈 없음)")

    _clean_cache()
    print()
    if FAILS:
        print(f"❌ {len(FAILS)} FAIL")
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("✅ ALL PASS")


if __name__ == "__main__":
    main()
