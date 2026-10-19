"""날짜·금액 표기 유틸리티. 나라장터 데이터는 모두 한국 표준시(KST) 기준입니다."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
KOREAN_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")

_EOK = 100_000_000  # 1억
_CHEONMAN = 10_000_000  # 1천만


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return now_kst().date()


def parse_yyyymmdd(text: str) -> date:
    """``YYYYMMDD`` 문자열을 날짜로 변환합니다. 형식이 틀리면 ``ValueError``."""
    return datetime.strptime(text, "%Y%m%d").date()


def korean_date(day: date) -> str:
    """예: ``2026년 10월 19일 (월)`` — 로캘과 무관하게 항상 한글 요일을 씁니다."""
    weekday = KOREAN_WEEKDAYS[day.weekday()]
    return f"{day.year}년 {day.month:02d}월 {day.day:02d}일 ({weekday})"


def format_won(amount: int) -> str:
    """요약 리포트용 금액 (예: ``1.5억원``, ``3.2천만원``, ``5,000,000원``)."""
    if amount >= _EOK:
        return f"{amount / _EOK:.1f}억원"
    if amount >= _CHEONMAN:
        return f"{amount / _CHEONMAN:.1f}천만원"
    return f"{amount:,}원"


def format_won_rounded(amount: int) -> str:
    """이메일 카드용 금액 — 천만 단위 반올림 (예: ``1억 5천만원``, ``3천만원``)."""
    cheonman = round(amount / _CHEONMAN)
    if cheonman >= 10:
        eok, rest = divmod(cheonman, 10)
        return f"{eok}억 {rest}천만원" if rest else f"{eok}억원"
    if cheonman >= 1:
        return f"{cheonman}천만원"
    return f"{amount:,}원"


def format_won_kpi(amount: int) -> str:
    """KPI 합계 예산용 — 소수 억 표기 (예: ``9.9억``, ``3억``, ``5천만``)."""
    if amount >= _EOK:
        text = f"{amount / _EOK:.1f}"
        return f"{text.removesuffix('.0')}억"
    if amount >= _CHEONMAN:
        return f"{round(amount / _CHEONMAN)}천만"
    return f"{amount:,}"


def fill_placeholders(text: str, *, today: date, brand_name: str = "") -> str:
    """브랜딩 문구의 ``{year}``, ``{date}``, ``{brand_name}`` 자리표시자를 채웁니다.

    ``str.format`` 과 달리 알 수 없는 중괄호는 그대로 둡니다.
    """
    replacements = {
        "{year}": str(today.year),
        "{date}": today.isoformat(),
        "{brand_name}": brand_name,
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text
