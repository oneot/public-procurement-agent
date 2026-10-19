"""로그·오류 메시지에서 비밀값(인증키·연결 문자열·이메일 주소)을 가리는 유틸리티.

공개 저장소의 GitHub Actions 로그는 누구나 볼 수 있으므로, 서비스 키가 실린 요청 URL이나
수신자 주소가 로그에 남지 않도록 모든 로그 출력을 이 모듈로 한 번 더 걸러냅니다.
"""

from __future__ import annotations

import logging
import re
import threading
from urllib.parse import quote, quote_plus

MASK = "***"
_MIN_SECRET_LENGTH = 4
_SERVICE_KEY_PARAM = re.compile(r"(?i)(servicekey=)[^&\s'\"<>]+")

_lock = threading.Lock()
_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """값(및 URL 인코딩된 변형)을 이후 모든 로그·오류 메시지에서 가리도록 등록합니다."""
    if not value:
        return
    value = value.strip()
    if len(value) < _MIN_SECRET_LENGTH:
        return
    variants = {value, quote(value, safe=""), quote_plus(value)}
    with _lock:
        _secrets.update(variants)


def clear_secrets() -> None:
    """등록된 비밀값을 모두 지웁니다 (테스트용)."""
    with _lock:
        _secrets.clear()


def redact(text: str) -> str:
    """``serviceKey=`` 쿼리 값과 등록된 비밀값을 ``***`` 로 바꿉니다."""
    text = _SERVICE_KEY_PARAM.sub(rf"\g<1>{MASK}", text)
    with _lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, MASK)
    return text


class RedactingFormatter(logging.Formatter):
    """메시지·예외 트레이스백을 포함한 최종 로그 문자열 전체를 가립니다."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
