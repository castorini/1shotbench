from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bench.web_eval.features import load_features
from bench.web_eval.judge import JudgeClient, compute_correctness, _parse_judge_json
from bench.web_eval.prd import load_prd_context
from bench.web_eval.report import render_markdown
from bench.web_eval.schemas import EvidencePacket, FeatureCheck, FeatureJudgment, WebEvalSummary


class WebEvalSchemaTests(unittest.TestCase):
    def test_load_features_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "features.json"
            path.write_text(
                json.dumps(
                    {
                        "features": [
                            {
                                "id": "f1",
                                "title": "Feature 1",
                                "steps": [{"action": "open", "path": "/"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            features = load_features(path)
            self.assertEqual(len(features), 1)
            self.assertEqual(features[0].id, "f1")
            self.assertEqual(features[0].steps[0].action, "open")

    def test_compute_correctness(self) -> None:
        judgments = [
            FeatureJudgment("a", "pass", 0.9, "ok"),
            FeatureJudgment("b", "fail", 0.8, "no"),
            FeatureJudgment("c", "uncertain", 0.4, "maybe"),
        ]
        passed, failed, uncertain, pct = compute_correctness(judgments)
        self.assertEqual((passed, failed, uncertain), (1, 1, 1))
        self.assertAlmostEqual(pct, 33.333, places=2)

    def test_parse_judge_json(self) -> None:
        parsed = _parse_judge_json(
            '{"verdict":"pass","confidence":0.95,"reason":"works","evidence_used":["visible_text"]}'
        )
        self.assertEqual(parsed["verdict"], "pass")

    def test_dry_run_judge(self) -> None:
        judge = JudgeClient(dry_run=True)
        feature = FeatureCheck("f1", "Title", "desc", "accept")
        evidence = EvidencePacket(feature_id="f1", visible_text="hello")
        result = judge.judge_feature(feature, evidence, None)
        self.assertEqual(result.verdict, "pass")

    def test_prd_context_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prd = Path(tmp) / "PRD.md"
            prd.write_text(
                "## Goals\n- Goal one\n\n## Success Criteria\n- Users can search\n",
                encoding="utf-8",
            )
            context = load_prd_context(prd)
            self.assertIn("Success Criteria", context or "")
            self.assertIn("search", context or "")

    def test_report_render(self) -> None:
        summary = WebEvalSummary(
            eval_id="test-id",
            label="test",
            started_at="t0",
            ended_at="t1",
            project_path="/tmp/project",
            features_path="/tmp/features.yaml",
            prd_path=None,
            base_url="http://127.0.0.1:3000",
            total_features=1,
            passed=1,
            failed=0,
            uncertain=0,
            correctness_pct=100.0,
            judgments=[FeatureJudgment("f1", "pass", 1.0, "ok")],
        )
        md = render_markdown(summary, Path("/tmp/evals/test-id"))
        self.assertIn("100.0%", md)
        self.assertIn("f1", md)


if __name__ == "__main__":
    unittest.main()
