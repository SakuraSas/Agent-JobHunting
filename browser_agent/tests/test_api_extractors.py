from job_browsing_agent.api_extractors import extract_xiaomi_api_job, xiaomi_detail_url
from job_browsing_agent.models import BrowserSource


def _source() -> BrowserSource:
    return BrowserSource(
        name="xiaomi_campus_browser",
        adapter="xiaomi_campus",
        list_url="https://xiaomi.jobs.f.mioffice.cn/campus/?spread=J7NS6YR",
        robots_url="https://xiaomi.jobs.f.mioffice.cn/robots.txt",
        allowed_domains=["xiaomi.jobs.f.mioffice.cn"],
    )


def test_xiaomi_detail_url_preserves_spread() -> None:
    assert xiaomi_detail_url(_source(), "123") == (
        "https://xiaomi.jobs.f.mioffice.cn/campus/position/123/detail?spread=J7NS6YR"
    )


def test_extract_xiaomi_api_job() -> None:
    job = extract_xiaomi_api_job(
        {
            "id": "123",
            "title": "AI-Agent工程师",
            "description": "负责开发 Agent 平台和工具调用能力。",
            "requirement": "熟悉 Python、LangChain 和 API 集成。",
            "city_info": {"name": "南京"},
            "recruit_type": {"name": "实习"},
            "publish_time": 1779247988873,
        },
        _source(),
    )
    assert job is not None
    assert job.id == "xiaomi-campus-123"
    assert job.company == "小米"
    assert job.city == "南京"
    assert job.extraction_method == "xiaomi_public_api"
    assert job.source_url.endswith("/campus/position/123/detail?spread=J7NS6YR")


def test_extract_xiaomi_api_job_rejects_incomplete_payload() -> None:
    assert extract_xiaomi_api_job({"id": "123", "title": "Incomplete"}, _source()) is None
