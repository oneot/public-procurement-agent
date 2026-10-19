"""조달청 나라장터 입찰공고정보서비스(BidPublicInfoService) OpenAPI 클라이언트."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from typing import Any, Self

import httpx

from public_procurement_agent import __version__
from public_procurement_agent.redact import redact, register_secret

log = logging.getLogger(__name__)

USER_AGENT = (
    f"Mozilla/5.0 (compatible; public-procurement-agent/{__version__}; "
    "+https://github.com/oneot/public-procurement-agent-kr)"
)

#: 재시도할 HTTP 상태 코드
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
#: 공공데이터 OpenAPI 표준 결과코드 — 정상 / 데이터 없음 / 일시적 오류(재시도)
OK_RESULT_CODES = frozenset({"00", "0"})
NO_DATA_RESULT_CODES = frozenset({"03"})
RETRYABLE_RESULT_CODES = frozenset({"01", "02", "04", "05"})
#: totalCount 가 비정상일 때 무한 루프를 막기 위한 상한 (100건 x 1,000쪽)
MAX_PAGES = 1000

_XML_FIELD = re.compile(
    r"<(returnReasonCode|returnAuthMsg|errMsg|resultCode|resultMsg)>\s*([^<]*?)\s*</\1>"
)


class ApiError(RuntimeError):
    """API 호출 실패. 메시지에서 비밀값은 항상 가려집니다."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(redact(message))
        self.retryable = retryable


class NaraApiClient:
    """페이지네이션·타임아웃·재시도(지수 백오프)를 처리하는 동기 클라이언트."""

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str,
        page_size: int = 100,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not service_key:
            raise ValueError("service_key 가 비어 있습니다")
        register_secret(service_key)
        self._service_key = service_key
        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        # TLS 인증서는 항상 검증합니다 (httpx 기본값: certifi CA 번들).
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def fetch_all(self, operation: str, begin: str, end: str) -> list[dict[str, Any]]:
        """등록일시(``inqryDiv=1``) 기준 ``begin``~``end`` (YYYYMMDDHHMM) 공고를 모두 가져옵니다."""
        params = {"inqryDiv": "1", "inqryBgnDt": begin, "inqryEndDt": end}
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = self._request_with_retry(operation, params, page)
            page_items = _extract_items(body)
            if not page_items:
                break
            items.extend(page_items)
            if page * self._page_size >= _to_int(body.get("totalCount")):
                break
        else:
            log.warning("[%s] 최대 %d쪽에 도달해 수집을 중단했습니다.", operation, MAX_PAGES)
        return items

    def _request_with_retry(
        self, operation: str, params: Mapping[str, str], page: int
    ) -> dict[str, Any]:
        query = {
            "serviceKey": self._service_key,
            "type": "json",
            "numOfRows": str(self._page_size),
            "pageNo": str(page),
            **params,
        }
        attempt = 0
        while True:
            try:
                return self._request(operation, query)
            except ApiError as exc:
                if not exc.retryable or attempt >= self._max_retries:
                    raise
                delay = self._backoff_seconds * (2**attempt)
                attempt += 1
                log.warning("%s — %.1f초 후 재시도 (%d/%d)", exc, delay, attempt, self._max_retries)
                self._sleep(delay)

    def _request(self, operation: str, query: Mapping[str, str]) -> dict[str, Any]:
        url = f"{self._base_url}/{operation}"
        try:
            response = self._http.get(url, params=query)
        except httpx.TimeoutException as exc:
            raise ApiError(
                f"[{operation}] 응답 시간 초과 ({type(exc).__name__})", retryable=True
            ) from None
        except httpx.TransportError as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if "CERTIFICATE_VERIFY_FAILED" in detail:
                raise ApiError(
                    f"[{operation}] TLS 인증서 검증 실패 — {detail}. 사내 프록시 등으로 인증서가 "
                    "바뀌는 환경이라면 SSL_CERT_FILE 로 신뢰할 CA 번들을 지정하세요."
                ) from None
            raise ApiError(f"[{operation}] 네트워크 오류 — {detail}", retryable=True) from None

        status = response.status_code
        if status in RETRYABLE_STATUS:
            raise ApiError(f"[{operation}] HTTP {status}", retryable=True)
        text = response.content.decode("utf-8", errors="replace")
        try:
            data: Any = json.loads(text)
        except ValueError:
            data = None
        gateway_error = _gateway_error(data, text)
        if gateway_error is not None:
            code, detail = gateway_error
            prefix = f"HTTP {status} " if status >= 400 else ""
            raise ApiError(
                f"[{operation}] {prefix}API 오류 ({detail}). "
                "인증키·활용신청 승인 상태·요청 파라미터를 확인하세요.",
                retryable=code.zfill(2) in RETRYABLE_RESULT_CODES,
            )
        if status >= 400:
            raise ApiError(f"[{operation}] HTTP {status}: {_snippet(text)}")
        if data is None:
            raise ApiError(f"[{operation}] JSON 이 아닌 응답: {_snippet(text)}", retryable=True)
        return _parse_body(operation, data)


def _parse_body(operation: str, data: Any) -> dict[str, Any]:
    response = data.get("response") if isinstance(data, dict) else None
    if not isinstance(response, dict):
        raise ApiError(f"[{operation}] 예상하지 못한 응답 형식: {_snippet(json.dumps(data))}")
    header = response.get("header") or {}
    body = response.get("body") or {}
    code = header.get("resultCode") if isinstance(header, dict) else None
    if code is not None:
        code = str(code).strip()
        if code in NO_DATA_RESULT_CODES:
            return {}
        if code not in OK_RESULT_CODES:
            raise ApiError(
                f"[{operation}] 결과코드 {code}: {header.get('resultMsg')}",
                retryable=code in RETRYABLE_RESULT_CODES,
            )
    return body if isinstance(body, dict) else {}


def _gateway_error(data: Any, text: str) -> tuple[str, str] | None:
    """공공데이터포털 게이트웨이 오류(``OpenAPI_ServiceResponse``, JSON 또는 XML)를 해석합니다.

    예: 등록되지 않은 키 → ``("30", "30 등록되지 않은 서비스키 / SERVICE_KEY_IS_...")``
    """
    fields: dict[str, str] = {}
    if isinstance(data, dict):
        envelope = data.get("OpenAPI_ServiceResponse")
        header = envelope.get("cmmMsgHeader") if isinstance(envelope, dict) else None
        if isinstance(header, dict):
            fields = {key: str(value).strip() for key, value in header.items() if value}
    elif data is None and text.lstrip().startswith("<"):
        fields = {match.group(1): match.group(2) for match in _XML_FIELD.finditer(text)}
    if not fields:
        return None
    code = fields.get("returnReasonCode") or fields.get("resultCode") or ""
    messages = [fields.get(key, "") for key in ("returnAuthMsg", "errMsg", "resultMsg")]
    unique = [message for message in dict.fromkeys(messages) if message]
    detail = " ".join(part for part in (code, " / ".join(unique)) if part)
    return code, detail or _snippet(text)


def _extract_items(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: Any = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _snippet(text: str, limit: int = 300) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[:limit]}…"
