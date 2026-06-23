"""OPENDART API 얇은 클라이언트.

엔드포인트(검증된 사실):
- corpCode.xml   : 고유번호 전체목록 ZIP(CORPCODE.xml). 필드 corp_code/corp_name/stock_code/modify_date.
- company.json   : 기업개황. corp_cls(Y/K/N/E), induty_code(KSIC) 등.
- list.json      : 공시검색(메타데이터만). 정기공시 pblntf_ty=A.
- document.xml   : 공시서류원문 ZIP(회사별 HTML/XML, EUC-KR/CP949 다수). 주석 본문은 여기에만 존재.

주의: 본문 내용을 검색하는 API는 없다. list.json은 회사/날짜/보고서명만 검색한다.
"""
from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from typing import Iterator

import httpx

BASE = "https://opendart.fss.or.kr/api"

# ZIP 폭탄/메모리 고갈 방어 한도
MAX_ZIP_BYTES = 80 * 1024 * 1024            # 응답 압축본 상한
MAX_ZIP_ENTRIES = 80                        # 엔트리 수 상한
MAX_MEMBER_BYTES = 40 * 1024 * 1024         # 개별 엔트리 비압축 상한
MAX_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024  # 전체 비압축 상한

# XXE/billion-laughs 방어(가능하면 defusedxml 사용)
try:  # pragma: no cover
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except Exception:  # noqa: BLE001
    from xml.etree.ElementTree import fromstring as _xml_fromstring


def _safe_http_error(e: Exception) -> str:
    """예외 문자열에 요청 URL(=crtfc_key 포함)이 새지 않도록 안전 요약."""
    import httpx as _h

    if isinstance(e, _h.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return type(e).__name__

# 정상 외 상태코드(요약)
_STATUS = {
    "000": "정상",
    "010": "등록되지 않은 키",
    "011": "사용할 수 없는 키",
    "012": "접근할 수 없는 IP",
    "013": "조회된 데이터 없음",
    "014": "파일이 존재하지 않음",
    "020": "요청제한 초과(일 20,000건)",
    "021": "조회 가능한 회사 개수 초과",
    "100": "필드의 부적절한 값",
    "101": "부적절한 접근",
    "800": "시스템 점검",
    "900": "정의되지 않은 오류",
    "901": "사용자 계정의 개인정보 보유기간 만료",
}


class DartError(RuntimeError):
    def __init__(self, status: str, message: str = ""):
        self.status = status
        self.message = message or _STATUS.get(status, "")
        super().__init__(f"DART status={status} ({self.message})")


@dataclass
class Disclosure:
    corp_code: str
    corp_name: str
    rcept_no: str       # 접수번호(14자리)
    report_nm: str
    rcept_dt: str       # YYYYMMDD


class DartClient:
    def __init__(self, api_key: str, timeout: float = 30.0):
        self.api_key = api_key
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "dart-notes-mcp/0.1"},
            follow_redirects=False,  # 고정 호스트 외 리다이렉트 추적 금지(SSRF 하드닝)
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DartClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- 저수준 ----
    def _get(self, path: str, **params) -> httpx.Response:
        params = {"crtfc_key": self.api_key, **{k: v for k, v in params.items() if v is not None}}
        last_msg = "unknown"
        for attempt in range(3):
            try:
                r = self._client.get(f"{BASE}/{path}", params=params)
                r.raise_for_status()
                return r
            except httpx.HTTPError as e:  # 네트워크/일시 오류만 재시도
                # ★ 예외 문자열에 URL(=crtfc_key)이 들어가므로 절대 그대로 노출 금지
                last_msg = _safe_http_error(e)
                time.sleep(0.8 * (attempt + 1))
        raise DartError("900", f"network: {last_msg}")

    def _get_json(self, path: str, **params) -> dict:
        data = self._get(path, **params).json()
        status = str(data.get("status", "000"))
        if status not in ("000", "013"):
            raise DartError(status, str(data.get("message", "")))
        return data

    def _get_zip(self, path: str, **params) -> zipfile.ZipFile:
        r = self._get(path, **params)
        ctype = r.headers.get("content-type", "")
        # 오류 시 JSON(text)로 옴
        if "json" in ctype or r.content[:1] in (b"{", b"<") and b"status" in r.content[:200]:
            try:
                data = r.json()
                raise DartError(str(data.get("status", "900")), str(data.get("message", "")))
            except ValueError:
                pass
        content = r.content
        if len(content) > MAX_ZIP_BYTES:
            raise DartError("900", "zip response too large")
        zf = zipfile.ZipFile(io.BytesIO(content))
        # ZIP 폭탄 방어: 엔트리 수·개별/전체 비압축 크기 사전 검증
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise DartError("900", "too many entries in zip")
        total = 0
        for info in infos:
            total += info.file_size
            if info.file_size > MAX_MEMBER_BYTES or total > MAX_TOTAL_UNCOMPRESSED:
                raise DartError("900", "zip uncompressed size too large")
        return zf

    # ---- 고수준 ----
    def corp_code_list(self) -> list[dict]:
        """전체 고유번호 목록. [{corp_code, corp_name, stock_code, modify_date}]"""
        zf = self._get_zip("corpCode.xml")
        name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), zf.namelist()[0])
        root = _xml_fromstring(zf.read(name))  # defusedxml(가능 시) → XXE/entity 폭탄 방어
        out = []
        for el in root.iter("list"):
            out.append(
                {
                    "corp_code": (el.findtext("corp_code") or "").strip(),
                    "corp_name": (el.findtext("corp_name") or "").strip(),
                    "stock_code": (el.findtext("stock_code") or "").strip(),
                    "modify_date": (el.findtext("modify_date") or "").strip(),
                }
            )
        return out

    def company(self, corp_code: str) -> dict:
        """기업개황. corp_cls, induty_code, corp_name 등."""
        return self._get_json("company.json", corp_code=corp_code)

    def list_disclosures(
        self,
        corp_code: str,
        bgn_de: str,
        end_de: str,
        pblntf_ty: str = "A",   # A=정기공시
        pblntf_detail_ty: str | None = None,  # A001=사업보고서 ...
        page_count: int = 100,
    ) -> list[Disclosure]:
        out: list[Disclosure] = []
        page = 1
        while True:
            data = self._get_json(
                "list.json",
                corp_code=corp_code,
                bgn_de=bgn_de,
                end_de=end_de,
                pblntf_ty=pblntf_ty,
                pblntf_detail_ty=pblntf_detail_ty,
                page_no=page,
                page_count=page_count,
            )
            if str(data.get("status")) == "013":
                break
            for it in data.get("list", []):
                out.append(
                    Disclosure(
                        corp_code=it.get("corp_code", ""),
                        corp_name=it.get("corp_name", ""),
                        rcept_no=it.get("rcept_no", ""),
                        report_nm=it.get("report_nm", ""),
                        rcept_dt=it.get("rcept_dt", ""),
                    )
                )
            total_page = int(data.get("total_page", 1) or 1)
            if page >= total_page:
                break
            page += 1
        return out

    def document_files(self, rcept_no: str) -> list[tuple[str, str]]:
        """공시서류원문 ZIP의 모든 파일을 (파일명, 디코드된 텍스트)로 반환.

        인코딩은 EUC-KR/CP949 다수 → utf-8 폴백 체인.
        """
        zf = self._get_zip("document.xml", rcept_no=rcept_no)
        out: list[tuple[str, str]] = []
        for name in zf.namelist():
            raw = zf.read(name)
            text = _decode(raw)
            out.append((name, text))
        return out


def _decode(raw: bytes) -> str:
    for enc in ("euc-kr", "cp949", "utf-8", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def viewer_url(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
