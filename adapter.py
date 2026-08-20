"""Transport-injected YouTube response adapter.

The module has no network fallback. Production must inject an authenticated transport;
tests inject FakeTransport. It translates returned fields and collection failures without
deriving rates, ownership, demand, or other facts the API did not state.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re


DEFAULT_RETRIES = 2  # three total attempts
_last_unreturned: list[str] = []


class FakeTransport:
    def __init__(self, *, pages=None, stats=None, details=None,
                 echo_region=None, echo_language=None):
        self.pages = pages or {}
        self.stats = stats or {}
        self.details = details or {}
        self.echo_region = echo_region
        self.echo_language = echo_language
        self.calls = 0
        self._page_attempts = {}

    def search_page(self, token, **_request):
        self.calls += 1
        value = self.pages.get(token, ([], None))
        if isinstance(value, list):
            attempt = self._page_attempts.get(token, 0)
            self._page_attempts[token] = attempt + 1
            value = value[min(attempt, len(value) - 1)]
        if isinstance(value, Exception):
            raise value
        return value

    def statistics(self, ids):
        self.calls += 1
        return {video_id: self.stats[video_id] for video_id in ids
                if video_id in self.stats}

    def video_details(self, ids):
        self.calls += 1
        return {video_id: self.details[video_id] for video_id in ids
                if video_id in self.details}


def _require(transport):
    if transport is None:
        raise ValueError("an explicit transport is required; no network fallback exists")


def _chunks(values, size=50):
    unique = list(dict.fromkeys(values))
    for start in range(0, len(unique), size):
        yield unique[start:start + size]


def search(*, query: str, region: str, language: str, transport=None,
           retries: int = DEFAULT_RETRIES, max_pages: int | None = None) -> dict:
    _require(transport)
    if retries < 0:
        raise ValueError("retries cannot be negative")
    if max_pages is not None and max_pages <= 0:
        raise ValueError("max_pages must be positive")
    token = None
    seen_tokens = set()
    collected = []
    seen_ids = set()
    failed_pages = []
    retried_pages = []
    attempts = 0
    page_index = 0
    termination_reason = "end_of_results"
    while True:
        if token in seen_tokens:
            failed_pages.append(page_index)
            termination_reason = "pagination_token_loop"
            break
        seen_tokens.add(token)
        response = None
        for attempt in range(retries + 1):
            attempts += 1
            try:
                response = transport.search_page(
                    token, query=query, region=region, language=language)
                if attempt:
                    retried_pages.append(page_index)
                break
            except Exception:
                if attempt == retries:
                    failed_pages.append(page_index)
                    termination_reason = "page_request_failed"
        if response is None:
            break
        ids, next_token = response
        for video_id in ids:
            if video_id not in seen_ids:
                seen_ids.add(video_id)
                collected.append(video_id)
        page_index += 1
        if next_token is None:
            break
        if max_pages is not None and page_index >= max_pages:
            termination_reason = "page_limit_reached"
            break
        token = next_token
    complete = not failed_pages and termination_reason == "end_of_results"
    return {
        "query": query, "region": region.upper(), "language": language.casefold(),
        "video_ids": collected if complete else [],
        "retry_video_ids": [] if complete else collected,
        "complete": complete, "failed_pages": failed_pages,
        "attempts": attempts, "retried_pages": sorted(set(retried_pages)),
        "termination_reason": termination_reason,
        "page_limit": max_pages,
    }


def fetch_statistics(ids, *, transport=None) -> dict[str, dict]:
    global _last_unreturned
    _require(transport)
    requested = list(dict.fromkeys(ids))
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    returned = {}
    for batch in _chunks(requested):
        response = transport.statistics(batch)
        for video_id, raw in response.items():
            returned[video_id] = {
                "views": _counter(raw.get("viewCount")),
                "likes": _counter(raw.get("likeCount")),
                "comments": _counter(raw.get("commentCount")),
                "observed_at": observed_at,
                # Conversion failure must not discard what the platform actually sent.
                # Keeping all three raw values also distinguishes absent from malformed.
                "raw_statistics": {
                    "viewCount": raw.get("viewCount"),
                    "likeCount": raw.get("likeCount"),
                    "commentCount": raw.get("commentCount"),
                },
            }
    _last_unreturned = [video_id for video_id in requested if video_id not in returned]
    return returned


def last_unreturned_ids() -> list[str]:
    return list(_last_unreturned)


def _counter(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    if not re.fullmatch(r"[0-9]+", text):
        return None
    parsed = int(text)
    return parsed if parsed >= 0 else None


_DURATION = re.compile(
    r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$")


def _duration_seconds(value):
    if not value:
        return None
    match = _DURATION.fullmatch(value)
    if not match:
        return None
    parts = {name: int(number or 0) for name, number in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if parsed.tzinfo is not None else None


def fetch_details(ids, *, transport=None) -> dict[str, dict]:
    _require(transport)
    returned = {}
    for batch in _chunks(ids):
        response = transport.video_details(batch)
        for video_id, raw in response.items():
            returned[video_id] = {
                "duration_seconds": _duration_seconds(raw.get("duration")),
                "published_at": _timestamp(raw.get("publishedAt")),
                "title": raw.get("title"),
                "channel_id": raw.get("channelId"),
            }
    return returned
