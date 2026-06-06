from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from urllib.error import HTTPError, URLError

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, async_playwright

from job_browsing_agent.adapters import ADAPTERS
from job_browsing_agent.api_extractors import API_EXTRACTORS, xiaomi_detail_url
from job_browsing_agent.extractors import extract_with_rules
from job_browsing_agent.llm import DeepSeekFallback
from job_browsing_agent.models import BrowserRunReport, BrowserSource, PageSnapshot
from job_browsing_agent.quality import assess, needs_review


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DomainRateLimiter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request: dict[str, float] = {}

    async def wait(self, url: str) -> None:
        domain = urlsplit(url).netloc
        async with self._locks[domain]:
            loop = asyncio.get_running_loop()
            elapsed = loop.time() - self._last_request.get(domain, 0.0)
            if elapsed < self.delay_seconds:
                await asyncio.sleep(self.delay_seconds - elapsed)
            self._last_request[domain] = loop.time()


class BrowserAgent:
    def __init__(self, source: BrowserSource, output_root: Path) -> None:
        self.source = source
        self.output_root = output_root
        self.rate_limiter = DomainRateLimiter(source.request_delay_seconds)
        self.llm = DeepSeekFallback(source.llm_concurrency)

    def _allowed(self, url: str) -> bool:
        return urlsplit(url).netloc in self.source.allowed_domains

    def _robots_allows_list_page(self) -> bool:
        parser = RobotFileParser()
        parser.set_url(self.source.robots_url)
        try:
            parser.read()
        except (HTTPError, URLError):
            if self.source.allow_missing_robots_txt:
                print(f"[WARN] robots.txt unavailable; using manually approved source: {self.source.name}")
                return True
            raise
        return parser.can_fetch("job-browsing-agent", self.source.list_url)

    def _looks_like_detail(self, url: str) -> bool:
        if not self._allowed(url):
            return False
        path = urlsplit(url).path
        if self.source.detail_url_regex:
            return bool(re.search(self.source.detail_url_regex, path))
        return any(pattern in path for pattern in self.source.detail_url_patterns)

    async def _snapshot(self, page: Page, url: str) -> PageSnapshot:
        await self.rate_limiter.wait(url)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(self.source.navigation_wait_ms)
        snapshot = PageSnapshot(
            url=page.url,
            title=await page.title(),
            visible_text=await page.locator("body").inner_text(),
            html=await page.content(),
        )
        snapshot.save(self.output_root / "snapshots" / self.source.name)
        return snapshot

    async def _discover(self, page: Page) -> list[str]:
        # List navigation remains serial because pagination mutates one browser state.
        snapshot = await self._snapshot(page, self.source.list_url)
        soup = BeautifulSoup(snapshot.html, "lxml")
        urls = {
            urljoin(snapshot.url, node.get("href", ""))
            for node in soup.select("a[href]")
            if self._looks_like_detail(urljoin(snapshot.url, node.get("href", "")))
        }
        return sorted(urls)[: self.source.max_detail_jobs]

    async def _collect_api_pages(self, page: Page):
        if not self.source.api_response_pattern or not self.source.api_next_selector:
            raise ValueError(f"Missing API pagination config for source: {self.source.name}")
        extractor = API_EXTRACTORS.get(self.source.adapter or "")
        if extractor is None:
            raise ValueError(f"Missing API extractor for adapter: {self.source.adapter}")

        responses = []
        capture_tasks: list[asyncio.Task] = []

        async def capture(response):
            if self.source.api_response_pattern in response.url and response.status == 200:
                try:
                    payload = await response.json()
                except Exception:
                    return
                if isinstance(payload, dict) and payload.get("code") == 0:
                    responses.append((response.url, payload))

        page.on("response", lambda response: capture_tasks.append(asyncio.create_task(capture(response))))
        await self._snapshot(page, self.source.list_url)
        await page.wait_for_timeout(500)
        if not responses:
            raise RuntimeError(f"Did not observe public jobs API: {self.source.api_response_pattern}")

        page_number = 1
        while True:
            next_button = page.locator(self.source.api_next_selector)
            if await next_button.count() == 0:
                break
            if self.source.api_max_pages and page_number >= self.source.api_max_pages:
                break
            await self.rate_limiter.wait(self.source.list_url)
            async with page.expect_response(
                lambda response: (
                    self.source.api_response_pattern in response.url and response.status == 200
                ),
                timeout=30000,
            ):
                await next_button.click()
            page_number += 1
            await page.wait_for_timeout(250)

        if capture_tasks:
            await asyncio.gather(*capture_tasks)
        jobs = {}
        fallback_urls = set()
        unique_responses = dict(responses)
        api_output = self.output_root / "api" / self.source.name
        api_output.mkdir(parents=True, exist_ok=True)
        for page_number, (url, payload) in enumerate(unique_responses.items(), start=1):
            (api_output / f"page_{page_number:03d}.json").write_text(
                json.dumps({"url": url, "payload": payload}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            for item in payload.get("data", {}).get("job_post_list", []):
                candidate = extractor(item, self.source)
                if candidate:
                    jobs[candidate.id] = assess(candidate)
                elif item.get("id"):
                    fallback_urls.add(xiaomi_detail_url(self.source, str(item["id"])))
        return list(jobs.values()), sorted(fallback_urls)

    async def _collect_direct_api_pages(self, page: Page):
        if not self.source.api_response_pattern or not self.source.api_request_body:
            raise ValueError(f"Missing direct API config for source: {self.source.name}")
        extractor = API_EXTRACTORS.get(self.source.adapter or "")
        if extractor is None:
            raise ValueError(f"Missing API extractor for adapter: {self.source.adapter}")

        await self._snapshot(page, self.source.list_url)
        endpoint = urljoin(self.source.list_url, self.source.api_response_pattern)
        max_pages = self.source.api_max_pages or 1
        jobs = {}
        api_output = self.output_root / "api" / self.source.name
        api_output.mkdir(parents=True, exist_ok=True)

        for page_number in range(1, max_pages + 1):
            await self.rate_limiter.wait(endpoint)
            body = {
                **self.source.api_request_body,
                "pageIndex": page_number,
                "pageSize": self.source.api_page_size,
            }
            payload = await page.evaluate(
                """
                async ({ endpoint, body }) => {
                    const response = await fetch(endpoint, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(body)
                    });
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    return await response.json();
                }
                """,
                {"endpoint": endpoint, "body": body},
            )
            (api_output / f"page_{page_number:03d}.json").write_text(
                json.dumps({"url": endpoint, "body": body, "payload": payload}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not isinstance(payload, dict) or payload.get("code") != 0:
                raise RuntimeError(f"Unexpected API response from {endpoint}: {payload}")

            data = payload.get("data") or []
            if isinstance(data, dict):
                data = data.get("job_post_list") or []
            if not data:
                break
            for item in data:
                if not isinstance(item, dict):
                    continue
                candidate = extractor(item, self.source)
                if candidate:
                    jobs[candidate.id] = assess(candidate)

            page_info = payload.get("page") or {}
            total_page = int(page_info.get("totalPage") or max_pages)
            if page_number >= total_page:
                break

        return list(jobs.values()), []

    async def _extract_detail(self, browser: Browser, url: str):
        page = await browser.new_page()
        try:
            snapshot = await self._snapshot(page, url)
            adapter = ADAPTERS.get(self.source.adapter or "")
            candidate = adapter(snapshot, self.source.name) if adapter else None
            candidate = candidate or extract_with_rules(snapshot, self.source.name)
            if candidate is None and self.source.use_llm_fallback:
                from hashlib import sha256

                candidate = await self.llm.extract(
                    snapshot,
                    self.source.name,
                    f"{self.source.name}-{sha256(url.encode('utf-8')).hexdigest()[:16]}",
                )
            return assess(candidate) if candidate else None
        finally:
            await page.close()

    async def run(self) -> BrowserRunReport:
        started_at = _utc_now()
        if not await asyncio.to_thread(self._robots_allows_list_page):
            raise RuntimeError(f"robots.txt does not allow crawling: {self.source.list_url}")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                list_page = await browser.new_page()
                api_skipped_urls = []
                if self.source.api_pagination:
                    if self.source.api_request_body:
                        candidates, fallback_urls = await self._collect_direct_api_pages(list_page)
                    else:
                        candidates, fallback_urls = await self._collect_api_pages(list_page)
                    if fallback_urls:
                        semaphore = asyncio.Semaphore(self.source.detail_concurrency)

                        async def extract_fallback(url: str):
                            async with semaphore:
                                try:
                                    return await self._extract_detail(browser, url)
                                except Exception as exc:
                                    print(f"[WARN] skipped fallback detail page url={url} error={exc}")
                                    return None

                        fallback_candidates = await asyncio.gather(
                            *(extract_fallback(url) for url in fallback_urls)
                        )
                        api_skipped_urls = [
                            url
                            for url, candidate in zip(fallback_urls, fallback_candidates, strict=True)
                            if candidate is None
                        ]
                        candidates.extend(
                            candidate for candidate in fallback_candidates if candidate is not None
                        )
                    urls = [candidate.source_url for candidate in candidates]
                    collection_method = "public_api_pagination"
                else:
                    urls = await self._discover(list_page)
                    semaphore = asyncio.Semaphore(self.source.detail_concurrency)

                    async def extract(url: str):
                        async with semaphore:
                            try:
                                return await self._extract_detail(browser, url)
                            except Exception as exc:
                                print(f"[WARN] skipped detail page url={url} error={exc}")
                                return None

                    candidates = await asyncio.gather(*(extract(url) for url in urls))
                    collection_method = "detail_pages"
                await list_page.close()
            finally:
                await browser.close()

        accepted = []
        review = []
        skipped = []
        for url, candidate in zip(urls, candidates, strict=True):
            if candidate is None:
                skipped.append(url)
            elif needs_review(candidate):
                review.append(candidate)
            else:
                accepted.append(candidate)
        skipped.extend(api_skipped_urls)
        return BrowserRunReport(
            source=self.source.name,
            started_at=started_at,
            finished_at=_utc_now(),
            discovered_urls=urls,
            accepted_jobs=accepted,
            review_jobs=review,
            skipped_urls=skipped,
            collection_method=collection_method,
        )
