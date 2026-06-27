from pathlib import Path

import yaml

from driftless.configure import build_workflow_scaffold
from driftless.lifecycle import load_lifecycle
from driftless.scanner import detect_portability, scan_repo, scan_text


def test_lifecycle_lookup_exact_and_prefix():
    lc = load_lifecycle()
    assert lc.lookup("gpt-4o").status == "active"
    assert lc.lookup("gpt-3.5-turbo").at_risk
    # dated alias resolves via longest known prefix
    info = lc.lookup("gpt-3.5-turbo-0125")
    assert info is not None and info.model == "gpt-3.5-turbo"
    assert lc.lookup("totally-made-up-model") is None


def test_portability_detection(tmp_path: Path):
    (tmp_path / "client.py").write_text(
        "import litellm\n"
        "resp = litellm.completion(model=os.environ['MODEL'], messages=msgs)\n"
    )
    assert detect_portability(tmp_path) is True
    result = scan_repo(tmp_path)
    assert result.portable is True


def test_no_portability_for_single_sdk(tmp_path: Path):
    (tmp_path / "client.py").write_text("from openai import OpenAI\nc = OpenAI()\n")
    assert detect_portability(tmp_path) is False
    assert scan_repo(tmp_path).portable is False


def test_scan_text_detects_signals():
    text = "\n".join(
        [
            "from openai import OpenAI",
            'MODEL = os.environ["SUPPORT_CLASSIFIER_MODEL"]',
            'resp = client.chat(model="gpt-3.5-turbo")',
            "  model: claude-3-5-sonnet",
        ]
    )
    findings = scan_text("app.py", text)
    kinds = {f.kind for f in findings}
    assert "provider_sdk" in kinds
    assert "model_id" in kinds
    assert "env_model" in kinds

    providers = {f.provider for f in findings if f.provider}
    assert "openai" in providers
    env_vars = {f.env_var for f in findings if f.env_var}
    assert "SUPPORT_CLASSIFIER_MODEL" in env_vars
    models = {f.model for f in findings if f.model}
    assert {"gpt-3.5-turbo", "claude-3-5-sonnet"} <= models


def test_scan_repo_and_model_risks(tmp_path: Path):
    (tmp_path / "svc.py").write_text(
        'import anthropic\nMODEL = "claude-2"  # retired\n'
    )
    (tmp_path / "ok.py").write_text('model = "gpt-4o"\n')
    # ignored directory should be skipped
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text('model="gpt-3.5-turbo"')

    lc = load_lifecycle()
    result = scan_repo(tmp_path, lifecycle=lc)
    paths = set(result.files())
    assert "svc.py" in paths and "ok.py" in paths
    assert not any("node_modules" in p for p in paths)

    risks = {info.model: (info, c) for info, c in result.model_risks(lc) if hasattr(info, "model")}
    assert risks["claude-2"][0].status == "retired"
    assert risks["gpt-4o"][0].status == "active"


def test_configure_prefills_from_at_risk_model(tmp_path: Path):
    (tmp_path / "classify.py").write_text(
        '\n'.join(
            [
                "from openai import OpenAI",
                'm = os.getenv("TICKET_MODEL", "gpt-3.5-turbo")',
                'resp = client.chat(model="gpt-3.5-turbo")',
            ]
        )
    )
    snippet, model = build_workflow_scaffold("ticket_router", tmp_path)
    assert model == "gpt-3.5-turbo"

    parsed = yaml.safe_load(snippet)
    wf = parsed["workflows"]["ticket_router"]
    assert wf["model"]["current"] == "gpt-3.5-turbo"
    assert wf["model"]["provider"] == "openai"
    assert wf["model"]["env_var"] == "TICKET_MODEL"
    # recommended replacement from lifecycle data
    assert wf["model"]["target_candidates"] == ["gpt-4o-mini"]


def test_configure_generic_when_no_detection(tmp_path: Path):
    (tmp_path / "empty.py").write_text("print('hello')\n")
    snippet, model = build_workflow_scaffold("thing", tmp_path)
    assert model is None
    parsed = yaml.safe_load(snippet)
    wf = parsed["workflows"]["thing"]
    assert wf["model"]["env_var"] == "THING_MODEL"
    assert wf["model"]["current"] == "<current-model>"
