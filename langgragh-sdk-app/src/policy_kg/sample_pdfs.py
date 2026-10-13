"""Generate the fictional Northline Bank policy PDFs."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

# Statements stay short so a core PDF font does not wrap the policy block.
POLICY_SPECS: list[dict[str, str]] = [
    {
        "policy_id": "POL-SSD-001",
        "title": "Secure software delivery",
        "owner": "Chief Information Security Officer",
        "applies_to": "payments-delivery",
        "oscal_controls": "ds-cm-1, ds-ci-1, ds-sb-1, aia-9, aia-17",
        "classification": "Internal",
        "statement": (
            "Production payment changes require peer review and a change record. "
            "Pipeline artifacts are signed and an SBOM is stored with the release. "
            "Material model or service changes pass the AI risk process and the quality system."
        ),
    },
    {
        "policy_id": "POL-SEC-002",
        "title": "Secrets and cryptographic keys",
        "owner": "Chief Information Security Officer",
        "applies_to": "credit-decisioning, payments-delivery",
        "oscal_controls": "ds-sc-1, aia-15",
        "classification": "Internal",
        "statement": (
            "Application secrets and signing keys live in the approved secrets service. "
            "Source repositories and images must not contain long-lived credentials. "
            "Credit-model endpoints require authenticated, encrypted access."
        ),
    },
    {
        "policy_id": "POL-VUL-003",
        "title": "Vulnerability and dependency management",
        "owner": "Chief Information Security Officer",
        "applies_to": "credit-decisioning, payments-delivery",
        "oscal_controls": "ds-vm-1, aia-15",
        "classification": "Internal",
        "statement": (
            "Payment and credit-decision dependencies are scanned on the cadence set in the profile. "
            "Exploitable findings are tracked to a fix or a time-bounded exception. "
            "Model-serving images are rebuilt when the base image is patched."
        ),
    },
    {
        "policy_id": "POL-ACC-004",
        "title": "Workforce and privileged access",
        "owner": "Chief Information Security Officer",
        "applies_to": "credit-decisioning, payments-delivery",
        "oscal_controls": "ds-ac-1, aia-14",
        "classification": "Internal",
        "statement": (
            "Access for the workforce is role-based, reviewed, and removed when a role ends. "
            "Privileged pipeline and production access requires a named approver. "
            "People who oversee credit decisions can interrupt the automated outcome."
        ),
    },
    {
        "policy_id": "POL-LOG-005",
        "title": "Audit logging and monitoring",
        "owner": "Chief Information Security Officer",
        "applies_to": "credit-decisioning, payments-delivery",
        "oscal_controls": "ds-au-1, aia-12",
        "classification": "Internal",
        "statement": (
            "Security-relevant admin and release events are logged and retained. "
            "Credit decisions keep the records needed to trace inputs, model version, and outcome."
        ),
    },
    {
        "policy_id": "POL-INC-006",
        "title": "Incident response",
        "owner": "Chief Information Security Officer",
        "applies_to": "credit-decisioning, payments-delivery",
        "oscal_controls": "ds-ir-1, aia-73",
        "classification": "Internal",
        "statement": (
            "Security incidents have an owner, a severity, and a customer-impact note. "
            "A serious incident in the credit AI system follows the reporting deadlines in the control."
        ),
    },
    {
        "policy_id": "POL-AIR-007",
        "title": "Credit AI risk management",
        "owner": "Head of Model Risk",
        "applies_to": "credit-decisioning",
        "oscal_controls": "aia-6, aia-9, aia-10, aia-14, aia-15",
        "classification": "Internal",
        "statement": (
            "The credit platform is classified under the high-risk creditworthiness use case. "
            "Data used to train or run the model is documented, access-controlled, and checked for errors. "
            "Human oversight can review and stop an automated credit outcome. "
            "Accuracy and cybersecurity limits are recorded before a model is promoted."
        ),
    },
    {
        "policy_id": "POL-REG-008",
        "title": "Regulatory exposure and penalties",
        "owner": "Chief Compliance Officer",
        "applies_to": "credit-decisioning, payments-delivery",
        "oscal_controls": "aia-99",
        "classification": "Internal",
        "statement": (
            "Control owners record the penalty exposure that applies when an AI obligation is missed. "
            "Exceptions are visible to compliance before they are accepted."
        ),
    },
]


def _statement_lines(statement: str) -> list[str]:
    words = statement.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join([*current, word])
        if len(trial) > 60 and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def render_policy_text(spec: dict[str, str]) -> str:
    lines = [
        "NORTHLINE BANK plc",
        "DevSecOps and AI policy",
        "Fictional illustration. Not legal advice. Not a conformity assessment.",
        "",
        spec["title"],
        "",
        "POLICY-BLOCK-START",
        f"policy_id={spec['policy_id']}",
        f"title={spec['title']}",
        f"owner={spec['owner']}",
        f"applies_to={spec['applies_to']}",
        f"oscal_controls={spec['oscal_controls']}",
        f"classification={spec['classification']}",
    ]
    for part in _statement_lines(spec["statement"]):
        lines.append(f"statement={part}")
    lines.append("POLICY-BLOCK-END")
    return "\n".join(lines) + "\n"


def write_pdf(path: Path, text: str) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Courier", size=10)
    pdf.multi_cell(0, 5, text)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


def write_plain_pdf(path: Path, text: str) -> None:
    write_pdf(path, text)


def generate_pdfs(out_dir: Path, specs: list[dict[str, str]] | None = None) -> list[Path]:
    written: list[Path] = []
    for spec in specs or POLICY_SPECS:
        dest = out_dir / f"{spec['policy_id'].lower()}.pdf"
        write_pdf(dest, render_policy_text(spec))
        written.append(dest)
    return written
