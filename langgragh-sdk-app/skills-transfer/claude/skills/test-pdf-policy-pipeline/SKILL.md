---
name: test-pdf-policy-pipeline
description: >-
  Runs and fixes the policy knowledge-graph test suite, including Neo4j. Use
  when testing a PDF policy change, a LangGraph pipeline change, or a failing
  pytest.
---

# Test the policy pipeline

Work in `langgragh-sdk-app/`. Run the whole suite. Do not skip the Neo4j test.

## Setup

```bash
python3.13 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev]"
```

GitHub Actions uses Python 3.12. Locally, 3.12 or 3.13 both match `requires-python`.

## Run

```bash
.venv/bin/pytest
```

`tests/conftest.py` starts `docker-compose.test.yml` (project `policykgtest`, Bolt `localhost:7688`) when `NEO4J_URI` is unset. The suite wipes that database. It refuses to wipe a database whose password is not `policy-graph-test`.

In CI, `.github/workflows/test.yml` provides Neo4j and sets:

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=policy-graph-test
```

## When a test fails

1. Read the finding code or traceback.
2. Fix the pipeline or the sample OSCAL. Do not weaken the assertion to hide a real gap.
3. Add a regression test if the bug was not already named.
4. Run `pytest` again until it exits 0.
5. Stop the disposable database with `make test-down` only after the suite is green if you need the port freed.

`make test` is the same pytest entry point after `make install`. If `.venv/bin/pytest` points at a removed interpreter, run `.venv/bin/python -m pytest`.

`tests/test_intake.py`, `tests/test_analyze.py`, `tests/test_frontend.py`, `tests/test_batch.py`, and `tests/test_stored.py` cover a policy link, a sourced PDF, drag-and-drop and folder intake, S3 and folder batch, and the stored-graph page. Keep those passing when the page changes.

For a batch run follow `test-batch-policy-pipeline`. For the interactive app follow `test-interactive-policy-app`.
