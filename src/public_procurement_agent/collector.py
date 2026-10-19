"""입찰공고 수집 → 분류 → 필터 → 중복 제거."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from public_procurement_agent.client import ApiError
from public_procurement_agent.config import AppConfig
from public_procurement_agent.filters import classify
from public_procurement_agent.models import BidNotice

log = logging.getLogger(__name__)


class CollectionError(RuntimeError):
    """모든 업무 구분의 API 호출이 실패해 결과를 신뢰할 수 없을 때 발생합니다."""


class BidSource(Protocol):
    def fetch_all(self, operation: str, begin: str, end: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class Period:
    """조회 기간 (등록일시 기준, ``YYYYMMDDHHMM``)."""

    begin: str
    end: str
    label: str

    @classmethod
    def single_day(cls, day: date) -> Period:
        stamp = f"{day:%Y%m%d}"
        return cls(begin=f"{stamp}0000", end=f"{stamp}2359", label=f"{day:%Y-%m-%d}")

    @classmethod
    def last_days(cls, today: date, days: int) -> Period:
        """``today`` 기준 최근 ``days`` 일 (어제까지)."""
        if days < 1:
            raise ValueError("days 는 1 이상이어야 합니다")
        start = today - timedelta(days=days)
        end = today - timedelta(days=1)
        return cls(
            begin=f"{start:%Y%m%d}0000",
            end=f"{end:%Y%m%d}2359",
            label=f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}",
        )


@dataclass(slots=True)
class CollectionResult:
    period: Period
    scanned: int = 0
    k12_count: int = 0
    notices: list[BidNotice] = field(default_factory=list)
    failed_operations: list[str] = field(default_factory=list)


def collect(
    source: BidSource, config: AppConfig, period: Period, *, min_budget: int
) -> CollectionResult:
    """모든 업무 구분을 조회해 K-12 × 초점 주제 × 최소 예산 조건에 맞는 공고를 반환합니다.

    일부 업무 구분만 실패하면 경고 후 계속 진행하고, 전부 실패하면 :class:`CollectionError`.
    """
    result = CollectionResult(period=period)
    matched: list[BidNotice] = []
    operations = config.api.operations
    for operation, label in operations.items():
        try:
            items = source.fetch_all(operation, period.begin, period.end)
        except ApiError as exc:
            log.error("  - %s: 오류 → %s", label, exc)
            result.failed_operations.append(label)
            continue
        log.info("  - %s: %4d건 조회", label, len(items))
        for item in items:
            result.scanned += 1
            notice = classify(
                item, label, config.filters, large_budget_mark=config.collect.large_budget_mark
            )
            if not notice.is_k12:
                continue
            result.k12_count += 1
            if notice.topics and notice.budget >= min_budget:
                matched.append(notice)

    if len(result.failed_operations) == len(operations):
        raise CollectionError(
            "모든 업무 구분의 API 호출이 실패했습니다. 인증키(NARA_SERVICE_KEY)와 "
            "공공데이터포털 활용신청 상태를 확인하세요."
        )
    result.notices = dedupe(matched)
    return result


def dedupe(notices: Iterable[BidNotice]) -> list[BidNotice]:
    """(공고번호, 차수)가 같은 공고는 처음 것만 남깁니다."""
    seen: set[tuple[str, str]] = set()
    unique: list[BidNotice] = []
    for notice in notices:
        if notice.key not in seen:
            seen.add(notice.key)
            unique.append(notice)
    return unique
