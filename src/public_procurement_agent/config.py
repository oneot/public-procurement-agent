"""설정 로딩: 패키지 기본 TOML → 사용자 TOML(``--config``) → ``BRIEF_*`` 환경변수(브랜딩)."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import unquote

_PACKAGE = "public_procurement_agent"
SERVICE_KEY_ENV = "NARA_SERVICE_KEY"

#: 브랜딩 설정 키 → 덮어쓰기용 환경변수 (빈 값은 무시)
BRANDING_ENV_VARS: Mapping[str, str] = {
    "brand_name": "BRIEF_BRAND_NAME",
    "logo_url": "BRIEF_LOGO_URL",
    "logo_mark_colors": "BRIEF_LOGO_MARK_COLORS",
    "eyebrow": "BRIEF_EYEBROW",
    "title": "BRIEF_TITLE",
    "section_label": "BRIEF_SECTION_LABEL",
    "footer_text": "BRIEF_FOOTER_TEXT",
    "email_subject": "BRIEF_EMAIL_SUBJECT",
}

_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}")
_LOGO_MARK_SIZE = 4


class ConfigError(Exception):
    """설정이 잘못되었거나 필수 환경변수가 없을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class ApiConfig:
    base_url: str
    operations: Mapping[str, str]
    page_size: int
    timeout_seconds: float
    max_retries: int
    backoff_seconds: float


@dataclass(frozen=True, slots=True)
class CollectConfig:
    days: int
    min_budget: int
    large_budget_mark: int
    output_dir: Path


@dataclass(frozen=True, slots=True)
class FilterConfig:
    edu_keywords: tuple[str, ...]
    edu_exclude: tuple[str, ...]
    school_name_noise: tuple[str, ...]
    topics: Mapping[str, tuple[str, ...]]
    audience_label: str
    topic_label: str


@dataclass(frozen=True, slots=True)
class EmailConfig:
    highlight_topic: str
    urgent_days: int


@dataclass(frozen=True, slots=True)
class BrandingConfig:
    brand_name: str
    logo_url: str
    logo_mark_colors: tuple[str, ...]
    eyebrow: str
    title: str
    section_label: str
    footer_text: str
    email_subject: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    api: ApiConfig
    collect: CollectConfig
    filters: FilterConfig
    email: EmailConfig
    branding: BrandingConfig


def load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> AppConfig:
    """기본 설정에 사용자 설정 파일과 환경변수 덮어쓰기를 적용해 반환합니다.

    사용자 설정은 섹션 단위로 병합되며, 섹션 안에서 지정한 키는 값 전체가 교체됩니다.
    """
    data = _parse_toml(
        resources.files(_PACKAGE).joinpath("default_config.toml").read_text("utf-8"),
        source="default_config.toml",
    )
    if path is not None:
        try:
            text = path.read_text("utf-8")
        except OSError as exc:
            raise ConfigError(f"설정 파일을 읽을 수 없습니다: {path} ({exc.strerror})") from None
        data = _merge(data, _parse_toml(text, source=str(path)), source=str(path))
    _apply_branding_env(data["branding"], os.environ if env is None else env)
    return _build(data)


def get_service_key(env: Mapping[str, str] | None = None) -> str:
    """``NARA_SERVICE_KEY`` 를 읽어 Decoding 형태로 정규화해 반환합니다."""
    raw = (os.environ if env is None else env).get(SERVICE_KEY_ENV, "").strip()
    if not raw:
        raise ConfigError(
            f"환경변수 {SERVICE_KEY_ENV} 가 설정되지 않았습니다. 공공데이터포털(data.go.kr)에서 "
            "'조달청_나라장터 입찰공고정보서비스' 활용신청 후 받은 인증키를 지정하세요 "
            "(로컬: .env 파일 / GitHub Actions: 저장소 시크릿)."
        )
    return normalize_service_key(raw)


def normalize_service_key(key: str) -> str:
    """포털의 Encoding 키(``%2B`` 등)와 Decoding 키를 모두 받아 Decoding 형태로 통일합니다."""
    key = key.strip()
    return unquote(key) if "%" in key else key


def parse_color_list(text: str) -> tuple[str, ...]:
    """``"#f00, #0f0"`` 처럼 쉼표로 구분한 색상 목록을 튜플로 변환합니다."""
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _parse_toml(text: str, *, source: str) -> dict[str, dict[str, Any]]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: TOML 형식 오류 — {exc}") from None
    for section, values in data.items():
        if not isinstance(values, dict):
            raise ConfigError(f"{source}: [{section}] 은(는) 표(table)여야 합니다")
    return data


def _merge(
    base: Mapping[str, Mapping[str, Any]],
    override: Mapping[str, Mapping[str, Any]],
    *,
    source: str,
) -> dict[str, dict[str, Any]]:
    merged = {section: dict(values) for section, values in base.items()}
    for section, values in override.items():
        if section not in merged:
            raise ConfigError(f"{source}: 알 수 없는 설정 섹션 [{section}]")
        unknown = sorted(set(values) - set(merged[section]))
        if unknown:
            raise ConfigError(f"{source}: [{section}] 에 알 수 없는 키 — {', '.join(unknown)}")
        merged[section].update(values)
    return merged


def _apply_branding_env(branding: dict[str, Any], env: Mapping[str, str]) -> None:
    for key, var in BRANDING_ENV_VARS.items():
        value = env.get(var, "")
        if not value.strip():
            # GitHub Actions 에서 정의하지 않은 vars.* 는 빈 문자열로 전달되므로 무시합니다.
            continue
        branding[key] = parse_color_list(value) if key == "logo_mark_colors" else value.strip()


class _Section:
    """TOML 섹션 값을 타입 검사하며 꺼내는 도우미."""

    def __init__(self, name: str, values: Mapping[str, Any]) -> None:
        self._name = name
        self._values = values

    def _error(self, key: str, expected: str) -> ConfigError:
        return ConfigError(
            f"설정 [{self._name}] {key}: {expected} 이어야 합니다 "
            f"(현재 값: {self._values.get(key)!r})"
        )

    def _get(self, key: str) -> Any:
        if key not in self._values:
            raise ConfigError(f"설정 [{self._name}] 에 {key} 값이 없습니다")
        return self._values[key]

    def text(self, key: str) -> str:
        value = self._get(key)
        if not isinstance(value, str):
            raise self._error(key, "문자열")
        return value

    def integer(self, key: str, *, minimum: int = 0) -> int:
        value = self._get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise self._error(key, f"{minimum} 이상의 정수")
        return value

    def number(self, key: str, *, minimum: float = 0.0) -> float:
        value = self._get(key)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < minimum:
            raise self._error(key, f"{minimum} 이상의 숫자")
        return float(value)

    def texts(self, key: str) -> tuple[str, ...]:
        value = self._get(key)
        if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
            raise self._error(key, "문자열 목록")
        return tuple(value)

    def text_map(self, key: str) -> dict[str, str]:
        value = self._get(key)
        if (
            not isinstance(value, dict)
            or not value
            or not all(isinstance(v, str) for v in value.values())
        ):
            raise self._error(key, "비어 있지 않은 '이름 = 문자열' 표")
        return dict(value)

    def texts_map(self, key: str) -> dict[str, tuple[str, ...]]:
        value = self._get(key)
        if (
            not isinstance(value, dict)
            or not value
            or not all(
                isinstance(v, list) and all(isinstance(s, str) for s in v) for v in value.values()
            )
        ):
            raise self._error(key, "비어 있지 않은 '이름 = [문자열, ...]' 표")
        return {name: tuple(keywords) for name, keywords in value.items()}


def _build(data: Mapping[str, Mapping[str, Any]]) -> AppConfig:
    api = _Section("api", data["api"])
    collect = _Section("collect", data["collect"])
    filters = _Section("filters", data["filters"])
    email = _Section("email", data["email"])
    branding = _Section("branding", data["branding"])

    base_url = api.text("base_url").rstrip("/")
    if not base_url.startswith("https://"):
        raise ConfigError("설정 [api] base_url: https:// 로 시작해야 합니다")

    logo_url = branding.text("logo_url").strip()
    if logo_url and not logo_url.startswith("https://"):
        raise ConfigError("설정 [branding] logo_url: https:// 로 시작하는 주소만 허용합니다")

    mark_colors = branding.texts("logo_mark_colors")
    if mark_colors and (
        len(mark_colors) != _LOGO_MARK_SIZE
        or not all(_HEX_COLOR.fullmatch(color) for color in mark_colors)
    ):
        raise ConfigError(
            "설정 [branding] logo_mark_colors: #RRGGBB 형식의 색상 4개(좌상·우상·좌하·우하)여야 "
            f"합니다 (현재 값: {list(mark_colors)!r})"
        )

    return AppConfig(
        api=ApiConfig(
            base_url=base_url,
            operations=api.text_map("operations"),
            page_size=api.integer("page_size", minimum=1),
            timeout_seconds=api.number("timeout_seconds", minimum=1.0),
            max_retries=api.integer("max_retries"),
            backoff_seconds=api.number("backoff_seconds"),
        ),
        collect=CollectConfig(
            days=collect.integer("days", minimum=1),
            min_budget=collect.integer("min_budget"),
            large_budget_mark=collect.integer("large_budget_mark"),
            output_dir=Path(collect.text("output_dir")),
        ),
        filters=FilterConfig(
            edu_keywords=filters.texts("edu_keywords"),
            edu_exclude=filters.texts("edu_exclude"),
            school_name_noise=filters.texts("school_name_noise"),
            topics=filters.texts_map("topics"),
            audience_label=filters.text("audience_label"),
            topic_label=filters.text("topic_label"),
        ),
        email=EmailConfig(
            highlight_topic=email.text("highlight_topic"),
            urgent_days=email.integer("urgent_days"),
        ),
        branding=BrandingConfig(
            brand_name=branding.text("brand_name").strip(),
            logo_url=logo_url,
            logo_mark_colors=mark_colors,
            eyebrow=branding.text("eyebrow"),
            title=branding.text("title"),
            section_label=branding.text("section_label"),
            footer_text=branding.text("footer_text"),
            email_subject=branding.text("email_subject"),
        ),
    )
