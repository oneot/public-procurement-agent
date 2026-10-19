from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest

from public_procurement_agent import __version__, cli
from public_procurement_agent.client import NaraApiClient
from public_procurement_agent.config import AppConfig
from public_procurement_agent.formatting import today_kst
from public_procurement_agent.report import write_csv
from tests.factories import (
    FAKE_SERVICE_KEY,
    MAIL_ENV,
    FakeEmailClient,
    api_json,
    make_item,
    make_notice,
)

Handler = Callable[[httpx.Request], httpx.Response]
FAR_FUTURE = "2099-12-31 10:00:00"  # 실행 날짜와 무관하게 '마감 전' 공고


def ok_handler(request: httpx.Request) -> httpx.Response:
    operation = request.url.path.rsplit("/", 1)[-1]
    items = []
    if operation == "getBidPblancListInfoServc":
        items = [
            make_item(bidNtceNo="S1", bidClseDt=FAR_FUTURE),
            make_item(bidNtceNo="S2", bidNtceNm="교실 청소 용역", bidClseDt=FAR_FUTURE),
        ]
    return httpx.Response(200, json=api_json(items, total=len(items)))


def xml_error_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        text="<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>"
        "SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30"
        "</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>",
    )


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[httpx.Request]]:
    """CLI 가 실제 API 대신 MockTransport 를 쓰도록 바꾸고, 받은 요청 목록을 돌려줍니다."""

    def install(handler: Handler) -> list[httpx.Request]:
        requests: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handler(request)

        def factory(config: AppConfig, service_key: str) -> NaraApiClient:
            return NaraApiClient(
                service_key,
                base_url=config.api.base_url,
                transport=httpx.MockTransport(recording),
                sleep=lambda _: None,
            )

        monkeypatch.setattr(cli, "_make_client", factory)
        return requests

    return install


def set_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_collect_requires_service_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["collect"]) == cli.EXIT_USAGE
    assert "NARA_SERVICE_KEY" in capsys.readouterr().err


def test_run_without_send_writes_reports_and_brief(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fake_api: Callable[[Handler], list[httpx.Request]],
) -> None:
    set_env(monkeypatch, NARA_SERVICE_KEY=FAKE_SERVICE_KEY)
    requests = fake_api(ok_handler)

    assert cli.main(["run"]) == cli.EXIT_OK

    assert len(requests) == 4  # 물품·용역·공사·외자
    stamp = f"{today_kst():%Y%m%d}"
    output = tmp_path / "output"
    for name in (
        f"초중고교육청_입찰공고_{stamp}.csv",
        f"초중고교육청_요약_{stamp}.md",
        f"초중고교육청_입찰공고_{stamp}.xlsx",
        f"초중고교육청_브리핑_{stamp}.html",
        "brief_latest.html",
    ):
        assert (output / name).exists(), name
    html = (output / "brief_latest.html").read_text(encoding="utf-8")
    assert "AI 기반 학습관리 플랫폼 구축" in html
    assert "교실 청소 용역" not in html

    err = capsys.readouterr().err
    assert "[결과] 전체 2건 → 교육기관 2건 → 초점 주제 매칭 1건" in err
    assert "이메일은 발송하지 않았습니다" in err
    assert FAKE_SERVICE_KEY not in err


def test_run_with_send(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_api: Callable[[Handler], list[httpx.Request]],
    fake_acs: type[FakeEmailClient],
) -> None:
    set_env(monkeypatch, NARA_SERVICE_KEY=FAKE_SERVICE_KEY, BRIEF_BRAND_NAME="Example", **MAIL_ENV)
    fake_api(ok_handler)

    assert cli.main(["run", "--send"]) == cli.EXIT_OK

    assert len(fake_acs.sent) == 1
    content = fake_acs.sent[0]["content"]
    assert content["subject"] == (
        f"WEEKLY KOREA K-12 MARKET PROCUREMENT BRIEF | {today_kst().isoformat()}"
    )
    assert ">Example</td>" in content["html"]
    err = capsys.readouterr().err
    assert "수신자 2명" in err
    assert "alice@example.com" not in err


def test_run_with_send_checks_mail_settings_before_calling_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_api: Callable[[Handler], list[httpx.Request]],
) -> None:
    set_env(monkeypatch, NARA_SERVICE_KEY=FAKE_SERVICE_KEY)
    requests = fake_api(ok_handler)

    assert cli.main(["run", "--send"]) == cli.EXIT_USAGE
    assert requests == []
    assert "MAIL_TO" in capsys.readouterr().err


def test_all_operations_failing_exits_non_zero_without_brief(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fake_api: Callable[[Handler], list[httpx.Request]],
) -> None:
    set_env(monkeypatch, NARA_SERVICE_KEY=FAKE_SERVICE_KEY)
    fake_api(xml_error_handler)

    assert cli.main(["run"]) == cli.EXIT_FAILURE
    assert not (tmp_path / "output" / "brief_latest.html").exists()
    err = capsys.readouterr().err
    assert "모든 업무 구분의 API 호출이 실패했습니다" in err
    assert "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in err
    assert FAKE_SERVICE_KEY not in err


def test_partial_failure_warns_in_github_actions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_api: Callable[[Handler], list[httpx.Request]],
) -> None:
    set_env(monkeypatch, NARA_SERVICE_KEY=FAKE_SERVICE_KEY, GITHUB_ACTIONS="true")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getBidPblancListInfoCnstwk"):
            return xml_error_handler(request)
        return ok_handler(request)

    fake_api(handler)
    assert cli.main(["collect"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert "::warning title=일부 API 조회 실패::일부 업무 구분(공사)" in captured.out


def test_collect_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_api: Callable[[Handler], list[httpx.Request]],
) -> None:
    set_env(monkeypatch, NARA_SERVICE_KEY=FAKE_SERVICE_KEY)
    requests = fake_api(ok_handler)
    config_file = tmp_path / "my.toml"
    config_file.write_text('[collect]\noutput_dir = "reports"\n', encoding="utf-8")

    assert cli.main(["collect", "--date", "20260724", "-c", str(config_file), "-v"]) == 0

    assert requests[0].url.params["inqryBgnDt"] == "202607240000"
    assert requests[0].url.params["inqryEndDt"] == "202607242359"
    assert any((tmp_path / "reports").glob("초중고교육청_입찰공고_*.csv"))


def test_dotenv_file_is_loaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_api: Callable[[Handler], list[httpx.Request]],
) -> None:
    (tmp_path / ".env").write_text(f"NARA_SERVICE_KEY={FAKE_SERVICE_KEY}\n", encoding="utf-8")
    requests = fake_api(ok_handler)
    assert cli.main(["collect", "--days", "1"]) == cli.EXIT_OK
    assert requests[0].url.params["serviceKey"] == FAKE_SERVICE_KEY


def test_build_email_uses_latest_csv(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    write_csv([make_notice(close_dt=FAR_FUTURE)], output / "초중고교육청_입찰공고_20261019.csv")

    assert cli.main(["build-email", "--date", "20261019"]) == cli.EXIT_OK
    html = (output / "초중고교육청_브리핑_20261019.html").read_text(encoding="utf-8")
    assert "2026년 10월 19일 (월)" in html


def test_build_email_without_csv(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["build-email"]) == cli.EXIT_FAILURE
    assert "먼저 collect 를 실행하세요" in capsys.readouterr().err


def test_send_dry_run_does_not_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fake_acs: type[FakeEmailClient],
) -> None:
    set_env(monkeypatch, BRIEF_EMAIL_SUBJECT="주간 브리핑 {date}", **MAIL_ENV)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "brief_latest.html").write_text("<p>hi</p>", encoding="utf-8")

    assert cli.main(["send", "--dry-run"]) == cli.EXIT_OK

    assert fake_acs.sent == []
    err = capsys.readouterr().err
    assert f"제목: 주간 브리핑 {today_kst().isoformat()}" in err
    assert "수신자 2명" in err
    assert "alice@example.com" not in err


def test_send_with_explicit_html_and_subject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_acs: type[FakeEmailClient]
) -> None:
    set_env(monkeypatch, **MAIL_ENV)
    html = tmp_path / "custom.html"
    html.write_text("<p>custom</p>", encoding="utf-8")

    assert cli.main(["send", "--html", str(html), "--subject", "직접 지정"]) == cli.EXIT_OK
    assert fake_acs.sent[0]["content"] == {"subject": "직접 지정", "html": "<p>custom</p>"}


def test_send_missing_html(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, **MAIL_ENV)
    assert cli.main(["send"]) == cli.EXIT_FAILURE


def test_unexpected_errors_are_logged_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_api: Callable[[Handler], list[httpx.Request]],
) -> None:
    set_env(monkeypatch, NARA_SERVICE_KEY=FAKE_SERVICE_KEY)
    fake_api(ok_handler)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(f"unexpected failure for key {FAKE_SERVICE_KEY}")

    monkeypatch.setattr(cli, "write_reports", boom)
    assert cli.main(["collect"]) == cli.EXIT_FAILURE
    err = capsys.readouterr().err
    assert "예상하지 못한 오류" in err
    assert "Traceback" in err
    assert FAKE_SERVICE_KEY not in err


def test_parser_accepts_global_options_before_or_after_subcommand() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["collect", "-v", "-c", "x.toml", "--days", "3", "--min", "1,000"])
    assert (args.verbose, args.config, args.days, args.min_budget) == (
        True,
        Path("x.toml"),
        3,
        1000,
    )
    args = parser.parse_args(["-v", "--config", "y.toml", "run", "--send"])
    assert (args.verbose, args.config, args.send) == (True, Path("y.toml"), True)
    args = parser.parse_args(["build-email", "a.csv", "--date", "20261019"])
    assert (args.verbose, args.config, args.csv, args.date) == (
        False,
        None,
        Path("a.csv"),
        date(2026, 10, 19),
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["collect", "--days", "0"],
        ["collect", "--date", "2026-10-19"],
        ["collect", "--days", "3", "--date", "20261019"],
        ["collect", "--min", "-1"],
        [],
    ],
)
def test_invalid_arguments_exit_with_usage_error(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv)
    assert excinfo.value.code == 2


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out
