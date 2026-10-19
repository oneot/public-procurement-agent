# 기여 가이드 (Contributing)

이슈와 PR 모두 환영합니다. 큰 변경은 먼저 이슈로 방향을 맞춰 주세요.

## 개발 환경

[uv](https://docs.astral.sh/uv/) 를 사용합니다.

```bash
uv sync --all-extras        # 가상환경 + 개발 도구(ruff, mypy, pytest) 설치
uv run ruff check           # 린트
uv run ruff format          # 포맷
uv run mypy                 # 타입 검사 (strict)
uv run pytest               # 테스트
```

의존성을 바꿨다면 `uv lock` 으로 `uv.lock` 을 갱신해 함께 커밋하세요.

## 규칙

- **실제 API 응답이나 개인정보를 커밋하지 마세요.** 나라장터 응답에는 담당 공무원 이름·전화번호가
  들어 있습니다. 테스트 데이터는 반드시 가짜(합성) 값으로 만드세요 (`tests/conftest.py` 참고).
- 인증키·연결 문자열·이메일 주소를 코드, 테스트, 로그 출력에 넣지 마세요.
- 기본 필터(키워드·제외어·임계값)와 CSV 컬럼은 하위 호환을 위해 함부로 바꾸지 않습니다.
  바꿔야 한다면 PR 설명에 이유와 영향을 적어 주세요.
- 새 기능에는 테스트를 추가하고, CI(ruff · mypy · pytest)가 통과해야 병합합니다.
- 보안 문제는 이슈 대신 [SECURITY.md](SECURITY.md) 절차를 따라 주세요.
