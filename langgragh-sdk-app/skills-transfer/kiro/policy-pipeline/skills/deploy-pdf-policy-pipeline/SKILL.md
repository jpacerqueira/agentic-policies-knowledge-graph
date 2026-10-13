---
name: deploy-pdf-policy-pipeline
description: >-
  Deploys the LangGraph policy pipeline and the local Neo4j knowledge graph
  with Docker Compose, and checks the GitHub Actions deploy workflow. Use when
  deploying the pipeline, publishing the container image, or starting Neo4j.
---

# Deploy the policy pipeline

Work in `langgragh-sdk-app/`. The local Neo4j password in compose is a development default, not a production secret.

## Local deploy

The only runtime is `docker-compose.yml`. It starts `policy-kg-neo4j` and `policy-kg-app` on the dedicated network `policy-kg-net`. Do not attach these containers to another network.

```bash
docker compose up -d --build --wait
```

`make deploy` is that command. Both containers stay up. The app container runs the pipeline once Neo4j is healthy, then serves the policy intake page on port 8080. Neo4j Browser stays at http://localhost:7474. The intake page is http://localhost:8080. The stored policies and ontology are at http://localhost:8080/graph.

`submissions/` on the host is mounted at `/app/submissions` in `policy-kg-app`. Do not commit files dropped there.

Check the load from the app container, which is on `policy-kg-net`:

```bash
docker compose exec app policy-kg query policies
docker compose exec app policy-kg query gaps
```

`gaps` must be an empty list for the sample baseline.

## GitHub Actions

- `.github/workflows/test.yml` runs pytest against `neo4j:5.26-community` on every push and pull request.
- `.github/workflows/deploy.yml` builds `langgragh-sdk-app/Dockerfile` and pushes `ghcr.io/<owner>/<repo>/policy-kg` on `workflow_dispatch` and on pushes to `main` that change `langgragh-sdk-app/**`.

Confirm `deploy.yml` still has `workflow_dispatch`, `docker/build-push-action`, and context `langgragh-sdk-app` before treating a deploy as ready. Do not put a real registry password in the repo. `GITHUB_TOKEN` is the registry credential in the workflow.
