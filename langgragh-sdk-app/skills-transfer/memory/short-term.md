# Short-term memory — 2026-10-13

Read `README.md` and `long-term.md` first. This file is the handoff for the next Cursor session.

## Done in this session

- The app runs as Compose project `policy-kg` on `policy-kg-net`.
- http://localhost:8080 accepts a drag-and-drop, a local folder, a policy link, or an S3 folder (`s3://bucket/prefix/`).
- Each submission run is a date-time folder under `submissions/`, bind-mounted into the app container at `/app/submissions`. The contents are gitignored. The baseline scan does not read them.
- http://localhost:8080/graph shows the policies and the OSCAL ontology stored in Neo4j.
- Analysis results and the stored graph render each record as a blue box. Field names are blue, values are green, and a mapped policy shows `validated` in the corner.
- `policy-kg batch --from-dir` and `policy-kg batch --s3-uri` stage PDFs into one submission folder and can merge them into Neo4j.
- Skills for those runs: `test-batch-policy-pipeline`, `debug-batch-policy-pipeline`, `test-interactive-policy-app`, `debug-interactive-policy-app`.
- This folder is the pack to copy to another Cursor account: changes log, Claude skills, Kiro power, and these memory files.

## Check first next time

1. `docker compose up -d --build --wait` from `langgragh-sdk-app/`.
2. Open http://localhost:8080, submit a PDF or a link, and confirm the analysis names a control when the text supports one.
3. `docker compose exec app policy-kg query gaps` should still be `[]` for the sample baseline.
4. Run `.venv/bin/python -m pytest` from `langgragh-sdk-app/`. The `pytest` script shebang can still point at the old `langgraph/.venv` path; the `python -m pytest` form is the one that works. Recreate the venv with `make install` if the host CLI is needed. Docker does not use that venv.
5. Do not rewrite `changes-log/2026-10-13.md`. Add a new dated file when the next change lands, and update this short-term file.

## Not done

Nothing is pushed to a remote. The next session should not push unless asked.
