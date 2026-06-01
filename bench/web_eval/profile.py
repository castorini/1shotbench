from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from bench.web_eval.schemas import AppProfile


def resolve_app_profile(
    project_path: Path,
    *,
    base_url: str | None,
    profile_data: dict[str, Any] | None,
    no_start: bool,
) -> AppProfile:
    if base_url:
        return AppProfile(base_url=base_url.rstrip("/"))

    if profile_data:
        return _profile_from_mapping(project_path, profile_data)

    detected = _detect_profile(project_path)
    if detected:
        return detected

    raise ValueError(
        "No app URL configured. Pass --base-url, add `app` to the features file, "
        "or place eval-profile.yaml in the project directory."
    )


def _profile_from_mapping(project_path: Path, data: dict[str, Any]) -> AppProfile:
    url = data.get("url") or data.get("base_url")
    if not url:
        port = str(data.get("port", "3000"))
        host = data.get("host", "127.0.0.1")
        url = f"http://{host}:{port}"
    start = data.get("start_command") or data.get("start")
    start_command: list[str] | None = None
    if isinstance(start, str):
        start_command = start.split()
    elif isinstance(start, list):
        start_command = [str(part) for part in start]
    cwd = data.get("cwd")
    env = {str(k): str(v) for k, v in (data.get("env") or {}).items()}
    ready_url = data.get("ready_url")
    timeout = int(data.get("ready_timeout_seconds", data.get("timeout_seconds", 120)))
    return AppProfile(
        base_url=str(url).rstrip("/"),
        start_command=start_command,
        cwd=str(cwd) if cwd else None,
        env=env,
        ready_url=str(ready_url) if ready_url else None,
        ready_timeout_seconds=timeout,
    )


def _detect_profile(project_path: Path) -> AppProfile | None:
    package_json = project_path / "package.json"
    if package_json.exists():
        pkg = json.loads(package_json.read_text(encoding="utf-8"))
        scripts = pkg.get("scripts") or {}
        if (project_path / "server.js").exists() and "start" in scripts:
            port = os.environ.get("PORT", "3000")
            return AppProfile(
                base_url=f"http://127.0.0.1:{port}",
                start_command=["npm", "start"],
                cwd=str(project_path),
                env={"PORT": port},
                ready_url=f"http://127.0.0.1:{port}/",
            )
        if (project_path / "server.py").exists():
            port = os.environ.get("PORT", "5000")
            return AppProfile(
                base_url=f"http://127.0.0.1:{port}",
                start_command=["python", "server.py"],
                cwd=str(project_path),
                env={"PORT": port},
                ready_url=f"http://127.0.0.1:{port}/",
            )
        if "dev" in scripts:
            port = os.environ.get("FRONTEND_PORT", os.environ.get("PORT", "3000"))
            return AppProfile(
                base_url=f"http://127.0.0.1:{port}",
                start_command=["npm", "run", "dev"],
                cwd=str(project_path),
                env={"PORT": port, "FRONTEND_PORT": port},
                ready_url=f"http://127.0.0.1:{port}/",
                ready_timeout_seconds=180,
            )
    nested = list(project_path.glob("**/package.json"))
    for candidate in nested:
        if "node_modules" in candidate.parts:
            continue
        parent = candidate.parent
        if parent == project_path:
            continue
        nested_profile = _detect_profile(parent)
        if nested_profile:
            return nested_profile
    return None


class AppServer:
    def __init__(self, profile: AppProfile, project_path: Path):
        self.profile = profile
        self.project_path = project_path
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        if not self.profile.start_command:
            return
        if self.profile.cwd:
            cwd_path = Path(self.profile.cwd)
            cwd = cwd_path if cwd_path.is_absolute() else self.project_path / cwd_path
        else:
            cwd = self.project_path
        env = os.environ.copy()
        env.update(self.profile.env)
        self.process = subprocess.Popen(
            self.profile.start_command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        ready = self.profile.ready_url or self.profile.base_url
        _wait_for_url(
            ready,
            timeout_seconds=self.profile.ready_timeout_seconds,
            process=self.process,
        )

    def stop(self) -> None:
        if not self.process:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None


def _process_exit_detail(process: subprocess.Popen[str] | None) -> str | None:
    if not process or process.poll() is None:
        return None
    output = ""
    if process.stdout:
        try:
            output = process.stdout.read() or ""
        except Exception:
            output = ""
    tail = "\n".join(output.strip().splitlines()[-15:])
    detail = f"start command exited with code {process.returncode}"
    if tail:
        detail += f":\n{tail}"
    return detail


def _wait_for_url(
    url: str,
    timeout_seconds: int,
    *,
    process: subprocess.Popen[str] | None = None,
) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        exit_detail = _process_exit_detail(process)
        if exit_detail:
            raise RuntimeError(
                f"App process failed before becoming ready at {url}. {exit_detail}"
            )
        try:
            with urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return
        except URLError as exc:
            last_error = str(exc)
        time.sleep(1)
    exit_detail = _process_exit_detail(process)
    if exit_detail:
        raise RuntimeError(
            f"App process failed before becoming ready at {url}. {exit_detail}"
        )
    raise TimeoutError(f"App did not become ready at {url}: {last_error}")
