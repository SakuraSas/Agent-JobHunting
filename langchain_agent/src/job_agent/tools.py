from typing import Any

from langchain.tools import tool

from job_agent.db import get_job_by_id, get_job_database_summary, list_job_catalog
from job_agent.rag import semantic_search
from job_agent.resume import read_resume_by_name


@tool
def search_jobs(
    query: str,
    city: str | None = None,
    job_type: str | None = None,
    min_salary: int | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """根据求职需求搜索真实岗位。城市、岗位类型和最低薪资可作为硬条件。"""
    try:
        return semantic_search(
            query=query,
            city=city,
            job_type=job_type,
            min_salary=min_salary,
            top_k=top_k,
        )
    except Exception as exc:
        return [
            {
                "error": "向量索引读取失败，请先重建 Chroma 索引后再检索岗位。",
                "detail": str(exc),
            }
        ]


@tool
def list_available_jobs(
    limit: int = 50,
    offset: int = 0,
    city: str | None = None,
    job_type: str | None = None,
) -> dict[str, Any]:
    """分页列出数据库中的 active 岗位，并返回 active 总数。用于查询全部岗位或岗位数量。"""
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
    return list_job_catalog(limit=safe_limit, offset=safe_offset, city=city, job_type=job_type)


@tool
def summarize_job_database(exclude_company: str | None = None, company_limit: int = 50) -> dict[str, Any]:
    """统计数据库 active 岗位的来源和公司分布。用于回答有哪些数据源、除了某公司还有哪些岗位或公司。"""
    return get_job_database_summary(
        exclude_company=exclude_company,
        company_limit=max(1, min(company_limit, 200)),
    )


@tool
def get_job_detail(job_id: str) -> dict[str, Any]:
    """根据岗位 ID 查询完整的岗位信息。"""
    job = get_job_by_id(job_id)
    if job is None:
        return {"error": f"没有找到岗位：{job_id}"}

    return job


@tool
def read_resume_profile(resume_name: str) -> dict:
    """按固定目录中的简历文件名读取简历，用于简历概览、优化建议和能力分析。"""
    return {
        "resume_name": resume_name,
        "resume": read_resume_by_name(resume_name),
    }


@tool
def analyze_job_match(job_id: str, resume_name: str) -> dict:
    """根据岗位 ID 和固定目录中的简历文件名读取真实数据，用于匹配建议。"""
    job = get_job_by_id(job_id)

    if job is None:
        return {"error": f"没有找到岗位：{job_id}"}

    resume = read_resume_by_name(resume_name)

    return {
        "job": job,
        "resume": resume,
    }
