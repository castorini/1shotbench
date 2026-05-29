# Pi Bench — Agent Handoff

This document summarizes project context, recent work, known issues, and next steps so a new agent can continue development on a machine where `bwrap` works.

---

## Project purpose

**Pi Bench** is a multi-model coding-agent benchmark harness. It runs the **same task prompt** through separate **Pi agent workspaces** (one per model) and compares process-level outcomes: duration, tokens, cost, exit status, and logs.

It is **not** (yet) an automated task scorer. PRD success (app works, Playwright passes) must be verified manually in each model workspace.

**Overarching goal:** fair, reproducible comparison of coding agents under a controlled harness — intended to become a research toolkit and paper demo.

---

## Current benchmark tasks

| Task dir | Prompt file | What agents build |
|----------|-------------|-------------------|
| `anserini-frontend/` | `PRDv2.md` | Next.js frontend + Anserini REST API for MS MARCO passage search |
| `anserini-evaluator/` | `PRD-anserini-evaluator.md` | Web app for prebuilt-index catalog + CLI retrieval/evaluation (Playwright e2e) |

Each task has model workspaces named `{model-key}-workspace/` with a `bench.toml` (provider, model, tools, required skills).

Default model keys (from `scripts/create_agent_workspaces.py`): `gpt`, `claude`, `gemini`, `glm`, `kimi`, `minimax`.

**User-added:** `deepseek-workspace/` exists under both tasks (not in the scaffold script yet).

---

## Changes made this session (may be uncommitted)

Check `git status` — at handoff time these were present:

### 1. Linux sandbox via `bwrap` (main code change)

**Problem:** Preflight required macOS-only `sandbox-exec`, blocking all runs on Linux.

**Solution:** New `bench/sandbox.py` with platform detection:

- **macOS:** `sandbox-exec -f workspace.sb` (unchanged behavior)
- **Linux:** `bwrap` with `--bind / /` and `--ro-bind <empty-dir> <denied-path>` over sibling workspaces + `.codex-private/`

**Key files:**

| File | Role |
|------|------|
| `bench/sandbox.py` | Sandbox backend selection, denied-path logic, macOS profile + bwrap wrapping |
| `bench/runner.py` | Calls `sandbox_preflight_error()` and `apply_workspace_sandbox()` |
| `tests/test_sandbox.py` | Unit tests + optional bwrap integration test (skipped if bwrap non-functional) |
| `README.md` | Updated docs for both backends |

**Sandbox policy (unchanged intent):**

- Default-allow filesystem access
- Deny read/write to **sibling `*-workspace/` dirs** and **`.codex-private/`**
- Does **not** block repo root, `bench/`, `.git`, or network

**Backend selection:** `sandbox-exec` if available, else functional `bwrap`, else preflight fails.

**Artifacts per run:**

- macOS: `runs/<id>/<model>/workspace.sb`
- Linux: `runs/<id>/<model>/workspace.bwrap.json`, `sandbox-deny-overlay/`

### 2. DeepSeek workspaces (user setup)

- `anserini-frontend/deepseek-workspace/bench.toml`
- `anserini-evaluator/deepseek-workspace/bench.toml`

Example config:

```toml
provider = "deepseek"
model = "deepseek-v4-flash"   # or deepseek-v4-pro
thinking = "high"
required_skills = ["install-anserini-fatjar", "anserini-cli", "anserini-reproduction"]
```

**Model key for CLI:** `deepseek` (from directory name `deepseek-workspace`, **not** the Pi model ID).

User logged into DeepSeek via `pi /login` with API key.

---

## Problems encountered on the old machine

### 1. `bwrap` installed but non-functional

```sh
bwrap --unshare-user-try --die-with-parent -- true
# bwrap: setting up uid map: Permission denied
```

Cause: `/usr/bin/bwrap` was **not setuid** and unprivileged user namespaces were restricted.

Pi Bench preflight correctly reported:

```text
`bwrap` is installed but cannot create a sandbox (user namespaces or setuid bubblewrap may be unavailable).
```

**On the new machine:** verify bwrap works before benchmarking:

```sh
bwrap --unshare-user-try --die-with-parent -- true && echo OK
python -m unittest tests.test_sandbox.BwrapIsolationIntegrationTests -v
```

Typical fixes on Linux: install `bubblewrap` package with setuid bit, or enable unprivileged user namespaces.

### 2. `Unknown model keys: deepseek`

Usually caused by:

- Missing `--task-dir` pointing at the task that contains `deepseek-workspace/`
- Web UI (`uvicorn`) started **before** workspace was created — restart server (workspaces loaded at import time in `bench/web.py`)
- Using `deepseek-v4-flash` as `--models` key instead of `deepseek`

### 3. CLI output `[output] deepseek: None`

Normal. The CLI prints `event.get("status")` but `output` events have no `status` field. Watch for `[complete] deepseek: completed` and `runs/<id>/summary.json`.

### 4. Environment-dependent artifacts

LLM-built apps differ by OS, Java/Node versions, network, install paths. macOS vs Linux comparisons need same OS or separate leaderboards.

---

## How to run benchmarks

### Setup

```sh
pip install -r requirements.txt
scripts/install_anserini_skills.sh   # prepared-environment track
# Configure Pi auth: ~/.pi/agent/auth.json or .env
```

Requirements: Python 3.11+, `pi` on PATH, functional `sandbox-exec` (macOS) or `bwrap` (Linux).

### Example commands

**Anserini frontend + DeepSeek:**

```sh
python -m bench.cli \
  --task-dir anserini-frontend \
  --prompt-file anserini-frontend/PRDv2.md \
  --models deepseek \
  --mode sequential \
  --timeout-seconds 1800 \
  --label anserini-frontend-deepseek-1
```

**Anserini evaluator + DeepSeek:**

```sh
python -m bench.cli \
  --task-dir anserini-evaluator \
  --prompt-file anserini-evaluator/PRD-anserini-evaluator.md \
  --models deepseek \
  --mode sequential \
  --timeout-seconds 1800 \
  --label anserini-evaluator-deepseek-1
```

### Run outputs

```text
runs/<run_id>/
  prompt.txt
  summary.json | summary.csv | summary.md
  <model>/
    stdout.log, stderr.log, events.jsonl, result.json
    workspace.sb | workspace.bwrap.json
```

Curated published results live in `benchmark-artifacts/` (e.g. `anserini-evaluator-clean-rerun/`). No frontend rerun published yet.

---

## Key codebase map

```text
bench/
  cli.py          — CLI entry: python -m bench.cli
  runner.py       — Async benchmark orchestration, Pi subprocess, summaries
  sandbox.py      — Platform sandbox (sandbox-exec / bwrap)  [NEW]
  config.py       — Task dir resolution, bench.toml loading, .env
  schemas.py      — WorkspaceConfig, RunJobResult, pi_args()
  metrics.py      — Token/cost parsing from Pi JSON events
  web.py          — FastAPI UI (port 4010)

scripts/
  create_agent_workspaces.py  — Scaffold *-workspace dirs + bench.toml
  install_anserini_skills.sh  — Copy Anserini skills to .agents/skills/

tests/
  test_runner.py  — Timeout/stream/process-group tests
  test_sandbox.py — Sandbox unit + bwrap integration tests  [NEW]

anserini-frontend/     — Task 1 + model workspaces (contain prior agent-built apps)
anserini-evaluator/    — Task 2 + model workspaces
.agents/skills/        — Preinstalled Anserini skills (prepared track)
benchmark-artifacts/   — Committed subset of run results for papers/docs
runs/                  — Local run output (gitignored)
```

### Important concepts

- **`--models` keys** = workspace directory prefix (`gpt`, `deepseek`, …)
- **`bench.toml` `model`** = Pi model ID passed to `pi --model`
- **Prepared-environment track (default):** skills preinstalled; preflight fails if missing
- **Bootstrap track (future):** agents find/install skills themselves — keep separate run labels

---

## Immediate next steps on new machine

1. **Verify bwrap:** smoke test + `tests/test_sandbox.py` integration test
2. **Run a short DeepSeek benchmark** on one task; confirm `runs/<id>/` artifacts and workspace app builds
3. **Optionally verify isolation:** from `deepseek-workspace`, agent/bash should not read sibling workspace secrets (integration test covers this)
4. **Commit session changes** if not already: `bench/sandbox.py`, `bench/runner.py`, `tests/test_sandbox.py`, `README.md`, deepseek workspaces

---

## Future goals (discussed, not implemented)

### Near-term engineering

- **Add DeepSeek to `create_agent_workspaces.py`** scaffold defaults
- **Automated task scoring** — post-run Playwright/e2e per task; add `task_score` to `summary.json`
- **Run manifest / reproducibility bundle** — pin Pi version, skill commit, prompt hash
- **Linux sandbox hardening** — optional whitelist (RW workspace only, RO repo root); explicitly out of scope for bwrap v1
- **Relax or improve web UI** — reload workspaces without restart; fix CLI `[output]: None` noise

### Research / paper / demo

- **Public results site** (e.g. Vercel) — leaderboard, cost/tokens/duration, links to deployed model demos
- **Bootstrap vs prepared tracks** as first-class `--track` flag
- **Multi-run statistics** — replicates, confidence intervals, failure taxonomy from `events.jsonl`
- **Human eval layer** — blind A/B on UX/code quality
- **Task suite expansion** — more PRD sibling dirs with evaluation hooks
- **Publish `anserini-frontend` clean rerun** to `benchmark-artifacts/` (evaluator rerun exists as template)

### Known non-goals (for now)

- Whitelist sandbox blocking repo root / git
- Full container isolation (Docker) unless needed later
- Mixing bootstrap and prepared track results in one leaderboard

---

## Git / commit state note

At handoff, sandbox changes and deepseek workspaces were **modified/untracked** relative to `f978503`. A new agent should run `git status` and commit when ready. Do not commit `.env`, `runs/`, or huge `events.jsonl` files.

---

## Quick reference: sandbox equivalence

| macOS (`sandbox-exec`) | Linux (`bwrap`) |
|------------------------|-----------------|
| `(allow default)` | `--bind / /` |
| `(deny file-read* (subpath PATH))` | `--ro-bind <empty> PATH` |
| `(deny file-write* (subpath PATH))` | same overlay (read-only empty dir masks content) |

Both deny: sibling `*-workspace/` paths + `.codex-private/`.

---

## Questions for the user if unclear

- Which task to prioritize for first Linux validation run?
- Should DeepSeek be added to the default scaffold script?
- Is the paper targeting prepared-environment track only for v1?
- Where will deployed demos be hosted (Vercel frontend only vs full Java backend)?
