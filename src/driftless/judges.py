"""LLM-as-judge evaluation for free-form tasks (summarization / generation / QA).

A :class:`Judge` scores one output at a time against a rubric. The concrete
:class:`LLMJudge` dispatches to the same provider clients the patch generator
uses; the completion call is injectable so judges can be tested deterministically
(and so the regression harness never needs a network).

Putting a second model inside the trust loop is the whole reason judge work is
risky: the judge can be noisy, biased, or itself drift. So we keep it
*injectable* (deterministic stub for tests), normalize to a single 0..1 scale,
and offer a calibration/agreement check (:func:`judge_agreement`) so a team can
quantify how much to trust the judge before optimizing against it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .contract import JudgeSpec
from .errors import DriftlessError


@dataclass
class JudgeResult:
    """One judged record: the normalized 0..1 score, plus evidence."""

    score: float  # normalized to 0..1
    rationale: str = ""
    raw_score: float | None = None  # pre-normalization (on the rubric's scale)


class Judge(Protocol):
    """Implement this to plug in your own evaluator (or a deterministic stub)."""

    def score(self, *, input_text: str | None, output_text: str | None) -> JudgeResult:
        ...


_JUDGE_SYSTEM = (
    "You are a strict, consistent evaluator of AI outputs. You score a single "
    "output against a rubric and explain your score briefly. You are calibrated "
    "and deterministic: the same output always gets the same score. Respond with "
    "STRICT JSON only."
)


def _build_judge_prompt(
    spec: JudgeSpec, input_text: str | None, output_text: str | None
) -> str:
    scale = spec.scale_max
    return (
        f"RUBRIC:\n{spec.rubric}\n\n"
        f"INPUT (the task given to the model):\n{input_text or '(none provided)'}\n\n"
        f"OUTPUT (the model's response to score):\n{output_text or '(empty output)'}\n\n"
        f"Score the OUTPUT on a scale from 0 to {scale:g} per the rubric. "
        "Respond with JSON of the form:\n"
        f'{{"score": <number 0..{scale:g}>, "rationale": "<one or two sentences>"}}'
    )


class LLMJudge:
    """Score outputs with an LLM against a rubric. Implements :class:`Judge`."""

    def __init__(self, spec: JudgeSpec, *, complete_fn: Any | None = None) -> None:
        self.spec = spec
        if complete_fn is not None:
            self.complete_fn = complete_fn
            self.provider = spec.provider or "custom"
            self.model = spec.model or "custom"
        else:
            # Reuse the generator's provider dispatch (lazy: SDKs are optional).
            from .generators import (
                _DEFAULT_MODELS,
                _make_complete_fn,
                _resolve_provider,
            )

            self.provider = _resolve_provider(spec.provider)
            self.model = spec.model or _DEFAULT_MODELS[self.provider]
            self.complete_fn = _make_complete_fn(self.provider, self.model)

    def score(self, *, input_text: str | None, output_text: str | None) -> JudgeResult:
        from .generators import _extract_json

        prompt = _build_judge_prompt(self.spec, input_text, output_text)
        try:
            text = self.complete_fn(_JUDGE_SYSTEM, prompt, 0.0)
        except DriftlessError:
            raise
        except Exception as exc:  # a flaky judge call -> worst score + evidence
            return JudgeResult(0.0, f"judge call failed: {exc}", None)

        data = _extract_json(text)
        raw = data.get("score") if isinstance(data, dict) else None
        rationale = str(data.get("rationale", "")) if isinstance(data, dict) else ""
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            return JudgeResult(0.0, rationale or "judge returned no numeric score", None)
        norm = max(0.0, min(1.0, float(raw) / self.spec.scale_max))
        return JudgeResult(norm, rationale, float(raw))


def build_judge(spec: JudgeSpec, *, complete_fn: Any | None = None) -> Judge:
    """Factory for the configured judge (currently always the LLM judge)."""
    return LLMJudge(spec, complete_fn=complete_fn)


# --------------------------------------------------------------------------- #
# Judge reliability: agreement against a human-scored calibration set
# --------------------------------------------------------------------------- #
@dataclass
class JudgeAgreement:
    n: int
    mean_abs_error: float  # mean |judge - human| on the normalized 0..1 scale
    correlation: float | None  # Pearson r (None when undefined, e.g. no variance)

    @property
    def summary(self) -> str:
        r = f"{self.correlation:.2f}" if self.correlation is not None else "n/a"
        return (
            f"judge vs. human on {self.n} records: MAE={self.mean_abs_error:.3f}, "
            f"corr={r}"
        )


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return float(num / (dx * dy))


def judge_agreement(
    judge: Judge, spec: JudgeSpec, *, cwd: Path | None = None
) -> JudgeAgreement | None:
    """Measure judge<->human agreement on ``judge.calibration_path``.

    The calibration file is JSONL with, per record, the model ``input``/``output``
    text and a human ``score`` (on the rubric's ``scale_max``). Returns ``None``
    when no calibration set is configured, so callers can treat it as optional
    evidence rather than a hard gate.
    """
    if not spec.calibration_path:
        return None
    cwd = (cwd or Path.cwd()).resolve()
    path = (cwd / spec.calibration_path).resolve()
    if not path.is_file():
        raise DriftlessError(
            f"judge calibration file not found: {spec.calibration_path}"
        )

    human: list[float] = []
    model: list[float] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DriftlessError(
                f"calibration line {line_no} is not valid JSON"
            ) from exc
        if not isinstance(rec, dict) or "score" not in rec:
            raise DriftlessError(
                f"calibration line {line_no} is missing a human 'score'"
            )
        h = float(rec["score"]) / spec.scale_max
        res = judge.score(input_text=rec.get("input"), output_text=rec.get("output"))
        human.append(max(0.0, min(1.0, h)))
        model.append(res.score)

    if not human:
        return None
    mae = sum(abs(m - h) for m, h in zip(model, human)) / len(human)
    return JudgeAgreement(n=len(human), mean_abs_error=mae, correlation=_pearson(model, human))


def require_judge_agreement(
    judge: Judge, spec: JudgeSpec, *, cwd: Path | None = None
) -> JudgeAgreement | None:
    """Run ``judge_agreement`` and enforce optional ``max_mae`` / ``min_correlation`` gates."""
    agreement = judge_agreement(judge, spec, cwd=cwd)
    if spec.max_mae is None and spec.min_correlation is None:
        return agreement
    if agreement is None:
        raise DriftlessError(
            "judge agreement gate requires a non-empty calibration set",
            hint=f"add human-scored records to {spec.calibration_path}",
        )
    if spec.max_mae is not None and agreement.mean_abs_error > spec.max_mae:
        raise DriftlessError(
            f"judge mean absolute error {agreement.mean_abs_error:.3f} exceeds "
            f"max_mae={spec.max_mae:g}",
            hint=agreement.summary,
        )
    if spec.min_correlation is not None:
        if agreement.correlation is None:
            raise DriftlessError(
                f"judge correlation is undefined on {agreement.n} calibration records; "
                f"need min_correlation={spec.min_correlation:g}",
                hint=agreement.summary,
            )
        if agreement.correlation < spec.min_correlation:
            raise DriftlessError(
                f"judge correlation {agreement.correlation:.3f} below "
                f"min_correlation={spec.min_correlation:g}",
                hint=agreement.summary,
            )
    return agreement


def judge_evidence_samples(
    rows: list[Any], *, max_samples: int = 5
) -> list[dict[str, Any]]:
    """Lowest-scoring judge-graded rows with rationale for PR reports."""
    low = [r for r in rows if getattr(r, "is_low_score", False) and getattr(r, "rationale", None)]
    low.sort(key=lambda r: getattr(r, "score", 0.0) or 0.0)
    out: list[dict[str, Any]] = []
    for row in low[:max_samples]:
        out.append(
            {
                "index": row.index,
                "score": row.score,
                "rationale": row.rationale,
            }
        )
    return out
