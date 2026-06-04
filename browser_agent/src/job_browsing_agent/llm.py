from __future__ import annotations

import asyncio
import json
import os

from openai import AsyncOpenAI

from job_browsing_agent.models import ExtractedJobCandidate, PageSnapshot

SYSTEM_PROMPT = """Extract one public job posting from visible webpage text.
Return JSON only with fields: title, company, city, job_type, description,
requirements, education, published_at. Never invent missing facts. Use null for
missing optional values. Preserve named technology stacks and years of experience."""


class DeepSeekFallback:
    def __init__(self, concurrency: int) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        key = os.getenv("DEEPSEEK_API_KEY")
        self._client = AsyncOpenAI(
            api_key=key or "missing",
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
        self._enabled = bool(key)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def extract(
        self, snapshot: PageSnapshot, source: str, candidate_id: str
    ) -> ExtractedJobCandidate | None:
        if not self.enabled:
            return None
        async with self._semaphore:
            response = await self._client.chat.completions.create(
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": snapshot.visible_text[:24000]},
                ],
            )
        payload = json.loads(response.choices[0].message.content or "{}")
        if not payload.get("title") or not payload.get("description"):
            return None
        return ExtractedJobCandidate(
            id=candidate_id,
            source=source,
            title=payload["title"],
            company=payload.get("company") or "未说明",
            city=payload.get("city") or "未说明",
            job_type=payload.get("job_type") or "公开职位",
            description=payload["description"],
            requirements=payload.get("requirements") or "未单独说明，请查看职位描述",
            education=payload.get("education"),
            published_at=payload.get("published_at"),
            source_url=snapshot.url,
            extraction_method="deepseek_fallback",
            confidence=0.72,
            evidence=["DeepSeek extraction from visible text"],
            snapshot_path=snapshot.snapshot_path,
        )
