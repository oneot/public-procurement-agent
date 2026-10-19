"""데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass

#: 수집 CSV 컬럼 (순서·이름은 하위 호환을 위해 고정)
CSV_COLUMNS: tuple[str, ...] = (
    "주제",
    "카테고리",
    "공고번호",
    "차수",
    "공고명",
    "고객기관",
    "공고기관",
    "계약방법",
    "예산금액(원)",
    "공고일시",
    "입찰마감",
    "개찰일시",
    "담당자",
    "연락처",
    "대형",
    "공고URL",
)


@dataclass(frozen=True, slots=True)
class BidNotice:
    """분류된 입찰공고 한 건."""

    category: str  # 업무 구분 (물품/용역/공사/외자)
    bid_no: str  # 공고번호
    bid_ord: str  # 차수
    name: str  # 공고명
    customer: str  # 고객기관 (수요기관 우선, 없으면 공고기관)
    notice_org: str  # 공고기관
    contract_method: str  # 계약방법
    budget: int  # 예산금액(원) — 배정예산·추정가격 중 최댓값
    notice_dt: str  # 공고일시
    close_dt: str  # 입찰마감
    open_dt: str  # 개찰일시
    officer: str  # 담당자
    phone: str  # 연락처
    url: str  # 공고URL
    is_k12: bool  # K-12 교육기관 여부
    topics: tuple[str, ...]  # 매칭된 초점 주제
    is_large: bool  # 대형 사업 여부

    @property
    def key(self) -> tuple[str, str]:
        """중복 제거 키 (공고번호, 차수)."""
        return (self.bid_no, self.bid_ord)

    def csv_row(self) -> list[str | int]:
        return [
            "/".join(self.topics),
            self.category,
            self.bid_no,
            self.bid_ord,
            self.name,
            self.customer,
            self.notice_org,
            self.contract_method,
            self.budget,
            self.notice_dt,
            self.close_dt,
            self.open_dt,
            self.officer,
            self.phone,
            "Y" if self.is_large else "",
            self.url,
        ]
