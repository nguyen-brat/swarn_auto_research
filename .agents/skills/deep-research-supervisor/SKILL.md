---
name: deep-research-supervisor
description: Use when the user asks for deep research, a literature survey, or a handbook from a topic inside the main Codex terminal session.
---

# Deep Research Supervisor

The main Codex session is the supervisor, not the worker. Keep chat context small:
start the durable runner, wait for it, inspect file logs on failure, fix narrowly,
and resume from the failed stage.

## Start

For a new topic:

```bash
env PYTHONPATH=. python scripts/run_auto_research.py --topic "<topic>" --phase all --executor sdk-cli-fallback --max-workers 20
```

For an existing run:

```bash
env PYTHONPATH=. python scripts/run_auto_research.py --run-id <run_id> --phase write --resume --executor sdk-cli-fallback --max-workers 20
```

Do not manually execute stages in chat. Do not paste paper/chapter contents into
the conversation unless diagnosing a failure.

Stages 0-10 run as separate stage-scoped agent tasks under the durable runner,
using SDK transport first and CLI transport as a fallback. This can be quiet
for 40+ minutes on real topics. Do not interrupt solely because no new output
or run directory is visible; wait for the runner timeout, process exit, or a
clear error.

Do not run a separate `sdk.codex` probe while the durable runner is active.
A short probe can time out when the app-server notification path is queued or
stalled even though the real runner still has hours left on its stage timeout.
Treat `--status` `status=running` plus a live `run_auto_research.py` process as
authoritative: keep waiting unless the runner exits, writes `status=failed`,
writes `status=interrupted`, exceeds its own timeout, or the user explicitly
asks to stop it.

Do not send a final answer while the durable runner is still `status=running`.
Continue polling status and process liveness instead. A running background
process is not a completed supervised research run.

The runner uses a 15-minute SDK notification idle timeout by default, while the
stage timeout remains much longer. If the SDK app-server is silent for that idle
window, the same shard is retried through `codex exec` CLI transport instead of
being failed by the supervising chat session. Override with
`SWARN_SDK_NOTIFICATION_TIMEOUT_SECONDS` only when diagnosing transport issues.
The runner caps effective shard fanout by stage. Most parallel stages use up to
20 workers, while Stage 6 expansion uses up to 10 workers. Stage fanout is
still bounded by the number of pending shards.
`SWARN_MAX_EFFECTIVE_WORKERS` applies a global cap, and
`SWARN_STAGE_<N>_MAX_EFFECTIVE_WORKERS` overrides one stage cap when
diagnosing memory or throughput, for example
`SWARN_STAGE_10_MAX_EFFECTIVE_WORKERS=8`.
Stages 8 and 9 are direct Python deterministic stages, not Codex sub-agent
stages.
Stage 8 never edits `07_scoring/promoted_papers.json`. If arxiv2md returns
empty markdown, the runner records the paper in
`08_full_markdown/unavailable_markdown.csv`; Stage 9 and later full-text stages
skip that paper until a later Stage 8 resume fetches non-empty markdown.

## Failure Loop

If the runner exits non-zero:

1. Run:
   ```bash
   env PYTHONPATH=. python scripts/run_auto_research.py --run-id <run_id> --status
   ```
2. Read only the failed shard manifest and stderr path named by `--status`.
3. If needed, use the saved `thread_id` / `turn_id` from the manifest to inspect the SDK child thread.
4. Fix the smallest broken input, prompt, or code path.
5. Resume from the failed stage:
   ```bash
   env PYTHONPATH=. python scripts/run_auto_research.py --run-id <run_id> --phase <draft|write> --resume --from-stage <stage> --executor sdk-cli-fallback --max-workers 20
   ```

## Success

Report only:
- `run_id`
- `16_book/SUMMARY.md`
- `16_book/NEEDS_REVIEW.md`
- `19_handbook/`
- remaining quarantined count, if any

The file system is the source of truth. The main session should not remember
chapter details; it should read artifacts when needed.
