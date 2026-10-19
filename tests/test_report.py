from __future__ import annotations

import builtins
import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from public_procurement_agent.collector import CollectionResult, Period
from public_procurement_agent.config import AppConfig
from public_procurement_agent.report import (
    render_summary,
    write_csv,
    write_reports,
    write_xlsx,
)
from tests.factories import make_notice

# 기존 narajangter_bid_collector.py 의 CSV_COLS — 하위 호환을 위해 그대로여야 합니다.
ORIGINAL_CSV_COLUMNS = [
    "주제", "카테고리", "공고번호", "차수", "공고명", "고객기관", "공고기관",
    "계약방법", "예산금액(원)", "공고일시", "입찰마감", "개찰일시",
    "담당자", "연락처", "대형", "공고URL",
]  # fmt: skip

PERIOD = Period("202610120000", "202610182359", "2026-10-12 ~ 2026-10-18")


def make_result(**overrides: Any) -> CollectionResult:
    notices = [
        make_notice(bid_no="A", budget=150_000_000),
        make_notice(
            bid_no="B",
            name="학생용 노트북 구매",
            category="물품",
            topics=("PC",),
            budget=1_200_000_000,
            is_large=True,
            url="",
        ),
    ]
    values: dict[str, Any] = {"scanned": 120, "k12_count": 9, "notices": notices}
    values.update(overrides)
    return CollectionResult(period=PERIOD, **values)


def test_csv_has_original_columns_and_bom(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    write_csv(make_result().notices, path)

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ORIGINAL_CSV_COLUMNS
    assert rows[1][:5] == ["AI/SW", "용역", "A", "000", "AI 기반 학습관리 플랫폼 구축"]
    assert rows[1][8] == "150000000"
    assert rows[2][14] == "Y"


def test_summary_lists_opportunities_by_budget(config: AppConfig) -> None:
    text = render_summary(
        make_result(),
        topic_names=list(config.filters.topics),
        large_budget_mark=config.collect.large_budget_mark,
        generated_at=datetime(2026, 10, 19, 9, 0),
    )
    assert text.startswith(
        "# 나라장터 입찰공고 — 초·중·고/교육청 AI·SW·클라우드·보안·PC 사업 기회\n"
    )
    assert "- 수집 기간: 2026-10-12 ~ 2026-10-18 (등록일시 기준)" in text
    assert "- 생성 시각: 2026-10-19 09:00" in text
    assert "**120건** → 교육기관: **9건** → **초점 주제 매칭: 2건**" in text
    assert "- 주제별: AI 1건, SW 1건, PC 1건" in text
    assert "- 업무별: 물품 1건, 용역 1건" in text
    assert "- 대형(10억+): **1건**" in text
    # 예산 큰 순서, 대형은 ★ 표시
    assert text.index("★ `[PC]` **학생용 노트북 구매**") < text.index("`[AI/SW]`")
    assert "  - 가상초등학교 · 1.5억원 · 용역 · 마감 2026-10-23 10:00:00" in text
    # 개인정보(담당자·연락처)는 요약에 넣지 않습니다.
    assert "김테스트" not in text
    assert "000-0000-0000" not in text


def test_summary_without_results(config: AppConfig) -> None:
    text = render_summary(
        make_result(notices=[]),
        topic_names=list(config.filters.topics),
        large_budget_mark=config.collect.large_budget_mark,
        generated_at=datetime(2026, 10, 19),
    )
    assert "- 조건에 맞는 공고가 없습니다." in text


def test_write_reports_creates_all_files(tmp_path: Path, config: AppConfig) -> None:
    paths = write_reports(
        make_result(),
        config,
        output_dir=tmp_path / "output",
        today=date(2026, 10, 19),
        generated_at=datetime(2026, 10, 19, 9, 0),
    )
    assert paths.csv.name == "초중고교육청_입찰공고_20261019.csv"
    assert paths.summary.name == "초중고교육청_요약_20261019.md"
    assert paths.xlsx is not None
    assert paths.xlsx.name == "초중고교육청_입찰공고_20261019.xlsx"
    assert all(path.exists() for path in (paths.csv, paths.summary, paths.xlsx))


def test_xlsx_is_sorted_and_formula_like_text_stays_text(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    notices = [
        make_notice(bid_no="A", budget=10, name='=HYPERLINK("https://evil.example")'),
        make_notice(bid_no="B", budget=20),
    ]
    path = tmp_path / "out.xlsx"
    assert write_xlsx(notices, path)

    sheet = openpyxl.load_workbook(path).active
    assert [cell.value for cell in sheet[1]] == ORIGINAL_CSV_COLUMNS
    assert sheet["C2"].value == "B"  # 예산 큰 순
    assert sheet["E3"].data_type == "s"
    assert sheet["E3"].value == '=HYPERLINK("https://evil.example")'
    assert sheet.freeze_panes == "A2"


def test_xlsx_is_skipped_without_openpyxl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("openpyxl"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert write_xlsx([make_notice()], tmp_path / "out.xlsx") is False
    assert not (tmp_path / "out.xlsx").exists()
