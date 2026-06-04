from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT_DIR / "projects"
DEFAULT_PROJECT_NAME = "anserini-frontend"
RUNS_DIR_NAME = "runs"
EVALS_DIR_NAME = "evals"
TASK_FILE_PATTERNS = ("PRD*.md", "TASK*.md", "task*.md", "prompt*.md")


def resolve_project_dir(project: str | Path | None = None) -> Path:
    selected = project or os.environ.get("PI_BENCH_PROJECT") or DEFAULT_PROJECT_NAME
    path = Path(selected)
    if path.is_absolute():
        return path

    direct = ROOT_DIR / path
    if direct.exists():
        return direct

    nested = PROJECTS_DIR / path
    return nested


def project_runs_dir(project: str | Path | None = None) -> Path:
    return resolve_project_dir(project) / RUNS_DIR_NAME


def implementation_dir(run_dir: Path, implementation_key: str) -> Path:
    return run_dir / implementation_key


def implementation_workspace_dir(run_dir: Path, implementation_key: str) -> Path:
    return implementation_dir(run_dir, implementation_key) / "workspace"


def implementation_evals_dir(implementation_root: Path) -> Path:
    return implementation_root / EVALS_DIR_NAME


def discover_projects() -> list[Path]:
    projects: list[Path] = []
    if PROJECTS_DIR.exists():
        projects.extend(sorted(path for path in PROJECTS_DIR.iterdir() if path.is_dir()))

    for path in sorted(ROOT_DIR.iterdir()):
        if not path.is_dir() or path == PROJECTS_DIR:
            continue
        if path.name.startswith("."):
            continue
        if (path / "PRD.md").exists() or any(path.glob("*-workspace")):
            projects.append(path)

    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in projects:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def discover_shared_task_files(project: str | Path | None = None) -> list[Path]:
    files: dict[str, Path] = {}
    project_dir = resolve_project_dir(project)
    for pattern in TASK_FILE_PATTERNS:
        for path in project_dir.glob(pattern):
            if path.is_file():
                files[path.name] = path
    return [files[name] for name in sorted(files)]
