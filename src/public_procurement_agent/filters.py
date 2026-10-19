"""K-12 교육기관 판별 · 주제 매칭 · 공고 분류."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from public_procurement_agent.config import FilterConfig
from public_procurement_agent.models import BidNotice

#: 예산 후보 필드 (가장 큰 값을 사용)
BUDGET_FIELDS = ("bdgtAmt", "presmptPrce", "asignBdgtAmt")


def contains(text: str, keyword: str) -> bool:
    """영문 대문자로 시작하는 키워드는 대소문자를 구분해 매칭합니다 (AI, SW 등 오탐 방지)."""
    if keyword[:1].isupper():
        return keyword in text
    return keyword.lower() in text.lower()


def is_k12_institution(institution: str, filters: FilterConfig) -> bool:
    """기관명이 K-12 교육기관(교육청·초중고 등)이면 ``True``. 대학·병원 등은 제외합니다."""
    if any(word in institution for word in filters.edu_exclude):
        return False
    return any(word in institution for word in filters.edu_keywords)


def match_topics(name: str, filters: FilterConfig) -> tuple[str, ...]:
    """공고명에서 초점 주제를 찾습니다.

    학교 이름에 들어간 주제어(예: 소프트웨어마이스터고)는 먼저 지워 오탐을 막습니다.
    """
    cleaned = name
    for token in filters.school_name_noise:
        cleaned = cleaned.replace(token, "")
    return tuple(
        topic
        for topic, keywords in filters.topics.items()
        if any(contains(cleaned, keyword) for keyword in keywords)
    )


def budget_of(item: Mapping[str, Any]) -> int:
    """배정예산·추정가격 중 최댓값(원). 숫자가 아니면 0."""
    best = 0
    for field in BUDGET_FIELDS:
        raw = str(item.get(field, "") or "").replace(",", "").strip()
        try:
            best = max(best, int(float(raw)))
        except (ValueError, OverflowError):
            continue
    return best


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def classify(
    item: Mapping[str, Any],
    category: str,
    filters: FilterConfig,
    *,
    large_budget_mark: int,
) -> BidNotice:
    """API 응답 항목 하나를 :class:`BidNotice` 로 변환하며 교육기관·주제·대형 여부를 판정합니다."""
    notice_org = _text(item.get("ntceInsttNm"))
    demand_org = _text(item.get("dminsttNm"))
    name = _text(item.get("bidNtceNm"))
    budget = budget_of(item)
    return BidNotice(
        category=category,
        bid_no=_text(item.get("bidNtceNo")),
        bid_ord=_text(item.get("bidNtceOrd")),
        name=name,
        customer=demand_org or notice_org,  # 실제 고객 = 수요기관 우선
        notice_org=notice_org,
        contract_method=_text(item.get("cntrctCnclsMthdNm")),
        budget=budget,
        notice_dt=_text(item.get("bidNtceDt")),
        close_dt=_text(item.get("bidClseDt")),
        open_dt=_text(item.get("opengDt")),
        officer=_text(item.get("ntceInsttOfclNm")),
        phone=_text(item.get("ntceInsttOfclTelNo")),
        url=_text(item.get("bidNtceUrl") or item.get("bidNtceDtlUrl")),
        is_k12=is_k12_institution(f"{notice_org} {demand_org}", filters),
        topics=match_topics(name, filters),
        is_large=budget >= large_budget_mark,
    )
