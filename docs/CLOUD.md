# Working in the repo instead of on a laptop

Approved for ONE reason: coordination. Two accounts have already produced work that was
invisible to each other, and a credential has already been trapped in one person's shell
while the other needed it. Both are environment problems, and a shared reproducible
environment is the fix.

Not approved for compute. The whole pipeline peaks at 68 MB.

## What a Codespace does and does not give you

    DOES     one reproducible environment: same python, same ffmpeg, same deps
    DOES     secrets injected at runtime, so they live in a secret store, not a laptop
    DOES NOT give two agents one shared live workspace

Each codespace is its own machine. THE SINGLE TRUTH IS STILL GIT/MAIN, NOT THE VM.
docs/WORKFLOW.md still applies in full: branch, commit, merge to main, push. Codespaces
removes setup and secret divergence. It does not remove branch coordination.

## Secrets

Codespaces secrets are injected as environment variables at RUNTIME. They are not
available during image build, which is why bootstrap.sh installs and nothing else.

    GOOGLE_API_KEY           shared provider key    -> repository-scoped is fine
    YOUTUBE_CLIENT_ID        application identity   -> repository-scoped is fine
    YOUTUBE_CLIENT_SECRET    application identity   -> repository-scoped is fine
    YOUTUBE_REFRESH_TOKEN    THE CHANNEL OWNER      -> account-scoped, limited to this repo

That last distinction matters. A refresh token is not a shared service key; it is proof
that a specific human consented on behalf of a channel. Scope it to the person, not to the
project, and grant it to this repository only.

## The security boundary is wider than it looks

Anything that executes inside a codespace carrying these secrets can read them. That
includes dependencies, lifecycle scripts, and any code merged into a branch you then run.

    no secrets in Dockerfile or devcontainer build steps
    lifecycle scripts stay boring and auditable — read bootstrap.sh, it is 45 lines
    no installing packages or extensions from startup scripts
    never print env or config dumps, and never let an exception do it for you
    least-privileged credential per provider
    the YouTube upload stays an EXPLICIT command; no hook may ever trigger it
    no public port forwarding from an environment holding tokens
    treat a pull request as security-relevant BEFORE running it with secrets present

The repository is public. The source being public is fine. The environment holding the
credentials is the thing to protect.

## Falsification test for this migration

It has succeeded when a FRESH codespace can, with no local knowledge:

    clone -> bootstrap -> run all three offline suites -> release.py prepare

and nothing else needs to be expanded. If it passes, stop. Do not turn "let us use GitHub
directly" into a storage or platform migration project.

## What is explicitly NOT part of this

Cloudflare R2. The repo carries ~91 MB of tracked media and git does not delta-compress
mp4, so the history will grow badly — but that was true yesterday too. The two gates set
in ADR c18e32d still stand: measure what storage actually costs, and inventory the
semantics before migrating. "We are in the cloud now" is not evidence, and must not become
a way around a gate we set ourselves.

Measure the pain first: clone time, startup time, workspace disk. Solve it when it hurts.
