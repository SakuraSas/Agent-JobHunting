from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from job_browsing_agent.models import BrowserSource, ExtractedJobCandidate


def xiaomi_detail_url(source: BrowserSource, job_id: str) -> str:
    parts = urlsplit(source.list_url)
    query = parse_qs(parts.query)
    spread = query.get("spread", [])
    detail_query = urlencode({"spread": spread[0]}) if spread else ""
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            f"/campus/position/{job_id}/detail",
            detail_query,
            "",
        )
    )


def _published_at(value: object) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def extract_xiaomi_api_job(item: dict, source: BrowserSource) -> ExtractedJobCandidate | None:
    job_id = str(item.get("id") or "").strip()
    title = str(item.get("title") or "").strip()
    description = str(item.get("description") or "").strip()
    requirements = str(item.get("requirement") or "").strip()
    city_info = item.get("city_info") or {}
    recruit_type = item.get("recruit_type") or {}
    city = str(city_info.get("name") or "").strip() or "未说明"
    job_type = str(recruit_type.get("name") or "").strip() or "校招"
    if not job_id or not title or not description or not requirements:
        return None
    return ExtractedJobCandidate(
        id=f"xiaomi-campus-{job_id}",
        source=source.name,
        title=title,
        company="小米",
        city=city,
        job_type=job_type,
        description=description,
        requirements=requirements,
        source_url=xiaomi_detail_url(source, job_id),
        published_at=_published_at(item.get("publish_time")),
        extraction_method="xiaomi_public_api",
        confidence=0.97,
        evidence=["public /api/v1/search/job/posts response"],
    )


API_EXTRACTORS = {
    "xiaomi_campus": extract_xiaomi_api_job,
}
