"""나라장터(조달청) 입찰공고 수집 · K-12 교육 시장 주간 브리핑 생성기."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("public-procurement-agent")
except PackageNotFoundError:  # pragma: no cover - 설치하지 않은 소스 트리에서 실행할 때
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
