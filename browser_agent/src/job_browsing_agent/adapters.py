from __future__ import annotations

import re

from job_browsing_agent.extractors import _clean
from job_browsing_agent.models import ExtractedJobCandidate, PageSnapshot


def extract_xiaomi_campus(
    snapshot: PageSnapshot, source: str
) -> ExtractedJobCandidate | None:
    match = re.search(r"/campus/position/(\d+)/detail", snapshot.url)
    lines = [line.strip() for line in snapshot.visible_text.splitlines() if line.strip()]
    try:
        description_index = lines.index("职位描述")
        requirement_index = lines.index("职位要求")
    except ValueError:
        return None
    if not match or description_index < 1 or requirement_index <= description_index:
        return None

    metadata_index = next(
        (
            index
            for index in range(description_index - 1, -1, -1)
            if "校招" in lines[index] or "社招" in lines[index]
        ),
        -1,
    )
    if metadata_index < 1:
        return None
    metadata = lines[metadata_index]
    title_index = metadata_index - 1
    while title_index >= 0 and lines[title_index] in {"热招", "急招", "置顶"}:
        title_index -= 1
    title = lines[title_index] if title_index >= 0 else ""
    description = "\n".join(lines[description_index + 1 : requirement_index])
    requirement_lines = lines[requirement_index + 1 :]
    if "投递" in requirement_lines:
        requirement_lines = requirement_lines[: requirement_lines.index("投递")]
    requirements = "\n".join(requirement_lines)
    city_match = re.match(r"(.+?)(?:校招|社招)", metadata)
    job_type = "实习" if "实习" in metadata else "校招"

    if not title or not description or not requirements:
        return None
    return ExtractedJobCandidate(
        id=f"xiaomi-campus-{match.group(1)}",
        source=source,
        title=title,
        company="小米",
        city=_clean(city_match.group(1)) if city_match else "未说明",
        job_type=job_type,
        description=description,
        requirements=requirements,
        source_url=snapshot.url,
        extraction_method="xiaomi_campus_adapter",
        confidence=0.94,
        evidence=["xiaomi campus stable detail URL", "visible text 职位描述/职位要求 segmentation"],
        snapshot_path=snapshot.snapshot_path,
    )


ADAPTERS = {
    "xiaomi_campus": extract_xiaomi_campus,
}
