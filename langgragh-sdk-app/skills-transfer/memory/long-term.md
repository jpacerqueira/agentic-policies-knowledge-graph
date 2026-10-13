# Long-term memory

Read this before changing `langgragh-sdk-app/`. Pair it with `short-term.md` for the current state.

## What this is

LangGraph pipeline for a fictional tier-1 bank, Northline Bank plc, uuid `8f3c1a20-6b14-4d7e-9c31-0a6e5b7d1001`, 100000 employees. Systems: `credit-decisioning` (`...2001`) and `payments-delivery` (`...2002`). Not a real institution. Not legal advice. Not a conformity assessment.

OSCAL models loaded as JSON: catalog, profile, component-definition, system-security-plan, assessment-plan, assessment-results, plan-of-action-and-milestones. EU AI Act control ids come from the Apache-2.0 catalog at olon-standards/eu-ai-act-oscal (catalog uuid `f7b7352c-0824-4be8-b246-5c745d51c84b`). The offline snapshot is a short restatement with the same catalog uuid. `policy-kg fetch-eu-ai-act` downloads upstream files into `data/cache/eu-ai-act`, which is gitignored. When two catalogs share a uuid, the one with more controls wins. A fetched template SSP that is not tied to an organization system does not expand coverage.

## Pipeline

Stages, in order: discover, read_pdfs, extract_policies, load_oscal, align, project, validate, persist.

Persist runs only when validation has no error findings. The store is closed over by the graph and is not put in LangGraph state.

Bank PDFs use a `POLICY-BLOCK-START` / `POLICY-BLOCK-END` block with `policy_id`, `title`, `owner`, `applies_to`, `oscal_controls`, `classification`, and one or more `statement=` lines. Keep field lines under 80 characters. A continuation line without `=` is appended to the previous field.

Alignment: declared control ids (confidence 1.0) win. Otherwise phrase rules, then token overlap with score at least 3. Ties are ambiguous.

Finding codes include missing-policy-block, invalid-policy-block, duplicate-policy-id, unknown-system, unknown-control, ambiguous-control, unmapped-policy, uncovered-control, unimplemented-control, unknown-parameter, unresolved-import, invalid-oscal, unknown-oscal-model, organization-profile.

## Runtime

Docker Compose project `policy-kg`. Containers `policy-kg-neo4j` and `policy-kg-app`. Dedicated bridge network `policy-kg-net`. Tests use `docker-compose.test.yml`, project `policykgtest`, network `policy-kg-test-net`, Bolt `localhost:7688`, password `policy-graph-test`. Pytest refuses to wipe Neo4j unless that password is set.

App password `policy-graph-local` is a local default, not a production secret. Host ports: Neo4j 7474 and 7687, policy intake 8080. Inside the network the app uses `bolt://neo4j:7687`.

`list_pdfs` reads only `*.pdf` in the top of the policy directory. `submittions/<YYYY-MM-DDTHHMMSS>/` holds each interactive or batch submission and must stay out of that scan. The host directory is mounted at `/app/submittions`.

## Package

Python package `policy_kg`. Import the library as `from langgraph.graph import ...`. The folder name is `langgragh-sdk-app` (spelled with the extra `a`). CLI script: `policy-kg`.

Claude skills and the Kiro power must stay byte-identical. After editing one `SKILL.md`, copy `skills-transfer/claude/skills` over `skills-transfer/kiro/policy-pipeline/skills`.
