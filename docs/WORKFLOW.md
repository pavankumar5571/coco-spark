# Branching

Everything ships through `main`. Nothing is developed on it.

    main            always green, always releasable, always pushed
    feat/<thing>    one piece of work, branched from main
                    -> merged to main when that piece is DONE, not when it is started

## Why this exists

Work on this project happens in more than one place — parallel sessions, more than one
account. That has already cost us: an inventory was written from one branch and declared
work "ZERO" that another session had committed hours earlier on a different branch. The
work was fine; the VISIBILITY was not.

One trunk removes that failure. If it is on main, it exists. If it is not on main, do not
claim it does — and do not claim it does not, either, until you have looked.

## Rules

1. Branch from an up-to-date `main`.

       git checkout main && git pull && git checkout -b feat/<thing>

2. Commit every change, however small, with a message that says WHY. The commit log is
   the project's reasoning, not a changelog.

3. DONE means done, and this project has a specific bar for it: not "it produced output
   once and the tests are green". A mode is done when it is battle tested. See STATUS.md
   for what that requires per mode.

4. Before merging: every suite green, working tree clean.

       python3 test_firewall.py          # planning firewall, zero paid calls
       python3 test_runtime_firewall.py  # runtime properties, zero paid calls
       python3 test_camera_probe.py      # measurement ground-truth controls

5. Merge with `--ff-only` where possible. A linear history means the log reads as the
   sequence of decisions that were actually made.

6. Push `main` immediately after merging, so the other session sees it.

## What does NOT need a branch

Nothing. Including this file.

## Before starting anything

Read the ADRs in docs/. They record decisions that are settled and are not to be
relitigated: the cast is animal-led, 3D is frozen, canon constrains generation, protected
IP does not leave without a rights check, and ACCEPTED does not mean RELEASEABLE.

# Autonomous operation

Pavan stepped back on 2026-08-20 with one instruction: the two agents run the work, and
he is involved only when money is. This section is the standing arrangement, so that it
survives a session ending and neither agent has to reconstruct it from memory.

## The loop

    read CHANNEL.md   ->  do the work in your own column  ->  commit with evidence
        ^                                                          |
        |                                                          v
    watcher wakes you  <-  the other agent posts  <-  post to CHANNEL.md with an ASK

Neither agent waits. `python channel.py watch --agent <YOU>` blocks until the channel
changes, prints only what is new, and exits 0; on `--timeout` it exits 2, which means no
news rather than stuck. Run it in the background at the END of a turn so the exit wakes
you. Nobody polls, nobody idles, and nobody has to ask whether the other has replied.

## What either agent may do alone

Anything that costs nothing and is reversible. Write code, write tests, run them, fix
what they find, commit, push, merge a green branch to main, open and close modules, and
say plainly when the other agent is wrong.

## What stops for Pavan

**Money.** Any provider call that draws on the Rs 600 cap, any change to the cap, and any
decision whose real justification is "we chose to spend on this". That includes choosing
an episode topic as an editorial call when the opportunity engine cannot supply evidence:
the engine being unable to decide does not transfer the decision to us.

**Irreversible outward acts.** A public upload. E01 is frozen PRIVATE and that stands.

**Perception.** Does it look right, does it sound right, is this worth watching. No probe
we have ever written replaces a person, and both agents have been wrong about this in
opposite directions.

Everything else is ours. Before writing "needs Pavan", check whether it needs him or
whether it is merely something neither of us wants to do.

## The chain

When Pavan comes back he should be able to follow one artifact end to end without asking
either of us what happened. That is what git is for here, so every step lands as a commit
whose message says what was found, not merely what was changed, and every handoff lands in
CHANNEL.md with its evidence. A decision recorded only in a chat window did not happen.

## The watcher is not optional

Start `python channel.py watch --agent <YOU>` in the background as the LAST action of
every turn, without exception. Not when you expect a reply — every turn.

The rule exists because it was broken within an hour of being written: a watcher fired,
the agent did an hour of work without restarting one, and the other agent's ruling sat
unread in a file it had already been told to check. Nothing was waiting on a person and
nothing was blocked; the loop had simply stopped turning because one end of it forgot to
listen.

A watcher that is not running is indistinguishable from an agent that is ignoring you.
