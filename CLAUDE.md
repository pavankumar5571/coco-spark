# Read this first

You are one of two agents on this project. The other is GPT/Codex, which also writes to
this repository. Neither of you can read the other's chat window, so **everything that
matters is in git** — if it is not committed, it did not happen.

## Where the state is

    docs/STATE.md      what is true right now, and what is blocked on whom. START HERE.
    docs/CHANNEL.md    the agent-to-agent log. Append-only. Read the last entries.
    docs/DECISIONS.md  every ruling, with the reasoning that produced it
    docs/WORKFLOW.md   how the two agents operate, and what stops for Pavan
    docs/PRODUCTION-AUTOMATION.md  generic YouTube/Gemini/Suno/Blender launch contract
    docs/ADR-*.md      decisions that reverse expensively; read before reopening one

Read `docs/STATE.md` before doing anything. It is rewritten at every milestone precisely
so a new session starts with no gap.
Read `docs/PRODUCTION-AUTOMATION.md` before changing episode planning, generation,
validation, runners or storage; it prevents a new session from turning a generic production
system back into per-episode scripts.

## The loop

    python channel.py watch --agent CLAUDE

blocks until `docs/CHANNEL.md` changes, prints only what is new, exits 0. On timeout it
exits 2, which means no news rather than stuck. **Start it in the background as the last
action of every turn, without exception.** A watcher that is not running is
indistinguishable from an agent that is ignoring the other one — that has already happened
once, and a ruling sat unread for an hour.

Post with `python channel.py post --agent CLAUDE --module … --subject … --body -`.

## What stops for Pavan

Money against the Rs 600 cap, the cap itself, any choice whose real justification is "we
decided to spend on this", irreversible outward acts, and perceptual judgement — does it
look right, sound right, deserve watching. **Everything else is yours.** Before writing
"needs Pavan", check whether it needs him or whether it is merely something you would
rather not do. He has said explicitly that being the bottleneck is what cost him three
months.

## The invariants, each learned by breaking

- **A request is not evidence of a result.** Read back what actually happened. `verify`
  exists because "the upload returned 200" is not "the video is private".
- **Verify against source, not against the message describing it.** Both agents have been
  caught reviewing a description. Cite the commit SHA you actually read.
- **Generic, never per-episode.** If it names E01, Coco, a bedroom or bedtime, it is not a
  fix. Test: replace Coco with a robot, the cottage with a space station, BEDTIME_STORY
  with EDUCATIONAL — does the code still work with no special case?
- **Paid generation is the last step of validation, never the tool for discovering whether
  the spec is right.** If a defect is deterministically detectable, find it for Rs 0.
- **Reserve before invoking.** Money is committed locally before it can be committed
  remotely, or the guard is behind the charge.
- **Prose never held form.** Five separate prose guarantees were ignored by these
  providers. Only image references and deterministic code have ever held.
- **A test that reads an untracked file is testing the machine.** One suite had never once
  been green on a clean checkout and nobody knew.
- **Battle-tested is not green-once.** Three independent episodes of a mode, no code
  patches between them, before that mode is called done.

## Do not

Reopen a settled ADR without new evidence. Expand a predeclared battle-test contract
mid-flight — good ideas have been allowed to behave like blockers before. Start a third
module while yours is open. Or spend a rupee without Pavan.
