"""Azure Communication Services(ACS) Email 로 브리핑 HTML 을 발송합니다."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from public_procurement_agent.config import ConfigError
from public_procurement_agent.redact import redact, register_secret

log = logging.getLogger(__name__)

ACS_CONNECTION_STRING_ENV = "ACS_CONNECTION_STRING"
MAIL_SENDER_ENV = "MAIL_SENDER"
MAIL_TO_ENV = "MAIL_TO"

_RECIPIENT_SEPARATORS = re.compile(r"[,;\n]")


class SendError(RuntimeError):
    """이메일 발송 실패. 메시지에서 비밀값·주소는 항상 가려집니다."""

    def __init__(self, message: str) -> None:
        super().__init__(redact(message))


def parse_recipients(raw: str) -> tuple[str, ...]:
    """쉼표·세미콜론·줄바꿈으로 구분한 주소 목록을 정리합니다."""
    return tuple(part.strip() for part in _RECIPIENT_SEPARATORS.split(raw) if part.strip())


@dataclass(frozen=True, slots=True)
class MailSettings:
    """발송 설정. ``repr`` 에 비밀값·주소가 노출되지 않도록 숨깁니다."""

    connection_string: str = field(repr=False)
    sender: str = field(repr=False)
    recipients: tuple[str, ...] = field(repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MailSettings:
        env = os.environ if env is None else env
        names = (ACS_CONNECTION_STRING_ENV, MAIL_SENDER_ENV, MAIL_TO_ENV)
        values = {name: env.get(name, "").strip() for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigError(f"이메일 발송에 필요한 환경변수가 없습니다: {', '.join(missing)}")
        recipients = parse_recipients(values[MAIL_TO_ENV])
        if not recipients:
            raise ConfigError(f"{MAIL_TO_ENV} 에 받는 사람 주소가 없습니다")
        # 수신자 주소 등은 GitHub 시크릿 마스킹을 우회해 로그에 남을 수 있으므로 직접 가립니다.
        for secret in (values[ACS_CONNECTION_STRING_ENV], values[MAIL_SENDER_ENV], *recipients):
            register_secret(secret)
        return cls(
            connection_string=values[ACS_CONNECTION_STRING_ENV],
            sender=values[MAIL_SENDER_ENV],
            recipients=recipients,
        )


def build_message(settings: MailSettings, *, subject: str, html: str) -> dict[str, Any]:
    return {
        "senderAddress": settings.sender,
        "recipients": {"to": [{"address": address} for address in settings.recipients]},
        "content": {"subject": subject, "html": html},
    }


def send_email(settings: MailSettings, *, subject: str, html: str) -> str:
    """메일을 발송하고 ACS 메시지 ID 를 반환합니다. 실패하면 :class:`SendError`."""
    try:
        from azure.communication.email import EmailClient
    except ImportError:
        raise SendError(
            "azure-communication-email 패키지가 없습니다. `uv sync --extra send` 또는 "
            "`pip install 'public-procurement-agent[send]'` 로 설치하세요."
        ) from None

    try:
        client = EmailClient.from_connection_string(settings.connection_string)
        poller = client.begin_send(build_message(settings, subject=subject, html=html))
        result = poller.result()
    except Exception as exc:  # azure.core.exceptions.* 등 SDK 오류 전반
        raise SendError(f"ACS 발송 요청 실패 — {type(exc).__name__}: {exc}") from None

    status, message_id, error = _result_fields(result)
    if status.lower() != "succeeded":
        raise SendError(f"ACS 발송 실패 — status={status}, error={error}")
    # 주소는 절대 로그에 남기지 않고 인원수만 기록합니다.
    log.info(
        "ACS 발송 완료: status=%s, id=%s, 수신자 %d명", status, message_id, len(settings.recipients)
    )
    return message_id


def _result_fields(result: Any) -> tuple[str, str, Any]:
    if isinstance(result, Mapping):
        return str(result.get("status", "")), str(result.get("id", "")), result.get("error")
    return (
        str(getattr(result, "status", "")),
        str(getattr(result, "id", "")),
        getattr(result, "error", None),
    )
