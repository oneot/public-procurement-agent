from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from public_procurement_agent.brief import (
    find_latest_csv,
    load_items,
    render_brief,
    render_subject,
    write_brief,
)
from public_procurement_agent.config import AppConfig, load_config
from public_procurement_agent.report import write_csv
from tests.factories import make_notice

TODAY = date(2026, 10, 19)  # 월요일
# 브랜드 로고(마크·이미지·이름) 표와 브랜드 푸터 영역에만 쓰이는 스타일
LOGO_MARKUP = "display:inline-block;vertical-align:middle;border-collapse:collapse;"
BRAND_FOOTER_MARKUP = "border-top:1px solid rgba(226,232,240,.85)"


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    notices = [
        make_notice(
            bid_no="LATE",
            name="클라우드 VDI 구축",
            topics=("클라우드",),
            budget=500_000_000,
            close_dt="2026-10-30 10:00:00",
        ),
        make_notice(
            bid_no="SOON-SMALL",
            name="정보보안 관제",
            topics=("보안",),
            budget=30_000_000,
            close_dt="2026-10-21 10:00:00",
        ),
        make_notice(
            bid_no="SOON-BIG",
            name="AI 디지털교과서 <플랫폼> & 구축",
            topics=("AI", "SW"),
            budget=1_250_000_000,
            close_dt="2026-10-21 18:00:00",
        ),
        make_notice(bid_no="NODUE", name="학생용 노트북", topics=("PC",), close_dt=""),
        make_notice(bid_no="PAST", name="지난 공고", close_dt="2026-10-18 10:00:00"),
        make_notice(
            bid_no="TODAY", name="오늘 마감", topics=("AI",), close_dt="2026-10-19 17:00:00"
        ),
    ]
    path = tmp_path / "초중고교육청_입찰공고_20261019.csv"
    write_csv(notices, path)
    return path


def card_titles(html: str) -> list[str]:
    pattern = r'<div style="font-size:15px;font-weight:700;color:#111827;[^"]*">([^<]*)</div>'
    return re.findall(pattern, html)


def test_cards_sorted_by_deadline_then_budget_and_past_excluded(
    csv_path: Path, config: AppConfig
) -> None:
    html = render_brief(load_items(csv_path), today=TODAY, config=config)
    assert card_titles(html) == [
        "오늘 마감",
        "AI 디지털교과서 &lt;플랫폼&gt; &amp; 구축",  # HTML 이스케이프
        "정보보안 관제",
        "클라우드 VDI 구축",
        "학생용 노트북",
    ]
    assert "지난 공고" not in html
    assert "D-0" in html
    assert "마감 미정" in html
    assert "10-21 18:00" in html


def test_kpis(csv_path: Path, config: AppConfig) -> None:
    html = render_brief(load_items(csv_path), today=TODAY, config=config)
    kpis = re.findall(
        r'white-space:nowrap;">([^<]*)</div><div style="font-size:11px;color:#64748b;'
        r'margin-top:7px;line-height:1.3;">([^<]*)</div>',
        html,
    )
    # 오늘 마감 1.5억 + 12.5억 + 0.3억 + 5억 + 노트북 1.5억 = 20.8억
    assert kpis == [
        ("5", "총 신규 기회"),
        ("2", "AI 관련"),
        ("3", "마감 임박(3일)"),
        ("20.8억", "합계 예산"),
    ]


def test_korean_weekday_and_neutral_default_branding(csv_path: Path, config: AppConfig) -> None:
    html = render_brief(load_items(csv_path), today=TODAY, config=config)
    assert "📅 2026년 10월 19일 (월)" in html
    assert "<title>WEEKLY KOREA K-12 MARKET PROCUREMENT BRIEF | 2026-10-19</title>" in html
    assert ">Weekly Korea K-12 Market Procurement Brief</div>" in html
    assert ">🇰🇷 K-12 Public Procurement Agent</div>" in html
    assert ">✨ 이번주 주목할 주요 사업 기회 · 마감 임박순</div>" in html
    assert "필터: 시·도교육청·교육지원청·초중고 × AI/소프트웨어/클라우드/보안/PC" in html
    # 기본 브랜딩은 비어 있으므로 로고와 브랜드 푸터 영역을 그리지 않습니다.
    assert LOGO_MARKUP not in html
    assert BRAND_FOOTER_MARKUP not in html


def test_branding_overrides(csv_path: Path) -> None:
    config = load_config(
        env={
            "BRIEF_BRAND_NAME": "Example Team",
            "BRIEF_LOGO_URL": "https://example.com/logo.png?a=1&b=2",
            "BRIEF_LOGO_MARK_COLORS": "#111111,#222222,#333333,#444444",
            "BRIEF_FOOTER_TEXT": "© {year} {brand_name}. All rights reserved.",
            "BRIEF_SECTION_LABEL": "이번주 기회",
            "BRIEF_EMAIL_SUBJECT": "[{brand_name}] 주간 브리핑 {date}",
        }
    )
    html = render_brief(load_items(csv_path), today=TODAY, config=config)
    assert html.count(LOGO_MARKUP) == 2  # 헤더 + 푸터
    assert html.count(">Example Team</td>") == 2
    assert BRAND_FOOTER_MARKUP in html
    assert 'src="https://example.com/logo.png?a=1&amp;b=2"' in html
    assert "background:#444444" in html
    assert "© 2026 Example Team. All rights reserved." in html
    assert ">이번주 기회</div>" in html
    assert render_subject(config.branding, TODAY) == "[Example Team] 주간 브리핑 2026-10-19"
    assert "<title>[Example Team] 주간 브리핑 2026-10-19</title>" in html


def test_unsafe_urls_are_dropped(tmp_path: Path, config: AppConfig) -> None:
    path = tmp_path / "x.csv"
    write_csv([make_notice(url="javascript:alert(1)")], path)
    html = render_brief(load_items(path), today=TODAY, config=config)
    assert "javascript:" not in html
    assert 'href=""' in html


def test_empty_brief(tmp_path: Path, config: AppConfig) -> None:
    path = tmp_path / "empty.csv"
    write_csv([], path)
    html = render_brief(load_items(path), today=TODAY, config=config)
    assert "이번주 마감 전 신규 기회가 없습니다." in html
    assert "합계 예산" in html


def test_load_items_dedupes_like_the_original(tmp_path: Path) -> None:
    path = tmp_path / "dup.csv"
    write_csv(
        [
            make_notice(bid_no="A", bid_ord="000", budget=1),
            make_notice(bid_no="A", bid_ord="001", budget=2),  # 같은 공고번호 → 나중 행
            make_notice(bid_no="B", budget=3),  # 같은 (공고명, 고객기관) → 나중 행
            make_notice(bid_no="C", name="다른 공고", budget=4),
        ],
        path,
    )
    assert [(item.bid_no, item.budget) for item in load_items(path)] == [("B", 3), ("C", 4)]


def test_write_brief_and_find_latest_csv(tmp_path: Path, csv_path: Path, config: AppConfig) -> None:
    older = csv_path.parent / "초중고교육청_입찰공고_20261012.csv"
    older.write_text("", encoding="utf-8")
    assert find_latest_csv(csv_path.parent) == csv_path

    out = tmp_path / "output"
    paths = write_brief(csv_path, out, today=TODAY, config=config)
    assert paths.dated == out / "초중고교육청_브리핑_20261019.html"
    assert paths.latest == out / "brief_latest.html"
    assert paths.dated.read_text(encoding="utf-8") == paths.latest.read_text(encoding="utf-8")


def test_find_latest_csv_without_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="collect"):
        find_latest_csv(tmp_path)
