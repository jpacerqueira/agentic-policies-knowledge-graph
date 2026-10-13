# agentic-policies-knowledge-graph

LangGraph pipeline, tests, and deploy workflow for a DevSecOps and OSCAL knowledge graph.

The application lives in [`langgragh-sdk-app/`](langgragh-sdk-app/README.md). It reads policy PDFs, loads OSCAL (including the EU AI Act catalog shape from [olon-standards/eu-ai-act-oscal](https://github.com/olon-standards/eu-ai-act-oscal)), and writes a local Neo4j graph for a fictional tier-1 bank of 100,000 employees.

Agent instructions for coding, testing, deploying, and debugging a new policy PDF are in [`langgragh-sdk-app/skills-transfer/README.md`](langgragh-sdk-app/skills-transfer/README.md). That README explains the changes log, the Claude skills, the Kiro power, and how to carry the pack into another Cursor session.
