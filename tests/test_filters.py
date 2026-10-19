from __future__ import annotations

from typing import Any

import pytest

from public_procurement_agent.config import AppConfig
from public_procurement_agent.filters import (
    budget_of,
    classify,
    contains,
    is_k12_institution,
    match_topics,
)
from tests.factories import make_item


@pytest.mark.parametrize(
    ("text", "keyword", "expected"),
    [
        ("AI 기반 플랫폼", "AI", True),
        ("ai 기반 플랫폼", "AI", False),  # 대문자 시작 키워드는 대소문자 구분
        ("Mail 서버 교체", "AI", False),
        ("LMS 고도화", "LMS", True),
        ("lms 고도화", "LMS", False),
        ("Big DATA 분석", "data", True),  # 소문자 시작 키워드는 대소문자 무시
        ("피지컬ai 교구", "피지컬AI", True),  # 한글 시작 키워드는 대소문자 무시
        ("클라우드 전환", "클라우드", True),
    ],
)
def test_contains_case_rules(text: str, keyword: str, expected: bool) -> None:
    assert contains(text, keyword) is expected


@pytest.mark.parametrize(
    ("institution", "expected"),
    [
        ("가상특별시교육청 가상초등학교", True),
        ("가상교육지원청", True),
        ("가상과학고", True),
        ("가상유치원", True),
        ("가상대학교", False),
        ("가상교육청 가상대학교병원", False),  # 제외어가 우선
        ("가상교육청 보건소", False),
        ("가상시청", False),
        ("", False),
    ],
)
def test_is_k12_institution(config: AppConfig, institution: str, expected: bool) -> None:
    assert is_k12_institution(institution, config.filters) is expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("AI 디지털교과서 플랫폼 구축", ("AI", "SW")),
        ("학생용 노트북 및 태블릿 구매", ("PC",)),
        ("정보보안 관제 및 클라우드 VDI 구축", ("클라우드", "보안")),
        ("부산소프트웨어마이스터고 급식실 환경개선", ()),  # 학교 이름 속 주제어 무시
        ("부산소프트웨어마이스터고 노트북 구매", ("PC",)),
        ("Mail 서버 교체", ()),
        ("교실 청소 용역", ()),
    ],
)
def test_match_topics(config: AppConfig, name: str, expected: tuple[str, ...]) -> None:
    assert match_topics(name, config.filters) == expected


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"bdgtAmt": "150000000", "presmptPrce": "136363636"}, 150_000_000),
        ({"bdgtAmt": "", "presmptPrce": "1,234,567", "asignBdgtAmt": None}, 1_234_567),
        ({"bdgtAmt": "99999.9"}, 99_999),
        ({"bdgtAmt": "abc", "presmptPrce": "inf", "asignBdgtAmt": "nan"}, 0),
        ({}, 0),
    ],
)
def test_budget_of(fields: dict[str, Any], expected: int) -> None:
    assert budget_of(fields) == expected


def test_classify_maps_fields(config: AppConfig) -> None:
    notice = classify(make_item(), "용역", config.filters, large_budget_mark=1_000_000_000)
    assert notice.category == "용역"
    assert notice.customer == "가상초등학교"  # 수요기관 우선
    assert notice.notice_org == "가상특별시교육청"
    assert notice.budget == 150_000_000
    assert notice.is_k12
    assert notice.topics == ("AI", "SW")
    assert not notice.is_large
    assert notice.officer == "김테스트"


def test_classify_fallbacks_and_large_mark(config: AppConfig) -> None:
    item = make_item(
        dminsttNm=None,
        bidNtceUrl="",
        bidNtceDtlUrl="https://www.g2b.go.kr/detail",
        bdgtAmt="1000000000",
        bidNtceOrd=None,
    )
    notice = classify(item, "물품", config.filters, large_budget_mark=1_000_000_000)
    assert notice.customer == "가상특별시교육청"  # 수요기관이 없으면 공고기관
    assert notice.url == "https://www.g2b.go.kr/detail"
    assert notice.bid_ord == ""
    assert notice.is_large
