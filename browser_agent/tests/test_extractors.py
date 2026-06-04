from job_browsing_agent.extractors import extract_with_rules
from job_browsing_agent.adapters import extract_xiaomi_campus
from job_browsing_agent.models import PageSnapshot
from job_browsing_agent.quality import needs_review


def test_extracts_jsonld_job_posting() -> None:
    html = """
    <html><head><script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      "title": "Python Engineer",
      "description": "Build reliable Python services for our public platform.",
      "qualifications": "Python, Docker, SQL",
      "hiringOrganization": {"name": "Example Ltd"},
      "jobLocation": {"address": {"addressLocality": "Chengdu"}},
      "datePosted": "2026-06-01"
    }
    </script></head><body>Python Engineer</body></html>
    """
    snapshot = PageSnapshot(url="https://example.com/jobs/1", title="Job", visible_text="Job", html=html)
    job = extract_with_rules(snapshot, "example")
    assert job is not None
    assert job.title == "Python Engineer"
    assert job.company == "Example Ltd"
    assert job.requirements == "Python, Docker, SQL"
    assert not needs_review(job)


def test_rules_extract_visible_sections_for_review() -> None:
    text = """Backend Intern
    Company: Example
    岗位职责
    开发 Python API，维护服务稳定性，编写单元测试并参与代码评审。
    岗位要求
    熟悉 Python、FastAPI 和 SQL。
    工作地点
    成都
    """
    html = f"<html><body><h1>Backend Intern</h1><main>{text}</main></body></html>"
    snapshot = PageSnapshot(url="https://example.com/jobs/2", title="Job", visible_text=text, html=html)
    job = extract_with_rules(snapshot, "example")
    assert job is not None
    assert job.extraction_method == "visible_text_rules"
    assert "Python" in job.requirements
    assert needs_review(job)


def test_xiaomi_campus_adapter_extracts_visible_detail() -> None:
    text = """小米招聘投递须知
    登录
    AI-Agent工程师-2027届
    南京校招实习软件研发类实习生招聘计划
    职位描述
    1.参与智能体平台架构设计与模块集成
    2.负责AI Agent开发工具链的部署与优化
    职位要求
    1.本科及以上学历在读
    2.精通Python编程，熟悉LangChain、AutoGen
    投递
    """
    snapshot = PageSnapshot(
        url="https://xiaomi.jobs.f.mioffice.cn/campus/position/7629619317541325062/detail?spread=J7NS6YR",
        title="AI-Agent工程师-2027届 - 小米校园招聘",
        visible_text=text,
        html="<html></html>",
    )
    job = extract_xiaomi_campus(snapshot, "xiaomi_campus_browser")
    assert job is not None
    assert job.id == "xiaomi-campus-7629619317541325062"
    assert job.title == "AI-Agent工程师-2027届"
    assert job.company == "小米"
    assert job.city == "南京"
    assert job.job_type == "实习"
    assert "LangChain" in job.requirements


def test_xiaomi_campus_adapter_skips_hot_job_tag() -> None:
    text = """小米招聘投递须知
    登录
    计算机视觉算法实习生
    热招
    北京校招实习算法类实习生招聘计划
    职位描述
    1.参与图像相关领域的计算机视觉算法研发工作
    职位要求
    1.熟悉PyTorch和Python
    投递
    """
    snapshot = PageSnapshot(
        url="https://xiaomi.jobs.f.mioffice.cn/campus/position/7631489236621183286/detail",
        title="计算机视觉算法实习生 - 小米校园招聘",
        visible_text=text,
        html="<html></html>",
    )
    job = extract_xiaomi_campus(snapshot, "xiaomi_campus_browser")
    assert job is not None
    assert job.title == "计算机视觉算法实习生"
