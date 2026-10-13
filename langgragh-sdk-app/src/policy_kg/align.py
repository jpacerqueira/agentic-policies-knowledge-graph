"""Map policy statements onto OSCAL controls."""

from __future__ import annotations

import re

STOPWORDS = {
    "shall",
    "their",
    "which",
    "about",
    "there",
    "these",
    "those",
    "under",
    "where",
    "every",
    "other",
    "before",
    "after",
    "system",
    "policy",
    "northline",
    "bank",
}

# Phrase rules are the stable fallback when a PDF omits oscal_controls.
PHRASE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("serious incident",), "aia-73"),
    (("sbom",), "ds-sb-1"),
    (("signing key",), "ds-sc-1"),
    (("human oversight",), "aia-14"),
)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 5 and token not in STOPWORDS
    }


def _controls_for(control_id: str, controls: list[dict]) -> list[dict]:
    return [item for item in controls if item.get("control_id") == control_id]


def _declared(policy: dict, controls: list[dict]) -> list[dict]:
    alignments = []
    seen: set[str] = set()
    for control_id in policy.get("control_ids") or []:
        if control_id in seen:
            continue
        seen.add(control_id)
        matches = _controls_for(control_id, controls)
        if len(matches) == 1:
            alignments.append(
                {
                    "policy_id": policy["policy_id"],
                    "control_id": control_id,
                    "catalog_uuid": matches[0]["catalog_uuid"],
                    "method": "declared",
                    "confidence": 1.0,
                    "status": "matched",
                }
            )
        elif len(matches) > 1:
            alignments.append(
                {
                    "policy_id": policy["policy_id"],
                    "control_id": control_id,
                    "catalog_uuid": None,
                    "method": "declared",
                    "confidence": 0.0,
                    "status": "ambiguous",
                }
            )
        else:
            alignments.append(
                {
                    "policy_id": policy["policy_id"],
                    "control_id": control_id,
                    "catalog_uuid": None,
                    "method": "declared",
                    "confidence": 0.0,
                    "status": "unknown",
                }
            )
    return alignments


def _phrases(policy: dict, controls: list[dict]) -> list[dict]:
    statement = (policy.get("statement") or "").lower()
    alignments = []
    seen: set[str] = set()
    for phrases, control_id in PHRASE_RULES:
        if control_id in seen:
            continue
        if not all(phrase in statement for phrase in phrases):
            continue
        seen.add(control_id)
        matches = _controls_for(control_id, controls)
        status = "matched" if len(matches) == 1 else "unknown" if not matches else "ambiguous"
        alignments.append(
            {
                "policy_id": policy["policy_id"],
                "control_id": control_id,
                "catalog_uuid": matches[0]["catalog_uuid"] if status == "matched" else None,
                "method": "phrase",
                "confidence": 0.95 if status == "matched" else 0.0,
                "status": status,
            }
        )
    return alignments


def _overlap(policy: dict, controls: list[dict]) -> list[dict]:
    statement_tokens = _tokens(policy.get("statement") or "")
    scored: list[tuple[int, dict]] = []
    for item in controls:
        title_tokens = _tokens(f"{item.get('title', '')} {item.get('statement', '')}")
        score = len(statement_tokens & title_tokens)
        if score:
            scored.append((score, item))
    if not scored:
        return []
    best = max(score for score, _item in scored)
    if best < 3:
        return []
    winners = [item for score, item in scored if score == best]
    if len(winners) > 1:
        return [
            {
                "policy_id": policy["policy_id"],
                "control_id": item["control_id"],
                "catalog_uuid": None,
                "method": "overlap",
                "confidence": 0.0,
                "status": "ambiguous",
            }
            for item in winners
        ]
    winner = winners[0]
    return [
        {
            "policy_id": policy["policy_id"],
            "control_id": winner["control_id"],
            "catalog_uuid": winner["catalog_uuid"],
            "method": "overlap",
            "confidence": min(0.9, best / 10),
            "status": "matched",
        }
    ]


def align_policies(policies: list[dict], controls: list[dict]) -> list[dict]:
    alignments: list[dict] = []
    for policy in policies:
        if policy.get("control_ids"):
            alignments.extend(_declared(policy, controls))
            continue
        phrased = _phrases(policy, controls)
        if phrased:
            alignments.extend(phrased)
            continue
        alignments.extend(_overlap(policy, controls))
    return alignments
