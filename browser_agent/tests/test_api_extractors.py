from job_browsing_agent.api_extractors import (
    extract_uestc_recruitment_api_job,
    extract_xiaomi_api_job,
    xiaomi_detail_url,
)
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


def test_extract_uestc_internship_api_job() -> None:
    source = BrowserSource(
        name="uestc_internship_browser",
        adapter="uestc_recruitment",
        list_url="https://jiuye.uestc.edu.cn/career/recruitment/internship",
        robots_url="https://jiuye.uestc.edu.cn/robots.txt",
        allowed_domains=["jiuye.uestc.edu.cn"],
        api_request_body={"type": "INTERNSHIP_RECRUITMENT"},
    )
    job = extract_uestc_recruitment_api_job(
        {
            "id": "2061711229795868673",
            "companyName": "新华三技术有限公司",
            "recruitmentTypeLabel": "实习招聘",
            "workLocation": "北京市:海淀区,浙江省:杭州市",
            "publishTime": "2026-06-02 16:05:25",
            "resumeEndTime": "2026-09-01 00:00:00",
            "educationRequirementLabel": ["本科", "硕士"],
            "occupationCategoryLabel": ["技术类", "销售类"],
            "companyIntroduction": "<p>新华三集团作为数字化及AI解决方案领导者。</p>",
            "preachingUrls": '["https://career.h3c.com/intern/jobs"]',
            "attachmentUrl": (
                '[{"name":"新华三-2026年实习生招聘招聘简章.docx"}]'
            ),
        },
        source,
    )
    assert job is not None
    assert job.id == "uestc-internship-2061711229795868673"
    assert job.company == "新华三技术有限公司"
    assert job.city == "北京市:海淀区,浙江省:杭州市"
    assert job.job_type == "实习招聘"
    assert job.education == "本科、硕士"
    assert "新华三集团" in job.description
    assert "新华三-2026年实习生招聘招聘简章.docx" in job.requirements
    assert job.source_url.endswith("/career/recruitment/internship?id=2061711229795868673")
