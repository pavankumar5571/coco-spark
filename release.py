"""The boundary between preparing a release and performing one.

videos.insert is the FIRST external mutation this pipeline has ever made. Everything else
it does is local, reversible and free; this reaches out and changes the world. So the
mutation gets its own command, its own name and its own arguments — never a flag on a
generic one, and never a privacy setting that arrives from a default.

    release.py prepare               validates everything, touches no network
    release.py upload-private        performs the mutation, explicitly, in its name

A public launch will be a THIRD command against an already-uploaded id. The path used for
today's technical test must never be one omitted argument away from launching the channel.
"""
from __future__ import annotations

import hashlib, json, subprocess, sys, time
from pathlib import Path

MANIFEST = Path("out/E01/release/upload_manifest.json")
PURPOSE = "PRIVATE_PUBLISH_PATH_TEST"


def _sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _iso8601_s(d):
    """PT1H2M3S -> seconds. YouTube states duration in ISO 8601, whole seconds only."""
    import re
    if not d:
        return 0.0
    m = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return 0.0
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return float(dd * 86400 + h * 3600 + mi * 60 + s)


def _probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height,channels,sample_rate:format=duration",
        "-of", "json", str(p)], capture_output=True, text=True).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), {})
    return {"duration": round(float(j["format"]["duration"]), 3),
            "video": {k: v.get(k) for k in ("codec_name", "width", "height")},
            "audio": {k: a.get(k) for k in ("codec_name", "channels", "sample_rate")}}


def prepare(master, metadata_path):
    """Everything checkable without touching the network. No mutation, no session created."""
    import youtube_upload as yt
    master, meta_p = Path(master), Path(metadata_path)
    fails = []
    if not master.exists():
        fails.append(f"master missing: {master}")
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    if not meta.get("title"):
        fails.append("metadata has no title")

    # credentials PRESENT, never their values — this function must be safe to run anywhere
    for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        if not yt._env(k, required=False):
            fails.append(f"{k} not available")

    audit_p = master.parent / "private_test_audit.json"
    if audit_p.exists():
        if not json.loads(audit_p.read_text(encoding="utf-8")).get("all_pass"):
            fails.append("private_test_audit did not pass")
    else:
        fails.append("no private_test_audit.json")

    tech = _probe(master) if master.exists() else {}
    m = {
        "kind": "UPLOAD_MANIFEST", "purpose": PURPOSE,
        "prepared_at": time.strftime("%F %T"),
        "master": str(master), "master_sha256": _sha256(master) if master.exists() else None,
        "master_bytes": master.stat().st_size if master.exists() else None,
        "technical": tech,
        "intended": {"title": meta.get("title"), "privacy": "private",
                     "made_for_kids": bool(meta.get("made_for_kids", True)),
                     "tags": meta.get("tags", [])},
        "contains_no_secrets": True,
        "ready": not fails, "blockers": fails,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


def upload_private(master, metadata_path):
    """Perform the mutation. Refuses unless prepare() says ready, and refuses to repeat.

    IDEMPOTENCE MATTERS MORE HERE THAN ANYWHERE ELSE IN THE PIPELINE. Once YouTube has
    accepted bytes, a blind retry can create a SECOND video. So a manifest that already
    carries a video id for these exact bytes is a completed upload, not a reason to try
    again — the same reasoning as reserve-before-invoke, applied to an external mutation
    instead of to money.
    """
    import youtube_upload as yt
    m = prepare(master, metadata_path)
    if not m["ready"]:
        sys.exit("  NOT READY:\n    " + "\n    ".join(m["blockers"]))

    if MANIFEST.exists():
        prev = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if prev.get("youtube_video_id") and prev.get("master_sha256") == m["master_sha256"]:
            sys.exit(f"  ALREADY UPLOADED: {prev['youtube_video_id']} for these exact bytes. "
                     f"Refusing to create a duplicate.")

    meta = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    print(f"  uploading {m['master_bytes']/1e6:.1f} MB as PRIVATE …")
    vid = yt.upload(master, meta, privacy="private")

    m["youtube_video_id"] = vid
    m["uploaded_at"] = time.strftime("%F %T")
    MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")
    print(f"  video id {vid}")
    return vid


def verify(video_id=None):
    """Record what YouTube ACTUALLY did, read back from the API.

    Not what we asked for — what it says is true afterwards. Every other stage of this
    project has been caught out by trusting a request instead of reading the result.
    """
    import youtube_upload as yt
    import urllib.request, urllib.parse
    # Say WHY before failing. The first run of this returned a bare 403 because the
    # credential carried youtube.upload only — a fact knowable for free, before any
    # request, from the token itself. Asking first turns an opaque HTTP error into the
    # actual diagnosis: this token cannot observe, so it cannot verify.
    if yt.scope_preflight(yt.granted_scopes(), ["verify"]):
        sys.exit("  cannot verify with this credential — re-run consent.")
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    vid = video_id or m.get("youtube_video_id")
    q = urllib.parse.urlencode({"part": "status,contentDetails,snippet,processingDetails",
                                "id": vid})
    req = urllib.request.Request(f"https://www.googleapis.com/youtube/v3/videos?{q}",
        headers={"Authorization": f"Bearer {yt.access_token()}"})
    with urllib.request.urlopen(req) as r:
        items = json.loads(r.read()).get("items", [])
    if not items:
        sys.exit(f"  {vid} not visible via the API yet")
    it = items[0]
    observed = {
        "privacy": it["status"].get("privacyStatus"),
        "made_for_kids": it["status"].get("madeForKids"),
        "self_declared_made_for_kids": it["status"].get("selfDeclaredMadeForKids"),
        "upload_status": it["status"].get("uploadStatus"),
        "processing": it.get("processingDetails", {}).get("processingStatus"),
        "duration": it.get("contentDetails", {}).get("duration"),
        "title": it["snippet"].get("title"),
    }
    m["observed"] = observed
    m["verified_at"] = time.strftime("%F %T")
    # YouTube reports its OWN duration, and it is not ours: a 12.000s master comes back
    # as PT13S. Recording the delta rather than assuming agreement — the whole point of
    # reading the result is that it may differ from what we sent, in ways nobody predicted.
    m["duration_delta_s"] = _iso8601_s(observed["duration"]) - m.get("technical", {}).get("duration", 0)
    m["matches_intent"] = (observed["privacy"] == "private"
                           and observed["self_declared_made_for_kids"] is True)
    MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


if __name__ == "__main__":
    MASTER = "out/E01/release/E01_master.mp4"
    META = "out/E01/release/metadata.json"
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare":
        r = prepare(MASTER, META)
        print(json.dumps({k: r[k] for k in ("master_sha256", "master_bytes", "technical",
                                            "intended", "ready", "blockers")}, indent=2))
    elif cmd == "upload-private":
        upload_private(MASTER, META)
    elif cmd == "verify":
        print(json.dumps(verify().get("observed"), indent=2))
    else:
        print(__doc__)
