from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

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


def _published_at_text(value: object) -> str | None:
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


def _strip_html(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = BeautifulSoup(value, "lxml").get_text("\n")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _list_text(value: object) -> str:
    if isinstance(value, list):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ""
    return str(value).strip()


def _parse_json_list(value: object) -> list:
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _attachment_names(value: object) -> list[str]:
    names: list[str] = []
    for item in _parse_json_list(value):
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def _first_external_url(value: object) -> str | None:
    for item in _parse_json_list(value):
        if isinstance(item, str) and item.strip():
            url = item.strip()
            if url and url != "":
                return url if re.match(r"^https?://", url) else f"https://{url}"
    return None


def _published_at(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return value.strip()


def _uestc_source_url(source: BrowserSource, job_id: str) -> str:
    return f"{source.list_url}?id={job_id}"


def extract_uestc_recruitment_api_job(
    item: dict, source: BrowserSource
) -> ExtractedJobCandidate | None:
    job_id = str(item.get("id") or "").strip()
    company = str(item.get("companyName") or "").strip()
    recruitment_type = str(item.get("recruitmentTypeLabel") or "实习招聘").strip()
    city = str(item.get("workLocation") or "").strip() or "未说明"
    intro = _strip_html(item.get("companyIntroduction"))
    education = _list_text(item.get("educationRequirementLabel"))
    occupation = _list_text(item.get("occupationCategoryLabel"))
    publish_time = str(item.get("publishTime") or "").strip()
    deadline = str(item.get("resumeEndTime") or "").strip()
    contact_name = str(item.get("contactPerson") or "").strip()
    contact_phone = str(item.get("contactPhone") or "").strip()
    contact_email = str(item.get("contactEmail") or "").strip()
    expected_number = str(item.get("expectedNumber") or "").strip()
    attachment_names = _attachment_names(item.get("attachmentUrl"))
    external_url = _first_external_url(item.get("preachingUrls")) or str(item.get("onlineUrl") or "").strip()

    if not job_id or not company:
        return None

    title = str(item.get("title") or "").strip()
    if not title and attachment_names:
        title = re.sub(r"\.(docx?|pdf|xlsx?)$", "", attachment_names[0], flags=re.IGNORECASE).strip()
    if not title:
        title = f"{company}{recruitment_type}"

    description_parts = [
        f"招聘类型：{recruitment_type}",
        f"公司：{company}",
        f"工作地点：{city}",
        f"发布时间：{publish_time}" if publish_time else "",
        f"简历截止时间：{deadline}" if deadline else "",
        f"招聘人数：{expected_number}" if expected_number else "",
        f"公司介绍：{intro}" if intro else "",
    ]
    description = "\n".join(part for part in description_parts if part)

    requirement_parts = [
        f"学历要求：{education}" if education else "",
        f"岗位类别：{occupation}" if occupation else "",
        f"投递/宣讲链接：{external_url}" if external_url else "",
        f"附件：{'；'.join(attachment_names)}" if attachment_names else "",
        f"联系人：{contact_name}" if contact_name else "",
        f"联系电话：{contact_phone}" if contact_phone else "",
        f"联系邮箱：{contact_email}" if contact_email else "",
        "说明：电子科大就业网部分实习招聘的完整岗位职责和要求位于附件中，需打开原始链接或附件核实。",
    ]
    requirements = "\n".join(part for part in requirement_parts if part)

    confidence = 0.86 if intro and (education or occupation or attachment_names) else 0.72
    return ExtractedJobCandidate(
        id=f"uestc-internship-{job_id}",
        source=source.name,
        title=title,
        company=company,
        city=city,
        job_type="实习招聘",
        description=description,
        requirements=requirements,
        source_url=_uestc_source_url(source, job_id),
        education=education or None,
        published_at=_published_at_text(item.get("publishTime")),
        extraction_method="uestc_recruitment_public_api",
        confidence=confidence,
        evidence=["public /career/api/home/recruitmentList response"],
    )


API_EXTRACTORS = {
    "xiaomi_campus": extract_xiaomi_api_job,
    "uestc_recruitment": extract_uestc_recruitment_api_job,
}
