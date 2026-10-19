# 보안 정책 (Security Policy)

## 지원 버전

보안 수정은 `main` 브랜치의 최신 버전에만 적용됩니다.

## 취약점 신고

**공개 이슈로 신고하지 마세요.** GitHub의 비공개 취약점 신고 기능을 이용해 주세요.

1. 저장소의 **Security** 탭 → **Report a vulnerability** 를 누릅니다.
2. 재현 방법, 영향 범위, 가능하면 수정 제안을 함께 적어 주세요.

접수 후 가능한 한 빨리(보통 7일 이내) 회신하고, 수정이 배포되면 신고자와 협의해 공개합니다.

다음과 같은 경우도 비공개로 알려 주세요.

- 코드·커밋 기록·Actions 로그 등에서 인증키, 연결 문자열, 이메일 주소 같은 비밀값이나 개인정보를 발견한 경우
- 워크플로가 포크·외부 기여로 비밀값을 노출할 수 있는 경로를 발견한 경우

## 운영자 참고

- 인증키·연결 문자열은 저장소 시크릿에만 보관하고, 노출이 의심되면 즉시 재발급(rotate)하세요.
- 공개 저장소의 Actions 로그·아티팩트는 누구나 볼 수 있습니다. 이 프로젝트는 서비스 키와
  수신자 주소를 로그에서 가리고 리포트를 아티팩트로 올리지 않습니다 — 이 원칙을 깨는 변경은 받지 않습니다.
- 저장소 **Variables** 값은 Actions 로그에 가려지지 않고 그대로 출력됩니다. 공개 로그에 남기고 싶지 않은 값
  (예: `BRIEF_*` 브랜딩 문구)은 **Secrets** 로 등록하세요.

---

**English:** Please do not open public issues for security problems. Use GitHub's
[private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(**Security → Report a vulnerability**). Leaked secrets or personal data found in code, history, or
workflow logs should be reported the same way.
