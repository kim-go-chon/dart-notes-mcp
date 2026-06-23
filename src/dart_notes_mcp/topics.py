"""토픽 정밀매칭 엔진.

핵심: '유사 키워드 난잡 검색' 차단. 단순 grep이 아니라
  TITLE-ANCHOR(제목 정확매칭) > SUBJECT(주제 동의어 AND) > FACET(관점/aspect AND)
  > PERSPECTIVE(발행자 vs 취득자 등 관점 차단) > BOOST(가산) > EXCLUDE/NEGATIVE(차단)
계층으로 판정한다. 노이즈를 낼 바엔 비매칭(precision 우선).

두 가지 노이즈를 동시에 막는다:
 1) 주제는 맞지만 관계없는 주석에 키워드만 있는 경우(예: '전환사채','취득' 단순 동시출현).
 2) 같은 주제라도 관점이 다른 경우(예: 발행자 회계처리 ↔ 취득자 회계처리).

모든 비교는 공백제거 + ascii 소문자(_key) 후 부분문자열 매칭 → '공급자 금융약정'='공급자금융약정'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .notes_parser import NoteSection


def _key(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


# 회계정책/요약 노트 — 거의 모든 토픽을 일반 언급으로 포함 → 실제 공시와 구분(강등·태깅)
# 거의 모든 토픽을 '일반 언급'으로 포함하는 노트(정책·기준채택·개요) → 강등·태깅.
# 실제 공시(매입채무·금융위험·우발채무·전용노트 등)와 구분.
_POLICY_TITLE_MARKERS = [
    "회계정책", "회계처리방침", "유의적인회계", "중요한회계", "회계추정", "회계방침",
    "작성기준",
    # 기준 제·개정 채택 보일러플레이트
    "제개정", "제ㆍ개정", "기준서의적용", "기준서적용", "공시의변경",
    "새로운기준서", "개정된기준서", "기준서및해석서", "채택한기준서",
    # 일반정보 노트(실제 공시 위치가 아님 — 흡수/단순언급)
    "일반사항", "일반적사항", "회사의개요", "당사의개요",
    "종속기업의현황", "연결대상종속기업", "연결대상",
]


@dataclass
class TopicRule:
    key: str
    label: str
    title_anchors: list[str] = field(default_factory=list)       # 제목 정확매칭 → 고신뢰
    title_exclude: list[str] = field(default_factory=list)       # 제목에 있으면 하드 배제(부분문자열 오탐 차단)
    required_any: list[list[str]] = field(default_factory=list)  # 주제: 각 그룹 1개 이상(AND)
    facet_required: list[list[str]] = field(default_factory=list)  # 관점/aspect: 추가 AND 그룹
    perspective_exclude: list[str] = field(default_factory=list)   # 잘못된 관점 신호(발행자 등)
    perspective_strong: list[str] = field(default_factory=list)    # 이게 있으면 perspective_exclude 무시
    boost: list[str] = field(default_factory=list)
    exclude_solo: list[str] = field(default_factory=list)        # required 없이 단독이면 차단
    negative_guards: list[str] = field(default_factory=list)
    scope_titles: list[str] = field(default_factory=list)

    def norm(self) -> "TopicRule":
        k = _key
        return TopicRule(
            key=self.key,
            label=self.label,
            title_anchors=[k(x) for x in self.title_anchors],
            title_exclude=[k(x) for x in self.title_exclude],
            required_any=[[k(x) for x in g] for g in self.required_any],
            facet_required=[[k(x) for x in g] for g in self.facet_required],
            perspective_exclude=[k(x) for x in self.perspective_exclude],
            perspective_strong=[k(x) for x in self.perspective_strong],
            boost=[k(x) for x in self.boost],
            exclude_solo=[k(x) for x in self.exclude_solo],
            negative_guards=[k(x) for x in self.negative_guards],
            scope_titles=[k(x) for x in self.scope_titles],
        )


@dataclass
class MatchResult:
    matched: bool
    score: float
    confidence: str          # 'high' | 'medium' | 'low'
    reasons: list[str] = field(default_factory=list)


def match_topic(section: NoteSection, rule: TopicRule) -> MatchResult:
    r = rule.norm()
    nt = _key(section.title)
    # 제목 하드 배제(부분문자열 오탐: '리스'→'리스크/리스트', '금융리스채권' 등) — title-anchor보다 먼저
    te = next((x for x in r.title_exclude if x and x in nt), None)
    if te:
        return MatchResult(False, 0.0, "low", [f"BLOCKED title-exclude '{te}'"])
    ntext = _key(section.search_text())
    reasons: list[str] = []

    title_hit = next((a for a in r.title_anchors if a and a in nt), None)

    # 주제 + 관점 = 모두 AND
    groups = r.required_any + r.facet_required
    req_hits: list[str] = []
    required_ok = bool(groups)
    for group in groups:
        hit = next((tok for tok in group if tok and tok in ntext), None)
        if hit:
            req_hits.append(hit)
        else:
            required_ok = False

    boost_hits = [b for b in r.boost if b and b in ntext]
    scope_hit = next((s for s in r.scope_titles if s and s in nt), None)

    # ---- 1) 제목 정확매칭: 최고신뢰 ----
    if title_hit:
        score = 100 + 8 * min(len(boost_hits), 5)
        reasons.append(f"TITLE-ANCHOR '{title_hit}'")
        if boost_hits:
            reasons.append(f"BOOST {boost_hits}")
        return MatchResult(True, score, "high", reasons)

    # ---- 2) 주제+관점 AND 충족 ----
    if required_ok:
        # 관점 차단: 잘못된 관점 신호가 있고, 강한 관점 신호가 없으면 탈락
        if r.perspective_exclude:
            bad = next((g for g in r.perspective_exclude if g in ntext), None)
            good = any(s in ntext for s in r.perspective_strong)
            if bad and not good:
                return MatchResult(
                    False, 0.0, "low",
                    [f"BLOCKED perspective '{bad}' (관점 불일치 — {r.label} 아님, 강한신호 없음)"],
                )
        score = 60 + 8 * min(len(boost_hits), 5) + (10 if scope_hit else 0)
        is_policy = any(p in nt for p in _POLICY_TITLE_MARKERS)
        if is_policy:
            reasons.append("⚠ 회계정책/방침 노트의 일반 언급 — 실제 공시 아닐 수 있음")
        reasons.append(f"REQUIRED {req_hits}")
        if boost_hits:
            reasons.append(f"BOOST {boost_hits}")
        if scope_hit:
            reasons.append(f"SCOPE-title '{scope_hit}'")
        if is_policy:
            return MatchResult(True, max(score - 45, 12), "low", reasons)
        conf = "high" if len(boost_hits) >= 2 else "medium"
        return MatchResult(True, score, conf, reasons)

    # ---- 3) 비매칭: 차단 사유 기록(투명성) ----
    neg = next((g for g in r.negative_guards if g and g in ntext), None)
    if neg:
        reasons.append(f"BLOCKED negative-guard '{neg}' (주제 동의어 없음)")
    ex = next((e for e in r.exclude_solo if e and e in ntext), None)
    if ex:
        reasons.append(f"BLOCKED exclude-solo '{ex}' (주제 동의어 없음)")
    # 주제는 맞지만 관점/aspect 미충족
    subj_ok = bool(r.required_any) and all(
        any(t in ntext for t in g) for g in r.required_any
    )
    if subj_ok and r.facet_required:
        reasons.append("BLOCKED facet 미충족 (주제어는 있으나 해당 관점/aspect 신호 없음 = 키워드 우연출현)")
    return MatchResult(False, 0.0, "low", reasons)


# ---------- 토픽 사전 ----------
TOPICS: dict[str, TopicRule] = {
    "supplier_finance": TopicRule(
        key="supplier_finance",
        label="공급자금융약정 (IAS7 44F~44H / IFRS7 B11F)",
        title_anchors=["공급자금융약정", "supplier finance arrangement", "supplier finance arrangements"],
        required_any=[[
            "공급자금융약정", "역팩토링", "reverse factoring",
            "공급망금융", "매입채무금융", "supply chain finance",
        ]],
        boost=[
            # 44H 실제 공시항목 표현(보일러플레이트 아님). 기준번호(제1007호 등)는
            # '채택 보일러플레이트' 신호라 boost에서 제외(false high 방지).
            "금융제공자", "연장지급", "지급기일 범위", "한도약정", "비현금 변동",
            "문단44F", "문단44G", "문단44H", "B11F",
            "은행기한부신용장", "banker's usance", "bankers usance",
        ],
        exclude_solo=[
            "금융약정", "차입약정", "대출약정", "약정사항", "미사용 약정한도",
            "팩토링", "매출채권 유동화", "상생협력",
        ],
        negative_guards=["신용카드", "금융보증", "보증용 신용장"],
        scope_titles=[
            "금융상품", "재무위험관리", "유동성위험", "매입채무 및 기타채무",
            "매입채무", "차입금", "현금흐름표",
        ],
    ),
    # 전환사채 — '취득자(보유자)' 관점. 발행자 주석/우연출현 노이즈를 모두 배제.
    "convertible_bond_holder": TopicRule(
        key="convertible_bond_holder",
        label="전환사채 — 취득자(보유자) 회계처리 (금융자산으로 보유)",
        title_anchors=[],  # 전용 제목 거의 없음 → 주제+관점으로 판정
        required_any=[["전환사채", "전환상환우선주", "전환우선주"]],
        # 관점(FACET): 실제 '취득·보유' 명시 밀착구문만 인정.
        # ★광의 자산분류어(금융자산/매도가능증권/지분증권 등)는 회계정책 보일러플레이트·발행자
        #   노트에도 등장해 대량 오탐 유발 → facet에서 제외(2026-06-23 라이브 스캔서 238건 노이즈 확인).
        facet_required=[[
            "전환사채취득", "전환사채를취득", "취득한전환사채", "전환사채를보유",
            "보유한전환사채", "보유중인전환사채", "전환사채매입", "전환사채를매입",
            "전환사채에투자", "전환사채투자", "전환사채를인수",
        ]],
        # 발행자 관점이면 차단 — 단, 자산분류(강한신호)가 있으면 진짜 취득자이므로 유지
        perspective_exclude=[
            "발행", "전환권대가", "전환권조정", "자본조정", "사채상환할증금",
            "신주인수권조정", "사채할인발행차금", "자기사채",
        ],
        perspective_strong=[
            "금융자산", "매도가능증권", "단기매매증권", "당기손익-공정가치",
            "기타포괄손익-공정가치", "투자주식", "투자유가증권", "투자자산",
            "상각후원가측정금융자산", "당기손익인식금융자산", "채무증권", "지분증권",
        ],
        boost=["공정가치", "손상", "처분", "평가손익", "이자수익", "전환권"],
        scope_titles=["금융자산", "투자자산", "유가증권", "지분증권", "매도가능"],
    ),
    # 전환사채 — 발행자/일반 관점(취득자 토픽과 분리).
    "convertible_bond": TopicRule(
        key="convertible_bond",
        label="전환사채/신주인수권부사채 (발행자·일반)",
        title_anchors=["전환사채", "신주인수권부사채"],
        required_any=[["전환사채", "신주인수권부사채", "전환우선주"]],
        boost=["전환권", "전환가액", "상환할증금", "파생상품부채", "전환청구", "발행"],
        scope_titles=["사채", "차입금"],
    ),
    "related_party": TopicRule(
        key="related_party",
        label="특수관계자 거래",
        title_anchors=["특수관계자"],
        required_any=[["특수관계자"]],
        boost=["지배기업", "종속기업", "관계기업", "주요 경영진", "특수관계자거래", "채권채무"],
        scope_titles=["특수관계자"],
    ),
    "lease": TopicRule(
        key="lease",
        label="리스 (사용권자산/리스부채, K-IFRS 1116)",
        title_anchors=["리스"],
        # '리스' 부분문자열 오탐(리스크/리스트) + 리스제공자 채권 노트 배제
        title_exclude=["리스크", "리스트", "리스닝", "금융리스채권"],
        required_any=[[
            "사용권자산", "리스부채", "리스료", "운용리스", "금융리스",
            "리스이용", "리스기간", "리스개시", "리스계약",
        ]],
        boost=["사용권자산", "리스부채", "리스료", "증분차입이자율", "단기리스"],
        scope_titles=["리스"],
    ),
    "contingency": TopicRule(
        key="contingency",
        label="우발부채 및 약정사항",
        title_anchors=["우발부채", "우발채무", "약정사항", "우발상황"],
        required_any=[["우발부채", "우발채무", "계류 중인 소송", "지급보증", "견질"]],
        boost=["소송", "지급보증", "담보제공", "약정한도", "손해배상"],
        scope_titles=["우발", "약정"],
    ),
    # 수익인식(IFRS15) — '매출'·'수익' 보편어 난잡검색 차단(IFRS15 고유어 요구)
    "revenue_recognition": TopicRule(
        key="revenue_recognition",
        label="수익인식 (고객과의 계약, K-IFRS 1115)",
        title_anchors=["수익인식", "고객과의 계약", "고객과의계약에서생기는수익"],
        required_any=[[
            "수익인식", "수행의무", "고객과의 계약", "거래가격", "계약부채", "계약자산",
        ]],
        boost=[
            "수행의무", "거래가격", "진행기준", "계약자산", "계약부채", "변동대가",
            "기간에 걸쳐", "한 시점에", "일시점", "본인과 대리인", "반품",
        ],
        exclude_solo=["매출액", "매출원가", "매출채권"],  # IFRS15 고유어 없이 단독이면 차단
        scope_titles=["수익", "매출"],
    ),
    # 영업권 손상 — '손상'은 모든 자산에 등장 → 영업권 AND 손상신호(2그룹) 요구
    "goodwill_impairment": TopicRule(
        key="goodwill_impairment",
        label="영업권 손상검사 (K-IFRS 1036)",
        title_anchors=["영업권손상", "영업권손상검사", "영업권및무형자산손상"],
        required_any=[
            ["영업권"],
            ["손상", "회수가능액", "현금창출단위", "사용가치", "손상차손", "손상검사"],
        ],
        boost=[
            "회수가능액", "사용가치", "처분부대원가", "할인율", "손상차손",
            "현금창출단위", "영업권 배분", "성장률", "민감도",
        ],
        scope_titles=["영업권", "무형자산"],
    ),
    # 확정급여제도(DB) — 확정기여(DC) 단독 배제, 보험수리적 가정 중심
    "defined_benefit": TopicRule(
        key="defined_benefit",
        label="확정급여제도 / 보험수리적 가정 (K-IFRS 1019)",
        title_anchors=["확정급여", "순확정급여부채", "퇴직급여"],
        required_any=[["확정급여", "순확정급여", "보험수리적", "사외적립자산"]],
        boost=[
            "보험수리적", "할인율", "제도자산", "재측정요소", "사외적립자산",
            "예상임금상승률", "기대수익", "기여금", "급여지급",
        ],
        exclude_solo=["확정기여"],  # 확정기여만 있으면 DB 아님
        scope_titles=["퇴직급여", "종업원급여", "확정급여"],
    ),
    # 기대신용손실(ECL, IFRS9) — 손상/충당금 보편어와 구분
    "ecl": TopicRule(
        key="ecl",
        label="기대신용손실 / 손실충당금 (K-IFRS 1109)",
        title_anchors=["기대신용손실", "신용위험", "손실충당금"],
        required_any=[[
            "기대신용손실", "expected credit loss", "신용손실", "손실충당금", "신용위험",
        ]],
        boost=[
            "12개월", "전체기간", "채무불이행", "연체", "신용위험 유의적",
            "손실충당금", "신용등급", "회수율", "부도율",
        ],
        scope_titles=["금융상품", "매출채권", "금융자산", "신용위험"],
    ),
    # 주식기준보상(IFRS2)
    "share_based_payment": TopicRule(
        key="share_based_payment",
        label="주식기준보상 / 주식선택권 (K-IFRS 1102)",
        title_anchors=["주식기준보상", "주식선택권", "주식매수선택권", "주식보상"],
        required_any=[[
            "주식기준보상", "주식선택권", "주식매수선택권", "주식결제형", "현금결제형",
        ]],
        boost=[
            "공정가치", "가득조건", "행사가격", "부여", "보상원가",
            "이항모형", "블랙숄즈", "기대주가변동성", "가득기간",
        ],
        scope_titles=["주식기준보상", "자본", "주식선택권"],
    ),
}

# 자유어 → 토픽 라우팅(intent). (조건자, 토픽키). 위에서부터 먼저 매칭.
_ALIASES: list[tuple] = [
    # 전환사채 + 취득/보유/투자 + (발행 아님) → 취득자
    (lambda q: "전환사채" in q and any(w in q for w in ("취득", "보유", "투자", "매입")) and "발행" not in q,
     "convertible_bond_holder"),
    (lambda q: "전환사채" in q,  # 그 외 전환사채 질의 → 발행자/일반
     "convertible_bond"),
    (lambda q: any(w in q for w in ("공급자금융", "역팩토링", "공급망금융", "매입채무금융", "reverse factoring")),
     "supplier_finance"),
    (lambda q: any(w in q for w in ("수익인식", "매출인식", "수행의무", "고객과의계약", "고객과의 계약")),
     "revenue_recognition"),
    (lambda q: ("영업권" in q or "goodwill" in q) and any(w in q for w in ("손상", "회수가능", "검사", "impair")),
     "goodwill_impairment"),
    (lambda q: any(w in q for w in ("확정급여", "보험수리", "퇴직급여", "사외적립")),
     "defined_benefit"),
    (lambda q: any(w in q for w in ("기대신용손실", "ecl", "손실충당금", "신용위험")),
     "ecl"),
    (lambda q: any(w in q for w in ("주식기준보상", "주식선택권", "주식매수선택권", "스톡옵션", "스톡 옵션", "stock option")),
     "share_based_payment"),
]

# 자유어 required 토큰에서 제외할 일반어
_STOPWORDS = {
    "회계처리", "회계", "처리", "관련", "방법", "사항", "내역", "현황", "기준",
    "등", "및", "에", "대한", "의", "를", "을", "은", "는", "이", "가", "와", "과",
}


def get_topic_rule(topic: str) -> TopicRule:
    """등록 토픽키/라벨/앵커 → 사전 규칙. intent 라우팅 → 사전 규칙.
    그 외 자유어 → 모든 의미토큰 AND(정밀) 규칙."""
    t = topic.strip()
    if t in TOPICS:
        return TOPICS[t]

    qk = _key(t)
    # 라벨/앵커 정확일치
    for rule in TOPICS.values():
        if qk == _key(rule.label) or qk in [_key(a) for a in rule.title_anchors]:
            return rule
    # intent 라우팅(주제+관점 결합 우선). 영문 토큰 대비 소문자 비교.
    tl = t.lower()
    for pred, key in _ALIASES:
        try:
            if pred(tl):
                return TOPICS[key]
        except Exception:
            pass
    # 자유어: 의미토큰 전부 AND(정밀). DART의 OR식 난잡검색과 정반대.
    tokens = [w for w in re.split(r"[\s,/·]+", t) if w and _key(w) not in _STOPWORDS and len(w) >= 2]
    if not tokens:
        tokens = [t]
    # 의미토큰이 1개고 그것이 등록 토픽 앵커/키와 정확히 일치하면 그 규칙(예: '리스 회계처리'→lease)
    if len(tokens) == 1:
        wk = _key(tokens[0])
        for rule in TOPICS.values():
            if wk == rule.key or wk in [_key(a) for a in rule.title_anchors]:
                return rule
    return TopicRule(
        key="freetext",
        label=f"자유어(전 토큰 AND): {t}",
        title_anchors=[t],
        required_any=[[w] for w in tokens],
    )


def list_topics() -> list[dict]:
    out = []
    for r in TOPICS.values():
        out.append({
            "key": r.key,
            "label": r.label,
            "title_anchors": r.title_anchors,
            "subject(required)": r.required_any,
            "facet(관점)": r.facet_required,
            "perspective_exclude": r.perspective_exclude,
            "scope_titles": r.scope_titles,
        })
    return out
