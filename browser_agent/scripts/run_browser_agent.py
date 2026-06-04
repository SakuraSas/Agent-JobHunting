import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from job_browsing_agent.models import BrowserSource
from job_browsing_agent.runner import BrowserAgent

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "sources.json"
OUTPUT_PATH = ROOT / "output" / "latest_browser_jobs.json"
load_dotenv(ROOT / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_source(name: str | None) -> BrowserSource:
    raw_sources = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["sources"]
    sources = [BrowserSource.model_validate(item) for item in raw_sources if item.get("enabled", False)]
    if name:
        sources = [source for source in sources if source.name == name]
    if len(sources) != 1:
        available = ", ".join(source.name for source in sources) or "none"
        raise ValueError(f"Select exactly one enabled source. Available: {available}")
    return sources[0]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Extract public job postings with Playwright.")
    parser.add_argument("--source", help="Source name from config/sources.json")
    args = parser.parse_args()
    source = load_source(args.source)
    report = await BrowserAgent(source, ROOT / "output").run()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"[DONE] source={report.source} discovered={len(report.discovered_urls)} "
        f"accepted={len(report.accepted_jobs)} review={len(report.review_jobs)} "
        f"skipped={len(report.skipped_urls)} method={report.collection_method}"
    )
    print(f"[OUTPUT] {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
