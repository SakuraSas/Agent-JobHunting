from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

from bs4 import BeautifulSoup

from job_browsing_agent.models import ExtractedJobCandidate, PageSnapshot

DESCRIPTION_HEADINGS = ("岗位职责", "职位描述", "工作职责", "工作内容", "Job Description", "Responsibilities")
REQUIREMENTS_HEADINGS = ("岗位要求", "任职要求", "职位要求", "任职资格", "Requirements", "Qualifications")
STOP_HEADINGS = ("工作地点", "职位类别", "招聘对象", "投递", "申请", "About the Company", "How to Apply")


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _candidate_id(source: str, url: str) -> str:
    return f"{source}-{sha256(url.encode('utf-8')).hexdigest()[:16]}"


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(_as_text(item) for item in value if item)
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_as_text(item)}" for key, item in value.items() if item)
    return _clean(str(value)) if value is not None else ""


def _find_job_postings(value: Any) -> list[dict]:
    if isinstance(value, list):
        result: list[dict] = []
        for item in value:
            result.extend(_find_job_postings(item))
        return result
    if not isinstance(value, dict):
        return []
    result = [value] if value.get("@type") == "JobPosting" else []
    if "@graph" in value:
        result.extend(_find_job_postings(value["@graph"]))
    return result


def extract_jsonld(snapshot: PageSnapshot, source: str) -> ExtractedJobCandidate | None:
    soup = BeautifulSoup(snapshot.html, "lxml")
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            values = _find_job_postings(json.loads(node.get_text()))
        except json.JSONDecodeError:
            continue
        for value in values:
            title = _as_text(value.get("title"))
            description = _as_text(value.get("description"))
            company = _as_text((value.get("hiringOrganization") or {}).get("name"))
            address = ((value.get("jobLocation") or {}).get("address") or {})
            city = _as_text(address.get("addressLocality")) or _as_text(value.get("jobLocationType"))
            requirements = _as_text(
                value.get("qualifications") or value.get("skills") or value.get("experienceRequirements")
            )
            if title and company and description:
                return ExtractedJobCandidate(
                    id=_candidate_id(source, snapshot.url),
                    source=source,
                    title=title,
                    company=company,
                    city=city or "未说明",
                    job_type=_as_text(value.get("employmentType")) or "公开职位",
                    description=description,
                    requirements=requirements or "未单独说明，请查看职位描述",
                    source_url=snapshot.url,
                    published_at=_as_text(value.get("datePosted")) or None,
                    extraction_method="jsonld",
                    confidence=0.95,
                    evidence=["JSON-LD JobPosting"],
                    snapshot_path=snapshot.snapshot_path,
                )
    return None


def _section(text: str, headings: tuple[str, ...], stops: tuple[str, ...]) -> str:
    start = re.search("|".join(re.escape(item) for item in headings), text, re.IGNORECASE)
    if not start:
        return ""
    remainder = text[start.end() :]
    end = re.search("|".join(re.escape(item) for item in stops), remainder, re.IGNORECASE)
    return _clean(remainder[: end.start()] if end else remainder)


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        node = soup.select_one(f'meta[property="{name}"], meta[name="{name}"]')
        if node and node.get("content"):
            return _clean(node["content"])
    return ""


def extract_visible_text(snapshot: PageSnapshot, source: str) -> ExtractedJobCandidate | None:
    soup = BeautifulSoup(snapshot.html, "lxml")
    text = snapshot.visible_text
    description = _section(text, DESCRIPTION_HEADINGS, REQUIREMENTS_HEADINGS + STOP_HEADINGS)
    requirements = _section(text, REQUIREMENTS_HEADINGS, STOP_HEADINGS)
    title_node = soup.select_one("h1")
    title = _clean(title_node.get_text(" ", strip=True) if title_node else "")
    title = title or _meta(soup, "og:title") or snapshot.title
    company = _meta(soup, "og:site_name")
    if not company:
        match = re.search(r"(?:公司|Company)\s*[:：]\s*([^\n]{2,80})", text, re.IGNORECASE)
        company = _clean(match.group(1)) if match else "未说明"

    if not title or not description:
        return None
    confidence = 0.70 if requirements else 0.58
    return ExtractedJobCandidate(
        id=_candidate_id(source, snapshot.url),
        source=source,
        title=title,
        company=company,
        description=description,
        requirements=requirements or "未单独说明，请查看职位描述",
        source_url=snapshot.url,
        extraction_method="visible_text_rules",
        confidence=confidence,
        evidence=["visible text heading segmentation"],
        snapshot_path=snapshot.snapshot_path,
    )


def extract_with_rules(snapshot: PageSnapshot, source: str) -> ExtractedJobCandidate | None:
    return extract_jsonld(snapshot, source) or extract_visible_text(snapshot, source)

