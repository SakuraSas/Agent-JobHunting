from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import re
from urllib.parse import urlsplit, urlunsplit


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, parts.query, ""))


def build_dedupe_key(company: str, title: str, city: str, source_url: str) -> str:
    identity = "|".join(
        [_normalize(company), _normalize(title), _normalize(city), _normalize_url(source_url)]
    )
    return sha256(identity.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CrawledJob:
    id: str
    source: str
    title: str
    company: str
    city: str
    job_type: str
    description: str
    requirements: str
    source_url: str
    salary_min: int | None = None
    salary_max: int | None = None
    education: str | None = None
    published_at: str | None = None
    crawled_at: str | None = None
    content_hash: str | None = None
    dedupe_key: str | None = None
    last_seen_at: str | None = None
    inactive_reason: str | None = None
    status: str = "active"

    def finalize(self) -> "CrawledJob":
        if not self.crawled_at:
            self.crawled_at = datetime.now(timezone.utc).isoformat()
        self.last_seen_at = self.crawled_at
        self.content_hash = sha256(self.vector_text().encode("utf-8")).hexdigest()
        self.dedupe_key = build_dedupe_key(self.company, self.title, self.city, self.source_url)
        return self

    def vector_text(self) -> str:
        return "\n".join(
            [
                f"岗位名称：{self.title}",
                f"公司：{self.company}",
                f"城市：{self.city}",
                f"岗位类型：{self.job_type}",
                f"学历要求：{self.education or '未说明'}",
                f"岗位职责：{self.description}",
                f"任职要求：{self.requirements}",
            ]
        )

    def to_dict(self) -> dict:
        return asdict(self)
