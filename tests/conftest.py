from __future__ import annotations

import logging
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from public_procurement_agent import redact
from public_procurement_agent.config import BRANDING_ENV_VARS, AppConfig, load_config
from tests.factories import FakeEmailClient

_ISOLATED_ENV = (
    "NARA_SERVICE_KEY",
    "ACS_CONNECTION_STRING",
    "MAIL_SENDER",
    "MAIL_TO",
    "GITHUB_ACTIONS",
    *BRANDING_ENV_VARS.values(),
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """실제 환경변수·.env·로그 설정이 테스트에 섞이지 않도록 격리합니다."""
    for name in _ISOLATED_ENV:
        # setenv 로 원래 상태를 기록해 두면, 테스트 중 .env 로딩으로 생긴 값도 정리됩니다.
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    redact.clear_secrets()
    yield
    redact.clear_secrets()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == "public_procurement_agent.cli":
            root.removeHandler(handler)


@pytest.fixture
def config() -> AppConfig:
    return load_config(env={})


@pytest.fixture
def fake_acs(monkeypatch: pytest.MonkeyPatch) -> type[FakeEmailClient]:
    """실제 ACS SDK 대신 :class:`FakeEmailClient` 를 쓰도록 바꿉니다."""
    module = types.ModuleType("azure.communication.email")
    module.EmailClient = FakeEmailClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure.communication.email", module)
    monkeypatch.setattr(FakeEmailClient, "sent", [])
    return FakeEmailClient
