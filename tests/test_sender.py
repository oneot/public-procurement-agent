from __future__ import annotations

import logging
import sys
import types

import pytest

from public_procurement_agent.config import ConfigError
from public_procurement_agent.redact import redact
from public_procurement_agent.sender import (
    MailSettings,
    SendError,
    build_message,
    parse_recipients,
    send_email,
)
from tests.factories import MAIL_ENV, FakeEmailClient


def test_parse_recipients() -> None:
    assert parse_recipients(" a@x.com, b@x.com;c@x.com\nd@x.com ,, ") == (
        "a@x.com",
        "b@x.com",
        "c@x.com",
        "d@x.com",
    )


def test_settings_require_all_variables() -> None:
    with pytest.raises(ConfigError, match="ACS_CONNECTION_STRING, MAIL_SENDER, MAIL_TO"):
        MailSettings.from_env({})
    with pytest.raises(ConfigError, match="받는 사람"):
        MailSettings.from_env({**MAIL_ENV, "MAIL_TO": " , ; "})


def test_settings_hide_secrets_and_register_them_for_redaction() -> None:
    settings = MailSettings.from_env(MAIL_ENV)
    assert settings.recipients == ("alice@example.com", "bob@example.com")
    assert "alice" not in repr(settings)
    assert "FAKEKEY123" not in repr(settings)
    assert redact("to alice@example.com via DoNotReply@fake-sender.example") == "to *** via ***"


def test_build_message() -> None:
    message = build_message(MailSettings.from_env(MAIL_ENV), subject="제목", html="<p>본문</p>")
    assert message == {
        "senderAddress": "DoNotReply@fake-sender.example",
        "recipients": {"to": [{"address": "alice@example.com"}, {"address": "bob@example.com"}]},
        "content": {"subject": "제목", "html": "<p>본문</p>"},
    }


def test_send_email_success_logs_only_recipient_count(
    fake_acs: type[FakeEmailClient], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    message_id = send_email(MailSettings.from_env(MAIL_ENV), subject="제목", html="<p>x</p>")
    assert message_id == "msg-1"
    assert len(fake_acs.sent) == 1
    assert "수신자 2명" in caplog.text
    assert "alice@example.com" not in caplog.text
    assert "bob@example.com" not in caplog.text


def test_send_email_failed_status(
    fake_acs: type[FakeEmailClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        fake_acs, "result", {"id": "msg-2", "status": "Failed", "error": "bad alice@example.com"}
    )
    with pytest.raises(SendError, match="status=Failed") as excinfo:
        send_email(MailSettings.from_env(MAIL_ENV), subject="s", html="h")
    assert "alice@example.com" not in str(excinfo.value)


def test_send_email_object_result(
    fake_acs: type[FakeEmailClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    result = types.SimpleNamespace(id="msg-3", status="Succeeded", error=None)
    monkeypatch.setattr(fake_acs, "result", result)
    assert send_email(MailSettings.from_env(MAIL_ENV), subject="s", html="h") == "msg-3"


def test_send_email_sdk_error_is_wrapped_and_redacted(
    fake_acs: type[FakeEmailClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_acs, "error", RuntimeError("invalid recipient bob@example.com"))
    with pytest.raises(SendError, match="ACS 발송 요청 실패") as excinfo:
        send_email(MailSettings.from_env(MAIL_ENV), subject="s", html="h")
    assert "bob@example.com" not in str(excinfo.value)


def test_send_email_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "azure.communication.email", None)
    with pytest.raises(SendError, match="--extra send"):
        send_email(MailSettings.from_env(MAIL_ENV), subject="s", html="h")
