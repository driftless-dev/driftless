"""The workflow contract: the spine of driftless.

A contract (``driftless.yml``) declares one or more model-dependent
workflows. For each workflow it describes:

* how to run the real workflow (``run``)
* how to override which model is used (``model``)
* which files the migration engine may edit (``files``)
* how to evaluate outputs (``eval``)
* what thresholds must hold after migration (``thresholds``)
* what the migration engine is allowed to do (``migration``)

Everything downstream (compare / migrate / validate / report) reads from this
typed structure rather than poking at raw YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .errors import ContractError, WorkflowNotFoundError

CONTRACT_FILENAMES = ("driftless.yml", "driftless.yaml")


def _coerce_fraction(value: Any) -> float:
    """Accept ``0.7``, ``70`` (treated as percent), or ``"70%"`` -> ``0.7``."""
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        value = float(text)
    if isinstance(value, (int, float)):
        # Values > 1 are interpreted as percentages for ergonomics.
        return float(value) / 100.0 if value > 1 else float(value)
    raise ValueError(f"cannot interpret {value!r} as a fraction")


class StrictModel(BaseModel):
    """Reject unknown keys so typos surface as errors, not silent no-ops."""

    model_config = ConfigDict(extra="forbid")


class RunSpec(StrictModel):
    """How to execute the real workflow."""

    command: str | None = None
    # An HTTP endpoint that classifies/grades one input record per POST. The
    # harness sends each input record as JSON (with the model injected under
    # ``model_param``) and writes each JSON response as an output record.
    endpoint: str | None = None
    input_path: str
    output_path: str
    # For endpoints: the request-body key the model id is injected under
    # (default ``"model"``). For commands: an optional CLI/arg hint (unused by
    # the shell runner, which uses ``{{ model }}`` substitution / env_var).
    model_param: str | None = None
    timeout_seconds: int = 1800

    @field_validator("command", "endpoint")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("must not be blank")
        return v

    @model_validator(mode="after")
    def _one_runner(self) -> "RunSpec":
        if not self.command and not self.endpoint:
            raise ValueError("run requires either 'command' or 'endpoint'")
        if self.command and self.endpoint:
            raise ValueError("set only one of run.command or run.endpoint")
        return self


class ModelSpec(StrictModel):
    """Which model is used and how to override it."""

    provider: str | None = None
    current: str
    target_candidates: list[str] = Field(default_factory=list)

    # Override mechanisms (at least one required).
    env_var: str | None = None
    config_file: str | None = None
    config_path: str | None = None

    # The workflow routes models provider-agnostically (e.g. via LiteLLM /
    # OpenRouter / a gateway), so a cross-provider target is safe. When unset,
    # preflight falls back to static portability detection.
    portable: bool = False

    @field_validator("current")
    @classmethod
    def _current_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model.current must not be blank")
        return v

    def has_override(self) -> bool:
        return bool(self.env_var or (self.config_file and self.config_path))


class FilesSpec(StrictModel):
    """Edit scope. The migration engine may only touch ``editable`` files."""

    editable: list[str] = Field(default_factory=list)
    readonly: list[str] = Field(default_factory=list)
    # Read-only files whose contents are shown to the optimizer for *context*
    # (e.g. the output parser or pre/post-processing code). Never edited; they
    # help the optimizer reason about how outputs are produced and graded.
    context: list[str] = Field(default_factory=list)


class SplitSpec(StrictModel):
    tuning: float = 0.7
    holdout: float = 0.3

    _coerce = field_validator("tuning", "holdout", mode="before")(_coerce_fraction)


class JudgeSpec(StrictModel):
    """LLM-as-judge grading for free-form tasks (summarization / generation / QA).

    A second model scores each output against ``rubric`` on a 0..``scale_max``
    scale; driftless normalizes to 0..1, aggregates the mean as ``score``, and
    gates it with ``thresholds.min_score`` -- exactly like customer-supplied
    score mode, but we run the judge. Because this puts a fuzzy model inside the
    trust loop, ``calibration_path`` (records with a human ``score``) lets the
    run report judge<->human agreement, and the judge is injectable for
    deterministic tests.
    """

    rubric: str
    provider: str | None = None
    model: str | None = None
    # Raw scale the judge scores on (e.g. 5 for a 1..5 rubric). Normalized to 0..1.
    scale_max: float = 1.0
    # Optional: a row "passes" at or above this normalized score (0..1).
    pass_threshold: float | None = None
    # Optional: which input/output fields to show the judge. Default: the whole
    # input line and the raw output text (free-form outputs need not be JSON).
    input_field: str | None = None
    output_field: str | None = None
    # Optional path to human-scored records (carrying a numeric ``score``) for a
    # judge-reliability agreement check.
    calibration_path: str | None = None
    # Optional gates (require ``calibration_path``). When set, ``migrate`` /
    # ``compare`` / ``refine`` refuse to optimize against an untrusted judge.
    max_mae: float | None = None
    min_correlation: float | None = None

    @model_validator(mode="after")
    def _gates_need_calibration(self) -> "JudgeSpec":
        if (self.max_mae is not None or self.min_correlation is not None) and not self.calibration_path:
            raise ValueError(
                "eval.judge.max_mae/min_correlation require calibration_path"
            )
        return self

    @field_validator("rubric")
    @classmethod
    def _rubric_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("eval.judge.rubric must not be blank")
        return v

    @field_validator("scale_max")
    @classmethod
    def _scale_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("eval.judge.scale_max must be > 0")
        return v


class DataSourceSpec(StrictModel):
    """Where an *external* eval dataset lives + how to refresh it locally.

    For the in-repo case git is the change detector and this is unset. When the
    eval set lives outside the repo (object storage, a labeling tool, a
    warehouse), a scheduled ``poll`` refreshes the local files before
    fingerprinting: run ``command`` (your script writes the dataset -- the general
    escape hatch), and/or GET ``inputs_url`` / ``labels_url`` into the contract's
    ``run.input_path`` / ``eval.labels_path``. ``DRIFTLESS_DATASOURCE_TOKEN``
    adds an ``Authorization: Bearer`` header to the URL fetches.
    """

    command: str | None = None
    inputs_url: str | None = None
    labels_url: str | None = None
    timeout_seconds: int = 1800

    @field_validator("command", "inputs_url", "labels_url")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("must not be blank")
        return v

    @model_validator(mode="after")
    def _at_least_one(self) -> "DataSourceSpec":
        if not (self.command or self.inputs_url or self.labels_url):
            raise ValueError(
                "eval.data_source needs a command and/or inputs_url/labels_url"
            )
        return self


class EvalSpec(StrictModel):
    labels_path: str | None = None
    schema_path: str | None = None
    split: SplitSpec = Field(default_factory=SplitSpec)
    # External-dataset refresh for the `poll` job (unset = in-repo data; use git).
    data_source: DataSourceSpec | None = None

    # Field in each output record holding the predicted class (classification).
    label_field: str = "label"
    # Field used to align outputs<->labels when present (else align by index).
    id_field: str | None = None
    # --- Customer-supplied grading (the task-agnostic escape hatch) ---
    # When the workflow's command emits its own per-record grade, point at it here
    # and driftless aggregates it instead of doing classification scoring:
    #   * ``score_field``: a numeric score per record -> mean score (``min_score``).
    #   * ``pass_field``: a boolean pass/fail per record -> pass-rate (``min_score``).
    # This makes grading work for *any* task, because the team that owns "good"
    # supplies the score. Mutually exclusive; both leave label-based scoring off.
    score_field: str | None = None
    pass_field: str | None = None
    # --- Structured extraction grading ---
    # Per-field scoring over structured output: each name is a slot we score with
    # precision/recall/F1 vs. the gold record (which carries the same fields).
    # Requires id_field + labels_path. Aggregates to macro F1, gated by min_f1.
    fields: list[str] = Field(default_factory=list)
    # --- LLM-as-judge grading (free-form tasks) ---
    judge: JudgeSpec | None = None
    # Optional per-record numeric cost field emitted by the workflow.
    cost_field: str | None = None
    # Optional per-record token-usage fields. When ``cost_field`` is absent,
    # cost is derived from these times the catalog price for the run's model.
    prompt_tokens_field: str | None = None
    completion_tokens_field: str | None = None
    # A record is a "refusal" if label_field is empty/null, ``refused`` is
    # truthy, or the predicted value appears in this list.
    refusal_values: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_grading_mode(self) -> "EvalSpec":
        modes = sum(
            (
                self.score_field is not None,
                self.pass_field is not None,
                bool(self.fields),
                self.judge is not None,
            )
        )
        if modes > 1:
            raise ValueError(
                "set only one grading mode: score_field, pass_field, fields, or judge"
            )
        if self.fields and not self.id_field:
            raise ValueError("eval.fields (extraction) requires eval.id_field")
        if self.fields and not self.labels_path:
            raise ValueError("eval.fields (extraction) requires eval.labels_path")
        return self

    @property
    def grading(self) -> str:
        """Which scoring layer applies: ``judge`` | ``extraction`` | ``score`` | ``pass`` | ``label``."""
        if self.judge is not None:
            return "judge"
        if self.fields:
            return "extraction"
        if self.score_field is not None:
            return "score"
        if self.pass_field is not None:
            return "pass"
        return "label"


class ThresholdsSpec(StrictModel):
    min_f1: float | None = None
    min_precision: float | None = None
    min_recall: float | None = None
    # Mean score / pass-rate floor for customer-supplied grading (score/pass mode).
    min_score: float | None = None
    max_schema_error_rate: float | None = None
    max_cost_increase: float | None = None
    max_latency_increase: float | None = None
    # When no absolute quality threshold is set, the bar becomes "don't regress
    # beyond this tolerance vs. the current baseline" (see compare.check_thresholds).
    regression_tolerance: float | None = None

    def has_absolute_quality(self) -> bool:
        """True if any absolute quality/error threshold is configured."""
        return any(
            v is not None
            for v in (
                self.min_f1,
                self.min_precision,
                self.min_recall,
                self.min_score,
                self.max_schema_error_rate,
            )
        )


class MigrationSpec(StrictModel):
    allow_prompt_edits: bool = True
    allow_example_edits: bool = True
    allow_config_edits: bool = True
    allow_schema_edits: bool = False
    allow_business_logic_edits: bool = False
    max_iterations: int = 8
    holdout_required: bool = True


class RepairSpec(StrictModel):
    """Customize the prompt the LLM repair generator uses.

    Precedence: inline values win over their ``*_path`` file counterparts.
    ``guidance`` is appended to whichever system prompt is in effect, so teams
    can add domain rules without rewriting the whole prompt. ``user_template``
    supports ``{{placeholder}}`` substitution (see generators for the available
    placeholders); when omitted the built-in user prompt is used.
    """

    system_prompt: str | None = None
    system_prompt_path: str | None = None
    guidance: str | None = None
    user_template: str | None = None
    user_template_path: str | None = None


class Workflow(StrictModel):
    """A single model-dependent behavior contract."""

    description: str = ""
    run: RunSpec
    model: ModelSpec
    files: FilesSpec = Field(default_factory=FilesSpec)
    eval: EvalSpec = Field(default_factory=EvalSpec)
    thresholds: ThresholdsSpec = Field(default_factory=ThresholdsSpec)
    migration: MigrationSpec = Field(default_factory=MigrationSpec)
    repair: RepairSpec = Field(default_factory=RepairSpec)


class Contract(StrictModel):
    """Top-level ``driftless.yml`` document."""

    version: int = 1
    workflows: dict[str, Workflow]

    @field_validator("workflows")
    @classmethod
    def _at_least_one(cls, v: dict[str, Workflow]) -> dict[str, Workflow]:
        if not v:
            raise ValueError("at least one workflow must be defined")
        return v

    def workflow(self, name: str) -> Workflow:
        try:
            return self.workflows[name]
        except KeyError:
            known = ", ".join(sorted(self.workflows)) or "(none)"
            raise WorkflowNotFoundError(
                f"workflow {name!r} not found in contract",
                hint=f"known workflows: {known}",
            ) from None


def find_contract(start: Path | None = None) -> Path | None:
    """Search ``start`` and its parents for a contract file."""
    start = (start or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        for name in CONTRACT_FILENAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def load_contract(path: Path | None = None) -> Contract:
    """Load and validate a contract, raising a friendly ``ContractError``."""
    contract_path = path or find_contract()
    if contract_path is None:
        raise ContractError(
            "no driftless.yml found",
            hint="run `driftless init` to scaffold one",
        )
    if not contract_path.is_file():
        raise ContractError(f"contract file not found: {contract_path}")

    try:
        raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"could not parse {contract_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ContractError(f"{contract_path} must contain a YAML mapping")

    try:
        return Contract.model_validate(raw)
    except ValidationError as exc:
        raise ContractError(
            f"invalid contract {contract_path}:\n{_format_validation_error(exc)}"
        ) from exc


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)
