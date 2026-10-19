"""명령행 인터페이스: ``procurement-agent {collect,build-email,send,run}``."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from public_procurement_agent import __version__
from public_procurement_agent.brief import (
    LATEST_BRIEF_NAME,
    find_latest_csv,
    render_subject,
    write_brief,
)
from public_procurement_agent.client import ApiError, NaraApiClient
from public_procurement_agent.collector import CollectionError, CollectionResult, Period, collect
from public_procurement_agent.config import AppConfig, ConfigError, get_service_key, load_config
from public_procurement_agent.formatting import now_kst, parse_yyyymmdd, today_kst
from public_procurement_agent.redact import RedactingFormatter
from public_procurement_agent.report import ReportPaths, write_reports
from public_procurement_agent.sender import MailSettings, SendError, send_email

log = logging.getLogger("public_procurement_agent")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

_LOG_HANDLER_NAME = "public_procurement_agent.cli"
#: 요청 URL·헤더 등을 INFO 이하로 기록할 수 있는 외부 로거 — 항상 WARNING 이상만 출력
_QUIET_LOGGERS = ("httpx", "httpcore", "azure")

Handler = Callable[[argparse.Namespace, AppConfig], int]

_EPILOG = """\
예시:
  procurement-agent run                      # 지난 7일 수집 → 리포트 + HTML 브리핑 (발송 안 함)
  procurement-agent run --send               # 위 과정 + ACS 이메일 발송
  procurement-agent collect --days 3 --min 100000000
  procurement-agent build-email output/초중고교육청_입찰공고_20261019.csv --date 20261019
  procurement-agent send --dry-run

환경변수(.env 지원): NARA_SERVICE_KEY (필수),
ACS_CONNECTION_STRING · MAIL_SENDER · MAIL_TO (발송 시), BRIEF_* (브랜딩).
자세한 내용은 README 를 참고하세요.
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(verbose=args.verbose)
    _load_dotenv()
    handler: Handler = args.handler
    try:
        return handler(args, load_config(args.config))
    except ConfigError as exc:
        log.error("설정 오류: %s", exc)
        return EXIT_USAGE
    except (ApiError, CollectionError, SendError, OSError) as exc:
        log.error("%s", exc)
        return EXIT_FAILURE
    except KeyboardInterrupt:
        log.error("사용자가 중단했습니다.")
        return EXIT_INTERRUPTED
    except Exception:
        log.exception("예상하지 못한 오류가 발생했습니다.")
        return EXIT_FAILURE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="procurement-agent",
        description="나라장터 입찰공고에서 K-12 교육기관 × AI/SW/클라우드/보안/PC 사업 기회를 "
        "수집하고 주간 이메일 브리핑을 만듭니다.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", type=Path, metavar="TOML", help="사용자 설정 파일")
    parser.add_argument("-v", "--verbose", action="store_true", help="디버그 로그 출력")

    # 하위 명령 뒤에 써도 되도록 같은 옵션을 다시 받되, 생략하면 상위 값이 유지되게 SUPPRESS 합니다.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c",
        "--config",
        type=Path,
        metavar="TOML",
        default=argparse.SUPPRESS,
        help="사용자 설정 파일 (기본 설정 위에 섹션 단위로 병합)",
    )
    common.add_argument(
        "-v", "--verbose", action="store_true", default=argparse.SUPPRESS, help="디버그 로그 출력"
    )

    output = argparse.ArgumentParser(add_help=False)
    output.add_argument(
        "-o", "--output-dir", type=Path, metavar="DIR", help="출력 디렉터리 (기본: 설정값 output)"
    )

    collect_opts = argparse.ArgumentParser(add_help=False)
    period = collect_opts.add_mutually_exclusive_group()
    period.add_argument(
        "--days",
        type=_positive_int,
        metavar="N",
        help="오늘(KST) 기준 최근 N일, 어제까지 (기본: 7)",
    )
    period.add_argument(
        "--date", type=_date_arg, metavar="YYYYMMDD", help="특정 날짜 하루만 수집 (등록일 기준)"
    )
    collect_opts.add_argument(
        "--min-budget",
        "--min",
        dest="min_budget",
        type=_non_negative_int,
        metavar="WON",
        help="최소 예산(원) (기본: 0 = 제한 없음)",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser(
        "collect",
        parents=[common, collect_opts, output],
        help="입찰공고 수집 → CSV·요약(MD)·엑셀 리포트",
    )
    p.set_defaults(handler=_cmd_collect)

    p = sub.add_parser(
        "build-email", parents=[common, output], help="수집 CSV → HTML 이메일 브리핑"
    )
    p.add_argument(
        "csv", nargs="?", type=Path, help="수집 CSV (기본: 출력 디렉터리에서 가장 최근 CSV)"
    )
    p.add_argument(
        "--date",
        type=_date_arg,
        metavar="YYYYMMDD",
        help="기준일 — 마감 D-day 계산·파일명에 사용 (기본: 오늘 KST)",
    )
    p.set_defaults(handler=_cmd_build_email)

    p = sub.add_parser("send", parents=[common, output], help="HTML 브리핑을 ACS Email 로 발송")
    p.add_argument(
        "--html", type=Path, help=f"발송할 HTML (기본: <출력 디렉터리>/{LATEST_BRIEF_NAME})"
    )
    p.add_argument("--subject", help="메일 제목 (기본: 설정 branding.email_subject)")
    p.add_argument("--dry-run", action="store_true", help="발송하지 않고 설정·본문만 확인")
    p.set_defaults(handler=_cmd_send)

    p = sub.add_parser(
        "run",
        parents=[common, collect_opts, output],
        help="collect → build-email → (--send 지정 시) send",
    )
    p.add_argument("--send", action="store_true", help="이메일까지 발송 (기본: 발송하지 않음)")
    p.set_defaults(handler=_cmd_run)
    return parser


def _cmd_collect(args: argparse.Namespace, config: AppConfig) -> int:
    _collect(args, config, today=today_kst())
    return EXIT_OK


def _cmd_build_email(args: argparse.Namespace, config: AppConfig) -> int:
    output_dir = _output_dir(args, config)
    csv_path: Path = args.csv or find_latest_csv(output_dir)
    today: date = args.date or today_kst()
    paths = write_brief(csv_path, output_dir, today=today, config=config)
    log.info("[완료] 브리핑 생성: %s (기준일 %s)", paths.dated, today.isoformat())
    return EXIT_OK


def _cmd_send(args: argparse.Namespace, config: AppConfig) -> int:
    settings = MailSettings.from_env()
    html_path: Path = args.html or _output_dir(args, config) / LATEST_BRIEF_NAME
    html = html_path.read_text(encoding="utf-8")
    subject: str = args.subject or render_subject(config.branding, today_kst())
    if args.dry_run:
        log.info(
            "[dry-run] 발송 생략 — 제목: %s / 수신자 %d명 / 본문 %d바이트",
            subject,
            len(settings.recipients),
            len(html.encode("utf-8")),
        )
        return EXIT_OK
    send_email(settings, subject=subject, html=html)
    return EXIT_OK


def _cmd_run(args: argparse.Namespace, config: AppConfig) -> int:
    # 발송할 계획이면 API 를 호출하기 전에 발송 설정부터 검증합니다.
    settings = MailSettings.from_env() if args.send else None
    today = today_kst()
    report = _collect(args, config, today=today)
    brief = write_brief(report.csv, _output_dir(args, config), today=today, config=config)
    log.info("[완료] 브리핑 생성: %s", brief.dated)
    if settings is None:
        log.info("이메일은 발송하지 않았습니다 (발송하려면 --send).")
        return EXIT_OK
    send_email(
        settings,
        subject=render_subject(config.branding, today),
        html=brief.latest.read_text(encoding="utf-8"),
    )
    return EXIT_OK


def _collect(args: argparse.Namespace, config: AppConfig, *, today: date) -> ReportPaths:
    service_key = get_service_key()
    period = (
        Period.single_day(args.date)
        if args.date
        else Period.last_days(today, args.days or config.collect.days)
    )
    min_budget: int = config.collect.min_budget if args.min_budget is None else args.min_budget
    log.info("[수집기간] %s (등록일시 기준)", period.label)
    log.info("[대상] %s × %s", config.filters.audience_label, config.filters.topic_label)

    with _make_client(config, service_key) as client:
        result = collect(client, config, period, min_budget=min_budget)
    if result.failed_operations:
        _warn_partial_failure(result)
    log.info(
        "[결과] 전체 %d건 → 교육기관 %d건 → 초점 주제 매칭 %d건",
        result.scanned,
        result.k12_count,
        len(result.notices),
    )
    paths = write_reports(
        result, config, output_dir=_output_dir(args, config), today=today, generated_at=now_kst()
    )
    written = [paths.csv, paths.summary, *([paths.xlsx] if paths.xlsx else [])]
    log.info("[완료] 리포트 생성: %s", ", ".join(str(path) for path in written))
    return paths


def _make_client(config: AppConfig, service_key: str) -> NaraApiClient:
    api = config.api
    return NaraApiClient(
        service_key,
        base_url=api.base_url,
        page_size=api.page_size,
        timeout_seconds=api.timeout_seconds,
        max_retries=api.max_retries,
        backoff_seconds=api.backoff_seconds,
    )


def _warn_partial_failure(result: CollectionResult) -> None:
    message = (
        f"일부 업무 구분({', '.join(result.failed_operations)}) 조회에 실패했습니다. "
        "브리핑에서 해당 공고가 빠졌을 수 있습니다."
    )
    log.warning(message)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=일부 API 조회 실패::{message}", flush=True)


def _output_dir(args: argparse.Namespace, config: AppConfig) -> Path:
    output_dir: Path | None = args.output_dir
    return output_dir or config.collect.output_dir


def _configure_logging(*, verbose: bool) -> None:
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == _LOG_HANDLER_NAME:
            root.removeHandler(existing)
    handler = logging.StreamHandler()
    handler.set_name(_LOG_HANDLER_NAME)
    handler.setFormatter(RedactingFormatter("%(levelname)-7s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _load_dotenv() -> None:
    """현재 디렉터리의 ``.env`` 를 읽습니다. 이미 설정된 환경변수가 우선합니다."""
    env_file = Path.cwd() / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)


def _int_arg(text: str) -> int:
    try:
        return int(text.replace(",", "").replace("_", ""))
    except ValueError:
        raise argparse.ArgumentTypeError(f"정수가 아닙니다: {text!r}") from None


def _positive_int(text: str) -> int:
    value = _int_arg(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"1 이상의 정수여야 합니다: {text!r}")
    return value


def _non_negative_int(text: str) -> int:
    value = _int_arg(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"0 이상의 정수여야 합니다: {text!r}")
    return value


def _date_arg(text: str) -> date:
    try:
        return parse_yyyymmdd(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"YYYYMMDD 형식의 날짜가 아닙니다: {text!r}") from None
