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
env PYTHONPATH=. python scripts/run_auto_research.py --topic "<topic>" --phase all --executor sdk --max-workers 20
```

For an existing run:

```bash
env PYTHONPATH=. python scripts/run_auto_research.py --run-id <run_id> --phase write --resume --executor sdk --max-workers 20
```

Do not manually execute stages in chat. Do not paste paper/chapter contents into
the conversation unless diagnosing a failure.

Stages 0-10 run as separate stage-scoped SDK tasks under the durable runner,
including paper pool collection. This can be quiet for 40+ minutes on real
topics. Do not interrupt solely because no new output or run directory is
visible; wait for the runner timeout, process exit, or a clear error.

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
   env PYTHONPATH=. python scripts/run_auto_research.py --run-id <run_id> --phase <draft|write> --resume --from-stage <stage> --executor sdk --max-workers 20
   ```

## Success

Report only:
- `run_id`
- `16_book/SUMMARY.md`
- `16_book/NEEDS_REVIEW.md`
- remaining quarantined count, if any

The file system is the source of truth. The main session should not remember
chapter details; it should read artifacts when needed.
