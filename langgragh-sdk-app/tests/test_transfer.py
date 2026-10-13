import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SKILLS = (
    "code-pdf-policy-pipeline",
    "test-pdf-policy-pipeline",
    "deploy-pdf-policy-pipeline",
    "debug-pdf-policy-run",
    "test-batch-policy-pipeline",
    "debug-batch-policy-pipeline",
    "test-interactive-policy-app",
    "debug-interactive-policy-app",
)


def test_claude_and_kiro_skills_match():
    claude = ROOT / "skills-transfer" / "claude" / "skills"
    kiro = ROOT / "skills-transfer" / "kiro" / "policy-pipeline" / "skills"
    for name in SKILLS:
        assert (claude / name / "SKILL.md").read_text(encoding="utf-8") == (
            kiro / name / "SKILL.md"
        ).read_text(encoding="utf-8")


def test_power_manifest_and_changes_log():
    manifest = json.loads(
        (ROOT / "skills-transfer" / "kiro" / "policy-pipeline" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "policy-pipeline"
    assert "pdf" in manifest["keywords"]
    assert "oscal" in manifest["keywords"]
    assert "neo4j" in manifest["keywords"]
    log = (ROOT / "skills-transfer" / "changes-log" / "2026-10-13.md").read_text(encoding="utf-8")
    assert "2026-10-13" in log
    assert "Claude" in log
    assert "Kiro" in log


def test_skills_cover_code_test_deploy_and_debug():
    claude = ROOT / "skills-transfer" / "claude" / "skills"
    code = (claude / "code-pdf-policy-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    test = (claude / "test-pdf-policy-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    deploy = (claude / "deploy-pdf-policy-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    debug = (claude / "debug-pdf-policy-run" / "SKILL.md").read_text(encoding="utf-8")
    assert "POLICY-BLOCK-START" in code
    assert "policy-kg run" in code
    assert "pytest" in test
    assert "docker compose" in deploy
    assert "unknown-control" in debug
    assert "missing-policy-block" in debug


def test_transfer_readme_explains_the_pack_and_how_to_move_it():
    readme = (ROOT / "skills-transfer" / "README.md").read_text(encoding="utf-8")
    assert "changes-log" in readme
    assert "Claude" in readme
    assert "Kiro" in readme
    assert "another Cursor session" in readme
    for name in SKILLS:
        assert name in readme
    memory = (ROOT / "skills-transfer" / "memory" / "long-term.md").read_text(encoding="utf-8")
    short = (ROOT / "skills-transfer" / "memory" / "short-term.md").read_text(encoding="utf-8")
    assert "policy-kg-net" in memory
    assert "8080" in short


def test_github_actions_are_present():
    test_wf = (REPO / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    deploy_wf = (REPO / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "pytest" in test_wf
    assert "neo4j:5.26-community" in test_wf
    assert "docker/build-push-action" in deploy_wf
    assert "workflow_dispatch" in deploy_wf
