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


def _load_env_file(path=".env"):
    """Read a git-ignored .env WITHOUT overriding anything already in the environment.

    A real export always wins. This exists only so a secret can live in one 0600 file
    instead of being re-exported into every shell that needs it.
    """
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _env(name, required=True):
    _load_env_file()
    v = os.environ.get(name)
    if required and not v:
        sys.exit(f"  {name} is not set. Export it; do not put it in a file in this repo.")
    return v


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def consent_loopback(port=0, host="127.0.0.1"):
    """Run the whole consent flow against a LOOPBACK redirect and store the token.

    The out-of-band redirect (urn:ietf:wg:oauth:2.0:oob) that this module used first is
    DEPRECATED by Google and now returns redirect_uri_mismatch. Desktop OAuth clients are
    expected to redirect to http://127.0.0.1:<port>, and Google accepts ANY port on the
    loopback address for a Desktop client — which is why nothing has to be pre-registered.

    Doing it this way also removes the copy-paste step: the browser hands the code straight
    back to a server running for a few seconds on this machine, so the code never passes
    through a clipboard, a terminal or a chat window.
    """
    import http.server, socket, threading, webbrowser

    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in got
            self.wfile.write(
                (f"<h2 style='font-family:system-ui'>{'Approved — you can close this tab.' if ok else 'No code returned.'}</h2>"
                 f"<p style='font-family:system-ui;color:#666'>Coco Spark TV</p>").encode())

        def log_message(self, *a):
            pass                      # never log the query string; it carries the code

    srv = http.server.HTTPServer((host if host != "localhost" else "127.0.0.1", port),
                                 Handler)
    port = srv.server_address[1]
    redirect = f"http://{host}:{port}"
    url = mint_consent_url(redirect)

    threading.Thread(target=srv.handle_request, daemon=True).start()
    print(f"  listening on {redirect}")
    print(f"  opening your browser — approve with the account that owns the channel\n")
    print(f"  if it does not open, paste this:\n\n{url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    import time as _t
    for _ in range(300):
        if got:
            break
        _t.sleep(1)
    srv.server_close()

    if "error" in got:
        sys.exit(f"  consent failed: {got['error']}")
    if "code" not in got:
        sys.exit("  timed out waiting for approval")

    rt = exchange_code(got["code"], redirect)
    if not rt:
        sys.exit("  no refresh_token returned — Google only sends one on FIRST consent. "
                 "Revoke this app at myaccount.google.com/permissions and retry.")
    envf = Path(".env")
    with open(envf, "a") as f:
        f.write(f"\nYOUTUBE_REFRESH_TOKEN={rt}\n")
    os.chmod(envf, 0o600)
    print(f"  refresh token written to {envf} (0600, git-ignored). Not printed.")


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
    if len(sys.argv) > 1 and sys.argv[1] == "consent":
        # A DESKTOP client accepts any loopback port, so the default random port works.
        # A WEB client does NOT: it only accepts redirect URIs registered on it, exactly,
        # port included — which is what "Access blocked: this app's request is invalid"
        # means in practice. For that case pin a port and register the matching URI.
        #   python3 youtube_upload.py consent 8080
        #   python3 youtube_upload.py consent 8080 localhost
        prt = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        hst = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
        consent_loopback(prt, hst)
    elif len(sys.argv) > 1 and sys.argv[1] == "consent-url":
        print(mint_consent_url())
    elif len(sys.argv) > 2 and sys.argv[1] == "exchange":
        # NEVER printed. It was, in the first version, and that is a secret in stdout,
        # in scrollback and in any log capturing this process. Written straight to a
        # git-ignored .env at 0600 instead, so it exists exactly where it is needed and
        # nowhere else.
        rt = exchange_code(sys.argv[2])
        if not rt:
            sys.exit("  no refresh_token returned — was prompt=consent used?")
        envf = Path(".env")
        with open(envf, "a") as f:
            f.write(f"\nYOUTUBE_REFRESH_TOKEN={rt}\n")
        os.chmod(envf, 0o600)
        print(f"  refresh token written to {envf} (0600, git-ignored). Not printed.")
    else:
        print(__doc__)
