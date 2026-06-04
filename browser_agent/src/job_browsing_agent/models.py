from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, parts.query, ""))


class BrowserSource(BaseModel):
    name: str
    enabled: bool = True
    adapter: str | None = None
    list_url: str
    robots_url: str
    allow_missing_robots_txt: bool = False
    allowed_domains: list[str]
    detail_url_patterns: list[str] = Field(default_factory=list)
    detail_url_regex: str | None = None
    api_pagination: bool = False
    api_response_pattern: str | None = None
    api_next_selector: str | None = None
    api_max_pages: int | None = Field(default=None, ge=1)
    max_list_pages: int = Field(default=1, ge=1)
    max_detail_jobs: int = Field(default=30, ge=1)
    detail_concurrency: int = Field(default=3, ge=1, le=5)
    llm_concurrency: int = Field(default=2, ge=1, le=3)
    request_delay_seconds: float = Field(default=1.0, ge=0.5)
    navigation_wait_ms: int = Field(default=500, ge=0, le=10000)
    use_llm_fallback: bool = False


class PageSnapshot(BaseModel):
    url: str
    title: str
    visible_text: str
    html: str
    captured_at: str = Field(default_factory=utc_now)
    snapshot_path: str | None = None

    def save(self, root: Path) -> Path:
        digest = sha256(self.url.encode("utf-8")).hexdigest()[:16]
        target = root / f"{digest}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"URL: {self.url}\nTITLE: {self.title}\nCAPTURED_AT: {self.captured_at}\n\n"
            f"{self.visible_text}",
            encoding="utf-8",
        )
        self.snapshot_path = str(target.resolve())
        return target


class ExtractedJobCandidate(BaseModel):
    id: str
    source: str
    title: str
    company: str
    city: str = "未说明"
    job_type: str = "公开职位"
    description: str
    requirements: str
    source_url: str
    salary_min: int | None = None
    salary_max: int | None = None
    education: str | None = None
    published_at: str | None = None
    extraction_method: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    snapshot_path: str | None = None

    @field_validator("title", "company", "description", "requirements")
    @classmethod
    def required_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("field must not be blank")
        return cleaned

    def crawled_job_payload(self) -> dict:
        return {
            key: value
            for key, value in self.model_dump().items()
            if key
            in {
                "id",
                "source",
                "title",
                "company",
                "city",
                "job_type",
                "description",
                "requirements",
                "source_url",
                "salary_min",
                "salary_max",
                "education",
                "published_at",
            }
        }


class BrowserRunReport(BaseModel):
    source: str
    started_at: str
    finished_at: str
    discovered_urls: list[str]
    accepted_jobs: list[ExtractedJobCandidate]
    review_jobs: list[ExtractedJobCandidate]
    skipped_urls: list[str]
    collection_method: str = "detail_pages"
