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
