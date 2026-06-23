"""오프라인 골든 테스트 (DART 키 불필요).

검증:
1. parse_notes: 번호+제목 섹션 분해, 연결/별도(fs_div) 태깅, 표 분리, 연속성 게이트.
2. 정밀매칭: 공급자금융약정 양성은 잡고, 함정 음성(금융약정·팩토링·상생협력)은 0건.
3. 비표준 위치(금융상품 주석 본문 내 SFA)도 required 토큰으로 잡음.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dart_notes_mcp.notes_parser import parse_notes  # noqa: E402
from dart_notes_mcp.topics import get_topic_rule, match_topic  # noqa: E402

# ---------- 픽스처 ----------
# 회사 A: 전용 '공급자금융약정' 주석(연결+별도). 함정으로 팩토링/금융약정도 포함.
DOC_A = ("company_A.xml", """
<html><body>
<p>연결재무제표에 대한 주석</p>
<p>제 53 기 2024.01.01 부터 2024.12.31 까지</p>
<p>1. 일반사항</p>
<p>지배기업은 ... 영위하고 있습니다.</p>
<p>2. 중요한 회계정책</p>
<p>연결재무제표는 한국채택국제회계기준에 따라 작성되었습니다.</p>
<p>3. 매출채권 및 기타채권</p>
<p>당사는 매출채권 일부를 금융기관에 팩토링으로 양도하였습니다.</p>
<table><tr><td>구분</td><td>금액</td></tr><tr><td>매출채권</td><td>1,000</td></tr></table>
<p>4. 차입금</p>
<p>당사의 차입금 약정 현황과 미사용 약정한도는 다음과 같으며, 금융약정에 따른 담보가 제공되어 있습니다.</p>
<table><tr><td>구분</td><td>한도</td><td>실행</td></tr><tr><td>운전자금</td><td>5,000</td><td>3,000</td></tr></table>
<p>5. 공급자금융약정</p>
<p>당사는 금융제공자와 공급자금융약정(역팩토링)을 체결하고 있습니다. 약정의 연장지급 조건과 한도약정 사용 현황, 비현금 변동은 다음과 같으며, 본 약정 관련 금융부채의 지급기일 범위는 매입채무와 비교하여 공시합니다.</p>
<table><tr><td>구분</td><td>기초</td><td>기말</td></tr><tr><td>공급자금융약정 관련 금융부채</td><td>500</td><td>700</td></tr></table>
<p>6. 특수관계자</p>
<p>지배기업 및 종속기업, 주요 경영진 보상 내역은 다음과 같습니다.</p>
<p>독립된 감사인의 감사보고서</p>
<p>우리는 ... 감사하였습니다.</p>
<p>재무제표에 대한 주석</p>
<p>1. 일반사항</p>
<p>회사는 ... (별도)</p>
<p>2. 공급자금융약정</p>
<p>회사(별도)는 금융제공자와 공급자금융약정(공급망금융)을 운영하며 매입채무금융 형태로 금융부채를 인식합니다.</p>
</body></html>
""")

# 회사 B: 전용 제목 없이 '금융상품 및 재무위험관리' 주석 본문에 SFA 서술.
DOC_B = ("company_B.xml", """
<html><body>
<p>연결재무제표에 대한 주석</p>
<p>1. 일반사항</p><p>...</p>
<p>2. 중요한 회계정책</p><p>...</p>
<p>3. 금융상품 및 재무위험관리</p>
<p>유동성위험 관리 목적상, 당사는 금융제공자가 참여하는 매입채무금융(공급망금융) 약정을 운영하고 있습니다. 해당 약정의 비현금 변동과 지급기일 범위는 아래와 같습니다.</p>
<p>4. 자본금</p><p>...</p>
</body></html>
""")

# 회사 C: SFA 없음. 함정 음성만(금융약정/미사용약정한도/상생협력).
DOC_C = ("company_C.xml", """
<html><body>
<p>연결재무제표에 대한 주석</p>
<p>1. 일반사항</p><p>...</p>
<p>2. 차입금</p>
<p>금융약정에 따른 미사용 약정한도와 대출약정 현황은 다음과 같습니다.</p>
<p>3. 상생협력</p>
<p>당사는 동반성장을 위해 상생협력 기금을 출연하였습니다.</p>
</body></html>
""")

# --- 전환사채 취득자(보유자) 회계처리 시나리오 ---
# 양성: 전환사채를 '금융자산'으로 보유(취득자 관점).
CB_HOLDER = ("cb_holder.xml", """
<html><body>
<p>재무제표에 대한 주석</p>
<p>1. 일반사항</p><p>...</p>
<p>2. 당기손익-공정가치 측정 금융자산</p>
<p>당사가 보유한 전환사채(취득한 전환사채)는 당기손익-공정가치 측정 금융자산으로 분류하며, 공정가치 평가손익을 인식합니다. 전환사채취득 원가와 기말 공정가치는 다음과 같습니다.</p>
<table><tr><td>구분</td><td>취득원가</td><td>공정가치</td></tr><tr><td>전환사채</td><td>900</td><td>1,050</td></tr></table>
</body></html>
""")
# 음성①(발행자): 회사가 전환사채를 '발행'(부채/자본). 취득자 아님.
CB_ISSUER = ("cb_issuer.xml", """
<html><body>
<p>재무제표에 대한 주석</p>
<p>1. 일반사항</p><p>...</p>
<p>2. 전환사채</p>
<p>당사는 운영자금 조달을 위해 전환사채를 발행하였으며, 전환권대가는 자본조정으로, 사채상환할증금은 부채로 인식하였습니다.</p>
</body></html>
""")
# 음성②(우연출현): 유형자산 '취득' + 다른 문장에 '전환사채' 언급. 자산분류 없음.
CB_COINCIDENT = ("cb_coincident.xml", """
<html><body>
<p>재무제표에 대한 주석</p>
<p>1. 일반사항</p><p>...</p>
<p>2. 유형자산</p>
<p>당기 중 기계장치를 취득하였습니다. 한편 당사는 과거 발행한 전환사채를 전액 상환하였습니다.</p>
</body></html>
""")

FAILS = []


def check(cond, msg):
    if cond:
        print(f"  PASS  {msg}")
    else:
        print(f"  FAIL  {msg}")
        FAILS.append(msg)


def test_parser():
    print("[1] 파서 — 섹션 분해 / fs_div / 표")
    secs = parse_notes([DOC_A])
    titles = [(s.fs_div, s.note_no, s.title) for s in secs]
    print("    sections:", titles)
    cfs = [s for s in secs if s.fs_div == "CFS"]
    ofs = [s for s in secs if s.fs_div == "OFS"]
    check(len(cfs) == 6, f"CFS 주석 6개 분해 (got {len(cfs)})")
    check(any(s.title.startswith("공급자금융약정") and s.fs_div == "CFS" for s in secs),
          "연결 '공급자금융약정' 섹션 존재")
    check(any(s.title.startswith("공급자금융약정") and s.fs_div == "OFS" for s in secs),
          "별도 '공급자금융약정' 섹션 존재(중복제거에도 보존)")
    sfa = next(s for s in secs if s.title.startswith("공급자금융약정") and s.fs_div == "CFS")
    check(len(sfa.tables_md) == 1 and "700" in sfa.tables_md[0], "SFA 섹션 표 분리 추출")
    check(all("감사보고서" not in s.title for s in secs), "감사보고서 경계 이후 미혼입")


def test_precision_positive():
    print("[2] 정밀매칭 — 양성(전용 제목 / 비표준 위치)")
    rule = get_topic_rule("공급자금융약정")  # 한국어 직접 입력 → supplier_finance 규칙
    check(rule.key == "supplier_finance", "'공급자금융약정' → supplier_finance 규칙 해석")

    for doc, who in [(DOC_A, "A(전용제목)"), (DOC_B, "B(금융상품 본문)")]:
        secs = parse_notes([doc])
        matched = [(s, match_topic(s, rule)) for s in secs]
        hits = [(s, m) for s, m in matched if m.matched]
        check(len(hits) >= 1, f"{who}: SFA 매칭 ≥1건 (got {len(hits)})")
        # 매칭된 건 모두 실제 SFA 섹션이어야(노이즈 0)
        for s, m in hits:
            ok = ("공급자금융약정" in s.search_text() or "매입채무금융" in s.search_text()
                  or "공급망금융" in s.search_text())
            check(ok, f"{who}: 매칭 '{s.title[:20]}' 은 진짜 SFA (conf={m.confidence})")


def test_precision_negative():
    print("[3] 정밀매칭 — 함정 음성(노이즈 0)")
    rule = get_topic_rule("공급자금융약정")
    secs = parse_notes([DOC_C])
    hits = [(s, match_topic(s, rule)) for s in secs]
    matched = [(s, m) for s, m in hits if m.matched]
    print("    C 섹션:", [(s.title, match_topic(s, rule).matched) for s in secs])
    check(len(matched) == 0, f"C(금융약정/팩토링/상생협력)에서 SFA 0건 (got {len(matched)})")
    # 차단 사유가 기록되는지
    cha = next(s for s in secs if s.title.startswith("차입금"))
    r = match_topic(cha, rule)
    check(not r.matched and any("BLOCKED" in x for x in r.reasons),
          f"차입금 노트 차단 사유 기록: {r.reasons}")


def test_negative_guard():
    print("[4] NEGATIVE 가드 — 신용카드/금융보증 단독은 SFA 아님")
    sec_doc = ("x.xml", """<html><body>
<p>재무제표에 대한 주석</p>
<p>1. 금융상품</p>
<p>당사는 신용카드 결제와 금융보증(보증용 신용장)을 이용하고 있습니다.</p>
</body></html>""")
    rule = get_topic_rule("공급자금융약정")
    secs = parse_notes([sec_doc])
    r = match_topic(secs[0], rule)
    check(not r.matched, f"신용카드/금융보증만 → 비매칭 ({r.reasons})")


def test_cb_holder():
    print("[5] 전환사채 취득자(보유자) — 관점 노이즈 제거")
    rule = get_topic_rule("전환사채 취득자 회계처리")
    check(rule.key == "convertible_bond_holder",
          f"'전환사채 취득자 회계처리' → 취득자 규칙 라우팅 (got {rule.key})")

    # 양성
    secs = parse_notes([CB_HOLDER])
    hit = [s for s in secs if match_topic(s, rule).matched]
    check(len(hit) == 1 and "금융자산" in hit[0].title,
          f"보유(금융자산) 전환사채 매칭 1건 (got {[s.title for s in hit]})")

    # 음성① 발행자
    secs = parse_notes([CB_ISSUER])
    res = [(s.title, match_topic(s, rule)) for s in secs]
    iss = next(s for s in secs if s.title.startswith("전환사채"))
    r = match_topic(iss, rule)
    check(not r.matched, f"발행자 전환사채 주석 → 비매칭 ({r.reasons})")

    # 음성② 우연출현(유형자산 취득)
    secs = parse_notes([CB_COINCIDENT])
    coin = next(s for s in secs if s.title.startswith("유형자산"))
    r = match_topic(coin, rule)
    check(not r.matched and any("facet" in x for x in r.reasons),
          f"유형자산 취득+전환사채 우연출현 → 비매칭(facet) ({r.reasons})")

    # 발행자 질의는 다른 토픽으로
    issuer_rule = get_topic_rule("전환사채 발행")
    check(issuer_rule.key == "convertible_bond",
          f"'전환사채 발행' → 발행자/일반 규칙 ({issuer_rule.key})")


def test_real_world_formats():
    print("[6] 실전 포맷 — 주석-prefix / 본문흡수 방지 / 정책노트 강등")

    # (A) XBRL 뷰어 export 포맷: '주석 - N. 제목 - 연결' (이마트 등)
    doc_juseok = ("emart.xml", """<html><body>
<p>3. 연결재무제표 주석</p>
<p>주석 - 1. 일반사항 - 연결 (연결)</p><p>지배기업은 ...</p>
<p>주석 - 2. 공급자금융약정 - 연결 (연결)</p>
<p>당사는 금융제공자와 공급자금융약정을 체결하고 있습니다.</p>
</body></html>""")
    secs = parse_notes([doc_juseok])
    titles = [s.title for s in secs]
    check(any(t == "공급자금융약정" for t in titles),
          f"'주석 - N. 제목' 포맷 파싱 (got {titles})")
    sfa = get_topic_rule("공급자금융약정")
    sfa_hit = [s for s in secs if match_topic(s, sfa).matched]
    check(any(s.title == "공급자금융약정" for s in sfa_hit), "주석-prefix 포맷에서 SFA 매칭")

    # (B) 마지막 노트가 사업보고서 후속본문(배당/마케팅)을 흡수하지 않음
    doc_absorb = ("absorb.xml", """<html><body>
<p>재무제표에 대한 주석</p>
<p>1. 일반사항</p><p>...</p>
<p>2. 보고기간 후 사건</p><p>중요한 사건 없음</p>
<p>6. 배당에 관한 사항</p>
<p>당사는 4K TV 144Hz 제품과 관련하여 전환사채를 발행하였고 특수관계자 거래가 있습니다.</p>
</body></html>""")
    secs = parse_notes([doc_absorb])
    last = next(s for s in secs if "보고기간" in s.title)
    check("144Hz" not in last.search_text() and "배당에 관한 사항" not in last.search_text(),
          f"STOP-phrase로 후속본문 미흡수 (body{len(last.body)}자)")
    # 흡수 안 됐으므로 특수관계자/SFA 검색 0건
    rp = get_topic_rule("특수관계자")
    check(not any(match_topic(s, rp).matched for s in secs), "흡수 차단 → 특수관계자 오탐 0")

    # (C) 회계정책/작성기준 노트의 일반 언급은 low + ⚠ 강등
    doc_policy = ("policy.xml", """<html><body>
<p>재무제표에 대한 주석</p>
<p>1. 일반사항</p><p>...</p>
<p>2. 재무제표 작성기준 및 중요한 회계정책</p>
<p>공급자금융약정 관련 기업회계기준서 제1007호, 제1107호 개정사항을 적용하였습니다.</p>
</body></html>""")
    secs = parse_notes([doc_policy])
    pol = next(s for s in secs if "작성기준" in s.title)
    m = match_topic(pol, sfa)
    check(m.matched and m.confidence == "low" and any("회계정책" in x for x in m.reasons),
          f"정책/작성기준 노트 → low+⚠ 강등 (conf={m.confidence})")


def test_decimal_and_adoption():
    print("[7] 소수점 번호 오분할 방지 + 기준채택 강등 + 실제공시 우선")
    doc = ("smallcap.xml", """<html><body>
<p>재무제표에 대한 주석</p>
<p>1. 일반사항</p>
<p>1.1 회사의 개요 당사는 자동차 부품을 제조합니다.</p>
<p>1.2 종속기업의 현황 당기말 현재 종속기업은 다음과 같습니다.</p>
<p>2. 재무제표 작성기준 및 중요한 회계정책</p>
<p>2.1 당사는 공급자금융약정 관련 기업회계기준서 제1007호 개정사항을 당기부터 적용하였습니다.</p>
<p>3. 매입채무 및 기타채무</p>
<p>당사는 금융제공자와 공급자금융약정을 운영하고 있으며, 본 약정 관련 금융부채의 지급기일 범위는 다음과 같습니다.</p>
</body></html>""")
    secs = parse_notes([doc])
    titles = [s.title for s in secs]
    print("    sections:", [(s.note_no, s.title[:24]) for s in secs])
    check(all(not s.title[:1].isdigit() for s in secs),
          f"소수점 하위번호가 별도 섹션으로 안 잡힘 (titles={titles})")
    check(any(t.startswith("매입채무") for t in titles), "'매입채무 및 기타채무' 섹션 분해")

    rule = get_topic_rule("공급자금융약정")
    matched = [(s, match_topic(s, rule)) for s in secs]
    matched = [(s, m) for s, m in matched if m.matched]
    top = max(matched, key=lambda x: x[1].score)
    check(top[0].title.startswith("매입채무") and top[1].confidence != "low",
          f"실제공시(매입채무)가 최상위·non-low (top={top[0].title[:20]} {top[1].confidence})")
    pol = next((m for s, m in matched if "작성기준" in s.title), None)
    check(pol is not None and pol.confidence == "low",
          "작성기준(기준채택) 노트는 low 강등")


def test_security_and_robustness():
    print("[8] 보안·견고성 회귀 (Codex 리뷰 반영)")
    from dart_notes_mcp.notes_parser import NoteSection
    from dart_notes_mcp.search import (
        _cache_path, _clamp_int, _validate_markets, _validate_year,
    )

    def sec(title, body):
        return NoteSection("CFS", 1, title, body)

    # (a) 악성 rcept_no → path traversal 차단
    blocked = False
    try:
        _cache_path("../../evil")
    except ValueError:
        blocked = True
    check(blocked, "악성 rcept_no(_cache_path) 차단")
    check(_cache_path("20250311001085").name == "20250311001085.json", "정상 14자리 rcept_no 허용")

    # (b) 입력 검증
    for bad in [-1, 1800, 2100, True, "2024"]:
        ok = False
        try:
            _validate_year(bad)
        except ValueError:
            ok = True
        check(ok, f"year={bad!r} 거부")
    check(_clamp_int(-1, 1, 50, "x") == 1, "max_companies=-1 → 1 클램프(음수 슬라이스 우회 차단)")
    check(_clamp_int(9999, 1, 50, "x") == 50, "max_companies 상한 클램프")
    okm = False
    try:
        _validate_markets(["화성"])
    except ValueError:
        okm = True
    check(okm, "알 수 없는 시장 거부")

    # (c) '리스' 부분문자열 오탐 차단
    rule = get_topic_rule("리스")
    check(not match_topic(sec("리스크 관리", "시장위험 및 신용위험을 관리"), rule).matched,
          "'리스크 관리' → 리스 비매칭(title-exclude)")
    check(not match_topic(sec("금융리스채권", "리스료를 수취"), rule).matched,
          "'금융리스채권'(리스제공자 채권) → 비매칭")
    check(match_topic(sec("리스", "사용권자산과 리스부채를 인식"), rule).matched,
          "실제 리스 노트 → 매칭")

    # (d) 전환사채 취득자: '발행' 단어가 있어도 채무증권 분류면 매칭(false negative 보완)
    cbh = get_topic_rule("전환사채 취득자 회계처리")
    s = sec("금융자산", "타사가 발행한 전환사채를 취득하여 보유 중이며 채무증권으로 분류")
    check(match_topic(s, cbh).matched, "발행+채무증권 분류 → 취득자 매칭(perspective_strong)")


if __name__ == "__main__":
    test_parser()
    test_precision_positive()
    test_precision_negative()
    test_negative_guard()
    test_cb_holder()
    test_real_world_formats()
    test_decimal_and_adoption()
    test_security_and_robustness()
    print()
    if FAILS:
        print(f"❌ {len(FAILS)} FAIL")
        for f in FAILS:
            print("   -", f)
        sys.exit(1)
    print("✅ ALL PASS")
