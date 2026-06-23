# dart-notes-mcp

DART 전자공시 **재무제표 주석(footnotes) 정밀검색** MCP.
회계사가 주석을 작성할 때 *"다른 회사는 이 회계이슈를 주석에 어떻게 썼나"* 를
**시장(코스피/코스닥/코넥스/비상장)·업종(KSIC)별로, 정확히** 찾기 위한 도구.

## 왜 직접 만들었나 (DART API의 한계)

- DART Open API에는 **공시 본문(주석) 내용을 검색하는 엔드포인트가 없다.**
  공시검색(`list.json`)은 회사·날짜·보고서명 같은 **메타데이터만** 검색한다.
- 주석 본문은 오직 **공시원문 `document.xml`(ZIP, EUC-KR)** 안의 회사별 HTML에만 있다.
- 그래서 이 MCP는 **원문 다운로드 → 주석을 섹션으로 분해 → 토픽 정밀매칭** 을 직접 수행한다.

## 정밀도가 핵심 (단순 키워드 검색과 다른 점)

DART/일반검색은 "전환사채 취득"을 치면 **전환사채·취득 키워드가 우연히 같이 있는
주석까지 전부** 나온다. 이 MCP는 **토픽별 규칙**으로 노이즈를 차단한다:

| 계층 | 역할 | 예 (공급자금융약정) |
|---|---|---|
| TITLE-ANCHOR | 주석 제목 정확매칭 → 고신뢰 | 제목 `공급자금융약정` |
| SUBJECT (required AND) | 주제 동의어 중 1+ 필수 | 공급자금융약정·역팩토링·공급망금융·매입채무금융 |
| FACET (관점 AND) | 관점/aspect 신호 필수 | (전환사채 취득자) 금융자산·매도가능증권 분류 |
| PERSPECTIVE | 잘못된 관점 차단 | (취득자) 발행자 신호 `발행·전환권대가` 배제 |
| EXCLUDE / NEGATIVE | 보편어·예외 차단 | 금융약정·팩토링·상생협력 / 신용카드·금융보증 |

→ **노이즈를 낼 바엔 0건 반환**(precision 우선). 매칭마다 `reasons`로 *왜 잡혔는지* 표시.

내장 토픽(11종):
- `supplier_finance`(공급자금융약정), `convertible_bond_holder`(전환사채 취득자),
  `convertible_bond`(발행자), `related_party`(특수관계자), `lease`(리스), `contingency`(우발부채)
- `revenue_recognition`(수익인식 IFRS15), `goodwill_impairment`(영업권 손상),
  `defined_benefit`(확정급여/보험수리적), `ecl`(기대신용손실), `share_based_payment`(주식기준보상)

자유어도 가능(전 토큰 AND + intent 라우팅). 반복 이슈는 `src/dart_notes_mcp/topics.py`에
규칙 한 줄 추가 시 정밀도가 가장 높다(예: 영업권 손상 = 영업권 AND 손상신호 2그룹 요구로
'손상' 보편어 노이즈 차단).

## 아키텍처 (하이브리드 v1)

- **메타 캐시(1회)**: 상장사 시장구분(`corp_cls`)·업종(`induty_code`→KSIC명)을 SQLite에 캐시
  → 시장×업종 필터는 런타임 API 호출 0.
- **온디맨드 검색**: 필터로 동종 N개사 선정 → 최신 사업보고서 원문 → 섹션분해 → 정밀매칭.
- **lazy 인덱스**: 파싱된 주석은 `rcept_no`별 디스크 캐시 → 재검색 시 재사용(v2 영구인덱스 seed).

## 설치 & 설정

```powershell
cd C:\Users\kyhh0\dart-notes-mcp
python -m pip install -e .
```

1) **인증키**: `.env.example` → `.env` 복사 후 `DART_API_KEY=<40자 키>` 입력.

2) **메타 캐시 구축**(1회, 상장사 ~2,800개·수분):
```powershell
python -m dart_notes_mcp.build_meta          # 전체
python -m dart_notes_mcp.build_meta --limit 300   # 빠른 테스트
```

3) **MCP 등록** (Claude Code / Desktop `claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "dart-notes": {
      "command": "python",
      "args": ["-m", "dart_notes_mcp.server"],
      "cwd": "C:\\Users\\kyhh0\\dart-notes-mcp"
    }
  }
}
```

## MCP 도구

| 도구 | 용도 |
|---|---|
| `search_company_notes(topic, market?, industry_code?, industry_name?, year?, companies?, max_companies?)` | **핵심** — 여러 회사 주석 정밀검색 |
| `get_company_note(company, topic, year?)` | 단일 회사 주석 전문(표 포함) |
| `list_note_topics()` | 등록된 정밀 토픽 규칙 |
| `list_industries(market?, contains?)` | 캐시에 존재하는 업종(회사수) |
| `resolve_company_info(name_or_code)` | 회사 → 시장·업종 메타 |
| `meta_status()` | 캐시 현황 |
| `build_company_meta(limit?)` | (관리) 메타 캐시 구축 |

### 예시
- "코스피 반도체 업종에서 **공급자금융약정** 2024 주석 보여줘"
  → `search_company_notes(topic="공급자금융약정", market=["코스피"], industry_name="반도체", year=2024)`
- "**전환사채 취득자 회계처리** 사례 (발행자·우연출현 제외)"
  → `search_company_notes(topic="전환사채 취득자 회계처리", year=2024)`

## 라이브 검증 결과 (2024 사업보고서, 실측)

공급자금융약정으로 대형 제조·유통사 검증 — **실제 공시는 medium/high, 정책 보일러플레이트는 low ⚠ 로 정확히 분리**:

| 회사 | 판정 | 매칭 위치 |
|---|---|---|
| 한온시스템 | ★ high | 전용노트 "공급자금융약정" (TITLE-ANCHOR) |
| 현대모비스·현대제철·삼성전기 | ★ medium | "매입채무 및 기타채무" 주석 |
| 기아 | ★ medium | "금융위험 관리" 주석 |
| 포스코인터내셔널 | ★ medium | "우발채무와 약정사항"(공급망금융) |
| 삼성전자·이마트·롯데쇼핑·현대위아 | low ⚠ | 회계정책/작성기준 노트의 일반 언급뿐(실제 공시 없음) |

파서는 삼성전자(64섹션)·이마트(주석-prefix 포맷)·현대제철(86섹션) 등 **서로 다른 HTML 포맷에서 모두 정상 섹션 분해**. 실전에서 발견한 함정(마지막 노트의 본문 흡수, `144Hz`→`44h` 오탐, 정책노트 일반언급)은 모두 차단·테스트에 고정.

## 한계 (정직한 고지)

- **비상장(E)** 은 전수 enumeration이 비현실적 → `companies=[회사명]` 지정 시 on-demand 조회.
  (메타 캐시는 상장사 기준. 비상장 업종필터는 v1 미지원)
- 주석 HTML은 회사·연도·감사인별 편차가 커, 드물게 섹션 분해가 빗나갈 수 있음
  (번호 연속성 게이트로 완화). **결론·조서 인용 전 DART 원문 대사 권장.**
- 연결(CFS)·별도(OFS) 주석을 모두 보존(수치가 다를 수 있어 임의 dedup 안 함).
- `year`는 사업연도(귀속). 공급자금융약정은 **2024 최초적용**.

## 테스트 (네트워크/키 불필요)
```powershell
python tests\test_core.py            # 파서 + 정밀매칭(양성/함정음성)
python tests\test_search_offline.py  # 검색 파이프라인(FakeClient)
```

## 보안 (Codex GPT-5.5 리뷰 반영)

- **인증키 비커밋**: `DART_API_KEY`는 `.env`에만(`.gitignore`로 `*.env` 차단). 코드 하드코딩 없음.
- **키 누출 방지**: httpx 예외 문자열에 요청 URL(=키)이 포함될 수 있어, 오류는 상태코드/타입명만 노출.
- **ZIP 폭탄 방어**: 공시원문 ZIP의 응답크기·엔트리수·비압축 총량 상한 검증.
- **경로 검증**: 캐시 파일명(`rcept_no`)은 14자리 숫자만 허용 + 디렉터리 이탈 차단.
- **입력 검증**: `year`(1999~2027)·`max_companies`(1~50 클램프, 음수 슬라이스 우회 차단)·시장 화이트리스트.
- **프롬프트 인젝션 방어**: 반환되는 DART 공시 본문은 신뢰불가 데이터임을 `content_safety`로 명시.
- **XXE/엔티티 폭탄**: corpCode XML 파싱에 `defusedxml`(설치 시) 적용. 리다이렉트 추적 비활성화.

향후(권고): 보고서 조회 결과 캐시, bounded concurrency, 토픽 규칙 추가 확장.

## 데이터 출처 / 라이선스

- 공시 데이터: 금융감독원 **OPEN DART**(opendart.fss.or.kr) — 본 도구는 비공식 클라이언트.
- 업종 매핑(`data/ksic/`): 통계청 한국표준산업분류(KSIC) 기반, [FinanceData/KSIC](https://github.com/FinanceData/KSIC).
- 본 도구 코드: MIT License (`LICENSE`).
- ⚠ 인증키(`DART_API_KEY`)는 `.env`에만 두며 저장소에 커밋하지 않는다(`.gitignore`).
