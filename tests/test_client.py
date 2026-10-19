from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from public_procurement_agent.client import ApiError, NaraApiClient
from tests.factories import FAKE_SERVICE_KEY, api_json, make_item

BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
OPERATION = "getBidPblancListInfoServc"


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    sleeps: list[float] | None = None,
    **kwargs: Any,
) -> NaraApiClient:
    record = sleeps if sleeps is not None else []
    return NaraApiClient(
        FAKE_SERVICE_KEY,
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        sleep=record.append,
        **kwargs,
    )


def json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(payload, ensure_ascii=False).encode())


def test_fetch_all_paginates_and_sends_expected_query() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["pageNo"])
        count = 100 if page == 1 else 50
        items = [make_item(bidNtceNo=f"R{page}-{i}") for i in range(count)]
        return json_response(api_json(items, total=150))

    with make_client(handler) as client:
        items = client.fetch_all(OPERATION, "202610120000", "202610182359")

    assert len(items) == 150
    assert len(requests) == 2
    first = requests[0]
    assert first.url.path.endswith(f"/{OPERATION}")
    assert first.url.params["type"] == "json"
    assert first.url.params["inqryDiv"] == "1"
    assert first.url.params["inqryBgnDt"] == "202610120000"
    assert first.url.params["inqryEndDt"] == "202610182359"
    assert first.url.params["numOfRows"] == "100"
    assert first.url.params["serviceKey"] == FAKE_SERVICE_KEY
    # 기존 urllib.parse.urlencode 와 같은 방식으로 '+', '/', '=' 를 인코딩합니다.
    assert b"serviceKey=FAKE%2BKEY%2Ffor%3D%3Dtests" in first.url.query
    assert first.headers["User-Agent"].startswith(
        "Mozilla/5.0 (compatible; public-procurement-agent/"
    )


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ({"item": make_item()}, 1),  # 단건이면 dict 로 옴
        ({"item": [make_item(), make_item(bidNtceNo="R2")]}, 2),
        ("", 0),  # 결과가 없으면 빈 문자열
        ([], 0),
    ],
)
def test_items_shapes(items: Any, expected: int) -> None:
    client = make_client(lambda request: json_response(api_json(items, total=expected)))
    assert len(client.fetch_all(OPERATION, "a", "b")) == expected


def test_no_data_result_code_is_empty() -> None:
    client = make_client(lambda request: json_response(api_json("", code="03", msg="NODATA")))
    assert client.fetch_all(OPERATION, "a", "b") == []


def test_retries_transient_errors_with_backoff() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        if calls == 2:
            return httpx.Response(503)
        return json_response(api_json([make_item()]))

    sleeps: list[float] = []
    items = make_client(handler, sleeps).fetch_all(OPERATION, "a", "b")
    assert len(items) == 1
    assert sleeps == [2.0, 4.0]


def test_gives_up_after_max_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    sleeps: list[float] = []
    with pytest.raises(ApiError, match="HTTP 500"):
        make_client(handler, sleeps, max_retries=3).fetch_all(OPERATION, "a", "b")
    assert calls == 4
    assert sleeps == [2.0, 4.0, 8.0]


def test_xml_error_is_not_retried_and_explains_cause() -> None:
    xml = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
        "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
        "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=xml)

    with pytest.raises(ApiError, match="30 SERVICE_KEY_IS_NOT_REGISTERED_ERROR") as excinfo:
        make_client(handler).fetch_all(OPERATION, "a", "b")
    assert calls == 1
    assert not excinfo.value.retryable


def test_gateway_json_error_with_http_403() -> None:
    """실제 API 가 등록되지 않은 키에 돌려주는 형식 (HTTP 403 + JSON)."""
    payload = {
        "OpenAPI_ServiceResponse": {
            "cmmMsgHeader": {
                "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                "returnAuthMsg": "등록되지 않은 서비스키",
                "returnReasonCode": "30",
            }
        }
    }
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(payload, status=403)

    with pytest.raises(ApiError) as excinfo:
        make_client(handler).fetch_all(OPERATION, "a", "b")
    assert str(excinfo.value).startswith(
        f"[{OPERATION}] HTTP 403 API 오류 "
        "(30 등록되지 않은 서비스키 / SERVICE_KEY_IS_NOT_REGISTERED_ERROR)."
    )
    assert calls == 1


def test_html_page_is_retried() -> None:
    sleeps: list[float] = []
    client = make_client(
        lambda request: httpx.Response(200, text="<html>점검 중</html>"), sleeps, max_retries=1
    )
    with pytest.raises(ApiError, match="JSON 이 아닌 응답: <html>점검 중</html>"):
        client.fetch_all(OPERATION, "a", "b")
    assert sleeps == [2.0]


@pytest.mark.parametrize(("code", "retryable"), [("22", False), ("05", True)])
def test_result_code_errors(code: str, retryable: bool) -> None:
    client = make_client(lambda request: json_response(api_json([], code=code, msg="ERR")))
    with pytest.raises(ApiError, match=f"결과코드 {code}") as excinfo:
        client.fetch_all(OPERATION, "a", "b")
    assert excinfo.value.retryable is retryable


def test_client_errors_are_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, text="Unauthorized")

    with pytest.raises(ApiError, match="HTTP 401: Unauthorized"):
        make_client(handler).fetch_all(OPERATION, "a", "b")
    assert calls == 1


def test_non_json_response_is_retried() -> None:
    sleeps: list[float] = []
    client = make_client(lambda request: httpx.Response(200, text="oops"), sleeps, max_retries=1)
    with pytest.raises(ApiError, match="JSON 이 아닌 응답"):
        client.fetch_all(OPERATION, "a", "b")
    assert sleeps == [2.0]


def test_service_key_never_appears_in_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    with pytest.raises(ApiError) as excinfo:
        make_client(handler, max_retries=0).fetch_all(OPERATION, "a", "b")
    message = str(excinfo.value)
    assert "네트워크 오류" in message
    assert FAKE_SERVICE_KEY not in message
    assert "FAKE%2BKEY" not in message
    assert "serviceKey=***" in message


def test_tls_errors_are_not_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    sleeps: list[float] = []
    with pytest.raises(ApiError, match="TLS 인증서 검증 실패"):
        make_client(handler, sleeps).fetch_all(OPERATION, "a", "b")
    assert sleeps == []


def test_empty_service_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="service_key"):
        NaraApiClient("", base_url=BASE_URL)
