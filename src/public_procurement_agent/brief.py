"""수집 CSV → 반응형 HTML 이메일 브리핑."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from public_procurement_agent.config import AppConfig, BrandingConfig
from public_procurement_agent.formatting import (
    fill_placeholders,
    format_won_kpi,
    format_won_rounded,
    korean_date,
)
from public_procurement_agent.report import CSV_PREFIX

LATEST_BRIEF_NAME = "brief_latest.html"
BRIEF_PREFIX = "초중고교육청_브리핑_"

#: 주제 배지 그라데이션 (기본색, 끝색). 목록에 없는 주제는 회색.
TOPIC_COLORS: Mapping[str, tuple[str, str]] = {
    "AI": ("#4f46e5", "#6366f1"),
    "SW": ("#0d9488", "#14b8a6"),
    "클라우드": ("#0284c7", "#0ea5e9"),
    "보안": ("#e11d48", "#f43f5e"),
    "PC": ("#d97706", "#f59e0b"),
}
DEFAULT_TOPIC_COLORS = ("#64748b", "#94a3b8")

_NO_DUE_SORT_KEY = 999
_DUE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M")


@dataclass(frozen=True, slots=True)
class BriefItem:
    bid_no: str
    name: str
    customer: str
    category: str
    topics: tuple[str, ...]
    budget: int
    due: datetime | None
    due_raw: str
    url: str


@dataclass(frozen=True, slots=True)
class Badge:
    topic: str
    color: str
    color_end: str


@dataclass(frozen=True, slots=True)
class Card:
    badges: tuple[Badge, ...]
    category: str
    name: str
    customer: str
    budget: str
    due: str
    urgency_color: str
    urgency_label: str
    url: str


@dataclass(frozen=True, slots=True)
class Kpi:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class BriefPaths:
    dated: Path
    latest: Path


def find_latest_csv(output_dir: Path) -> Path:
    """출력 디렉터리에서 가장 최근 날짜의 수집 CSV 를 찾습니다."""
    candidates = sorted(output_dir.glob(f"{CSV_PREFIX}*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"{output_dir} 에 수집 CSV({CSV_PREFIX}YYYYMMDD.csv)가 없습니다. "
            "먼저 collect 를 실행하세요."
        )
    return candidates[-1]


def load_items(csv_path: Path) -> list[BriefItem]:
    """수집 CSV 를 읽고 공고번호 → (공고명, 고객기관) 순으로 중복을 제거합니다 (나중 행 우선)."""
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        items = [_to_item(row) for row in csv.DictReader(handle)]
    by_bid_no = {item.bid_no: item for item in items}
    by_title = {(item.name.strip(), item.customer.strip()): item for item in by_bid_no.values()}
    return list(by_title.values())


def render_subject(branding: BrandingConfig, today: date) -> str:
    return fill_placeholders(branding.email_subject, today=today, brand_name=branding.brand_name)


def render_brief(items: Sequence[BriefItem], *, today: date, config: AppConfig) -> str:
    """마감이 지나지 않은 공고를 마감 임박순(같으면 예산 큰 순)으로 정렬해 HTML 을 만듭니다."""
    active = [item for item in items if item.due is None or _days_left(item, today) >= 0]
    active.sort(key=lambda item: (_days_left(item, today), -item.budget))

    highlight = config.email.highlight_topic
    urgent_days = config.email.urgent_days
    kpis = (
        Kpi("총 신규 기회", str(len(active))),
        Kpi(f"{highlight} 관련", str(sum(1 for item in active if highlight in item.topics))),
        Kpi(
            f"마감 임박({urgent_days}일)",
            str(
                sum(
                    1
                    for item in active
                    if item.due is not None and 0 <= _days_left(item, today) <= urgent_days
                )
            ),
        ),
        Kpi("합계 예산", format_won_kpi(sum(item.budget for item in active))),
    )

    branding = config.branding

    def fill(text: str) -> str:
        return fill_placeholders(text, today=today, brand_name=branding.brand_name)

    template = _environment().get_template("brief.html.j2")
    return template.render(
        subject=render_subject(branding, today),
        brand_name=branding.brand_name,
        logo_url=branding.logo_url,
        mark_colors=branding.logo_mark_colors,
        has_logo=bool(branding.brand_name or branding.logo_url or branding.logo_mark_colors),
        eyebrow=fill(branding.eyebrow),
        title=fill(branding.title),
        section_label=fill(branding.section_label),
        footer_text=fill(branding.footer_text),
        date_text=korean_date(today),
        topic_label=config.filters.topic_label,
        audience_label=config.filters.audience_label,
        kpis=kpis,
        cards=[_to_card(item, today) for item in active],
    )


def write_brief(csv_path: Path, output_dir: Path, *, today: date, config: AppConfig) -> BriefPaths:
    html = render_brief(load_items(csv_path), today=today, config=config)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = BriefPaths(
        dated=output_dir / f"{BRIEF_PREFIX}{today:%Y%m%d}.html",
        latest=output_dir / LATEST_BRIEF_NAME,
    )
    for path in (paths.dated, paths.latest):
        path.write_text(html, encoding="utf-8")
    return paths


@cache
def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("public_procurement_agent", "templates"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _to_item(row: Mapping[str, str | None]) -> BriefItem:
    due_raw = row.get("입찰마감") or ""
    return BriefItem(
        bid_no=row.get("공고번호") or "",
        name=row.get("공고명") or "",
        customer=row.get("고객기관") or "",
        category=row.get("카테고리") or "",
        topics=tuple(topic for topic in (row.get("주제") or "").split("/") if topic),
        budget=_parse_int(row.get("예산금액(원)")),
        due=_parse_due(due_raw),
        due_raw=due_raw,
        url=row.get("공고URL") or "",
    )


def _to_card(item: BriefItem, today: date) -> Card:
    urgency_color, urgency_label = _urgency(item, today)
    due = item.due_raw[:16] if item.due_raw else "미정"
    return Card(
        badges=tuple(
            Badge(topic, *TOPIC_COLORS.get(topic, DEFAULT_TOPIC_COLORS)) for topic in item.topics
        ),
        category=item.category,
        name=item.name.strip(),
        customer=item.customer.strip(),
        budget=format_won_rounded(item.budget),
        due=due[5:] if len(due) >= 10 else due,  # "2026-10-23 10:00" → "10-23 10:00"
        urgency_color=urgency_color,
        urgency_label=urgency_label,
        url=_safe_url(item.url),
    )


def _days_left(item: BriefItem, today: date) -> int:
    return (item.due.date() - today).days if item.due else _NO_DUE_SORT_KEY


def _urgency(item: BriefItem, today: date) -> tuple[str, str]:
    if item.due is None:
        return ("#64748b", "마감 미정")
    days = _days_left(item, today)
    if days <= 2:
        return ("#e11d48", f"D-{days}")
    if days <= 5:
        return ("#d97706", f"D-{days}")
    return ("#0d9488", f"D-{days}")


def _parse_due(text: str) -> datetime | None:
    text = text.strip()
    for fmt in _DUE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_int(text: str | None) -> int:
    try:
        return int((text or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def _safe_url(url: str) -> str:
    url = url.strip()
    return url if url.lower().startswith(("https://", "http://")) else ""
