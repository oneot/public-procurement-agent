from __future__ import annotations

import logging
import sys

from public_procurement_agent.redact import (
    MASK,
    RedactingFormatter,
    redact,
    register_secret,
)


def test_redacts_service_key_query_parameter_even_if_unregistered() -> None:
    url = "https://apis.data.go.kr/x?serviceKey=abc%2Bdef&type=json"
    assert redact(url) == f"https://apis.data.go.kr/x?serviceKey={MASK}&type=json"
    assert redact("SERVICEKEY=zzz") == f"SERVICEKEY={MASK}"


def test_redacts_registered_secret_and_encoded_variants() -> None:
    register_secret("s3cr3t+/=")
    assert redact("raw s3cr3t+/= quoted s3cr3t%2B%2F%3D plus s3cr3t%2B%2F%3D") == (
        f"raw {MASK} quoted {MASK} plus {MASK}"
    )


def test_ignores_empty_and_very_short_values() -> None:
    register_secret("")
    register_secret(None)
    register_secret("ab")
    assert redact("ab cd") == "ab cd"


def test_formatter_redacts_messages_and_tracebacks() -> None:
    register_secret("TOPSECRET")
    formatter = RedactingFormatter("%(message)s")
    try:
        raise RuntimeError("failed with TOPSECRET")
    except RuntimeError:
        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "key=%s", ("TOPSECRET",), sys.exc_info()
        )
    output = formatter.format(record)
    assert "TOPSECRET" not in output
    assert f"key={MASK}" in output
    assert f"failed with {MASK}" in output
