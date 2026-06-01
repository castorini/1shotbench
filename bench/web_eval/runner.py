from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bench.config import ROOT_DIR, load_project_env
from bench.web_eval.features import load_features_file
from bench.web_eval.judge import JudgeClient, compute_correctness
from bench.web_eval.prd import load_prd_context
from bench.web_eval.profile import AppServer, resolve_app_profile
from bench.web_eval.report import write_artifacts
from bench.web_eval.schemas import BrowserAction, EvidencePacket, FeatureCheck, WebEvalSummary


EVALS_DIR = ROOT_DIR / "evals"
WEB_EVAL_DIR = Path(__file__).resolve().parent
BROWSER_SCRIPT = WEB_EVAL_DIR / "browser.mjs"


@dataclass
class WebEvalOptions:
    project_path: Path
    features_path: Path
    prd_path: Path | None = None
    base_url: str | None = None
    profile_path: Path | None = None
    label: str = "web-eval"
    eval_id: str | None = None
    no_start: bool = False
    dry_run: bool = False
    judge_model: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit(root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


class WebEvalRunner:
    def __init__(self, root_dir: Path = ROOT_DIR):
        self.root_dir = root_dir

    def preflight(self) -> list[str]:
        errors: list[str] = []
        if not BROWSER_SCRIPT.exists():
            errors.append(f"Missing browser script: {BROWSER_SCRIPT}")
        node_modules = WEB_EVAL_DIR / "node_modules"
        if not node_modules.exists():
            errors.append(
                "Playwright layer not installed. Run: "
                f"cd {WEB_EVAL_DIR} && npm install && npx playwright install chromium"
            )
        return errors

    def run(self, options: WebEvalOptions) -> WebEvalSummary:
        errors = self.preflight()
        if errors:
            raise RuntimeError("\n".join(errors))

        project_path = options.project_path.resolve()
        if not project_path.exists():
            raise FileNotFoundError(f"Project path not found: {project_path}")

        features, app_data = load_features_file(options.features_path.resolve())
        profile_path = options.profile_path
        profile_data = None
        if profile_path and profile_path.exists():
            import yaml

            raw = profile_path.read_text(encoding="utf-8")
            loaded = yaml.safe_load(raw)
            profile_data = loaded.get("app", loaded) if isinstance(loaded, dict) else None
        elif app_data:
            profile_data = app_data

        profile = resolve_app_profile(
            project_path,
            base_url=options.base_url,
            profile_data=profile_data,
            no_start=options.no_start,
        )

        eval_id = options.eval_id or _make_eval_id()
        output_dir = EVALS_DIR / eval_id
        output_dir.mkdir(parents=True, exist_ok=True)

        started_at = _now_iso()
        server = AppServer(profile, project_path)
        load_project_env()
        try:
            if not options.no_start and profile.start_command:
                server.start()
            prd_context = load_prd_context(options.prd_path)
            judge = JudgeClient(model=options.judge_model, dry_run=options.dry_run)
            evidence_by_feature: dict[str, EvidencePacket] = {}
            judgments = []
            for feature in features:
                evidence = self._collect_evidence(
                    feature=feature,
                    profile=profile,
                    output_dir=output_dir,
                )
                evidence_by_feature[feature.id] = evidence
                judgment = judge.judge_feature(feature, evidence, prd_context)
                judgments.append(judgment)

            passed, failed, uncertain, pct = compute_correctness(judgments)
            ended_at = _now_iso()
            summary = WebEvalSummary(
                eval_id=eval_id,
                label=options.label,
                started_at=started_at,
                ended_at=ended_at,
                project_path=str(project_path),
                features_path=str(options.features_path.resolve()),
                prd_path=str(options.prd_path) if options.prd_path else None,
                base_url=profile.base_url,
                total_features=len(features),
                passed=passed,
                failed=failed,
                uncertain=uncertain,
                correctness_pct=pct,
                judgments=judgments,
                git_commit=_git_commit(self.root_dir),
                judge_model=None if options.dry_run else judge.model,
                notes=None,
            )
            write_artifacts(output_dir, summary=summary, evidence_by_feature=evidence_by_feature, judgments=judgments)
            metadata = {
                "options": {
                    "project_path": str(project_path),
                    "features_path": str(options.features_path),
                    "prd_path": str(options.prd_path) if options.prd_path else None,
                    "base_url": profile.base_url,
                    "no_start": options.no_start,
                    "dry_run": options.dry_run,
                },
                "app_profile": profile.to_dict(),
            }
            (output_dir / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            return summary
        finally:
            server.stop()

    def _collect_evidence(
        self,
        *,
        feature: FeatureCheck,
        profile,
        output_dir: Path,
    ) -> EvidencePacket:
        job = {
            "featureId": feature.id,
            "baseURL": profile.base_url,
            "outputDir": str(output_dir),
            "steps": [_step_to_json(step) for step in feature.steps],
        }
        jobs_dir = output_dir / "jobs"
        jobs_dir.mkdir(exist_ok=True)
        job_path = jobs_dir / f"{feature.id}.json"
        evidence_path = output_dir / "evidence" / f"{feature.id}.browser.json"
        evidence_path.parent.mkdir(exist_ok=True)
        job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

        env = load_project_env()
        proc = subprocess.run(
            ["node", str(BROWSER_SCRIPT), "--job", str(job_path), "--output", str(evidence_path)],
            cwd=str(WEB_EVAL_DIR),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if evidence_path.exists():
            raw = json.loads(evidence_path.read_text(encoding="utf-8"))
            return _evidence_from_raw(raw)
        return EvidencePacket(
            feature_id=feature.id,
            error=(proc.stderr or proc.stdout or "browser layer failed").strip(),
        )


def _step_to_json(step: BrowserAction) -> dict:
    return {"action": step.action, **step.params}


def _evidence_from_raw(raw: dict) -> EvidencePacket:
    return EvidencePacket(
        feature_id=str(raw.get("feature_id", "")),
        url=raw.get("url"),
        page_title=raw.get("page_title"),
        visible_text=raw.get("visible_text"),
        aria_snapshot=raw.get("aria_snapshot"),
        screenshot_path=raw.get("screenshot_path"),
        console_errors=list(raw.get("console_errors") or []),
        network_errors=list(raw.get("network_errors") or []),
        action_log=list(raw.get("action_log") or []),
        checks=dict(raw.get("checks") or {}),
        error=raw.get("error"),
    )


def _make_eval_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"
