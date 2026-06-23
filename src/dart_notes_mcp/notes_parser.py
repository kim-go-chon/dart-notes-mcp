"""공시원문 HTML/XML → 주석 섹션 분해.

검증된 사실 기반 설계:
- 주석은 의미적 heading 태그가 없고 <p>/텍스트 + 볼드 + <table>로만 표현된다.
- 'N. 제목'(number-dot-title) 관행이나 강제표준이 아니다(회사·연도·감사인별 편차).
- 연결(CFS)·별도(OFS) 주석이 한 보고서/ZIP에 모두 들어가며 수치가 다를 수 있다.

전략: 문서를 (텍스트라인 | 표) 블록열로 평탄화 → '재무제표에 대한 주석' 앵커로
주석 영역만 잘라냄 → 번호 '연속성 게이트'로 섹션 split(인라인 'N.' 오분할 차단) →
각 섹션을 {번호, 제목, 본문, 표} 로 구조화. 이 섹션 경계가 검색·인용 단위가 된다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

# 줄바꿈을 유발하는 블록 태그
_LINEBREAK_TAGS = {
    "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "title", "caption",
}
_SKIP_TAGS = {"script", "style", "head"}

# 'N. 제목' — 제목 첫 글자는 비숫자(소수점 하위번호 '1.2' 를 최상위로 오인 방지)
_NUM_TITLE = re.compile(r"^\s*(\d{1,3})\s*[.\．·]\s*([^\d\s].{0,60})$")
# '주석 - N. 제목 - 연결/별도' (XBRL 뷰어 export 형식, 이마트 등)
_NUM_TITLE_JUSEOK = re.compile(
    r"^\s*주석\s*[-–—:]\s*(\d{1,3})\s*[.\．·]\s*([^\d\s].{0,49}?)\s*(?:[-–—]\s*(?:연결|별도|개별)\b.*)?$"
)


def _parse_header(line: str) -> tuple[int, str] | None:
    """섹션 헤더 라인 → (번호, 제목). 두 가지 표기 모두 지원."""
    for pat in (_NUM_TITLE, _NUM_TITLE_JUSEOK):
        m = pat.match(line)
        if m:
            return int(m.group(1)), m.group(2).strip().rstrip(".．· ").strip()
    return None

# 주석 영역 시작 앵커(공백 제거 비교)
_NOTE_ANCHORS = [
    ("CFS", "연결재무제표에대한주석"),
    ("CFS", "연결재무제표주석"),
    ("OFS", "재무제표에대한주석"),
    ("OFS", "재무제표주석"),
]
# 주석 영역 종료 경계(다른 상위 섹션) — 짧은 헤딩라인 대상
_BOUNDARIES = [
    "독립된감사인의감사보고서",
    "외부감사인의감사보고서",
    "내부회계관리제도",
    "대표이사등의확인",
    "전문가의의견",
    "감사의의견",
]

# 주석 뒤 사업보고서 후속 섹션 — 라인 길이와 무관하게 '포함'되면 영역 종료.
# (삼성처럼 보고서 전체가 한 파일일 때 마지막 노트가 본문을 흡수하는 것을 차단)
_STOP_PHRASES = [
    "배당에관한사항",
    "이사의경영진단및분석의견",
    "임원및직원등에관한사항",
    "임원및직원의현황",
    "계열회사에관한사항",
    "주주에관한사항",
    "내부회계관리제도에관한",
    "이사회등회사의기관",
    "회계감사인의감사의견",
    "최대주주및그특수관계인의주식소유",
    "주식의총수에관한사항",
    "그밖에투자자보호를위하여",
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


@dataclass
class NoteSection:
    fs_div: str               # 'CFS'(연결) | 'OFS'(별도/개별) | '?'
    note_no: int | None
    title: str
    body: str                 # 표 제외 텍스트
    tables_md: list[str] = field(default_factory=list)
    source_doc: str = ""

    def search_text(self) -> str:
        """매칭용 전체 텍스트(제목+본문+표)."""
        return "\n".join([self.title, self.body, *self.tables_md])

    def dedup_key(self) -> str:
        h = hashlib.md5(_norm(self.body)[:600].encode("utf-8")).hexdigest()[:12]
        return f"{self.fs_div}|{_norm(self.title)}|{h}"


# ---------- 블록 평탄화 ----------
def _render_table(table: Tag) -> tuple[list[list[str]], str]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if any(cells):
            rows.append(cells)
    # 마크다운(셀 내 파이프 escape)
    md_lines = []
    for r in rows:
        md_lines.append("| " + " | ".join(cell.replace("|", "/") for cell in r) + " |")
    return rows, "\n".join(md_lines)


def _iter_tokens(node):
    """문서 순서대로 ('text', str) / ('table', md) / ('break',) 토큰 산출."""
    for child in getattr(node, "children", []):
        if isinstance(child, NavigableString):
            t = str(child)
            if t.strip():
                yield ("text", t)
        elif isinstance(child, Tag):
            name = child.name.lower()
            if name in _SKIP_TAGS:
                continue
            if name == "table":
                _, md = _render_table(child)
                if md:
                    yield ("table", md)
                continue
            yield from _iter_tokens(child)
            if name in _LINEBREAK_TAGS:
                yield ("break",)


@dataclass
class _Block:
    kind: str   # 'line' | 'table'
    text: str   # 라인 텍스트 또는 표 마크다운


def _flatten(html: str) -> list[_Block]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    root = soup.body or soup

    blocks: list[_Block] = []
    buf: list[str] = []

    def flush():
        if buf:
            line = re.sub(r"[ \t ]+", " ", "".join(buf)).strip()
            if line:
                blocks.append(_Block("line", line))
            buf.clear()

    for tok in _iter_tokens(root):
        if tok[0] == "text":
            buf.append(tok[1])
        elif tok[0] == "break":
            flush()
        elif tok[0] == "table":
            flush()
            blocks.append(_Block("table", tok[1]))
    flush()
    return blocks


# ---------- 주석 영역 추출 ----------
def _find_regions(blocks: list[_Block]) -> list[tuple[str, list[_Block]]]:
    """[(fs_div, region_blocks)] — 앵커부터 다음 앵커/경계까지."""
    anchors: list[tuple[int, str]] = []     # (idx, fs_div)
    boundary_idx: set[int] = set()
    for i, b in enumerate(blocks):
        if b.kind != "line":
            continue
        n = _norm(b.text)
        if len(n) <= 40:
            for fs_div, key in _NOTE_ANCHORS:
                if key in n:
                    anchors.append((i, fs_div))
                    break
            else:
                if any(k in n for k in _BOUNDARIES):
                    boundary_idx.add(i)

    regions: list[tuple[str, list[_Block]]] = []
    starts = [a[0] for a in anchors]
    for k, (idx, fs_div) in enumerate(anchors):
        # 종료점: 다음 앵커 또는 다음 경계 중 가장 가까운 것
        next_anchor = starts[k + 1] if k + 1 < len(starts) else len(blocks)
        next_boundary = min((bi for bi in boundary_idx if bi > idx), default=len(blocks))
        end = min(next_anchor, next_boundary)
        region = blocks[idx + 1 : end]
        if region:
            regions.append((fs_div, region))
    return regions


# ---------- 섹션 split (연속성 게이트) ----------
def _split_sections(fs_div: str, region: list[_Block], source_doc: str) -> list[NoteSection]:
    sections: list[NoteSection] = []
    cur: NoteSection | None = None
    cur_no = 0
    cur_body: list[str] = []
    cur_tables: list[str] = []

    def close():
        nonlocal cur, cur_body, cur_tables
        if cur is not None:
            cur.body = "\n".join(cur_body).strip()
            cur.tables_md = list(cur_tables)
            sections.append(cur)
        cur_body, cur_tables = [], []

    for b in region:
        header = None
        if b.kind == "line":
            nl = _norm(b.text)
            # 사업보고서 후속 섹션 도달 → 영역 종료(본문 흡수 차단)
            if any(p in nl for p in _STOP_PHRASES):
                break
            ph = _parse_header(b.text)
            if ph:
                n, title = ph
                # 연속성 게이트: 첫 섹션은 1~3, 이후는 expected..expected+3
                if (not sections and cur is None and 1 <= n <= 3) or (
                    cur is not None and cur_no < n <= cur_no + 3
                ):
                    header = (n, title)
                # 번호 큰 폭 역행 = 주석 영역 이탈(새 번호체계) → 종료
                elif cur is not None and cur_no >= 5 and n <= cur_no - 5:
                    break

        if header:
            close()
            cur_no = header[0]
            cur = NoteSection(fs_div=fs_div, note_no=header[0], title=header[1], body="", source_doc=source_doc)
        elif cur is not None:
            if b.kind == "line":
                cur_body.append(b.text)
            else:
                cur_tables.append(b.text)
        # cur is None(섹션 시작 전 프리앰블)이면 버림
    close()
    return sections


def parse_notes(documents: list[tuple[str, str]]) -> list[NoteSection]:
    """[(파일명, html)] → 중복 제거된 주석 섹션 리스트.

    연결/별도는 fs_div로 보존(같은 제목이라도 수치가 달라 삭제하지 않음).
    완전히 동일한(같은 fs_div·제목·본문) 섹션만 제거(본문 vs 감사보고서 중복).
    """
    all_sections: list[NoteSection] = []
    for fname, html in documents:
        blocks = _flatten(html)
        for fs_div, region in _find_regions(blocks):
            all_sections.extend(_split_sections(fs_div, region, fname))

    seen: dict[str, NoteSection] = {}
    for s in all_sections:
        key = s.dedup_key()
        if key not in seen:
            seen[key] = s
        else:
            # 본문(사업보고서)을 감사보고서보다 우선(표가 더 많은 쪽 유지)
            if len(s.tables_md) > len(seen[key].tables_md):
                seen[key] = s
    return list(seen.values())
