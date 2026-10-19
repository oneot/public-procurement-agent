from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from public_procurement_agent.client import ApiError
from public_procurement_agent.collector import CollectionError, Period, collect, dedupe
from public_procurement_agent.config import AppConfig
from tests.factories import make_item, make_notice


class FakeSource:
    """업무 구분(오퍼레이션)별로 정해 둔 항목을 돌려주거나 오류를 냅니다."""

    def __init__(self, responses: dict[str, list[dict[str, Any]] | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, str]] = []

    def fetch_all(self, operation: str, begin: str, end: str) -> list[dict[str, Any]]:
        self.calls.append((operation, begin, end))
        response = self.responses.get(operation, [])
        if isinstance(response, Exception):
            raise response
        return response


PERIOD = Period.last_days(date(2026, 10, 19), 7)


def test_period_last_days_ends_yesterday() -> None:
    assert Period("202610120000", "202610182359", "2026-10-12 ~ 2026-10-18") == PERIOD
    with pytest.raises(ValueError):
        Period.last_days(date(2026, 10, 19), 0)


def test_period_single_day() -> None:
    assert Period.single_day(date(2026, 7, 24)) == Period(
        "202607240000", "202607242359", "2026-07-24"
    )


def test_collect_filters_k12_topics_and_budget(config: AppConfig) -> None:
    source = FakeSource(
        {
            "getBidPblancListInfoServc": [
                make_item(bidNtceNo="S1"),  # K-12 × AI/SW → 대상
                make_item(bidNtceNo="S2", dminsttNm="가상대학교", ntceInsttNm="가상대학교"),
                make_item(bidNtceNo="S3", bidNtceNm="교실 청소 용역"),  # 주제 없음
                make_item(bidNtceNo="S4", bdgtAmt="1000", presmptPrce=""),  # 최소 예산 미달
            ],
            "getBidPblancListInfoThng": [make_item(bidNtceNo="T1", bidNtceNm="학생용 노트북 구매")],
        }
    )
    result = collect(source, config, PERIOD, min_budget=10_000)

    assert [call[0] for call in source.calls] == list(config.api.operations)
    assert all(call[1:] == (PERIOD.begin, PERIOD.end) for call in source.calls)
    assert result.scanned == 5
    assert result.k12_count == 4
    assert [(n.bid_no, n.category, n.topics) for n in result.notices] == [
        ("T1", "물품", ("PC",)),  # 설정의 업무 구분 순서(물품 → 용역 → …)대로 조회
        ("S1", "용역", ("AI", "SW")),
    ]
    assert result.failed_operations == []


def test_collect_dedupes_by_bid_number_and_order(config: AppConfig) -> None:
    duplicate = make_item(bidNtceNo="D1", bidNtceOrd="000")
    source = FakeSource(
        {
            "getBidPblancListInfoServc": [duplicate, duplicate],
            "getBidPblancListInfoThng": [make_item(bidNtceNo="D1", bidNtceOrd="001")],
        }
    )
    result = collect(source, config, PERIOD, min_budget=0)
    assert [n.key for n in result.notices] == [("D1", "001"), ("D1", "000")]


def test_partial_failure_continues(config: AppConfig) -> None:
    source = FakeSource(
        {
            "getBidPblancListInfoCnstwk": ApiError("boom"),
            "getBidPblancListInfoServc": [make_item()],
        }
    )
    result = collect(source, config, PERIOD, min_budget=0)
    assert result.failed_operations == ["공사"]
    assert len(result.notices) == 1


def test_all_operations_failing_raises(config: AppConfig) -> None:
    source = FakeSource({operation: ApiError("boom") for operation in config.api.operations})
    with pytest.raises(CollectionError, match="모든 업무 구분"):
        collect(source, config, PERIOD, min_budget=0)


def test_dedupe_keeps_first_occurrence() -> None:
    first = make_notice(bid_no="A", bid_ord="000", name="first")
    notices = [
        first,
        make_notice(bid_no="A", bid_ord="000", name="second"),
        make_notice(bid_no="B"),
    ]
    assert [n.name for n in dedupe(notices)] == ["first", make_notice(bid_no="B").name]
