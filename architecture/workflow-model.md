# CIE Platform Workflow Model
# File: architecture/workflow-model.md
# Version: 2.1.0
# Status: Draft
# Changelog v2.1.0 (ADR-0001):
#   - Workflow Selection section added: Orchestrator selects workflow_id
#   - Planner produces intent_object only (does not select workflow)
#   - 4 static workflows defined in spec/workflow.yaml
#   - workflow_selection_rules (WS-001 to WS-004) documented

## Purpose

This document defines how business workflows are modeled, executed, validated,
and evolved within the CIE Platform.

Workflows represent business intent.
Agents execute workflows.
Workflows are architecture.
Agents are implementation.

---

## Definition

A workflow is a declarative description of:
- business objectives
- execution sequence
- dependencies
- decision points
- validation requirements
- completion criteria

A workflow never contains implementation code.

---

## Workflow Architecture

```
Intent (intent_object from Planner)
        │
        ▼
Workflow Selection (Orchestrator — ADR-0001)
  WS-001: outcome_type=survival    → clinical_analysis_survival
  WS-002: objective=systematic_review → clinical_analysis_meta
  WS-003: objective=prediction_model  → clinical_analysis_prediction
  WS-004: default                  → clinical_analysis_standard
        │
        ▼
Workflow Instance (from spec/workflow.yaml — static)
        │
        ▼
Task Graph (DAG — immutable at runtime)
        │
        ▼
Agent Execution
        │
        ▼
Validation
        │
        ▼
Evaluation
        │
        ▼
Completion
```

---

## ADR-0001: Planner vs Orchestrator Boundary

This is the most critical architectural boundary in the workflow layer.

| Component | Responsibility | Forbidden |
|-----------|---------------|-----------|
| Planner Agent | Produces `intent_object` | Setting `workflow_id` |
| Orchestrator | Selects `workflow_id` via WS-rules | Modifying `intent_object` |
| Workflow definitions | Static DAG in spec/workflow.yaml | Runtime mutation |

The boundary in one sentence:
**Planner decides WHAT. Orchestrator decides HOW.**

---

## Workflow Lifecycle

```
Created → Validated → Planned → Executed
       → Verified → Evaluated → Completed → Archived
```

Failure at any stage returns control to the Orchestrator.

---

## Workflow Components

Each workflow contains:
```
Workflow
  ├── Metadata
  ├── Intent mapping (handled by Orchestrator WS-rules)
  ├── Inputs
  ├── Preconditions
  ├── Tasks (DAG nodes)
  ├── Decision Nodes
  ├── Outputs
  ├── Validation Rules
  ├── Evaluation Rules
  └── Completion Rules
```

---

## Registered Workflows (spec/workflow.yaml)

| workflow_id | Category | WS-Rule |
|-------------|---------|---------|
| `clinical_analysis_standard` | Statistics (default) | WS-004 |
| `clinical_analysis_survival` | Survival analysis | WS-001 |
| `clinical_analysis_meta` | Meta-analysis | WS-002 |
| `clinical_analysis_prediction` | Prediction model | WS-003 |

New workflows require an ADR entry and static definition in spec/workflow.yaml.
Dynamic workflow generation is forbidden (ADR-0001 Principle 1).

---

## Workflow Instance

A workflow definition is immutable.
Execution creates a Workflow Instance.

```
Workflow Definition (static)
        ↓
Workflow Instance #00021
        ↓
Execution State
        ↓
Results → Archived
```

Definitions never store execution state.

---

## Task Model

Each workflow consists of Tasks.
Tasks are atomic. Tasks own exactly one responsibility.

Standard task sequence (clinical_analysis_standard):
```
intake → validate_dataset → classify_variables
→ detect_missing_values → detect_outliers
→ select_analysis → assumption_check
→ decision_assumption → generate_r_script
→ security_review (human approval)
→ runtime_execution → visualization
→ reporting → reviewer → evaluation
```

---

## Task Requirements

Each task declares:
- Identifier
- Description
- Required Inputs
- Expected Outputs
- Responsible Agent
- Dependencies
- Retry Policy
- Validation Rules
- Completion Criteria

---

## Dependency Model

Tasks form a Directed Acyclic Graph (DAG).
Circular dependencies are prohibited.

---

## Decision Nodes

Some workflows require branching.

Example:
```
Normal Distribution?
        │
   ┌────┴────┐
  Yes        No
   │          │
t-test   Mann-Whitney U
```

Decision rules are explicit and testable.
`decision_branch_taken` is recorded in every decision node (AP-018).

---

## Human Decision Nodes

Some workflow steps require human approval (AP-010):
- Export Report
- Install Package
- Execute R script (security_review node)
- External API Call
- Architecture Modification

Execution pauses until approval.
Approval events are logged in immutable audit_log.

---

## Workflow State Machine

Valid states (matches orchestrator.yaml):
```
draft → validated → planned → running
→ waiting_for_human → retrying
→ completed → failed → cancelled → archived
```

State transitions are controlled by the Orchestrator.

---

## Agent Assignment

Workflows define WHAT. Agents define HOW.

```
Workflow: "Perform Assumption Check"
        ↓
Statistics Agent
        ↓
Chooses implementation (per knowledge/statistics/assumption_checklist.md)
```

Workflows never call runtime directly.

---

## Evaluation Stage

Every completed workflow is evaluated against:
- Scientific Correctness (evaluation/correctness.yaml)
- Statistical Validity (evaluation/statistical.yaml)
- Security Compliance (evaluation/security.yaml)
- Usability (evaluation/usability.yaml)
- Regression / Behavioral Consistency (evaluation/regression.yaml)

Minimum passing score: 90/100 per dimension.

---

## Error Handling

Recoverable (retry up to 3 times):
- runtime_timeout
- temporary_io_failure
- runtime_busy

Non-Recoverable (immediate abort):
- schema_validation_failure
- security_violation
- permission_denied
- corrupted_dataset

---

## Retry Policy

```yaml
retry:
  maximum_attempts: 3
  backoff: exponential
  retryable:
    - runtime_timeout
    - temporary_io_failure
    - runtime_busy
```

Agents never invent retry logic.

---

## Workflow Versioning

Workflow Definitions: Immutable
Workflow Instances: Mutable, archived after completion
Older workflow versions remain reproducible.

---

## Workflow Quality Requirements

Every workflow shall satisfy:
- Single Purpose
- Schema Validation
- Deterministic Flow
- Explicit Decision Rules
- Observable Execution
- Version Traceability
- Evaluation Support
- Security Compliance
- Human Review Support
- Reproducibility

---

## Architectural Rule

Business knowledge belongs inside workflows.
Execution knowledge belongs inside agents.
Infrastructure knowledge belongs inside runtime providers.

Mixing these responsibilities is an architectural violation.
