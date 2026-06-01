from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bench.config import ROOT_DIR
from bench.web_eval.runner import WebEvalRunner, WebEvalOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pi-Bench web app feature evaluation (Playwright evidence + LLM judge)"
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Path to agent-generated app workspace (e.g. anserini-evaluator/gpt-workspace)",
    )
    parser.add_argument(
        "--features",
        required=True,
        help="YAML/JSON feature checks (e.g. anserini-evaluator/features.yaml)",
    )
    parser.add_argument("--prd", help="Optional PRD markdown for judge context")
    parser.add_argument("--profile", help="Optional eval-profile.yaml (overrides features `app` block)")
    parser.add_argument("--base-url", help="App URL when the server is already running")
    parser.add_argument("--no-start", action="store_true", help="Do not start the app; use --base-url or running server")
    parser.add_argument("--label", default="web-eval", help="Label for this evaluation run")
    parser.add_argument("--eval-id", help="Override output directory name under evals/")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip LLM judge only; still starts the app (unless --no-start) and runs Playwright",
    )
    parser.add_argument("--judge-model", help="Override judge model (default: WEB_EVAL_JUDGE_MODEL or gpt-4o-mini)")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    project = Path(args.project)
    if not project.is_absolute():
        project = ROOT_DIR / project

    features = Path(args.features)
    if not features.is_absolute():
        features = ROOT_DIR / features

    prd = Path(args.prd) if args.prd else None
    if prd and not prd.is_absolute():
        prd = ROOT_DIR / prd

    profile = Path(args.profile) if args.profile else None
    if profile and not profile.is_absolute():
        profile = ROOT_DIR / profile

    runner = WebEvalRunner()
    options = WebEvalOptions(
        project_path=project,
        features_path=features,
        prd_path=prd,
        base_url=args.base_url,
        profile_path=profile,
        label=args.label,
        eval_id=args.eval_id,
        no_start=args.no_start,
        dry_run=args.dry_run,
        judge_model=args.judge_model,
    )

    try:
        summary = runner.run(options)
    except Exception as exc:
        print(f"web-eval failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary.to_dict(), indent=2))
    print(f"\nArtifacts written to: {ROOT_DIR / 'evals' / summary.eval_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
