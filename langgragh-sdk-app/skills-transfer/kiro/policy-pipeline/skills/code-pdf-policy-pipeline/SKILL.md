---
name: code-pdf-policy-pipeline
description: >-
  Adds or updates a DevSecOps PDF policy and its OSCAL control mapping in the
  LangGraph policy knowledge-graph pipeline. Use when coding a new PDF policy,
  extending the Northline Bank catalog, profile, SSP, or component definition,
  or changing how policy PDFs are parsed.
---

# Code a PDF policy into the pipeline

Work in `langgragh-sdk-app/` inside `agentic-policies-knowledge-graph`. Northline Bank plc is a fictional tier-1 bank with 100000 employees. Do not present a pipeline result as legal advice or a conformity assessment.

## Policy block

Generate the PDF with `policy-kg generate-pdfs` or write a PDF whose extracted text contains:

```text
POLICY-BLOCK-START
policy_id=POL-NEW-001
title=Short title
owner=Chief Information Security Officer
applies_to=credit-decisioning
oscal_controls=aia-9
classification=Internal
statement=One short sentence on its own line.
POLICY-BLOCK-END
```

Keep each field line under 80 characters. Repeat `statement=` to add sentences. `applies_to` accepts `credit-decisioning` and `payments-delivery`. Declared `oscal_controls` are required for a bank policy. Dotted ids such as `aia-5.1.a` stay intact.

## When the control is new

1. Add the control to `data/oscal/devsecops/catalog.json` or, for an EU AI Act id, confirm it exists in the offline snapshot or the fetched upstream catalog.
2. Select it from `data/oscal/profiles/northline-tier1-profile.json`.
3. Add an `implemented-requirements` entry on `data/oscal/ssp/credit-decisioning-ssp.json` and, for a delivery control, on the matching component.
4. Map at least one policy to that control id.

A selected control with no policy fails as `uncovered-control`. A selected control with no SSP or component implementation fails as `unimplemented-control`.

## Code path

The LangGraph stages are `discover`, `read_pdfs`, `extract_policies`, `load_oscal`, `align`, `project`, `validate`, `persist`. Persist runs only when validation is clean. Parsing lives in `src/policy_kg/pdf_reader.py`. OSCAL loading lives in `src/policy_kg/oscal_loader.py`. Alignment lives in `src/policy_kg/align.py`.

`docs/oscal-layers.md` is the ontology. `project` writes eight `Layer` nodes under the `Ontology` `oscal-control-lifecycle`, in lifecycle order, joined by `FOLLOWS`. Each catalog, profile, component definition, system security plan, assessment plan, assessment results document, POA&M, and policy statement has `IN_LAYER`. Nodes merge on uuid or id. `policy-kg query layers` lists them. A full Neo4j rebuild is `docker compose down -v` then `docker compose up -d --build --wait`.

## Link or sourced PDF

The intake page at http://localhost:8080 (`policy-kg serve`) accepts an http(s) link or an uploaded PDF. `src/policy_kg/intake.py` stores the file under `data/intake/`. `src/policy_kg/analyze.py` uses a policy block when the PDF has one. Otherwise it segments the text and aligns it with the phrase rules and token overlap in `src/policy_kg/align.py`. Checked “add to the knowledge graph” merges that policy without removing the baseline nodes.

Do not put sourced PDFs in `data/policies/`. The baseline scan reads only top-level `*.pdf` files there, and a file without a policy block fails the sample run as `missing-policy-block`. Interactive and batch runs write each submission under `submissions/<YYYY-MM-DDTHHMMSS>/`, which is outside that scan and bind-mounted into the app container.

## Finish

1. Add or extend a test under `tests/` that asserts the new `policy_id` and its control ids.
2. Run `pytest`.
3. Append a dated file under `skills-transfer/changes-log/YYYY-MM-DD.md`. Do not rewrite `2026-10-13.md`.
4. If you change a skill, copy the same `SKILL.md` to both `skills-transfer/claude/skills/` and `skills-transfer/kiro/policy-pipeline/skills/`.

Run the new PDF with:

```bash
policy-kg run --policy-dir data/policies --oscal-dir data/oscal --organization data/organization.json --skip-neo4j --report /tmp/policy-kg-run.json
```
