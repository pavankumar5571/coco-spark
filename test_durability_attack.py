"""What survives a process that dies mid-write.

G03's persistence attack proved a RELOAD is byte-faithful. It never proved what happens
when the process does not get to close the store. Those are different questions: SQLite's
durability guarantees are real but they are guarantees about COMMITTED transactions, and
nothing in this project had ever checked which of our writes are committed when the
machine stops caring.

The failure this prevents is specific and quiet. A collector killed between two statements
could leave an observation whose timestamp landed but whose count did not, and G02 would
then compute a velocity across a row that describes an interrupted process rather than a
platform. A partial row is worse than a missing row: a missing row is refused, and a
partial row is believed.

    A KILLED PROCESS LEAVES NO HALF-WRITTEN OBSERVATION
    WHAT WAS ACKNOWLEDGED BEFORE THE KILL IS STILL THERE AFTER IT
    A STORE REOPENED AFTER A KILL IS NOT CORRUPT

The child process is killed with SIGKILL's Windows equivalent — no cleanup, no atexit, no
context manager. That is the point: a graceful shutdown proves nothing about a crash.
"""
from __future__ import annotations

import subprocess
import sqlite3
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from collector import Collector

WRITER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, r"{repo}")
    from collector import Collector
    c = Collector(store_path=r"{db}")
    for i in range({n}):
        c.record_observation(video_id=f"v{{i}}", observed_at=f"2026-08-20T{{10+i:02d}}:00:00Z",
                             views=100 + i)
        print(i, flush=True)
    time.sleep(30)
""")


def _ok(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:58s}{'' if cond else '  <-- ' + detail}")
    return bool(cond)


def _kill_mid_write(n=6, after=3):
    """Start a writer, let it acknowledge `after` rows, then kill it without warning."""
    db = str(Path(tempfile.mkdtemp()) / "state.sqlite3")
    script = WRITER.format(repo=str(Path(__file__).parent), db=db, n=n)
    proc = subprocess.Popen([sys.executable, "-c", script],
                            stdout=subprocess.PIPE, text=True)
    acknowledged = 0
    for line in proc.stdout:
        acknowledged = int(line.strip()) + 1
        if acknowledged >= after:
            break
    proc.kill()                      # no cleanup runs; this is a crash, not a shutdown
    proc.wait(timeout=30)
    return db, acknowledged


def acknowledged_writes_survive_the_kill():
    """A write the writer told us it had done must be there after the process dies.

    This is the half that makes the store trustworthy at all. If an acknowledged row can
    vanish, every interval we ever measure is provisional.
    """
    db, acknowledged = _kill_mid_write()
    rows = sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM observations").fetchone()[0]
    return _ok("every acknowledged write survived the kill", rows >= acknowledged,
               f"{acknowledged} acknowledged, {rows} present")


def no_row_is_half_written():
    """The row that matters. An observation with an instant and no count, or a count and
    no instant, is a row G02 would happily divide by."""
    db, _ = _kill_mid_write()
    con = sqlite3.connect(db)
    bad = con.execute(
        "SELECT COUNT(*) FROM observations "
        "WHERE video_id IS NULL OR observed_at IS NULL OR views IS NULL").fetchone()[0]
    return _ok("no observation is missing an id, an instant or a count", bad == 0,
               f"{bad} partial rows")


def the_store_reopens_and_is_usable():
    """A store that survives the crash but cannot be opened has failed differently, not
    less. The check runs through the Collector rather than raw sqlite3, because that is
    what production uses and a schema left mid-migration would show up here."""
    db, acknowledged = _kill_mid_write()
    try:
        c = Collector(store_path=db)
        ids = c.observed_video_ids()
        snaps = sum(len(c.snapshots(i)) for i in ids)
        c.close()
    except Exception as exc:
        return _ok("the store reopens through the Collector", False,
                   f"{type(exc).__name__}: {exc}")
    return _ok("the store reopens through the Collector", snaps >= acknowledged,
               f"{snaps} snapshots from {len(ids)} ids")


def an_integrity_check_passes_after_a_kill():
    """SQLite's own opinion, which is worth more than ours."""
    db, _ = _kill_mid_write()
    verdict = sqlite3.connect(db).execute("PRAGMA integrity_check").fetchone()[0]
    return _ok("sqlite reports the file intact", verdict == "ok", verdict)


def a_second_writer_can_take_over_after_a_kill():
    """A crashed writer must not leave a lock that locks everyone out forever. WAL keeps a
    -wal and a -shm file beside the database, and a stale lock here would look exactly like
    a hung collector on the next scheduled run."""
    db, acknowledged = _kill_mid_write()
    c = Collector(store_path=db)
    c.record_observation(video_id="after", observed_at="2026-08-20T23:00:00Z", views=7)
    rows = len(c.snapshots("after"))
    c.close()
    return _ok("a new writer can write after the crash", rows == 1,
               f"{rows} rows written by the successor")


def main():
    print("  DURABILITY ATTACK — a process that dies mid-write")
    results = []
    for fn in (acknowledged_writes_survive_the_kill,
               no_row_is_half_written,
               the_store_reopens_and_is_usable,
               an_integrity_check_passes_after_a_kill,
               a_second_writer_can_take_over_after_a_kill):
        try:
            results.append(fn())
        except Exception as exc:
            results.append(_ok(fn.__name__, False, f"{type(exc).__name__}: {exc}"))
    failed = results.count(False)
    print(f"  {len(results) - failed}/{len(results)} held, {failed} open")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
