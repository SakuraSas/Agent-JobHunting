import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
AGENT_ROOT = PROJECT_ROOT / "langchain_agent"
DB_PATH = AGENT_ROOT / "data" / "app.db"
CONFIG_PATH = ROOT / "config" / "sources.json"
OUTPUT_PATH = ROOT / "output" / "latest_browser_jobs.json"
from job_browsing_agent.models import BrowserSource  # noqa: E402
from job_browsing_agent.runner import BrowserAgent  # noqa: E402
from job_sync.models import CrawledJob  # noqa: E402
from job_sync.repository import (  # noqa: E402
    finish_sync_log,
    resolve_reviews_for_accepted_jobs,
    start_sync_log,
    sync_jobs,
    upsert_review_jobs,
)

load_dotenv(ROOT / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def load_source(name: str) -> BrowserSource:
    raw_sources = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["sources"]
    for item in raw_sources:
        if item.get("enabled", False) and item["name"] == name:
            return BrowserSource.model_validate(item)
    raise ValueError(f"Enabled Browser Agent source not found: {name}")


def to_crawled_job(payload: dict) -> CrawledJob:
    fields = CrawledJob.__dataclass_fields__
    return CrawledJob(**{key: payload.get(key) for key in fields if key in payload})


def update_vectors(changed_ids: list[str], inactive_ids: list[str]) -> None:
    if not changed_ids and not inactive_ids:
        print("[SYNC] no vector changes")
        return
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    for key, value in dotenv_values(AGENT_ROOT / ".env").items():
        if value is not None:
            env[key.lstrip("\ufeff")] = value
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/sync_index.py",
            json.dumps(changed_ids),
            json.dumps(inactive_ids),
        ],
        cwd=AGENT_ROOT,
        env=env,
        check=True,
    )


async def sync_source(source: BrowserSource) -> None:
    log_id = start_sync_log(DB_PATH, source.name)
    try:
        print(f"[SYNC] running Browser Agent source={source.name}")
        report = await BrowserAgent(source, ROOT / "output").run()
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        complete = bool(report.discovered_urls) and not report.skipped_urls
        accepted_payloads = [job.model_dump() for job in report.accepted_jobs]
        review_payloads = [job.model_dump() for job in report.review_jobs]
        observed_ids = {
            job["id"] for job in accepted_payloads + review_payloads
        }
        jobs = [to_crawled_job(job) for job in accepted_payloads]

        upsert_review_jobs(DB_PATH, source.name, review_payloads)
        resolve_reviews_for_accepted_jobs(DB_PATH, {job.id for job in jobs})
        result = sync_jobs(
            DB_PATH,
            source.name,
            jobs,
            mark_missing_inactive=complete,
            seen_job_ids=observed_ids,
        )
        finish_sync_log(
            DB_PATH,
            log_id,
            source.name,
            "success" if complete else "partial",
            len(observed_ids),
            result,
            None if complete else f"Skipped detail URLs: {len(report.skipped_urls)}",
        )
        update_vectors(result.changed_ids, result.inactive_ids)
        print(
            f"[DONE] source={source.name} method={report.collection_method} "
            f"observed={len(observed_ids)} accepted={len(jobs)} review={len(review_payloads)} "
            f"changed={len(result.changed_ids)} inactive={len(result.inactive_ids)} "
            f"complete={complete}"
        )
    except Exception as exc:
        finish_sync_log(DB_PATH, log_id, source.name, "failed", error=str(exc))
        raise


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run Browser Agent and incrementally sync jobs.")
    parser.add_argument("--source", default="xiaomi_campus_browser")
    args = parser.parse_args()
    await sync_source(load_source(args.source))


if __name__ == "__main__":
    asyncio.run(main())
