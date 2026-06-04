from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path

from bench.config import discover_shared_task_files, resolve_project_dir
from bench.layout import implementation_workspace_dir, project_runs_dir
from bench.model_catalog import MODEL_SPECS


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT = "anserini-frontend"


def default_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def create_run_scaffold(project_dir: Path, run_id: str, *, force: bool) -> None:
    run_dir = project_runs_dir(project_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    task_files = discover_shared_task_files(project_dir)

    for spec in MODEL_SPECS:
        workspace_dir = implementation_workspace_dir(run_dir, spec.key)
        workspace_dir.mkdir(parents=True, exist_ok=True)

        config_path = workspace_dir / "bench.toml"
        if force or not config_path.exists():
            config_path.write_text(spec.to_toml(), encoding="utf-8")
            print(f"wrote {config_path.relative_to(ROOT_DIR)}")
        else:
            print(f"kept  {config_path.relative_to(ROOT_DIR)}")

        for task_file in task_files:
            link_path = workspace_dir / task_file.name
            target = Path(os.path.relpath(task_file, workspace_dir))
            if link_path.is_symlink():
                if link_path.readlink() != target:
                    link_path.unlink()
                    link_path.symlink_to(target)
                    print(f"fixed {link_path.relative_to(ROOT_DIR)} -> {target}")
                continue
            if link_path.exists():
                print(f"skip  {link_path.relative_to(ROOT_DIR)} exists")
                continue
            link_path.symlink_to(target)
            print(f"link  {link_path.relative_to(ROOT_DIR)} -> {target}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create canonical Pi Bench implementation workspaces for a project run."
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=DEFAULT_PROJECT,
        help=f"Project directory or key. Default: {DEFAULT_PROJECT}",
    )
    parser.add_argument(
        "--run-id",
        default=default_run_id(),
        help="Run identifier under projects/<project>/runs/. Default: current local timestamp.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing bench.toml files with the default model specs.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_dir = resolve_project_dir(args.project)
    create_run_scaffold(project_dir=project_dir, run_id=args.run_id, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
