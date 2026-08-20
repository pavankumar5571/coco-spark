"""The only file in this repository that opens a socket to YouTube.

adapter.py has no network fallback by construction — it demands an injected transport and
raises without one. This is that transport, kept separate so the boundary stays visible in
the file listing rather than only in a docstring: if a change makes the pipeline talk to
YouTube, it changes THIS file, and a review that touches nothing else has not enabled a
network call.

It is deliberately thin. It fetches and returns raw JSON fragments exactly as the API sent
them. Every decision about what a missing field means, what an unparseable counter means,
and what a failed page means belongs to adapter.py, which is tested against a fake and
therefore actually testable.

    AIS_YOUTUBE_API_KEY is read from the environment or from D:/enterprise-ai-yt/.env

QUOTA IS NOT FREE EVEN THOUGH IT IS NOT MONEY. search.list costs 100 units against a
10,000/day default; videos.list costs 1. Every call this file makes is counted and
reported, because a collector that cannot say what it spent will eventually exhaust the
quota mid-run and hand the evidence engine a truncated batch — the exact failure G03 fails
closed on.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3"
ENTERPRISE_ENV = Path(r"D:\enterprise-ai-yt\.env")

# Published cost per call, so a run can report what it spent rather than guess.
QUOTA_UNITS = {"search": 100, "videos": 1, "channels": 1}


def api_key():
    key = os.environ.get("AIS_YOUTUBE_API_KEY") or os.environ.get("YOUTUBE_API_KEY")
    if key:
        return key
    if ENTERPRISE_ENV.exists():
        for line in ENTERPRISE_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*AIS_YOUTUBE_API_KEY\s*=\s*(.*)$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    raise RuntimeError("no YouTube API key available")


class LiveTransport:
    """Fetches. Decides nothing.

    Matches FakeTransport's interface exactly, so adapter.py cannot tell them apart —
    which is the point: everything proven against the fake is proven about the code that
    runs against the real thing.
    """

    def __init__(self, key=None, timeout=30):
        self.key = key or api_key()
        self.timeout = timeout
        self.calls = 0
        self.quota_units = 0
        self.log = []

    def _get(self, path, **params):
        self.calls += 1
        self.quota_units += QUOTA_UNITS.get(path, 1)
        url = f"{API}/{path}?" + urllib.parse.urlencode({**params, "key": self.key})
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                body = json.loads(r.read())
            self.log.append((path, params.get("q") or params.get("id", "")[:40], "ok"))
            return body
        except urllib.error.HTTPError as e:
            detail = e.read()[:200].decode("utf-8", "replace")
            self.log.append((path, params.get("q") or "", f"HTTP {e.code}"))
            # Raised, never swallowed. adapter.py turns this into a FAILED PAGE, which is
            # what makes G03 refuse the batch. A transport that returned partial results
            # here would convert a quota failure into evidence of a small market.
            raise RuntimeError(f"youtube {path} HTTP {e.code}: {detail}") from e

    # ---- the interface adapter.py expects -------------------------------------------
    def search_page(self, token, *, query=None, region=None, language=None, **_):
        params = {"part": "snippet", "type": "video", "q": query, "maxResults": 50,
                  "safeSearch": "strict", "order": "date"}
        if region:
            params["regionCode"] = region
        if language:
            params["relevanceLanguage"] = language
        if token:
            params["pageToken"] = token
        body = self._get("search", **params)
        ids = [i["id"]["videoId"] for i in body.get("items", [])
               if i.get("id", {}).get("videoId")]
        return ids, body.get("nextPageToken")

    def statistics(self, ids):
        body = self._get("videos", part="statistics", id=",".join(ids))
        return {i["id"]: i.get("statistics", {}) for i in body.get("items", [])}

    def video_details(self, ids):
        body = self._get("videos", part="snippet,contentDetails", id=",".join(ids))
        out = {}
        for i in body.get("items", []):
            out[i["id"]] = {"title": i.get("snippet", {}).get("title"),
                            "channelId": i.get("snippet", {}).get("channelId"),
                            "publishedAt": i.get("snippet", {}).get("publishedAt"),
                            "duration": i.get("contentDetails", {}).get("duration")}
        return out

    def report(self):
        return {"calls": self.calls, "quota_units": self.quota_units, "log": self.log}
