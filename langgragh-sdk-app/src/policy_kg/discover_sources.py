"""Locate local policy PDFs and, when asked, the upstream EU AI Act OSCAL files."""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

from policy_kg.frameworks import EU_AI_ACT_FILES


def list_pdfs(policy_dir: Path) -> list[str]:
    if not policy_dir.exists():
        return []
    return sorted(str(path.resolve()) for path in policy_dir.glob("*.pdf") if path.is_file())


def fetch_eu_ai_act(cache: Path, opener=None) -> list[str]:
    """Download the EU AI Act OSCAL catalog, profiles, SSP template, and scope note."""
    open_url = opener or urlopen
    written: list[str] = []
    for relative, url in EU_AI_ACT_FILES.items():
        destination = cache / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open_url(url, timeout=60) as response:
            destination.write_bytes(response.read())
        written.append(str(destination))
    return written
