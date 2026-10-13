---
name: debug-interactive-policy-app
description: >-
  Debugs the interactive policy app when drag-and-drop, a local folder, an S3
  folder, or the stored-graph page fails. Use when localhost:8080 will not
  analyze a submission or /graph does not show Neo4j policies and ontology.
---

# Debug the interactive policy app

Work in `langgragh-sdk-app/`. Start from the running stack:

```bash
docker compose up -d --build --wait
docker compose logs app
docker compose ps
```

`policy-kg-app` must be healthy. Health requires `/tmp/pipeline.ok` and a response from http://127.0.0.1:8080/health inside the container. If the pipeline failed, the page can still be up while the container stays unhealthy. Read the log line `pipeline failed with status`.

## Intake

| What you see | What to change |
| --- | --- |
| Page does not load | Port 8080 is not published, or `policy-kg serve` did not start. Check `docker compose logs app`. |
| Drop zone stays on the hint text | The browser did not receive a PDF. Non-PDF files are ignored by the drop script. |
| `Provide a policy link, PDFs or a local folder, or an S3 folder` | The form posted no file, link, or S3 URI. |
| `No PDF documents were found` | The selection had no bytes starting with `%PDF`. |
| `The upload is empty or larger than 200 MB` | Split the folder. Each PDF must also be at most 15 MB. |
| `Could not read the S3 folder` | The S3 URI or the AWS credential chain failed. Do not put keys in the repo. |
| `File is not a PDF` | A link did not return a PDF. |
| `Neo4j is not connected` on `/graph` | The server was started with `--skip-neo4j`, or Bolt to `neo4j:7687` failed. |
| Submission folder missing on the host | The compose file must mount `./submissions:/app/submissions`. |
| New policy missing from `/graph` | The checkbox to add policies was cleared, or the statement had no matched control. `unmapped-policy` is still stored as a policy node, but the policies query only lists `IMPLEMENTS` edges. |
| Sample run fails with `missing-policy-block` | A sourced PDF was placed in `data/policies/`. Keep uploads under `submissions/`. |

The stored page at http://localhost:8080/graph lists the organization, catalogs, frameworks, profiles, control groups, controls, and policy statements. Compare it with:

```bash
docker compose exec app policy-kg query policies
docker compose exec app policy-kg query frameworks
docker compose exec app policy-kg query gaps
```

`gaps` must be `[]` for the sample baseline. A batch or interactive import merges policies; it does not delete the baseline.
