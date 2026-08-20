"""Upload a finished master to YouTube, via the Data API rather than the Studio UI.

Driving the web UI was the wrong instinct and Pavan was right to challenge it: it is
slower, it breaks whenever Google reshapes the page, and it leaves no machine-readable
record of what was actually sent. The API leaves a request we can log and a video id we
can bind to the master's SHA.

CREDENTIALS ARE NEVER READ FROM THIS REPOSITORY. They come from the environment only.
The repo is public; a secret that reaches a commit here is world-readable within seconds
and rotating it afterwards does not un-publish it.

    YOUTUBE_CLIENT_ID       identifies the APPLICATION
    YOUTUBE_CLIENT_SECRET   identifies the APPLICATION
    YOUTUBE_REFRESH_TOKEN   identifies the CHANNEL OWNER, and only a human can create it

The third is the one that authorises anything. `videos.insert` acts on behalf of a channel,
so an API key cannot perform it at all — no amount of project-level credential substitutes
for a person consenting. mint_consent_url() prints the link; the human approves; the code
that comes back is exchanged once.
"""
from __future__ import annotations

import json, mimetypes, os, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

SCOPE = "https://www.googleapis.com/auth/youtube.upload"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
OOB = "urn:ietf:wg:oauth:2.0:oob"


def _env(name, required=True):
    v = os.environ.get(name)
    if required and not v:
        sys.exit(f"  {name} is not set. Export it; do not put it in a file in this repo.")
    return v


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def mint_consent_url(redirect=OOB):
    """Step 1. Prints a URL. A HUMAN opens it and approves — this is the step no
    automation may perform, because the grant is the channel owner's to give."""
    q = urllib.parse.urlencode({
        "client_id": _env("YOUTUBE_CLIENT_ID"), "redirect_uri": redirect,
        "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent"})
    return f"{AUTH}?{q}"


def exchange_code(code, redirect=OOB):
    """Step 2. Exchange the consent code for a refresh token. PRINTS NOTHING SECRET —
    it returns the token so the caller can store it, and the caller should store it in
    the environment, never in this tree."""
    t = _post(TOKEN, {"client_id": _env("YOUTUBE_CLIENT_ID"),
                      "client_secret": _env("YOUTUBE_CLIENT_SECRET"),
                      "code": code, "grant_type": "authorization_code",
                      "redirect_uri": redirect})
    return t.get("refresh_token")


def access_token():
    t = _post(TOKEN, {"client_id": _env("YOUTUBE_CLIENT_ID"),
                      "client_secret": _env("YOUTUBE_CLIENT_SECRET"),
                      "refresh_token": _env("YOUTUBE_REFRESH_TOKEN"),
                      "grant_type": "refresh_token"})
    return t["access_token"]


def upload(video_path, metadata, privacy="private"):
    """Resumable upload. Returns the video id.

    PRIVACY DEFAULTS TO PRIVATE and is passed explicitly rather than inherited, because
    the difference between private and public is the difference between a technical test
    and a launch, and a default should never be able to make that decision.
    """
    video_path = Path(video_path)
    size = video_path.stat().st_size
    body = {
        "snippet": {"title": metadata["title"],
                    "description": metadata.get("description", ""),
                    "tags": metadata.get("tags", []),
                    "categoryId": str(metadata.get("category_id", 27))},
        "status": {"privacyStatus": privacy,
                   "selfDeclaredMadeForKids": bool(metadata.get("made_for_kids", True))},
    }
    tok = access_token()
    init = urllib.request.Request(
        f"{UPLOAD}?{urllib.parse.urlencode({'uploadType':'resumable','part':'snippet,status'})}",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                 "X-Upload-Content-Length": str(size),
                 "X-Upload-Content-Type": mimetypes.guess_type(str(video_path))[0] or "video/mp4"})
    with urllib.request.urlopen(init) as r:
        session = r.headers["Location"]

    put = urllib.request.Request(session, data=video_path.read_bytes(), method="PUT",
        headers={"Authorization": f"Bearer {tok}", "Content-Length": str(size)})
    with urllib.request.urlopen(put) as r:
        return json.loads(r.read())["id"]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "consent-url":
        print(mint_consent_url())
    elif len(sys.argv) > 2 and sys.argv[1] == "exchange":
        rt = exchange_code(sys.argv[2])
        print("REFRESH TOKEN OBTAINED." if rt else "no refresh_token returned")
        print("Store it yourself:  export YOUTUBE_REFRESH_TOKEN='...'")
        print(rt or "")
    else:
        print(__doc__)
