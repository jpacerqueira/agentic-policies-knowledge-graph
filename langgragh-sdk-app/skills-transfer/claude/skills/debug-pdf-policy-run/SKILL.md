---
name: debug-pdf-policy-run
description: >-
  Debugs a failed LangGraph pipeline run for a new PDF policy, including
  missing policy blocks, unknown OSCAL controls, validation findings, and
  Neo4j connection errors. Use when a policy-kg run fails or the knowledge
  graph does not contain the expected policy.
---

# Debug a policy pipeline run

Work in `langgragh-sdk-app/`. Reproduce with Neo4j disconnected first so the report is the source of truth.

```bash
policy-kg run \
  --policy-dir data/policies \
  --oscal-dir data/oscal \
  --organization data/organization.json \
  --skip-neo4j \
  --report /tmp/policy-kg-run.json
```

Exit 0: validation passed. Exit 1: findings, and nothing was written to Neo4j. Exit 2: the process could not start (missing file, bad arguments, or Neo4j auth/connection). `trace` must be `discover`, `read_pdfs`, `extract_policies`, `load_oscal`, `align`, `project`, `validate`, `persist`.

## Finding codes

| Code | What to change |
| --- | --- |
| `missing-policy-block` | PDF text has no `POLICY-BLOCK-START` / `POLICY-BLOCK-END` |
| `invalid-policy-block` | A required field is empty: `policy_id`, `title`, `owner`, `applies_to`, `statement` |
| `duplicate-policy-id` | Two PDFs share one policy id |
| `unknown-system` | `applies_to` is not `credit-decisioning` or `payments-delivery` |
| `unknown-control` | `oscal_controls` names an id that is not in a loaded catalog, or a profile selects a missing id |
| `ambiguous-control` | The same control id exists in more than one catalog |
| `unmapped-policy` | No declared, phrase, or overlap match |
| `uncovered-control` | A control selected by the in-scope SSP profile has no policy |
| `unimplemented-control` | That control has no SSP or component `implemented-requirements` entry |
| `unknown-parameter` | A profile `set-parameters` id is missing or duplicated |
| `unresolved-import` | A profile `href` does not resolve to a catalog |
| `invalid-oscal` | Missing `uuid` or metadata title, last-modified, version, or oscal-version |
| `unknown-oscal-model` | JSON root is not an OSCAL model this pipeline loads |
| `organization-profile` | Organization is not tier 1 with `employee_count` 100000 |

Coverage applies only to profiles imported by an SSP whose system id belongs to the organization. A fetched EU AI Act template SSP does not expand that set.

## Neo4j

The pipeline runs inside `policy-kg-app` on `policy-kg-net`, next to `policy-kg-neo4j`. Start both with:

```bash
docker compose up -d --build --wait
```

Use `NEO4J_PASSWORD=policy-graph-local` for that database. After a green run, query from the app container:

```bash
docker compose exec app policy-kg query policies
docker compose exec app policy-kg query gaps
docker compose exec app policy-kg query frameworks
```

`frameworks` should show `eu-ai-act` with the SCOPE.md URL and the template SSP URL from olon-standards/eu-ai-act-oscal, plus `https://pages.nist.gov/OSCAL/`.

`policy-kg query layers` should list eight layers, from `catalog` through `policy`. If a layer is missing, the database still has the older projection. Rebuild with `docker compose down -v` and `docker compose up -d --build --wait`. The model is `docs/oscal-layers.md`.

If the PDF extracts but the block is split, shorten field lines. The parser appends a wrapped line that has no `=` onto the previous field, which corrupts a control id when the break falls inside the id.

## Intake page

The page is http://localhost:8080 inside the running stack. `docker compose logs app` shows pipeline and server output. A link must be `http` or `https`. `File is not a PDF` means the bytes do not start with `%PDF`. `unreadable-pdf` means pypdf could not read the file. `sourced-text` means the PDF had no policy block and the page analyzed the extracted text. `no-extractable-text` means the file had nothing long enough to align. An upload is stored under `submissions/<date-time>/` and does not enter the baseline `data/policies/*.pdf` scan.

Batch failures: follow `debug-batch-policy-pipeline`. Interactive app failures: follow `debug-interactive-policy-app`. The stored ontology is http://localhost:8080/graph.
