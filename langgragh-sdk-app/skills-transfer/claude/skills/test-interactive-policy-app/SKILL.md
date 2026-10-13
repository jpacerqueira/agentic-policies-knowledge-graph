---
name: test-interactive-policy-app
description: >-
  Tests the interactive policy app: drag-and-drop, local folder upload, an S3
  folder, and the page that shows policies and the OSCAL ontology in Neo4j.
  Use when checking the intake page or http://localhost:8080/graph.
---

# Test the interactive policy app

Work in `langgragh-sdk-app/`. The app is the Compose service `policy-kg-app` on `policy-kg-net`. The intake page and the stored-graph page are not legal advice and not a conformity assessment.

## Automated test

```bash
.venv/bin/python -m pytest tests/test_frontend.py tests/test_stored.py tests/test_intake.py tests/test_compose.py
```

## Run the app

```bash
docker compose up -d --build --wait
```

Confirm both containers are healthy. Then open:

- http://localhost:8080 for intake
- http://localhost:8080/graph for the policies and ontology stored in Neo4j
- http://localhost:8080/health returns `ok`

## Exercise intake

1. Drop one or more PDFs, or a folder of PDFs, onto “Drop PDF files or a folder here”. The drop zone should say how many PDFs are ready.
2. Or choose PDF files, or choose a local folder.
3. Or paste an http(s) link, or an S3 folder `s3://bucket/policies/`.
4. Leave “Add the analyzed policies to the knowledge graph” checked and submit Analyze policy.
5. The result names the submission folder `submissions/<YYYY-MM-DDTHHMMSS>/`. That directory is on the host and inside the container at `/app/submissions`.
6. Open http://localhost:8080/graph and confirm the new policy, its controls, and the catalogs, profiles, and control groups.
7. A mapped policy is a blue record box. Field names are blue, values are green, and the corner action reads `validated`. The stored graph uses the same boxes for the organization, catalogs, profiles, groups, controls, and policies.

An empty submit must say to provide a policy link, PDFs or a local folder, or an S3 folder.

`docker compose exec app policy-kg query gaps` stays `[]` for the sample baseline. Imported files must not appear as `missing-policy-block` on the next container start, because `submissions/` is outside `data/policies/*.pdf`.
