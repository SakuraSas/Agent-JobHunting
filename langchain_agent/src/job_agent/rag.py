from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from job_agent.config import settings
from job_agent.db import get_job_by_id, list_jobs

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"local_files_only": True},
    )


def get_vector_store() -> Chroma:
    chroma_dir = Path(settings.chroma_dir)
    if not chroma_dir.is_absolute():
        chroma_dir = PROJECT_ROOT / chroma_dir
    chroma_dir.mkdir(parents=True, exist_ok=True)

    return Chroma(
        collection_name="jobs",
        embedding_function=get_embeddings(),
        persist_directory=str(chroma_dir),
    )


def job_to_document(job: dict[str, Any]) -> Document:
    content = f"""
岗位名称：{job["title"]}
公司：{job["company"]}
城市：{job["city"]}
岗位类型：{job["job_type"]}
学历要求：{job["education"] or "未说明"}
岗位职责：{job["description"]}
任职要求：{job["requirements"]}
""".strip()

    return Document(
        page_content=content,
        metadata={
            "job_id": job["id"],
            "city": job["city"],
            "job_type": job["job_type"],
            "source_url": job["source_url"],
        },
    )


def rebuild_index() -> None:
    store = get_vector_store()
    jobs = list_jobs()

    if jobs:
        ids = [job["id"] for job in jobs]
        documents = [job_to_document(job) for job in jobs]

        store.delete(ids=ids)
        store.add_documents(documents=documents, ids=ids)

    print(f"已写入 {len(jobs)} 条岗位向量")


def sync_index(changed_ids: list[str], inactive_ids: list[str]) -> None:
    store = get_vector_store()
    jobs = [get_job_by_id(job_id) for job_id in changed_ids]
    active_jobs = [job for job in jobs if job and job.get("status", "active") == "active"]

    if active_jobs:
        ids = [job["id"] for job in active_jobs]
        documents = [job_to_document(job) for job in active_jobs]
        store.add_documents(documents=documents, ids=ids)

    if inactive_ids:
        store.delete(ids=inactive_ids)

    print(f"向量增量更新：upsert={len(active_jobs)} delete={len(inactive_ids)}")


def _build_chroma_filter(city: str | None, job_type: str | None) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = []
    if city:
        conditions.append({"city": {"$eq": city}})
    if job_type:
        conditions.append({"job_type": {"$eq": job_type}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def semantic_search(
    query: str,
    city: str | None = None,
    job_type: str | None = None,
    min_salary: int | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    allowed_jobs = list_jobs(
        city=city,
        job_type=job_type,
        min_salary=min_salary,
    )
    allowed_ids = {job["id"] for job in allowed_jobs}

    if not allowed_ids:
        return []

    store = get_vector_store()
    chroma_filter = _build_chroma_filter(city=city, job_type=job_type)
    candidate_k = max(top_k * 5, 50)

    documents = store.similarity_search(query, k=candidate_k, filter=chroma_filter)

    results: list[dict[str, Any]] = []
    for doc in documents:
        job_id = doc.metadata["job_id"]
        if job_id not in allowed_ids:
            continue

        results.append(
            {
                "job_id": job_id,
                "source_url": doc.metadata["source_url"],
                "content": doc.page_content,
            }
        )

        if len(results) >= top_k:
            break

    return results
