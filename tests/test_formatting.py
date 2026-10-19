from __future__ import annotations

from datetime import date

import pytest

from public_procurement_agent.formatting import (
    fill_placeholders,
    format_won,
    format_won_kpi,
    format_won_rounded,
    korean_date,
    parse_yyyymmdd,
)


def test_korean_date_uses_korean_weekday_regardless_of_locale() -> None:
    assert korean_date(date(2026, 10, 19)) == "2026년 10월 19일 (월)"
    week = [korean_date(date(2026, 10, 19 + offset))[-2] for offset in range(7)]
    assert week == ["월", "화", "수", "목", "금", "토", "일"]


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (150_000_000, "1.5억원"),
        (1_000_000_000, "10.0억원"),
        (25_000_000, "2.5천만원"),
        (5_000_000, "5,000,000원"),
        (0, "0원"),
    ],
)
def test_format_won(amount: int, expected: str) -> None:
    assert format_won(amount) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (1_250_000_000, "12억 5천만원"),
        (1_000_000_000, "10억원"),
        (345_600_000, "3억 5천만원"),
        (100_000_000, "1억원"),
        (30_000_000, "3천만원"),
        (9_000_000, "1천만원"),  # 천만 단위 반올림
        (4_000_000, "4,000,000원"),
    ],
)
def test_format_won_rounded(amount: int, expected: str) -> None:
    assert format_won_rounded(amount) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (990_000_000, "9.9억"),
        (300_000_000, "3억"),
        (50_000_000, "5천만"),
        (1_234, "1,234"),
    ],
)
def test_format_won_kpi(amount: int, expected: str) -> None:
    assert format_won_kpi(amount) == expected


def test_fill_placeholders_keeps_unknown_braces() -> None:
    text = "© {year} {brand_name} | {date} | {unknown}"
    assert (
        fill_placeholders(text, today=date(2026, 10, 19), brand_name="Example")
        == "© 2026 Example | 2026-10-19 | {unknown}"
    )


def test_parse_yyyymmdd() -> None:
    assert parse_yyyymmdd("20261019") == date(2026, 10, 19)
    with pytest.raises(ValueError):
        parse_yyyymmdd("2026-10-19")
