import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from job_sync.models import CrawledJob, build_dedupe_key


@dataclass(slots=True)
class SyncResult:
    changed_ids: list[str]
    inactive_ids: list[str]
    expired_count: int
    duplicate_count: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
    except ValueError:
        pass
    for fmt in ("%d %B %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
        except ValueError:
            continue
    return None


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dedupe_key ON jobs(dedupe_key)")
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
        rows = conn.execute(
            "SELECT id, company, title, city, source_url FROM jobs WHERE dedupe_key IS NULL"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE jobs SET dedupe_key = ? WHERE id = ?",
                (build_dedupe_key(row["company"], row["title"], row["city"], row["source_url"]), row["id"]),
            )


def start_sync_log(db_path: Path, source: str) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO source_sync_logs (source, started_at, status) VALUES (?, ?, 'running')",
            (source, _utc_now()),
        )
        return int(cursor.lastrowid)


def finish_sync_log(
    db_path: Path,
    log_id: int,
    source: str,
    status: str,
    crawled_count: int = 0,
    result: SyncResult | None = None,
    error: str | None = None,
) -> None:
    finished_at = _utc_now()
    result = result or SyncResult([], [], 0, 0)
    values = (
        finished_at,
        status,
        crawled_count,
        len(result.changed_ids),
        len(result.inactive_ids),
        result.expired_count,
        result.duplicate_count,
        error,
        log_id,
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE source_sync_logs
            SET finished_at = ?, status = ?, crawled_count = ?, changed_count = ?,
                inactive_count = ?, expired_count = ?, duplicate_count = ?, error = ?
            WHERE id = ?
            """,
            values,
        )
        conn.execute(
            """
            INSERT INTO source_sync_state (
                source, last_sync_at, last_success_at, last_status, last_error,
                crawled_count, changed_count, inactive_count, expired_count, duplicate_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                last_sync_at = excluded.last_sync_at,
                last_success_at = CASE
                    WHEN excluded.last_status = 'success' THEN excluded.last_success_at
                    ELSE source_sync_state.last_success_at
                END,
                last_status = excluded.last_status,
                last_error = excluded.last_error,
                crawled_count = excluded.crawled_count,
                changed_count = excluded.changed_count,
                inactive_count = excluded.inactive_count,
                expired_count = excluded.expired_count,
                duplicate_count = excluded.duplicate_count
            """,
            (
                source,
                finished_at,
                finished_at if status == "success" else None,
                status,
                error,
                crawled_count,
                len(result.changed_ids),
                len(result.inactive_ids),
                result.expired_count,
                result.duplicate_count,
            ),
        )


def sync_jobs(
    db_path: Path,
    source: str,
    jobs: list[CrawledJob],
    expires_after_days: int = 120,
    mark_missing_inactive: bool = True,
    seen_job_ids: set[str] | None = None,
) -> SyncResult:
    init_db(db_path)
    now = _utc_now()
    cutoff = datetime.now(timezone.utc) - timedelta(days=expires_after_days)
    changed_ids: set[str] = set()
    inactive_ids: set[str] = set()
    expired_count = 0
    duplicate_count = 0
    incoming: dict[str, CrawledJob] = {}
    seen_dedupe_keys: set[str] = set()

    for job in jobs:
        job.finalize()
        job.last_seen_at = now
        if job.dedupe_key in seen_dedupe_keys:
            duplicate_count += 1
            continue
        seen_dedupe_keys.add(job.dedupe_key or "")
        published_at = _parse_published_at(job.published_at)
        if published_at and published_at < cutoff:
            job.status = "inactive"
            job.inactive_reason = "expired"
            expired_count += 1
        incoming[job.id] = job

    with connect(db_path) as conn:
        existing = {
            row["id"]: row
            for row in conn.execute(
                "SELECT id, content_hash, status FROM jobs WHERE source = ?",
                (source,),
            )
        }
        for job in incoming.values():
            if job.status == "active":
                duplicate = conn.execute(
                    """
                    SELECT id FROM jobs
                    WHERE dedupe_key = ? AND id != ? AND status = 'active'
                    ORDER BY id LIMIT 1
                    """,
                    (job.dedupe_key, job.id),
                ).fetchone()
                if duplicate:
                    job.status = "inactive"
                    job.inactive_reason = f"duplicate_of:{duplicate['id']}"
                    duplicate_count += 1

            row = existing.get(job.id)
            if row is None or row["content_hash"] != job.content_hash or row["status"] != job.status:
                if job.status == "active":
                    changed_ids.add(job.id)
                else:
                    inactive_ids.add(job.id)
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
                job.to_dict(),
            )

        observed_ids = seen_job_ids if seen_job_ids is not None else set(incoming)
        if observed_ids:
            placeholders = ", ".join("?" for _ in observed_ids)
            conn.execute(
                f"UPDATE jobs SET last_seen_at = ? WHERE source = ? AND id IN ({placeholders})",
                (now, source, *sorted(observed_ids)),
            )
        missing_ids = (
            sorted(
                job_id
                for job_id, row in existing.items()
                if job_id not in observed_ids and row["status"] == "active"
            )
            if mark_missing_inactive
            else []
        )
        if missing_ids:
            conn.executemany(
                """
                UPDATE jobs
                SET status = 'inactive', inactive_reason = 'missing_from_source'
                WHERE id = ? AND status = 'active'
                """,
                [(job_id,) for job_id in missing_ids],
            )
            inactive_ids.update(missing_ids)

    return SyncResult(
        changed_ids=sorted(changed_ids),
        inactive_ids=sorted(inactive_ids),
        expired_count=expired_count,
        duplicate_count=duplicate_count,
    )


def upsert_review_jobs(db_path: Path, source: str, jobs: list[dict]) -> None:
    init_db(db_path)
    now = _utc_now()
    with connect(db_path) as conn:
        for job in jobs:
            conn.execute(
                """
                INSERT INTO job_review_queue (
                    job_id, source, title, company, city, source_url, confidence,
                    review_reasons, payload, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    source = excluded.source,
                    title = excluded.title,
                    company = excluded.company,
                    city = excluded.city,
                    source_url = excluded.source_url,
                    confidence = excluded.confidence,
                    review_reasons = excluded.review_reasons,
                    payload = excluded.payload,
                    status = CASE
                        WHEN job_review_queue.status = 'approved' THEN 'approved'
                        WHEN job_review_queue.status = 'ignored' THEN 'ignored'
                        ELSE 'pending'
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    job["id"],
                    source,
                    job["title"],
                    job["company"],
                    job["city"],
                    job["source_url"],
                    job["confidence"],
                    json.dumps(job.get("review_reasons", []), ensure_ascii=False),
                    json.dumps(job, ensure_ascii=False),
                    now,
                    now,
                ),
            )


def resolve_reviews_for_accepted_jobs(db_path: Path, job_ids: set[str]) -> None:
    if not job_ids:
        return
    init_db(db_path)
    placeholders = ", ".join("?" for _ in job_ids)
    with connect(db_path) as conn:
        conn.execute(
            f"""
            UPDATE job_review_queue
            SET status = 'approved', updated_at = ?, reviewed_at = COALESCE(reviewed_at, ?)
            WHERE job_id IN ({placeholders}) AND status = 'pending'
            """,
            (_utc_now(), _utc_now(), *sorted(job_ids)),
        )
