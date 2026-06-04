from __future__ import annotations

import os
import tomllib
from pathlib import Path

from bench.layout import (
    PROJECTS_DIR,
    ROOT_DIR,
    TASK_FILE_PATTERNS,
    discover_projects,
    discover_shared_task_files,
    project_runs_dir,
    resolve_project_dir,
)
from bench.model_catalog import load_model_catalog
from bench.schemas import WorkspaceConfig


WORKSPACE_CONFIG_NAME = "bench.toml"


def _as_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def list_projects() -> list[dict[str, str]]:
    return [{"key": path.name, "path": str(path.resolve())} for path in discover_projects()]


def load_workspace_configs(project: str | Path | None = None) -> dict[str, WorkspaceConfig]:
    configs = load_model_catalog()
    project_dir = resolve_project_dir(project)
    if not project_dir.exists():
        return configs

    # Temporary compatibility: if a project still has legacy top-level workspaces,
    # use those bench.toml files to override the catalog defaults.
    for workspace in sorted(project_dir.iterdir()):
        if not workspace.is_dir() or not workspace.name.endswith("-workspace"):
            continue
        config_path = workspace / WORKSPACE_CONFIG_NAME
        if not config_path.exists():
            continue

        parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
        key = workspace.name.removesuffix("-workspace")
        configs[key] = WorkspaceConfig(
            key=key,
            name=parsed.get("name", workspace.name),
            path="",
            model=parsed.get("model", ""),
            provider=parsed.get("provider"),
            thinking=parsed.get("thinking"),
            system_prompt=parsed.get("system_prompt"),
            append_system_prompt=_as_str_list(parsed.get("append_system_prompt")),
            tools=_as_str_list(parsed.get("tools")),
            required_skills=_as_str_list(parsed.get("required_skills")),
        )
    return configs


def load_project_env() -> dict[str, str]:
    env = dict(os.environ)
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return env
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


__all__ = [
    "PROJECTS_DIR",
    "ROOT_DIR",
    "TASK_FILE_PATTERNS",
    "WORKSPACE_CONFIG_NAME",
    "discover_shared_task_files",
    "list_projects",
    "load_project_env",
    "load_workspace_configs",
    "project_runs_dir",
    "resolve_project_dir",
]
