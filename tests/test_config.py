from __future__ import annotations

import re
from pathlib import Path

import pytest

from public_procurement_agent.config import (
    AppConfig,
    ConfigError,
    get_service_key,
    load_config,
    normalize_service_key,
)

# 기존 narajangter_bid_collector.py 의 상수 — 기본 설정이 그대로 유지되는지 확인합니다.
ORIGINAL_OPERATIONS = {
    "getBidPblancListInfoThng": "물품",
    "getBidPblancListInfoServc": "용역",
    "getBidPblancListInfoCnstwk": "공사",
    "getBidPblancListInfoFrgcpt": "외자",
}
ORIGINAL_EDU_KEYWORDS = (
    "교육청", "교육지원청",
    "초등학교", "중학교", "고등학교", "유치원", "특수학교",
    "과학고", "외국어고", "예술고", "체육고", "마이스터고",
    "특성화고", "국제고", "자율고",
)  # fmt: skip
ORIGINAL_EDU_EXCLUDE = ("대학", "병원", "의료원", "치과병원", "한방병원", "요양원", "보건소")
ORIGINAL_TOPICS = {
    "AI": ("AI", "인공지능", "생성형", "머신러닝", "딥러닝", "LLM", "챗봇",
           "지능형", "지능정보", "초거대", "피지컬AI", "Physical-AI", "AIDX"),
    "SW": ("소프트웨어", "SW", "라이선스", "라이센스", "구독", "솔루션",
           "정보시스템", "시스템 구축", "시스템 고도화", "고도화 구축", "플랫폼",
           "응용프로그램", "학습관리", "LMS", "원격수업", "에듀테크", "소프트웨어개발"),
    "클라우드": ("클라우드", "Cloud", "가상화", "VDI", "SaaS", "데이터센터 구축"),
    "보안": ("보안", "정보보호", "정보보안", "개인정보", "침해", "관제", "방화벽",
             "백신", "암호화", "취약점", "사이버", "EDR", "SIEM", "제로트러스트"),
    "PC": ("PC", "노트북", "데스크톱", "데스크탑", "크롬북", "태블릿", "컴퓨터", "올인원"),
}  # fmt: skip
ORIGINAL_SCHOOL_NAME_NOISE = (
    "소프트웨어마이스터고", "소프트웨어고등학교", "소프트웨어고",
    "소프트웨어과학고", "인공지능고등학교", "디지털미디어고",
)  # fmt: skip


def test_defaults_match_original_script(config: AppConfig) -> None:
    assert config.api.base_url == "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
    assert dict(config.api.operations) == ORIGINAL_OPERATIONS
    assert list(config.api.operations) == list(ORIGINAL_OPERATIONS)
    assert config.api.page_size == 100
    assert config.filters.edu_keywords == ORIGINAL_EDU_KEYWORDS
    assert config.filters.edu_exclude == ORIGINAL_EDU_EXCLUDE
    assert config.filters.school_name_noise == ORIGINAL_SCHOOL_NAME_NOISE
    assert dict(config.filters.topics) == ORIGINAL_TOPICS
    assert list(config.filters.topics) == list(ORIGINAL_TOPICS)  # 주제 순서도 유지
    assert config.collect.days == 7
    assert config.collect.min_budget == 0
    assert config.collect.large_budget_mark == 1_000_000_000
    assert config.collect.output_dir == Path("output")


def test_default_branding_is_neutral(config: AppConfig) -> None:
    branding = config.branding
    assert branding.brand_name == ""
    assert branding.logo_url == ""
    assert branding.logo_mark_colors == ()
    assert branding.footer_text == ""
    assert branding.eyebrow == "Weekly Korea K-12 Market Procurement Brief"
    assert branding.title == "🇰🇷 K-12 Public Procurement Agent"
    assert branding.section_label == "✨ 이번주 주목할 주요 사업 기회 · 마감 임박순"
    assert branding.email_subject == "WEEKLY KOREA K-12 MARKET PROCUREMENT BRIEF | {date}"


def test_user_config_merges_by_section(tmp_path: Path) -> None:
    path = tmp_path / "my.toml"
    path.write_text(
        '[collect]\ndays = 14\n\n[filters]\ntopics = { AI = ["AI", "인공지능"] }\n',
        encoding="utf-8",
    )
    config = load_config(path, env={})
    assert config.collect.days == 14
    assert config.collect.min_budget == 0  # 같은 섹션의 다른 키는 기본값 유지
    assert dict(config.filters.topics) == {"AI": ("AI", "인공지능")}  # 키 값은 통째로 교체
    assert config.filters.edu_keywords == ORIGINAL_EDU_KEYWORDS


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[unknown]\nx = 1\n", "알 수 없는 설정 섹션"),
        ("[collect]\ndayz = 3\n", "알 수 없는 키"),
        ('[collect]\ndays = "seven"\n', "1 이상의 정수"),
        ("[collect]\ndays = 0\n", "1 이상의 정수"),
        ("[collect]\ndays = true\n", "1 이상의 정수"),
        ("[filters]\ntopics = {}\n", "비어 있지 않은"),
        ("[filters]\nedu_keywords = [1, 2]\n", "문자열 목록"),
        ('[api]\nbase_url = "http://insecure.example"\n', "https://"),
        ("collect = 3\n", "표(table)"),
        ("[collect\n", "TOML 형식 오류"),
    ],
)
def test_invalid_user_config_is_rejected(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_config(path, env={})


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="설정 파일을 읽을 수 없습니다"):
        load_config(tmp_path / "nope.toml", env={})


def test_branding_env_overrides_ignore_blank_values() -> None:
    config = load_config(
        env={
            "BRIEF_BRAND_NAME": "  Example Team ",
            "BRIEF_LOGO_MARK_COLORS": "#111111, #222, #333333,#444444",
            "BRIEF_FOOTER_TEXT": "© {year} Example Team",
            "BRIEF_TITLE": "   ",  # GitHub Actions 의 미정의 vars.* → 빈 문자열
            "BRIEF_EMAIL_SUBJECT": "",
        }
    )
    branding = config.branding
    assert branding.brand_name == "Example Team"
    assert branding.logo_mark_colors == ("#111111", "#222", "#333333", "#444444")
    assert branding.footer_text == "© {year} Example Team"
    assert branding.title == "🇰🇷 K-12 Public Procurement Agent"
    assert branding.email_subject == "WEEKLY KOREA K-12 MARKET PROCUREMENT BRIEF | {date}"


@pytest.mark.parametrize(
    "colors", ["#111111,#222222,#333333", "#111111,#222222,#333333,red", "#1,#2,#3,#4"]
)
def test_logo_mark_colors_are_validated(colors: str) -> None:
    with pytest.raises(ConfigError, match="logo_mark_colors"):
        load_config(env={"BRIEF_LOGO_MARK_COLORS": colors})


@pytest.mark.parametrize("url", ["http://example.com/logo.png", "javascript:alert(1)"])
def test_logo_url_requires_https(url: str) -> None:
    with pytest.raises(ConfigError, match="logo_url"):
        load_config(env={"BRIEF_LOGO_URL": url})


def test_service_key_is_required() -> None:
    with pytest.raises(ConfigError, match="NARA_SERVICE_KEY"):
        get_service_key(env={})
    with pytest.raises(ConfigError, match="NARA_SERVICE_KEY"):
        get_service_key(env={"NARA_SERVICE_KEY": "   "})


def test_service_key_accepts_encoding_and_decoding_forms() -> None:
    assert get_service_key(env={"NARA_SERVICE_KEY": " abc+def/g== "}) == "abc+def/g=="
    assert normalize_service_key("abc%2Bdef%2Fg%3D%3D") == "abc+def/g=="
