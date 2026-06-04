# Pi Bench Handoff

This handoff summarizes the current state for the next agent. Read `README.md`, `STORY.md`, and `AGENTS.md` first; this file focuses on recent work, known hazards, and next steps.

## Project Purpose

Pi Bench compares coding agents by running the same prompt in isolated model workspaces through the Pi CLI. It now also includes `bench/web_eval`, a web-app evaluator that uses PRD-derived feature checks, setup planning, Playwright evidence, and an LLM judge to score whether an agent-built web app actually works.

The current active scoring target is `anserini-evaluator/`, where agents build a local browser app around the Anserini fatjar CLI for catalog discovery and CACM retrieval/evaluation.

## Critical Workspace Policy

Do not modify implementation `workspace/` directories under `projects/*/runs/*/*/workspace/` unless the user explicitly asks. These directories are benchmark specimens: the original one-shot outputs are meant to stay intact.

Allowed operational side effects during evaluation are limited to setup/runtime artifacts such as dependency installs, downloaded jars, or run/eval files. Do not patch app source, README, tests, manifests, or config inside a workspace to make an implementation pass.

This policy is now written in `AGENTS.md`. Earlier in the session, Gemini's `server.js` was briefly patched for diagnosis; that change has been reverted. Git currently reports no dirty files under implementation `workspace/` paths after cleanup.

## Current Code Areas

Important files:

```text
bench/web_eval/__main__.py    CLI entry point for web eval
bench/web_eval/runner.py      Orchestrates setup, app startup, evidence, judging, artifacts
bench/web_eval/judge.py       LLM prompts and OpenAI-compatible chat calls
bench/web_eval/setup.py       Setup context, allowlisted command execution, recovery logic
bench/web_eval/browser.mjs    Playwright evidence collection
bench/web_eval/profile.py     App profile discovery/repair, free-port handling, server lifecycle
bench/web_eval/report.py      summary/report/judgment/evidence artifact writer
tests/test_web_eval.py        Regression tests for web_eval harness behavior
STORY.md                      Longer narrative project overview for future agents
AGENTS.md                     Standing instructions and workspace preservation policy
```

`bench/web_eval/setup.py` is currently untracked in Git but is central to the harness. Do not lose it.

## Recent Harness Work

Recent work improved `bench/web_eval` in these areas:

- PRD-to-feature generation and `features.yaml` loading.
- Setup context collection from PRD, README files, manifests, and referenced skills.
- Compact `setup_hints` extracted from setup-like code blocks so the LLM does not miss important install steps in long skill docs.
- General setup command allowlist for package installs, project-local scripts, env assignments, downloads, Java/test smoke checks, safe stdout redirection, `grep -q`, and Playwright browser install.
- `npx playwright install ...` is normalized to `npx --yes playwright install ...` to avoid confirmation hangs.
- Maven Central recovery for bad guessed versions: on 404, read `maven-metadata.xml`, retry the same artifact at the published release, and update matching version/jar env vars.
- Java classpath recovery for Maven-downloaded jars that lack a needed class.
- Whitespace-normalized `grep -q` verification, important for padded Anserini metric output.
- Targeted setup invalidation instead of deleting every setup-created artifact when any later command fails.
- App profile repair for nested package directories and occupied ports.
- Playwright evidence improvements: visible text, ARIA snapshots, screenshots, console/network errors, interactive elements, result-like text, numeric candidates, and better visible click targeting.
- Per-feature LLM planning/judging errors now produce artifacts/uncertain judgments instead of aborting the whole run.

The guiding constraint remains: these are general harness improvements, not Anserini-specific installers.

## Recent Diagnoses

False negatives during Anserini evaluator judging came from several harness issues:

- setup planner found the skill workflow but the runner passed `>` literally to Java instead of handling stdout redirection
- skill verification `grep` commands were initially rejected by the allowlist
- `npx playwright install chromium` could hang waiting for confirmation
- guessed Maven versions caused 404s or jars with missing classes
- `grep` failed because Anserini padded metric names before tabs
- broad rollback deleted good downloaded jars after later verification failures
- stale apps on port 3000 caused evidence to come from the wrong implementation
- hardcoded app ports in agent implementations are implementation bugs; do not patch them unless the user asks
- an LLM API/planning failure previously aborted a run before `summary.json`/`report.md` were written

The latest known Gemini issue: `anserini-evaluator/gemini-workspace/server.js` hardcodes port 3000 and misleadingly logs success when port 3000 is occupied under Express 5. This is an implementation flaw, not a harness issue. The diagnostic patch was reverted per user instruction.

## How To Run Checks

For harness changes:

```sh
python3 -m unittest tests.test_web_eval -v
python3 -m compileall bench/web_eval tests/test_web_eval.py
node --check bench/web_eval/browser.mjs
```

For a web eval:

```sh
python3 -m bench.web_eval \
  --project projects/anserini-evaluator/runs/20260603-legacy-current-state/gpt \
  --features projects/anserini-evaluator/features.yaml \
  --prd projects/anserini-evaluator/PRD.md \
  --label gpt-evaluator
```

For process benchmark runs:

```sh
python -m bench.cli \
  --project anserini-evaluator \
  --prompt-file projects/anserini-evaluator/PRD.md \
  --models gpt claude \
  --mode sequential \
  --timeout-seconds 1800 \
  --label anserini-evaluator-rerun
```

## Artifact Inspection

For web eval failures, inspect in this order:

```text
evals/<id>/setup.json
evals/<id>/setup-context.json
evals/<id>/run.json
evals/<id>/evidence/*.json
evals/<id>/judgments/*.json
evals/<id>/report.md
evals/<id>/summary.json
```

If `report.md` or `summary.json` is missing, the runner likely hit a top-level exception. Per-feature LLM failures should now be captured as `uncertain`, but top-level failures may still need better artifact writing.

## Environment Notes

This development environment has often required escalated command execution because sandboxed tool calls fail with `bwrap` errors. That is a Codex/session environment issue, not necessarily a Pi Bench runtime issue.

Port 3000 is shared across users/processes on the `basilisk` GPU server. Many stale `node server.js` processes have existed at once. The judge harness should prefer free high ports and apps that honor `PORT`. If an app hardcodes port 3000, that is a fragility in the implementation and may cause stale-port false evidence.

## Git State Notes

At the time this handoff was written:

- agent workspaces were cleaned of reported dirty changes
- `AGENTS.md` was newly added
- `STORY.md` was newly added
- `HANDOFF.md` was rewritten
- multiple `bench/web_eval` files and tests remain modified from the current harness work
- `bench/web_eval/setup.py` is untracked but required

Run `git status` before editing. Do not revert unrelated user changes.

## Next Steps

1. Re-run web eval on `projects/anserini-evaluator/runs/20260603-legacy-current-state/{gpt,claude,gemini}` without modifying their source.
2. Confirm the harness writes `summary.json` and `report.md` even if setup or judge calls fail.
3. If setup still fails, inspect whether the LLM planned install commands from PRD/README/skills or relied on stale environment variables.
4. If a workspace app is genuinely broken, report it as an implementation failure rather than adapting tests to pass it.
5. Add regression tests for every harness-level false negative that is fixed.
6. Consider top-level failure artifacts for `bench.web_eval` so complete aborts leave an explicit error file.
