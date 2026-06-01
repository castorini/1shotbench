from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from bench.config import load_project_env
from bench.web_eval.schemas import EvidencePacket, FeatureCheck, FeatureJudgment, FeatureVerdict


JUDGE_SYSTEM = """You are a strict functional evaluator for web applications.
Judge whether the feature requirement is satisfied based ONLY on the evidence packet.
Different UI layouts are valid if behavior matches the acceptance criteria.
Return JSON only with keys: verdict, confidence, reason, evidence_used.
verdict must be one of: pass, fail, uncertain.
confidence is a float from 0 to 1.
reason is one short sentence.
evidence_used is a list of short strings naming evidence fields you relied on.
If evidence is insufficient, use uncertain."""


class JudgeClient:
    def __init__(
        self,
        *,
        model: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
        dry_run: bool = False,
    ):
        env = load_project_env()
        self.model = model or env.get("WEB_EVAL_JUDGE_MODEL") or env.get("OPENAI_MODEL") or "gpt-4o-mini"
        self.api_base = (api_base or env.get("WEB_EVAL_JUDGE_API_BASE") or env.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or env.get("WEB_EVAL_JUDGE_API_KEY") or env.get("OPENAI_API_KEY")
        self.dry_run = dry_run

    def judge_feature(
        self,
        feature: FeatureCheck,
        evidence: EvidencePacket,
        prd_context: str | None,
    ) -> FeatureJudgment:
        if evidence.error and not evidence.visible_text and not evidence.aria_snapshot:
            return FeatureJudgment(
                feature_id=feature.id,
                verdict="uncertain",
                confidence=0.2,
                reason=f"Browser evidence collection failed: {evidence.error}",
                evidence_used=["error"],
            )
        if self.dry_run:
            verdict: FeatureVerdict = "pass" if not evidence.error else "uncertain"
            return FeatureJudgment(
                feature_id=feature.id,
                verdict=verdict,
                confidence=0.5,
                reason="Dry-run mode: skipped LLM judge.",
                evidence_used=["dry_run"],
            )
        if not self.api_key:
            raise RuntimeError(
                "Judge API key missing. Set OPENAI_API_KEY or WEB_EVAL_JUDGE_API_KEY, or pass --dry-run."
            )
        payload = {
            "feature": feature.to_dict(),
            "evidence": evidence.compact_dict(),
            "prd_context": prd_context,
        }
        user_prompt = (
            "Evaluate this feature against the evidence.\n\n"
            f"{json.dumps(payload, indent=2)}"
        )
        raw = self._chat(user_prompt)
        parsed = _parse_judge_json(raw)
        return FeatureJudgment(
            feature_id=feature.id,
            verdict=parsed["verdict"],
            confidence=float(parsed.get("confidence", 0.5)),
            reason=str(parsed.get("reason", "")),
            evidence_used=[str(x) for x in parsed.get("evidence_used", [])],
            raw_response=raw,
        )

    def _chat(self, user_prompt: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        }
        request = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Judge API error ({exc.code}): {detail}") from exc
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Judge API returned no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            raise RuntimeError("Judge API returned empty content.")
        return str(content)


def _parse_judge_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    verdict = str(parsed.get("verdict", "uncertain")).lower()
    if verdict not in {"pass", "fail", "uncertain"}:
        verdict = "uncertain"
    parsed["verdict"] = verdict
    return parsed


def compute_correctness(judgments: list[FeatureJudgment]) -> tuple[int, int, int, float]:
    total = len(judgments)
    passed = sum(1 for j in judgments if j.verdict == "pass")
    failed = sum(1 for j in judgments if j.verdict == "fail")
    uncertain = sum(1 for j in judgments if j.verdict == "uncertain")
    pct = (passed / total * 100.0) if total else 0.0
    return passed, failed, uncertain, pct
