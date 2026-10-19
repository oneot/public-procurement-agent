"""합성(가짜) 테스트 데이터 생성기.

실제 나라장터 응답에는 담당 공무원의 이름·연락처가 들어 있으므로 테스트에서는 절대 실제 데이터를
쓰지 않습니다. 아래 기관명·담당자·번호는 모두 가상의 값입니다.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, ClassVar

from public_procurement_agent.models import BidNotice

FAKE_SERVICE_KEY = "FAKE+KEY/for==tests"


def make_item(**overrides: Any) -> dict[str, Any]:
    """나라장터 입찰공고 API 응답 항목(합성)."""
    item: dict[str, Any] = {
        "bidNtceNo": "R26BK00000001",
        "bidNtceOrd": "000",
        "bidNtceNm": "AI 기반 학습관리 플랫폼 구축",
        "ntceInsttNm": "가상특별시교육청",
        "dminsttNm": "가상초등학교",
        "cntrctCnclsMthdNm": "제한경쟁",
        "bdgtAmt": "150000000",
        "presmptPrce": "136363636",
        "asignBdgtAmt": "",
        "bidNtceDt": "2026-10-14 09:00:00",
        "bidClseDt": "2026-10-23 10:00:00",
        "opengDt": "2026-10-23 11:00:00",
        "ntceInsttOfclNm": "김테스트",
        "ntceInsttOfclTelNo": "000-0000-0000",
        "bidNtceUrl": "https://www.g2b.go.kr/example?bidno=R26BK00000001",
    }
    item.update(overrides)
    return item


def api_json(
    items: Any, *, total: int | None = None, code: str = "00", msg: str = "정상"
) -> dict[str, Any]:
    """BidPublicInfoService JSON 응답 형태로 감쌉니다."""
    count = total if total is not None else (len(items) if isinstance(items, list) else 1)
    return {
        "response": {
            "header": {"resultCode": code, "resultMsg": msg},
            "body": {"items": items, "numOfRows": 100, "pageNo": 1, "totalCount": count},
        }
    }


_BASE_NOTICE = BidNotice(
    category="용역",
    bid_no="R26BK00000001",
    bid_ord="000",
    name="AI 기반 학습관리 플랫폼 구축",
    customer="가상초등학교",
    notice_org="가상특별시교육청",
    contract_method="제한경쟁",
    budget=150_000_000,
    notice_dt="2026-10-14 09:00:00",
    close_dt="2026-10-23 10:00:00",
    open_dt="2026-10-23 11:00:00",
    officer="김테스트",
    phone="000-0000-0000",
    url="https://www.g2b.go.kr/example?bidno=R26BK00000001",
    is_k12=True,
    topics=("AI", "SW"),
    is_large=False,
)


def make_notice(**overrides: Any) -> BidNotice:
    return replace(_BASE_NOTICE, **overrides)


MAIL_ENV = {
    "ACS_CONNECTION_STRING": "endpoint=https://fake.communication.azure.com/;accesskey=FAKEKEY123",
    "MAIL_SENDER": "DoNotReply@fake-sender.example",
    "MAIL_TO": "alice@example.com, bob@example.com",
}


class FakePoller:
    def __init__(self, result: Any) -> None:
        self._result = result

    def result(self) -> Any:
        return self._result


class FakeEmailClient:
    """``azure.communication.email.EmailClient`` 대역. 실제로 메일을 보내지 않습니다."""

    sent: ClassVar[list[dict[str, Any]]] = []
    result: ClassVar[Any] = {"id": "msg-1", "status": "Succeeded", "error": None}
    error: ClassVar[Exception | None] = None

    @classmethod
    def from_connection_string(cls, connection_string: str) -> FakeEmailClient:
        assert connection_string == MAIL_ENV["ACS_CONNECTION_STRING"]
        return cls()

    def begin_send(self, message: dict[str, Any]) -> FakePoller:
        if self.error is not None:
            raise self.error
        self.sent.append(message)
        return FakePoller(self.result)
