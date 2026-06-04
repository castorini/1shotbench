from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bench.config import ROOT_DIR, discover_shared_task_files, list_projects, load_workspace_configs, project_runs_dir, resolve_project_dir
from bench.runner import BenchmarkRunner, RunnerOptions


app = FastAPI(title="Pi Agent Bench")
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "bench" / "static")), name="static")

event_queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
active_runs: dict[str, dict[str, Any]] = {}


class StartRunRequest(BaseModel):
    project: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    models: list[str] = Field(min_length=1)
    mode: str = "parallel"
    max_concurrency: int = 2
    timeout_seconds: int = 1800
    retries: int = 0
    label: str = "benchmark"
    warmup: bool = False


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT_DIR / "bench" / "static" / "index.html")


def _runner_for_project(project: str) -> tuple[Path, BenchmarkRunner]:
    project_dir = resolve_project_dir(project)
    workspaces = load_workspace_configs(project_dir)
    return project_dir, BenchmarkRunner(ROOT_DIR, workspaces, project_dir=project_dir)


def _find_run_dir(run_id: str) -> tuple[str, Path] | None:
    for project in list_projects():
        run_dir = project_runs_dir(project["path"]) / run_id
        if run_dir.exists():
            return project["key"], run_dir
    return None


def _load_run_summary(run_dir: Path) -> dict[str, Any] | None:
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))

    run_path = run_dir / "run.json"
    if not run_path.exists():
        return None

    metadata = json.loads(run_path.read_text(encoding="utf-8"))
    results = []
    for child in sorted(path for path in run_dir.iterdir() if path.is_dir() and path.name != "screenshots"):
        result_path = child / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        results.append(
            {
                "model_key": child.name,
                "status": result.get("status", "imported"),
                "duration_ms": result.get("duration_ms"),
                "stdout_path": str(child / "stdout.log"),
                "stderr_path": str(child / "stderr.log"),
                "metrics": result.get("metrics", {}),
            }
        )
    return {
        "run_id": metadata.get("run_id", run_dir.name),
        "label": metadata.get("label", run_dir.name),
        "started_at": metadata.get("started_at"),
        "duration_ms": metadata.get("duration_ms"),
        "mode": metadata.get("mode", "imported"),
        "results": results,
    }


@app.get("/api/projects")
async def projects() -> list[dict[str, Any]]:
    return list_projects()


@app.get("/api/projects/{project}/models")
async def models(project: str) -> list[dict[str, Any]]:
    _, runner = _runner_for_project(project)
    return [
        {
            "key": cfg.key,
            "name": cfg.name,
            "model": cfg.model,
            "provider": cfg.provider,
            "thinking": cfg.thinking,
            "tools": cfg.tools,
            "path": cfg.path,
        }
        for cfg in runner.workspaces.values()
    ]


@app.get("/api/projects/{project}/task-files")
async def task_files(project: str) -> list[dict[str, Any]]:
    return [
        {
            "name": path.name,
            "path": str(path),
            "size": path.stat().st_size,
        }
        for path in discover_shared_task_files(resolve_project_dir(project))
    ]


@app.post("/api/runs")
async def start_run(req: StartRunRequest) -> dict[str, Any]:
    project_dir, runner = _runner_for_project(req.project)
    errors = runner.preflight(req.models)
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    options = RunnerOptions(
        prompt=req.prompt,
        selected_models=req.models,
        mode=req.mode,
        max_concurrency=req.max_concurrency,
        timeout_seconds=req.timeout_seconds,
        retries=req.retries,
        label=req.label,
        warmup=req.warmup,
    )

    run_id = f"run-{len(active_runs) + 1}-{asyncio.get_running_loop().time():.0f}"
    active_runs[run_id] = {"status": "running", "summary": None, "project": project_dir.name}

    options.run_id = run_id

    async def execute() -> None:
        try:
            summary = await runner.run(options=options, event_callback=emit_event)
            active_runs[run_id] = {"status": "completed", "summary": summary.to_dict()}
            for queue in event_queues[run_id]:
                await queue.put({"type": "run_complete", "summary": summary.to_dict()})
        except Exception as exc:  # keep background task failures visible
            active_runs[run_id] = {"status": "failed", "summary": None, "error": str(exc)}
            for queue in event_queues[run_id]:
                await queue.put({"type": "run_failed", "error": str(exc)})

    async def emit_event(event: dict[str, Any]) -> None:
        for queue in event_queues[run_id]:
            await queue.put(event)

    asyncio.create_task(execute())
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = active_runs.get(run_id)
    if run:
        return run
    found = _find_run_dir(run_id)
    if found:
        project_key, run_dir = found
        summary = _load_run_summary(run_dir)
        if summary:
            return {"status": "completed", "summary": summary, "project": project_key}
    raise HTTPException(status_code=404, detail="Run not found")


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    event_queues[run_id].append(queue)

    async def stream():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "run_complete":
                    break
        finally:
            if queue in event_queues[run_id]:
                event_queues[run_id].remove(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/projects/{project}/history")
async def history(project: str) -> list[dict[str, Any]]:
    runs_dir = project_runs_dir(project)
    if not runs_dir.exists():
        return []
    items = []
    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        summary = _load_run_summary(run_dir)
        if not summary:
            continue
        items.append(
            {
                "run_id": summary.get("run_id"),
                "project": project,
                "label": summary.get("label"),
                "started_at": summary.get("started_at"),
                "duration_ms": summary.get("duration_ms"),
                "mode": summary.get("mode"),
            }
        )
    return items[:50]


@app.get("/api/runs/{run_id}/details")
async def run_details(run_id: str) -> dict[str, Any]:
    found = _find_run_dir(run_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Run not found")
    project_key, run_dir = found
    summary = _load_run_summary(run_dir)
    if not summary:
        raise HTTPException(status_code=404, detail="Run not found")
    prompt_path = run_dir / "prompt.txt"
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    outputs: dict[str, dict[str, str]] = {}
    for result in summary.get("results", []):
        model_key = result.get("model_key")
        if not model_key:
            continue
        stdout_path = Path(result.get("stdout_path", ""))
        stderr_path = Path(result.get("stderr_path", ""))
        outputs[model_key] = {
            "stdout": stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else "",
            "stderr": stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else "",
        }
    return {"summary": summary, "prompt": prompt, "outputs": outputs, "project": project_key}
