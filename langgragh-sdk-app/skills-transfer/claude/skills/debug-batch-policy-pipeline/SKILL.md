---
name: debug-batch-policy-pipeline
description: >-
  Debugs a failed batch ingest of policy PDFs from a folder or an S3 folder.
  Use when policy-kg batch exits 1 or 2, an S3 prefix returns no documents, or
  a submission folder is missing from submittions.
---

# Debug a batch policy run

Work in `langgragh-sdk-app/`. Reproduce with `--skip-neo4j` first so the JSON report is the source of truth.

```bash
policy-kg batch \
  --from-dir data/incoming \
  --oscal-dir data/oscal \
  --organization data/organization.json \
  --intake-dir submittions \
  --skip-neo4j \
  --report /tmp/policy-kg-batch.json
```

## Exit codes

Exit 0: every document was read. Exit 1: a document failed, or the folder or S3 prefix contained no PDFs. Exit 2: the folder is missing, the S3 URI is not `s3://bucket/prefix`, OSCAL or the organization file is missing, or Neo4j could not be reached. Add `--skip-neo4j` to separate analysis from the database.

## Report fields

| What you see | What to change |
| --- | --- |
| `Folder not found` | Pass a directory that exists inside the container. Host paths must be under `./data` or `./submittions`. |
| `Folder contains no PDF files` | The scan is recursive and only accepts `.pdf`. |
| `S3 location contains no PDF objects` | Check the prefix. Non-PDF keys are skipped. |
| `S3 location must look like s3://bucket/prefix` | Use the `s3://` scheme and a bucket name. |
| `File is not a PDF` | The object does not start with `%PDF`. |
| `PDF is larger than 15 MB` | Split or shrink that file. The rest of the run can still be staged. |
| `Could not read the S3 folder` | The container has no AWS credentials or the bucket is unreachable. Do not write keys into the repo. |
| `unreadable-pdf` | pypdf could not read the file. |
| `sourced-text` | There was no policy block. Alignment used the extracted text. |
| `unmapped-policy` | No declared, phrase, or overlap match. The statement was still stored when persist is on. |
| `unknown-control` | A declared id is not in a loaded catalog. |
| `submission_dir` empty | Nothing was staged, so no date-time folder was created. |

Open the date-time directory named in `submission_dir` and confirm the PDFs are the copies that were analyzed. The original folder is not modified.

After a persisted run, http://localhost:8080/graph should list the new policy ids. If the page is empty, the batch used `--skip-neo4j` or Neo4j was not the compose database `bolt://neo4j:7687`.
