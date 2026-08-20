"""Two agents wait on each other without either of them stopping.

Claude and Codex both work in this tree. Handoffs go in docs/CHANNEL.md, which is
append-only and lives in git, so neither of us has to be able to read the other's chat
window. The problem this file solves is the next one down: HOW DO YOU NOTICE.

Polling in a chat turn wastes a turn per check and stalls whoever is waiting. So instead:

    python channel.py watch

BLOCKS until the channel changes, prints only what is new, and exits. Run it in the
background and the agent gets woken by its exit rather than by asking repeatedly. Exit
code says which happened, so a wrapper can tell a handoff from a timeout:

    0   the channel changed; the new text is on stdout
    2   nothing happened before --timeout; nobody is stuck, there is just no news
    1   misuse

Both agents run the same command. Neither needs to know anything about the other's
runtime, and the thing they synchronise on is a file in git rather than a promise.
"""
from __future__ import annotations

import argparse, hashlib, json, sys, time
from pathlib import Path

CHANNEL = Path("docs/CHANNEL.md")
STATE = Path(".channel-seen.json")          # git-ignored; per-agent, not shared
POLL_SECONDS = 5
DEFAULT_TIMEOUT = 1800


def _digest(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def _text(p: Path):
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _seen(agent):
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8")).get(agent, {})
    except Exception:
        return {}


def _remember(agent, digest, length):
    """Per-agent marks. Two agents watching one file must not consume each other's news."""
    all_state = {}
    if STATE.exists():
        try:
            all_state = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            all_state = {}
    all_state[agent] = {"digest": digest, "length": length,
                        "at": time.strftime("%F %T")}
    STATE.write_text(json.dumps(all_state, indent=2), encoding="utf-8")


def watch(agent, timeout, poll, fetch):
    """Block until the channel changes. Print ONLY the appended text.

    The whole file is not reprinted, because the point of an append-only log is that
    what is new is the only part anyone has to read.
    """
    import subprocess
    prev = _seen(agent)
    start_len = prev.get("length", len(_text(CHANNEL)))
    start_digest = prev.get("digest", _digest(CHANNEL))
    deadline = time.time() + timeout

    while time.time() < deadline:
        if fetch:
            # Only if the other agent works from a different clone. In one shared tree
            # the file changes directly and this is unnecessary noise.
            subprocess.run(["git", "fetch", "--quiet"], capture_output=True)
            subprocess.run(["git", "merge", "--ff-only", "--quiet", "@{u}"],
                           capture_output=True)
        # AN AGENT MUST NOT WAKE ON ITSELF. If this agent posted while its own watcher
        # was running, its mark has moved past its own entry — adopt that and keep
        # waiting. Otherwise a handoff appears to have arrived when nothing has, which
        # is worse than silence: it looks exactly like the other agent replying.
        mark = _seen(agent)
        if mark.get("digest") and mark["digest"] != start_digest:
            start_digest, start_len = mark["digest"], mark.get("length", start_len)

        now_digest = _digest(CHANNEL)
        if now_digest != start_digest:
            body = _text(CHANNEL)
            new = body[start_len:] if len(body) > start_len else body
            _remember(agent, now_digest, len(body))
            sys.stdout.write(new.strip() + "\n")
            return 0
        time.sleep(poll)

    _remember(agent, start_digest, start_len)
    print(f"  no channel activity in {timeout}s")
    return 2


def post(agent, module, subject, state, evidence, ask, body):
    """Append one entry. Never rewrites, so two agents cannot lose each other's words."""
    if not CHANNEL.exists():
        sys.exit(f"  {CHANNEL} does not exist")
    entry = (f"\n---\n\n## {time.strftime('%F')} — {agent} — {module} — {subject}\n\n"
             f"STATE      {state}\n"
             f"EVIDENCE   {evidence}\n\n"
             f"{body.strip()}\n\n"
             f"ASK        {ask}\n")
    with open(CHANNEL, "a", encoding="utf-8") as f:
        f.write(entry)
    # Advance the POSTER's own mark past its own words, so its next watch does not
    # report them back as if the other agent had spoken.
    _remember(agent, _digest(CHANNEL), len(_text(CHANNEL)))
    print(f"  posted to {CHANNEL} as {agent}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["watch", "post", "tail"])
    ap.add_argument("--agent", default="CLAUDE")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--poll", type=int, default=POLL_SECONDS)
    ap.add_argument("--fetch", action="store_true",
                    help="pull before checking; only for agents in a separate clone")
    ap.add_argument("--module", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--state", default="DELIVERED")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--ask", default="NONE")
    ap.add_argument("--body", default="", help="entry body; '-' reads stdin")
    a = ap.parse_args(argv)

    if a.cmd == "watch":
        return watch(a.agent, a.timeout, a.poll, a.fetch)
    if a.cmd == "tail":
        txt = _text(CHANNEL)
        marker = txt.rfind("\n---\n")
        print(txt[marker:].strip() if marker > 0 else txt.strip())
        return 0
    body = sys.stdin.read() if a.body == "-" else a.body
    if not (a.module and a.subject and body.strip()):
        sys.exit("  post needs --module, --subject and --body")
    return post(a.agent, a.module, a.subject, a.state, a.evidence, a.ask, body)


if __name__ == "__main__":
    sys.exit(main())
