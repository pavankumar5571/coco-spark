# G01 — Opportunity Engine Audit

Date: 2026-08-20

## Ruling

**Five Little Stars is not a demonstrated market opportunity.** Keep E02 picture spend
blocked if the reason for making E02 is demand evidence. The concept may still be chosen as
an editorial or production-format experiment, but that is a different claim and requires
Pavan's spend decision.

This ruling costs Rs 0 and does not reject the song, brief, or production design. It rejects
only the claim that the current opportunity machinery has validated demand for the topic.

## Evidence boundary

The implementation audited is `enterprise-ai-yt` branch
`codex/youtube-opportunity-engine` at commit `6bf0b6f`. The opportunity-engine files were
introduced at `0defbc1` and last materially extended at `78aa65f`. Uncommitted changes in
that worktree were excluded from the audit.

The engine's declared contract is narrower than the decision E02 needs:

- it discovers recent videos from caller-authored broad queries;
- it requires repeated observations before velocity or acceleration has confidence;
- it scores video-level channel/cohort breakouts;
- it explicitly defers multi-video topic clustering and automatic backlog insertion;
- no durable opportunity report is committed, and this environment has neither the
  deployment `DATABASE_URL` nor `AIS_YOUTUBE_API_KEY` needed to reproduce one.

Therefore it cannot turn one title match, one large lifetime count, or the old enterprise
publication table into a topic-level recommendation for Five Little Stars.

## Independent public reconciliation

A focused public check found examples of the phrase, but not convergent breakout evidence:

- a recent exact-title YouTube result from a channel shown with 2.92M followers had only
  1,726 views at inspection time;
- an exact-title result published 2024-03-26 had 59,983 views on a channel shown with
  401K followers;
- the phrase also exists as older counting-rhyme/storytime material and as several recent
  music releases, which proves the concept is established but not that it is accelerating;
- there is no repeated observation series here, no age-matched velocity comparison, and no
  independent-channel cluster meeting the engine's own proposed next-step standard.

Public references inspected:

- https://www.youtube.com/watch?v=5Z18SEgMDVY
- https://www.youtube.com/watch?v=mWpVG1Q2pOw
- https://gelds.decal.ga.gov/Activity/Detail/1074
- https://www.madisonpubliclibrary.org/sites/www.madisonpubliclibrary.org/files/2025-01/It%2527s%2520Nighttime%2520Storytime%2520Kit%2520%25282024%2529.pdf

Search-result counts are observations, not a time series. They are sufficient to refuse a
positive opportunity claim, not sufficient to prove that demand is absent.

## What would change the ruling

The opportunity claim becomes reviewable only after evidence contains all of the following:

1. at least two observations per candidate separated by the collector's minimum interval;
2. multiple videos from independent channels forming the same topic cluster;
3. age-matched and channel-relative breakout scores with non-zero confidence;
4. preserved query, region, language, observation timestamps, IDs, and raw counters;
5. a deterministic explanation of why the cluster maps to E02 rather than merely sharing
   words such as `stars`, `counting`, or `bedtime`.

Until then, the honest label is `EDITORIAL_CANDIDATE / OPPORTUNITY_UNPROVEN`.
