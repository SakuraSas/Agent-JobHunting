import sqlite3
import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from job_agent.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, parts.query, ""))


def _build_dedupe_key(job: dict[str, Any]) -> str:
    identity = "|".join(
        [
            _normalize(job["company"]),
            _normalize(job["title"]),
            _normalize(job["city"]),
            _normalize_url(job["source_url"]),
        ]
    )
    return sha256(identity.encode("utf-8")).hexdigest()


def _content_hash(job: dict[str, Any]) -> str:
    content = "\n".join(
        [
            f"岗位名称：{job['title']}",
            f"公司：{job['company']}",
            f"城市：{job['city']}",
            f"岗位类型：{job['job_type']}",
            f"学历要求：{job.get('education') or '未说明'}",
            f"岗位职责：{job['description']}",
            f"任职要求：{job['requirements']}",
        ]
    )
    return sha256(content.encode("utf-8")).hexdigest()


def _get_db_path() -> Path:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        raise ValueError("第一版仅支持 sqlite:/// 格式的 DATABASE_URL")

    path = Path(settings.database_url.removeprefix(prefix))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                city TEXT NOT NULL,
                job_type TEXT NOT NULL,
                salary_min INTEGER,
                salary_max INTEGER,
                education TEXT,
                description TEXT NOT NULL,
                requirements TEXT NOT NULL,
                source_url TEXT NOT NULL
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        additions = {
            "source": "TEXT",
            "content_hash": "TEXT",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "published_at": "TEXT",
            "crawled_at": "TEXT",
            "dedupe_key": "TEXT",
            "last_seen_at": "TEXT",
            "inactive_reason": "TEXT",
        }
        for name, sql_type in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source_status ON jobs(source, status)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_sync_state (
                source TEXT PRIMARY KEY,
                last_sync_at TEXT NOT NULL,
                last_success_at TEXT,
                last_status TEXT NOT NULL,
                last_error TEXT,
                crawled_count INTEGER NOT NULL DEFAULT 0,
                changed_count INTEGER NOT NULL DEFAULT 0,
                inactive_count INTEGER NOT NULL DEFAULT 0,
                expired_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_sync_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                crawled_count INTEGER NOT NULL DEFAULT 0,
                changed_count INTEGER NOT NULL DEFAULT 0,
                inactive_count INTEGER NOT NULL DEFAULT 0,
                expired_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_review_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                city TEXT NOT NULL,
                source_url TEXT NOT NULL,
                confidence REAL NOT NULL,
                review_reasons TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reviewed_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_review_queue_status ON job_review_queue(status, updated_at)"
        )


def upsert_jobs(jobs: list[dict[str, Any]]) -> None:
    sql = """
        INSERT INTO jobs (
            id, title, company, city, job_type,
            salary_min, salary_max, education,
            description, requirements, source_url
        )
        VALUES (
            :id, :title, :company, :city, :job_type,
            :salary_min, :salary_max, :education,
            :description, :requirements, :source_url
        )
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            company = excluded.company,
            city = excluded.city,
            job_type = excluded.job_type,
            salary_min = excluded.salary_min,
            salary_max = excluded.salary_max,
            education = excluded.education,
            description = excluded.description,
            requirements = excluded.requirements,
            source_url = excluded.source_url
    """

    with get_connection() as conn:
        conn.executemany(sql, jobs)


def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    return dict(row) if row else None


def list_jobs(
    city: str | None = None,
    job_type: str | None = None,
    min_salary: int | None = None,
) -> list[dict[str, Any]]:
    init_db()
    conditions: list[str] = []
    params: list[Any] = []

    if city:
        conditions.append("city = ?")
        params.append(city)

    if job_type:
        conditions.append("job_type = ?")
        params.append(job_type)

    if min_salary is not None:
        conditions.append("salary_max >= ?")
        params.append(min_salary)

    conditions.append("(status IS NULL OR status = 'active')")

    sql = "SELECT * FROM jobs"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def list_job_catalog(
    limit: int = 50,
    offset: int = 0,
    city: str | None = None,
    job_type: str | None = None,
) -> dict[str, Any]:
    init_db()
    conditions = ["(status IS NULL OR status = 'active')"]
    params: list[Any] = []
    if city:
        conditions.append("city = ?")
        params.append(city)
    if job_type:
        conditions.append("job_type = ?")
        params.append(job_type)
    where = " WHERE " + " AND ".join(conditions)
    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM jobs{where}", params).fetchone()[0]
        inactive = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'inactive'").fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT id, title, company, city, job_type, published_at, source_url
            FROM jobs
            {where}
            ORDER BY published_at DESC, id
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    return {
        "active_total": total,
        "inactive_total": inactive,
        "offset": offset,
        "limit": limit,
        "returned": len(rows),
        "has_more": offset + len(rows) < total,
        "jobs": [dict(row) for row in rows],
    }


def get_job_database_summary(exclude_company: str | None = None, company_limit: int = 50) -> dict[str, Any]:
    init_db()
    active_where = "(status IS NULL OR status = 'active')"
    exclude_clause = ""
    params: list[Any] = []
    if exclude_company:
        exclude_clause = " AND company != ?"
        params.append(exclude_company)

    with get_connection() as conn:
        active_total = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {active_where}").fetchone()[0]
        inactive_total = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'inactive'").fetchone()[0]
        source_rows = conn.execute(
            f"""
            SELECT COALESCE(source, 'unknown') AS source, COUNT(*) AS count
            FROM jobs
            WHERE {active_where}
            GROUP BY COALESCE(source, 'unknown')
            ORDER BY count DESC, source
            """
        ).fetchall()
        company_rows = conn.execute(
            f"""
            SELECT company, COUNT(*) AS count
            FROM jobs
            WHERE {active_where}{exclude_clause}
            GROUP BY company
            ORDER BY count DESC, company
            LIMIT ?
            """,
            (*params, max(1, min(company_limit, 200))),
        ).fetchall()
        sample_rows = conn.execute(
            f"""
            SELECT id, title, company, city, job_type, source, source_url
            FROM jobs
            WHERE {active_where}{exclude_clause}
            ORDER BY published_at DESC, id
            LIMIT 20
            """,
            params,
        ).fetchall()

    return {
        "active_total": active_total,
        "inactive_total": inactive_total,
        "source_counts": [dict(row) for row in source_rows],
        "company_counts": [dict(row) for row in company_rows],
        "sample_jobs": [dict(row) for row in sample_rows],
        "exclude_company": exclude_company,
    }


def list_admin_jobs(limit: int = 200) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, source, title, company, city, source_url, published_at,
                   last_seen_at, status, inactive_reason
            FROM jobs
            ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                     published_at DESC, id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_source_sync_state() -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT source, last_sync_at, last_success_at, last_status, last_error,
                   crawled_count, changed_count, inactive_count, expired_count, duplicate_count
            FROM source_sync_state
            ORDER BY source
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_source_sync_logs(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, source, started_at, finished_at, status, crawled_count,
                   changed_count, inactive_count, expired_count, duplicate_count, error
            FROM source_sync_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_job_reviews(status: str | None = "pending", limit: int = 200) -> list[dict[str, Any]]:
    init_db()
    conditions = []
    params: list[Any] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    sql = """
        SELECT job_id, source, title, company, city, source_url, confidence,
               review_reasons, status, created_at, updated_at, reviewed_at
        FROM job_review_queue
    """
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    reviews = []
    for row in rows:
        item = dict(row)
        item["review_reasons"] = json.loads(item["review_reasons"])
        reviews.append(item)
    return reviews


def approve_job_review(job_id: str) -> str:
    init_db()
    now = _utc_now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT payload FROM job_review_queue WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Review job not found: {job_id}")
        job = json.loads(row["payload"])
        job["crawled_at"] = job.get("crawled_at") or now
        job["last_seen_at"] = now
        job["content_hash"] = _content_hash(job)
        job["dedupe_key"] = _build_dedupe_key(job)
        job["status"] = "active"
        job["inactive_reason"] = None
        conn.execute(
            """
            INSERT INTO jobs (
                id, title, company, city, job_type, salary_min, salary_max,
                education, description, requirements, source_url, source,
                content_hash, status, published_at, crawled_at, dedupe_key,
                last_seen_at, inactive_reason
            )
            VALUES (
                :id, :title, :company, :city, :job_type, :salary_min, :salary_max,
                :education, :description, :requirements, :source_url, :source,
                :content_hash, :status, :published_at, :crawled_at, :dedupe_key,
                :last_seen_at, :inactive_reason
            )
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                city = excluded.city,
                job_type = excluded.job_type,
                salary_min = excluded.salary_min,
                salary_max = excluded.salary_max,
                education = excluded.education,
                description = excluded.description,
                requirements = excluded.requirements,
                source_url = excluded.source_url,
                source = excluded.source,
                content_hash = excluded.content_hash,
                status = excluded.status,
                published_at = excluded.published_at,
                crawled_at = excluded.crawled_at,
                dedupe_key = excluded.dedupe_key,
                last_seen_at = excluded.last_seen_at,
                inactive_reason = excluded.inactive_reason
            """,
            job,
        )
        conn.execute(
            """
            UPDATE job_review_queue
            SET status = 'approved', updated_at = ?, reviewed_at = ?
            WHERE job_id = ?
            """,
            (now, now, job_id),
        )
    return job_id


def ignore_job_review(job_id: str) -> str:
    init_db()
    now = _utc_now()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE job_review_queue
            SET status = 'ignored', updated_at = ?, reviewed_at = ?
            WHERE job_id = ?
            """,
            (now, now, job_id),
        )
        if not cursor.rowcount:
            raise KeyError(f"Review job not found: {job_id}")
    return job_id
