---
name: test-batch-policy-pipeline
description: >-
  Tests a batch ingest of policy PDFs from a local folder or an S3 folder into
  the Northline knowledge graph. Use when running or checking policy-kg batch,
  a folder of PDFs, or an s3:// prefix.
---

# Test a batch policy run

Work in `langgragh-sdk-app/`. A batch run is one submission. It copies PDFs into `submittions/<YYYY-MM-DDTHHMMSS>/` and aligns them to the loaded OSCAL catalogs. This is not legal advice and not a conformity assessment.

## Automated test

```bash
.venv/bin/python -m pytest tests/test_batch.py tests/test_intake.py
```

If `.venv/bin/pytest` points at a removed interpreter, use `.venv/bin/python -m pytest`.

## Folder batch without Neo4j

Put PDFs in a directory and analyze them without writing the graph:

```bash
policy-kg batch \
  --from-dir data/incoming \
  --oscal-dir data/oscal \
  --organization data/organization.json \
  --intake-dir submittions \
  --skip-neo4j \
  --report /tmp/policy-kg-batch.json
```

Exit 0 means every PDF was read. Exit 1 means a document failed or the folder had no PDFs. Exit 2 means the command could not start. `submission_dir` in the report is the date-time folder. Nested PDFs are included. Other file types are ignored.

## Folder batch inside the running stack

`./data` and `./submittions` are mounted into `policy-kg-app`. Copy new PDFs under `data/incoming/` on the host, then:

```bash
docker compose exec app policy-kg batch \
  --from-dir data/incoming \
  --oscal-dir data/oscal \
  --organization data/organization.json \
  --intake-dir submittions
```

Then open http://localhost:8080/graph and confirm the new policy ids. `docker compose exec app policy-kg query gaps` must still be `[]` for the sample baseline.

## S3 folder

```bash
docker compose exec app policy-kg batch \
  --s3-uri s3://bucket/policies/ \
  --oscal-dir data/oscal \
  --organization data/organization.json \
  --intake-dir submittions
```

The URI must look like `s3://bucket/prefix/`. A key that ends in `.pdf` is one object. Any other prefix lists PDF objects under it. Credentials come from the AWS default chain. Do not put access keys in the repository.

## Pass criteria

- The report `ok` field is true.
- Each document lists `policy_id` values and matched control ids.
- The date-time directory exists under `submittions/` and contains only the staged PDFs.
- A second run in the same second uses a `-2` suffix and does not overwrite the first folder.
