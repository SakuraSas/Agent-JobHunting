from pathlib import Path

from job_sync.models import CrawledJob
from job_sync.repository import connect, sync_jobs


def _job(job_id: str, published_at: str | None = None) -> CrawledJob:
    return CrawledJob(
        id=job_id,
        source="test",
        title=f"Engineer {job_id}",
        company="Example",
        city="Chengdu",
        job_type="实习",
        description="Build reliable services and maintain production quality.",
        requirements="Python, SQL and automated testing.",
        source_url=f"https://example.com/jobs/{job_id}",
        published_at=published_at,
    )


def test_iso_timestamp_with_microseconds_can_expire(tmp_path: Path) -> None:
    result = sync_jobs(
        tmp_path / "app.db",
        "test",
        [_job("old", "2020-01-01T00:00:00.123000+00:00")],
        expires_after_days=30,
    )
    assert result.expired_count == 1
    with connect(tmp_path / "app.db") as conn:
        row = conn.execute("SELECT status, inactive_reason FROM jobs WHERE id = 'old'").fetchone()
    assert (row["status"], row["inactive_reason"]) == ("inactive", "expired")


def test_missing_inactive_job_is_not_deleted_twice(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    sync_jobs(db_path, "test", [_job("gone")])
    first = sync_jobs(db_path, "test", [])
    second = sync_jobs(db_path, "test", [])
    assert first.inactive_ids == ["gone"]
    assert second.inactive_ids == []
