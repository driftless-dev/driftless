"""LLM-backed patch generation.

This is a concrete :class:`~driftless.engine.PatchGenerator` that asks an LLM
to repair the editable files (prompt, format instructions, few-shot examples,
config) so the target model recovers the behavior the failure clusters describe.

It is provider-neutral: it dispatches to OpenAI or Anthropic based on the
available API key, and the completion call is injectable so it can be tested
without network access. Edit-scope is still enforced by the engine -- the LLM
can only ever touch files listed in ``files.editable``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from .contract import RepairSpec
from .engine import Patch, PatchContext, PatchGenerator, cluster_trajectories
from .errors import DriftlessError

CompleteFn = Callable[[str, str, float], str]

_SYSTEM_PROMPT = (
    "You are an expert at migrating production LLM workflows from one model to "
    "another. You repair prompts and configuration so the NEW model reproduces "
    "the previous model's behavior on a structured-output task.\n"
    "Rules:\n"
    "- You may ONLY edit the files provided to you.\n"
    "- Preserve the output schema, label taxonomy, and business rules.\n"
    "- Make focused, minimal changes that address the observed failure clusters.\n"
    "- Do not bloat the prompt; prefer precise instructions and targeted few-shot examples.\n"
    "- Respond with STRICT JSON only, no prose outside the JSON."
)

_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-20241022",
}


# --------------------------------------------------------------------------- #
# Provider dispatch (lazy imports so SDKs are optional)
# --------------------------------------------------------------------------- #
def _resolve_provider(provider: str | None) -> str:
    if provider:
        return provider
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    raise DriftlessError(
        "no LLM provider API key found for patch generation",
        hint="set OPENAI_API_KEY or ANTHROPIC_API_KEY, or pass --generator none",
    )


def _make_complete_fn(provider: str, model: str) -> CompleteFn:
    if provider == "openai":
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - import guard
            raise DriftlessError(
                "the openai package is required for --generator llm with OpenAI",
                hint="pip install 'driftless[llm]'",
            ) from exc
        client = OpenAI()

        def complete(system: str, user: str, temperature: float) -> str:
            resp = client.chat.completions.create(
                model=model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content or ""

        return complete

    if provider == "anthropic":
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - import guard
            raise DriftlessError(
                "the anthropic package is required for --generator llm with Anthropic",
                hint="pip install 'driftless[llm]'",
            ) from exc
        client = anthropic.Anthropic()

        def complete(system: str, user: str, temperature: float) -> str:
            resp = client.messages.create(
                model=model,
                max_tokens=4096,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(block.text for block in resp.content if block.type == "text")

        return complete

    raise DriftlessError(f"unknown provider: {provider!r}")


# --------------------------------------------------------------------------- #
# Prompt construction + response parsing
# --------------------------------------------------------------------------- #
# Default char budget for the evidence portion of the prompt (~6k tokens at
# ~4 chars/token). Editable file contents are never trimmed -- the model must
# return their full new content -- so only the evidence sections are budgeted.
DEFAULT_MAX_PROMPT_CHARS = 24000


def _truncate(text: str | None, limit: int = 600) -> str | None:
    """Keep prompts bounded: clip very long inputs/outputs with an ellipsis."""
    if text is None:
        return None
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [+{len(text) - limit} chars]"


def _failing_examples(
    context: PatchContext, limit: int = 12, *, value_chars: int = 600
) -> list[dict]:
    """Failing rows with their *real* input and raw model output.

    Showing the actual data (not just gold/pred labels) lets the optimizer see
    why a row failed -- malformed JSON, a borderline phrasing, a refusal -- and
    target the edit accordingly.
    """
    out = []
    for row in context.rows:
        if row.is_schema_error:
            kind = "schema_error"
        elif row.is_refusal:
            kind = "refusal"
        elif row.field_errors:
            kind = "field_error"
        elif row.is_low_score:
            kind = "low_score"
        elif row.is_correct is False:
            kind = "misclassification" if row.gold is not None else "failed_check"
        else:
            continue
        out.append(
            {
                "index": row.index,
                "type": kind,
                "input": _truncate(row.input_text, value_chars),
                "raw_output": _truncate(row.raw, value_chars),
                "gold": row.gold,
                "predicted": row.predicted,
                "score": row.score,
                # Extraction: which fields were wrong. Judge: why it scored low.
                "wrong_fields": row.field_errors or None,
                "judge_rationale": _truncate(row.rationale, 240),
            }
        )
        if len(out) >= limit:
            break
    return out


def _positive_exemplars(
    context: PatchContext, *, per_class: int = 2, total_limit: int = 8, value_chars: int = 600
) -> list[dict]:
    """Correctly-handled rows, balanced across gold classes.

    These show the optimizer what *good* looks like so its edits preserve
    working behavior instead of regressing rows that already pass.
    """
    by_class: dict[Any, list[dict]] = {}
    for row in context.rows:
        # A "good" row: a correct classification, or (in score/pass grading) a
        # row that graded well (passed / scored at-or-above the run mean).
        is_good = row.is_correct is True or (
            row.score is not None and not row.is_low_score and row.is_correct is not False
        )
        if not is_good:
            continue
        bucket = by_class.setdefault(row.gold, [])
        if len(bucket) >= per_class:
            continue
        bucket.append(
            {
                "input": _truncate(row.input_text, value_chars),
                "raw_output": _truncate(row.raw, value_chars),
                "label": row.gold,
                "score": row.score,
            }
        )
    out: list[dict] = []
    for bucket in by_class.values():
        out.extend(bucket)
        if len(out) >= total_limit:
            break
    return out[:total_limit]


def _attempt_history(context: PatchContext, limit: int = 12) -> list[dict]:
    """Compact log of prior edits and how they scored, to avoid repetition."""
    log = context.experiment_log[-limit:]
    return [
        {
            "iteration": a.iteration,
            "rationale": _truncate(a.rationale, 200),
            "files": a.files,
            "primary": round(a.primary, 4),
            "schema_error_rate": a.schema_error_rate,
            "accepted": a.accepted,
            "passed": a.passed_tuning,
        }
        for a in log
    ]


def _metric_summary(context: PatchContext) -> dict:
    def m(metrics):
        return {
            "f1": metrics.f1,
            "precision": metrics.precision,
            "score": metrics.score,
            "schema_error_rate": metrics.schema_error_rate,
            "refusal_rate": metrics.refusal_rate,
        }

    return {"baseline": m(context.baseline), "current_target": m(context.current)}


def _context_vars(context: PatchContext) -> dict[str, str]:
    """String-valued placeholders available to a custom ``user_template``."""
    return {
        "workflow": context.workflow_name,
        "description": context.workflow.description,
        "target_model": context.target_model,
        "iteration": str(context.iteration),
        "metrics": json.dumps(_metric_summary(context), default=str),
        "failure_clusters": json.dumps(
            [{"kind": c.kind, "key": c.key, "count": c.count} for c in context.clusters],
            default=str,
        ),
        "failing_examples": json.dumps(_failing_examples(context), default=str),
        "correct_examples": json.dumps(_positive_exemplars(context), default=str),
        "attempt_history": json.dumps(_attempt_history(context), default=str),
        "cluster_trajectory": json.dumps(
            cluster_trajectories(context.cluster_history), default=str
        ),
        "readonly_context_files": json.dumps(context.context_files, default=str),
        "editable_files": json.dumps(context.editable_files, default=str),
    }


_DEFAULT_USER_INSTRUCTIONS = (
    "Below is the current state of a model migration. The target model is "
    "underperforming. Revise one or more of the editable files to fix the "
    "failure clusters while preserving the output contract.\n\n"
    "Respond with JSON of the form:\n"
    '{"rationale": "<why these edits help>", '
    '"files": {"<editable path>": "<full new file content>"}}\n'
    "Only include files you actually changed. Return the FULL new content for each.\n"
    "`readonly_context_files` (e.g. the output parser / pre/post-processing) are "
    "shown for REFERENCE ONLY -- never edit or return them.\n\n"
    "MIGRATION STATE:\n"
)


# Progressive trimming levels: (failing, correct, history, value_chars). Earlier
# levels are richer; we fall back to leaner ones only when the budget is tight.
_BUDGET_LEVELS = [
    (12, 8, 12, 600),
    (8, 6, 8, 400),
    (5, 4, 6, 240),
    (3, 2, 4, 120),
]


def _evidence_payload(
    context: PatchContext, failing: int, correct: int, history: int, value_chars: int
) -> dict:
    return {
        "workflow": context.workflow_name,
        "description": context.workflow.description,
        "target_model": context.target_model,
        "iteration": context.iteration,
        "metrics": _metric_summary(context),
        "failure_clusters": [
            {"kind": c.kind, "key": c.key, "count": c.count} for c in context.clusters
        ],
        "failing_examples": _failing_examples(context, failing, value_chars=value_chars),
        "correct_examples": _positive_exemplars(
            context, total_limit=correct, value_chars=value_chars
        ),
        "attempt_history": _attempt_history(context, history),
        "cluster_trajectory": cluster_trajectories(context.cluster_history),
        "readonly_context_files": {
            path: _truncate(content, value_chars * 2)
            for path, content in context.context_files.items()
        },
    }


def build_user_prompt(
    context: PatchContext, *, max_chars: int = DEFAULT_MAX_PROMPT_CHARS
) -> str:
    """Build the prompt, shrinking evidence to fit ``max_chars``.

    Editable file contents are essential (the model returns their full new
    content), so they are never trimmed; only the evidence sections shrink.
    """
    text = ""
    for failing, correct, history, value_chars in _BUDGET_LEVELS:
        payload = _evidence_payload(context, failing, correct, history, value_chars)
        payload["editable_files"] = context.editable_files
        text = _DEFAULT_USER_INSTRUCTIONS + json.dumps(payload, indent=2, default=str)
        if len(text) <= max_chars:
            return text
    return text  # leanest level; editable files alone may exceed the budget


def _substitute(template: str, variables: dict[str, str]) -> str:
    """Replace ``{{key}}`` placeholders; unknown placeholders are left intact."""
    def repl(match: re.Match) -> str:
        key = match.group(1).strip()
        return variables.get(key, match.group(0))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", repl, template)


def _read_relative(path_str: str, cwd: Path) -> str:
    path = (cwd / path_str).resolve()
    if not path.is_file():
        raise DriftlessError(f"repair prompt file not found: {path_str}")
    return path.read_text(encoding="utf-8")


def resolve_system_prompt(repair: RepairSpec, cwd: Path) -> str:
    if repair.system_prompt is not None:
        base = repair.system_prompt
    elif repair.system_prompt_path:
        base = _read_relative(repair.system_prompt_path, cwd)
    else:
        base = _SYSTEM_PROMPT
    if repair.guidance:
        base = f"{base}\n\nAdditional domain guidance:\n{repair.guidance}"
    return base


def resolve_user_prompt(context: PatchContext, repair: RepairSpec) -> str:
    template = repair.user_template
    if template is None and repair.user_template_path:
        template = _read_relative(repair.user_template_path, context.cwd)
    if template is None:
        return build_user_prompt(context)
    return _substitute(template, _context_vars(context))


def parse_patch(text: str, editable: set[str]) -> Patch | None:
    """Parse an LLM JSON response into a scoped :class:`Patch`."""
    data = _extract_json(text)
    if not isinstance(data, dict):
        return None
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        return None
    scoped = {
        path: content
        for path, content in files.items()
        if path in editable and isinstance(content, str)
    }
    if not scoped:
        return None
    return Patch(files=scoped, rationale=str(data.get("rationale", "")), kind="llm")


def _extract_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Tolerate code fences or surrounding prose: grab the outermost object.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


# --------------------------------------------------------------------------- #
# The generator
# --------------------------------------------------------------------------- #
class LLMPatchGenerator:
    """Ask an LLM to repair editable files. Implements ``PatchGenerator``."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        num_candidates: int = 1,
        complete_fn: CompleteFn | None = None,
    ) -> None:
        self.num_candidates = max(1, num_candidates)
        if complete_fn is not None:
            self.complete_fn = complete_fn
            self.provider = provider or "custom"
            self.model = model or "custom"
        else:
            self.provider = _resolve_provider(provider)
            self.model = model or _DEFAULT_MODELS[self.provider]
            self.complete_fn = _make_complete_fn(self.provider, self.model)

    def generate(self, context: PatchContext) -> list[Patch]:
        editable = set(context.editable_files)
        if not editable:
            return []
        repair = context.workflow.repair
        system = resolve_system_prompt(repair, context.cwd)
        user = resolve_user_prompt(context, repair)
        patches: list[Patch] = []
        for i in range(self.num_candidates):
            # Vary temperature across candidates to diversify proposals.
            temperature = 0.2 + 0.3 * i
            try:
                text = self.complete_fn(system, user, temperature)
            except DriftlessError:
                raise
            except Exception:
                continue  # a flaky completion shouldn't abort the whole loop
            patch = parse_patch(text, editable)
            if patch is not None:
                patches.append(patch)
        return patches


def build_generator(
    kind: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    num_candidates: int = 1,
) -> PatchGenerator | None:
    """Factory used by the CLI. Returns ``None`` for the no-op generator."""
    if kind == "none":
        return None
    if kind == "llm":
        return LLMPatchGenerator(
            provider=provider, model=model, num_candidates=num_candidates
        )
    raise DriftlessError(f"unknown generator: {kind!r}", hint="choose 'llm' or 'none'")
