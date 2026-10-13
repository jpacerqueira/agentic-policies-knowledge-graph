"""Canonical framework sources projected into the knowledge graph.

Control identifiers for ``eu-ai-act`` follow the Apache-2.0 catalog published at
https://github.com/olon-standards/eu-ai-act-oscal . Statements shipped in this
repository are short local restatements so the pipeline runs offline. The
Official Journal text remains the authority. Fetching replaces the offline
snapshot with the upstream catalog.
"""

from __future__ import annotations

EU_AI_ACT_REPOSITORY = "https://github.com/olon-standards/eu-ai-act-oscal"
EU_AI_ACT_SCOPE = (
    "https://github.com/olon-standards/eu-ai-act-oscal/blob/main/docs/SCOPE.md"
)
EU_AI_ACT_SSP_TEMPLATE = (
    "https://github.com/olon-standards/eu-ai-act-oscal/blob/main/docs/examples/"
    "template-system-security-plan.json"
)
OSCAL_HOME = "https://pages.nist.gov/OSCAL/"

# Raw files the discover step can cache. Paths match the upstream repository.
EU_AI_ACT_FILES: dict[str, str] = {
    "catalogs/eu-ai-act/catalog.json": (
        "https://raw.githubusercontent.com/olon-standards/eu-ai-act-oscal/main/"
        "catalogs/eu-ai-act/catalog.json"
    ),
    "profiles/high-risk-provider-annex-iii/profile.json": (
        "https://raw.githubusercontent.com/olon-standards/eu-ai-act-oscal/main/"
        "profiles/high-risk-provider-annex-iii/profile.json"
    ),
    "docs/examples/template-system-security-plan.json": (
        "https://raw.githubusercontent.com/olon-standards/eu-ai-act-oscal/main/"
        "docs/examples/template-system-security-plan.json"
    ),
    "assessment-plans/high-risk-provider-readiness/assessment-plan.json": (
        "https://raw.githubusercontent.com/olon-standards/eu-ai-act-oscal/main/"
        "assessment-plans/high-risk-provider-readiness/assessment-plan.json"
    ),
    "docs/SCOPE.md": (
        "https://raw.githubusercontent.com/olon-standards/eu-ai-act-oscal/main/"
        "docs/SCOPE.md"
    ),
}

FRAMEWORKS: dict[str, dict[str, str]] = {
    "eu-ai-act": {
        "title": "EU Artificial Intelligence Act",
        "repository": EU_AI_ACT_REPOSITORY,
        "scope": EU_AI_ACT_SCOPE,
        "ssp_template": EU_AI_ACT_SSP_TEMPLATE,
        "specification": OSCAL_HOME,
    },
    "northline-devsecops": {
        "title": "Northline Bank DevSecOps baseline",
        "specification": OSCAL_HOME,
    },
}
