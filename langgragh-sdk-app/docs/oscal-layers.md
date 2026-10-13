# OSCAL layers in the policy graph

The graph follows the method in [Exploring OSCAL Using Neo4J](https://blog.container-solutions.com/exploring-oscal-using-neo4j) and the loader layout in [ContainerSolutions/oscal-neo4j](https://github.com/ContainerSolutions/oscal-neo4j). Each OSCAL model is one layer. A node is merged on its uuid or id, so the same party, role, or control is one node when a later document refers to it. An import href connects the later layer to the earlier document.

This is a model of the control lifecycle for Northline Bank plc. It is not legal advice and not a conformity assessment.

## How a layer is loaded

The blog loads one example folder at a time: a JSON document, a Cypher script that `MERGE`s nodes, and a shell script that runs that script. `make full-rebuild` wipes Neo4j and loads every example again.

This app does the same work in one pipeline run:

1. `load_oscal` reads every JSON model under `data/oscal`.
2. `project` writes one `Layer` node per model, in lifecycle order, under the `Ontology` node `oscal-control-lifecycle`.
3. Each root document gets an `IN_LAYER` edge. Controls, groups, and requirements stay attached to that document by the containment edges below.
4. `persist` merges the document into Neo4j. A rebuild is `docker compose down -v` and `docker compose up -d --build --wait`, which drops the old graph and loads it again.

`policy-kg query layers` returns the eight layers and how many documents sit in each one. The stored page at http://localhost:8080/graph shows the same list.

## Ontology

| Order | Layer id | Root node | What it holds |
| --- | --- | --- | --- |
| 1 | `catalog` | `Catalog` | Groups, controls, parts, parameters |
| 2 | `profile` | `Profile` | Selected controls and set parameters, imported from a catalog |
| 3 | `component-definition` | `ComponentDefinition` | Components and the requirements they implement |
| 4 | `system-security-plan` | `SystemSecurityPlan` | System characteristics, components, users, roles, parties, imported profile |
| 5 | `assessment-plan` | `AssessmentPlan` | Tasks and the controls reviewed for the imported plan |
| 6 | `assessment-results` | `AssessmentResults` | Findings against controls, imported from the assessment plan |
| 7 | `plan-of-action-and-milestones` | `PlanOfAction` | POA&M items, risks, and the controls those items address |
| 8 | `policy` | `PolicyStatement` | Bank policy text that implements a control |

`Layer` nodes are chained with `FOLLOWS` so the order is the control lifecycle: catalog, then profile, then implementation, then the system plan, then assessment, then results, then corrective action, then the bank policies that sit on the controls.

The sample data has no assessment-results file. That layer still exists. Its document count is zero until a file is added.

## Models and the edges that join them

Identity:

- `Catalog`, `Profile`, `ComponentDefinition`, `SystemSecurityPlan`, `AssessmentPlan`, `AssessmentResults`, `PlanOfAction`, `Party`, `Component`, `User`, `ImplementedRequirement`, `Finding`, `Risk`, `PoamItem` merge on `uuid`.
- `Control` merges on `catalog_uuid` plus `control_id`. Two catalogs can share a display id without becoming one node. The blog's single-catalog examples merge `Control` on `id` alone.
- `Role` merges on `role_id`. A role named in the system security plan and again in an assessment plan is one node.
- `Layer` merges on `layer_id`.

Containment, in the same direction the blog draws:

- `Catalog -HAS_GROUP-> ControlGroup -HAS_CONTROL-> Control`
- `Control -HAS_PART-> ControlPart` and `Control -HAS_PARAMETER-> Parameter`
- `ComponentDefinition -HAS_COMPONENT-> Component -HAS_REQUIREMENT-> ImplementedRequirement -SATISFIES-> Control`
- `SystemSecurityPlan -HAS_COMPONENT-> Component`, `-HAS_ROLE-> Role`, `-HAS_PARTY-> Party`
- `User -HAS_ROLE-> Role`
- `AssessmentPlan -HAS_TASK-> AssessmentTask`
- `AssessmentResults -HAS_FINDING-> Finding`
- `PlanOfAction -HAS_ITEM-> PoamItem`
- `Document -CONTAINS_POLICY-> PolicyStatement`

Imports and shared references:

- `Profile -IMPORTS-> Catalog` and `Profile -SELECTS-> Control`
- `SystemSecurityPlan -IMPORTS_PROFILE-> Profile` and `-DESCRIBES-> System`
- `AssessmentPlan -IMPORTS_SSP-> SystemSecurityPlan` and `-REVIEWED_CONTROL-> Control`
- `AssessmentResults -IMPORTS_AP-> AssessmentPlan`
- `PlanOfAction -IMPORTS_SSP-> SystemSecurityPlan`
- `Role -RESPONSIBLE_PARTY-> Party` when a document names that pair
- `PoamItem -RELATED_TO_RISK-> Risk` and `-ADDRESSES-> Control`
- `PolicyStatement -IMPLEMENTS-> Control` when alignment matched

`Organization -OPERATES-> System` is the bank context around the system security plan. It is not an OSCAL model.

## What a rebuild replaces

Wiping the Neo4j volume removes every node, including labels left by an older projection. The next `policy-kg run` inside `policy-kg-app` writes this ontology again. Queries that still use `REVIEWS`, `RELATED_RISK`, and `DEFINES` keep working: those edges are written next to `REVIEWED_CONTROL`, `RELATED_TO_RISK`, and `HAS_COMPONENT`.
