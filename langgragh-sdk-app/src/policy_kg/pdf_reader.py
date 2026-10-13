"""Read policy PDFs and the machine-readable policy block they carry."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pypdf import PdfReader

BLOCK_RE = re.compile(r"POLICY-BLOCK-START(.*?)POLICY-BLOCK-END", re.S)
REQUIRED_FIELDS = ("policy_id", "title", "owner", "applies_to", "statement")


def read_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def parse_policy_blocks(text: str) -> list[dict[str, object]]:
    """Return every policy block in extracted text.

    Repeated ``statement=`` lines are joined. A wrapped continuation line that
    does not contain ``=`` is appended to the previous field.
    """
    policies: list[dict[str, object]] = []
    for match in BLOCK_RE.finditer(text):
        fields: dict[str, str] = {}
        statements: list[str] = []
        current_key: str | None = None
        for raw_line in match.group(1).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                current_key = key
                if key == "statement":
                    statements.append(value)
                else:
                    fields[key] = value
            elif current_key == "statement":
                statements.append(line)
            elif current_key:
                fields[current_key] = f"{fields[current_key]} {line}".strip()
        fields["statement"] = " ".join(part for part in statements if part).strip()
        control_ids = [
            item.strip()
            for item in re.split(r"[,;]", fields.get("oscal_controls", ""))
            if item.strip()
        ]
        applies_to = [item.strip() for item in fields.get("applies_to", "").split(",") if item.strip()]
        policies.append(
            {
                "policy_id": fields.get("policy_id", ""),
                "title": fields.get("title", ""),
                "owner": fields.get("owner", ""),
                "applies_to": applies_to,
                "control_ids": control_ids,
                "statement": fields.get("statement", ""),
                "classification": fields.get("classification", ""),
                "missing_fields": [name for name in REQUIRED_FIELDS if not fields.get(name)],
            }
        )
    return policies


def extract_policies_from_pdf(path: Path) -> dict[str, object]:
    text = read_pdf_text(path)
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "text": text,
        "policies": parse_policy_blocks(text),
    }
