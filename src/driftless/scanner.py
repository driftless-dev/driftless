"""Best-effort static discovery of LLM model dependencies.

Static scanning is intentionally treated as best-effort (see the proposal): a
model ID may be hidden behind env vars, gateways, or runtime config. The
scanner surfaces *probable* usage and at-risk models so a human can confirm and
configure a migration-ready workflow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .lifecycle import Lifecycle, ModelInfo, load_lifecycle

SCAN_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".yml", ".yaml", ".json", ".toml", ".env", ".rb", ".go", ".java", ".rs", ".php",
}

IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "dist", "build", "__pycache__",
    ".driftless", ".mypy_cache", ".pytest_cache", ".next", "target", "vendor",
    "site-packages",
}

MAX_FILE_BYTES = 2_000_000

# Provider SDK usage signatures.
_PROVIDER_PATTERNS = {
    "openai": re.compile(r"\b(?:from\s+openai|import\s+openai|OpenAI\s*\(|AzureOpenAI\s*\(|openai\.\w+)\b", re.IGNORECASE),
    "anthropic": re.compile(r"\b(?:from\s+anthropic|import\s+anthropic|Anthropic\s*\(|anthropic\.\w+)\b|@anthropic-ai/sdk", re.IGNORECASE),
    "google": re.compile(r"google\.generativeai|google\.genai|\bgenai\.\w+|GenerativeModel\s*\(", re.IGNORECASE),
}

# Provider-portable routing: a cross-provider model swap is safe-ish because the
# workflow dispatches by model id through a gateway rather than a single SDK.
_PORTABILITY_PATTERN = re.compile(
    r"\b(?:litellm|openrouter|portkey|aisuite|any[_-]?llm)\b"
    r"|openrouter\.ai|litellm\.\w+",
    re.IGNORECASE,
)

# Probable model-id string literals across providers.
_MODEL_TOKEN = re.compile(
    r"\b("
    r"gpt-[0-9][\w.\-]*"
    r"|o[1-9][\w.\-]*"
    r"|text-(?:davinci|embedding)-[\w.\-]+"
    r"|claude-[\w.\-]+"
    r"|gemini-[\w.\-]+"
    r"|gemini-pro"
    r")\b"
)

# ALL-CAPS identifiers that look like a model env var (e.g. SUPPORT_CLASSIFIER_MODEL).
_ENV_MODEL_VAR = re.compile(r"\b([A-Z][A-Z0-9_]*MODEL[A-Z0-9_]*)\b")
# A `model:`/`model =` config key (e.g. in YAML or code).
_MODEL_KEY = re.compile(r"(?:^|[^\w])model\s*[:=]", re.IGNORECASE)


@dataclass
class Finding:
    path: str
    line: int
    kind: str  # "provider_sdk" | "model_id" | "env_model"
    snippet: str
    provider: str | None = None
    model: str | None = None
    env_var: str | None = None


@dataclass
class ScanResult:
    root: str
    findings: list[Finding] = field(default_factory=list)

    def files(self) -> dict[str, list[Finding]]:
        grouped: dict[str, list[Finding]] = {}
        for f in self.findings:
            grouped.setdefault(f.path, []).append(f)
        return dict(sorted(grouped.items()))

    @property
    def portable(self) -> bool:
        """True if any provider-portable routing (gateway) was detected."""
        return any(f.kind == "portability" for f in self.findings)

    def model_risks(self, lifecycle: Lifecycle) -> list[tuple[ModelInfo | str, int]]:
        """Distinct detected models with lifecycle info + occurrence counts."""
        counts: dict[str, int] = {}
        for f in self.findings:
            if f.kind == "model_id" and f.model:
                counts[f.model] = counts.get(f.model, 0) + 1
        out: list[tuple[ModelInfo | str, int]] = []
        for model, count in sorted(counts.items()):
            info = lifecycle.lookup(model)
            out.append((info or model, count))
        return out


def iter_source_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix not in SCAN_EXTENSIONS and path.name != ".env":
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def scan_text(rel_path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        snippet = line.strip()[:200]

        for provider, pattern in _PROVIDER_PATTERNS.items():
            if pattern.search(line):
                findings.append(Finding(rel_path, lineno, "provider_sdk", snippet, provider=provider))
                break

        if _PORTABILITY_PATTERN.search(line):
            findings.append(Finding(rel_path, lineno, "portability", snippet))

        for match in _MODEL_TOKEN.finditer(line):
            findings.append(Finding(rel_path, lineno, "model_id", snippet, model=match.group(1)))

        env_var = _ENV_MODEL_VAR.search(line)
        if env_var:
            findings.append(Finding(rel_path, lineno, "env_model", snippet, env_var=env_var.group(1)))
        elif _MODEL_KEY.search(line):
            findings.append(Finding(rel_path, lineno, "env_model", snippet))
    return findings


def detect_portability(root: Path | None = None) -> bool:
    """Cheap check: does any source file route models through a gateway?

    Stops at the first match so it stays fast enough to run in CLI preflight.
    """
    root = (root or Path.cwd()).resolve()
    for path in iter_source_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _PORTABILITY_PATTERN.search(text):
            return True
    return False


def scan_repo(root: Path | None = None, *, lifecycle: Lifecycle | None = None) -> ScanResult:
    root = (root or Path.cwd()).resolve()
    lifecycle = lifecycle or load_lifecycle()
    result = ScanResult(root=str(root))
    for path in iter_source_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        result.findings.extend(scan_text(rel, text))
    return result
