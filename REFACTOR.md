# Refactor Summary

This document summarizes the structural refactor currently present in the local uncommitted changes, relative to the original codebase layout.

## Original Structure

Originally, the repository mixed several different concerns at the top level:

- benchmark framework code under `bench/`
- example benchmark projects such as `anserini-evaluator/` and `anserini-frontend/`
- agent implementation workspaces directly under those project folders, using names like `gpt-workspace/`, `claude-workspace/`, `kimi-workspace/`
- preserved run artifacts under `benchmark-artifacts/`
- generated benchmark outputs under root-level locations like `runs/` and `evals/`

This created a few problems:

- project definitions and project history were separated
- implementation identity was inferred from folder names like `*-workspace`
- repeated runs of the same model were not first-class
- preserved artifacts such as `benchmark-artifacts/anserini-evaluator-clean-rerun` were not clearly connected to the canonical run model
- the CLI and web UI exposed internal path layout too directly

## New Structure

The refactor introduces a canonical `projects/` root and moves benchmark definitions plus benchmark history under that root.

The intended structure is:

```text
projects/
  <project>/
    PRD.md
    features.yaml
    project.json
    runs/
      <run-id>/
        run.json
        prompt.txt
        <implementation-key>/
          bench.toml
          workspace/
          stdout.log
          stderr.log
          events.jsonl
          result.json
          evals/
```

Key ideas:

- a `project` is a benchmark definition plus its historical runs
- a `run` is one batch execution under a project
- an `implementation` is one model/agent entry inside that run
- `workspace/` contains the actual generated implementation specimen
- eval outputs live under the implementation they belong to

## Folder Moves

The refactor moves the original example projects into `projects/`:

- `anserini-evaluator/` -> `projects/anserini-evaluator/`
- `anserini-frontend/` -> `projects/anserini-frontend/`

It also migrates the old one-shot workspace specimens into canonical run folders. For example, the old current-state workspaces are imported into run folders such as:

- `projects/anserini-evaluator/runs/20260603-legacy-current-state/...`
- `projects/anserini-frontend/runs/20260603-legacy-current-state/...`

The preserved historical rerun bundle under:

- `benchmark-artifacts/anserini-evaluator-clean-rerun/`

is migrated into:

- `projects/anserini-evaluator/runs/20260523-032002-d5f3fc6f/`

This makes preserved historical artifacts part of the same run model as new benchmark outputs.

## Naming Model

The refactor introduces a clearer hierarchy:

- `project`: which benchmark definition is being used
- `run-id`: which batch benchmark invocation is being referenced
- `implementation-key`: which model/agent specimen inside that run is being referenced

Example:

```text
projects/anserini-evaluator/runs/20260603-153937-deepseek-evaluator/gpt/
```

This path means:

- project: `anserini-evaluator`
- run: `20260603-153937-deepseek-evaluator`
- implementation: `gpt`

## Codebase Changes Required By The Refactor

This refactor is not just a folder move. The codebase had to be updated to understand the new model.

### 1. Path and layout abstraction

The original code assumed a flatter layout with immediate `*-workspace` directories. The refactor adds layout-aware helpers so code can construct and resolve canonical project/run/implementation paths without scattering path logic everywhere.

New support modules introduced for this include:

- `bench/layout.py`
- `bench/model_catalog.py`

### 2. Configuration and workspace discovery

The original config model inferred too much from directory names. The refactor changes config loading so the system can reason in terms of:

- project roots
- run directories
- implementation folders
- explicit metadata such as `project.json` and `run.json`

This required changes in:

- `bench/config.py`

### 3. Benchmark runner output paths

Originally, runner behavior assumed old workspace locations and root-level run artifacts. The refactor changes the runner so new benchmark executions materialize under:

- `projects/<project>/runs/<run-id>/<implementation>/workspace/`

and write logs/results alongside that implementation entry.

This required major changes in:

- `bench/runner.py`

Related changes include:

- creation of self-contained implementation folders for each run
- writing `summary.json`, `summary.csv`, and `summary.md` under the run directory
- writing per-model logs and results under the implementation directory
- using the materialized run-local workspaces for sandboxing instead of template entries

### 4. Sandbox behavior

Once implementations live under run-local workspaces, sandboxing must deny sibling implementation workspaces, not the repo root.

The refactor updates sandboxing so the allowed/denied boundaries fit the new structure:

- deny sibling implementation workspaces
- deny `.codex-private`
- allow repo root
- allow PRDs and other linked task files
- allow `.agents/`
- allow the current implementation workspace itself

This required changes in:

- `bench/sandbox.py`

### 5. CLI interface

The original CLI was more path-oriented and assumed the older task/workspace layout. The refactor shifts the interface toward project-aware operation.

Examples of the intended change:

- from `--task-dir` style assumptions
- toward `--project <project-name>`

The refactor also adds a centralized model catalog and a `--list-models` flow so the CLI can report the supported model keys from one source of truth.

This required changes in:

- `bench/cli.py`

### 6. Web UI / API

The original web interface assumed one default task directory at startup. Under the new structure, the UI needs to browse projects and runs explicitly.

This required changes in:

- `bench/web.py`
- `bench/static/index.html`

The refactor makes the web layer project-aware rather than assuming a single root benchmark target.

### 7. Web evaluation output layout

Originally, eval artifacts were more separate from the implementation they judged. The refactor moves eval outputs under the implementation entry itself:

- `projects/<project>/runs/<run-id>/<implementation>/evals/<eval-id>/`

This makes each implementation folder self-contained: code, logs, and evaluation all live together.

This required changes in:

- `bench/web_eval/__main__.py`
- `bench/web_eval/runner.py`

### 8. Workspace/bootstrap scripts

The original workspace generation logic assumed stable folders like `gpt-workspace` or `claude-workspace` under a project root.

Under the refactor, scaffolding needs to create:

- a run directory
- implementation entries inside that run
- run-local workspaces and config files

This required changes in:

- `scripts/create_agent_workspaces.py`

## README and Documentation Changes

The old README and docs described the older top-level layout and older CLI assumptions. They had to be updated to reflect:

- the new `projects/` root
- the fact that `anserini-evaluator` and `anserini-frontend` are example projects, not special root-level entities
- the new meaning of project, run, and implementation
- the new canonical location for run artifacts and eval artifacts
- the updated CLI examples that reference `--project` and canonical run paths

This required updates in:

- `README.md`
- `AGENTS.md`
- `HANDOFF.md`

## Git and Artifact Policy Implications

The refactor also changes how to think about generated artifacts:

- run-shaped artifacts now belong under `projects/*/runs/`
- preserved historical artifacts are folded into the same run namespace
- generated junk such as transient jars, logs, pid files, and temp outputs should be treated separately from canonical source and preserved run data

This required `.gitignore` updates so the ignore policy better matches the new canonical structure instead of the old root-level workspace layout.

## Test Changes

Because many tests assumed the original folder model, they also needed updates.

Affected areas include:

- runner tests
- sandbox tests
- web-eval tests

Examples:

- tests that assumed `*-workspace` folders under a task root had to be updated
- tests were added or updated to validate the new sandbox behavior around sibling run workspaces
- tests were updated for the new runner signatures and artifact locations

## Practical Outcome

After the refactor, the repository is organized around a simpler conceptual model:

- benchmark definitions live under `projects/`
- benchmark history lives under each project’s `runs/`
- each run contains self-contained implementation entries
- each implementation contains its own workspace, logs, results, and evals

This removes the split between:

- root-level project folders
- root-level run history
- separate preserved artifact buckets

and replaces it with one canonical project-centered structure.
