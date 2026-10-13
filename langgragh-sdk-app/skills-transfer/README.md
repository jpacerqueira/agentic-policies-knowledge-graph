# Skills transfer

This folder is the portable pack for the Northline Bank policy knowledge-graph app in `langgragh-sdk-app/`. Copy the whole folder into another Cursor session, or open this repository there, and start from this file.

The app reads DevSecOps policy PDFs, loads OSCAL (including the EU AI Act catalog shape), and writes a Neo4j graph for a fictional tier-1 bank of 100,000 employees. It is not legal advice and not a conformity assessment.

## What is inside

| Path | Role |
| --- | --- |
| `changes-log/` | Dated record of what was built. `2026-10-13.md` is the first day. Append a new file for a later day. Do not rewrite an older log. |
| `claude/skills/` | Claude skills. Each skill is a `SKILL.md` with `name` and `description` frontmatter. |
| `kiro/policy-pipeline/` | The Kiro power. `plugin.json` is the manifest. `skills/` is a byte-for-byte copy of the Claude skills. |
| `memory/long-term.md` | Stable facts: architecture, containers, organization, and rules that should survive across sessions. |
| `memory/short-term.md` | Current state: the intake page, how to run it, and what the next session should check first. |

The skills are:

- `code-pdf-policy-pipeline` — add or change a PDF policy and its OSCAL mapping
- `test-pdf-policy-pipeline` — run the suite and fix a failing test without hiding the gap
- `deploy-pdf-policy-pipeline` — start the Compose stack and check the GitHub Actions deploy workflow
- `debug-pdf-policy-run` — read finding codes, Neo4j errors, and a failed intake
- `test-batch-policy-pipeline` — test a folder or S3 batch run and its `submittions` date-time folder
- `debug-batch-policy-pipeline` — debug a failed `policy-kg batch` run
- `test-interactive-policy-app` — test drag-and-drop, local folder, S3 folder, and the stored-graph page
- `debug-interactive-policy-app` — debug the intake page and http://localhost:8080/graph

## Use the skills in this session

From `langgragh-sdk-app/`, ask the agent to follow the skill that matches the task. The agent should open the `SKILL.md` and do what it says.

Examples:

- “Follow `code-pdf-policy-pipeline` and add POL-NEW-001 for control aia-9.”
- “Follow `test-pdf-policy-pipeline` and run the suite.”
- “Follow `deploy-pdf-policy-pipeline` and start the stack.”
- “Follow `debug-pdf-policy-run`. The intake page returned `unmapped-policy`.”
- “Follow `test-batch-policy-pipeline` for a folder of new PDFs.”
- “Follow `debug-batch-policy-pipeline`. `policy-kg batch` exited 1.”
- “Follow `test-interactive-policy-app` and check drag-and-drop plus `/graph`.”
- “Follow `debug-interactive-policy-app`. The stored graph page is empty.”

Before changing the app, also read `memory/long-term.md` and `memory/short-term.md`.

## Transfer the pack to another Cursor session

1. Commit or copy this repository. The pack lives at `langgragh-sdk-app/skills-transfer/`. Secrets are not in this folder. The Compose password `policy-graph-local` is a local development default.
2. On the other machine, open the repository in Cursor with the account you want to continue from.
3. In the first message of that session, point the agent here:

   `Read langgragh-sdk-app/skills-transfer/README.md, then memory/long-term.md and memory/short-term.md, and continue from the short-term file.`

4. To install the skills so Cursor or Claude can discover them, copy each skill directory:

   ```bash
   mkdir -p .cursor/skills .claude/skills
   cp -R langgragh-sdk-app/skills-transfer/claude/skills/. .cursor/skills/
   cp -R langgragh-sdk-app/skills-transfer/claude/skills/. .claude/skills/
   ```

   Run that from the repository root. Copying into `.cursor/skills/` makes the skills available to a Cursor session in this project. Copying into `.claude/skills/` is the Claude Code layout.

5. For Kiro, import the power directory `langgragh-sdk-app/skills-transfer/kiro/policy-pipeline` (the folder that contains `plugin.json`).

6. Keep the two skill trees identical. After you edit a `SKILL.md`, copy it to the other tree:

   ```bash
   rm -rf langgragh-sdk-app/skills-transfer/kiro/policy-pipeline/skills
   cp -R langgragh-sdk-app/skills-transfer/claude/skills langgragh-sdk-app/skills-transfer/kiro/policy-pipeline/skills
   ```

7. When the session ends, update `memory/short-term.md` with what changed and what to do next. Add a new file under `changes-log/` named with that day’s date. Leave `2026-10-13.md` as the historical record.

## Runtime the skills assume

Work in `langgragh-sdk-app/`. The only runtime is Docker Compose project `policy-kg`: containers `policy-kg-neo4j` and `policy-kg-app` on the dedicated network `policy-kg-net`.

```bash
docker compose up -d --build --wait
```

- Policy intake: http://localhost:8080
- Neo4j Browser: http://localhost:7474 (`neo4j` / `policy-graph-local`)
- Queries: `docker compose exec app policy-kg query policies` and `docker compose exec app policy-kg query gaps`

The intake page accepts an http(s) link or a sourced PDF. Uploaded files are stored in `data/intake/` and are not part of the baseline `data/policies/*.pdf` scan.
