# CIE Platform Component Model
# File: architecture/component-model.md
# Version: 2.0.0
# Status: Draft
# Note: Skill Layer updated to reflect ADR-0002 3-namespace structure
#       (core/, meta/, user/). Workflow Selection updated per ADR-0001
#       (Orchestrator selects workflow_id; Planner produces intent_object only).

## Purpose

This document defines every architectural component within the CIE Platform.
A component owns a single responsibility.
Components communicate only through contracts.
Components never access another component's internal implementation.

---

## High-Level Architecture

```
                         User
                           │
                           ▼
                  Presentation Layer
                           │
                           ▼
                Intent Interpretation Layer
                           │
                           ▼
                   Workflow Engine
                  (static definitions)
                           │
                           ▼
                   Orchestrator Layer
                  (selects workflow_id;  ← ADR-0001
                   executes DAG)
                           │
      ┌────────────┬───────┴────────┬────────────┐
      ▼            ▼                ▼            ▼
 Data Quality  Statistics      Reporting   Visualization
    Agent        Agent           Agent        Agent
      │            │               │            │
      └────────────┴───────────────┴────────────┘
                           │
                           ▼
                   Runtime Provider
                           │
             ┌─────────────┴──────────────┐
             ▼                            ▼
   Local Restricted Runtime         Docker Runtime
                           │
                           ▼
                  Evaluation Harness
                           │
                           ▼
                    Human Validation
```

---

## Component Classification

| Layer | Responsibility |
|-------|---------------|
| Presentation | User interaction |
| Intent | User objective understanding |
| Workflow | Business process definition |
| Orchestration | Task coordination + workflow selection (ADR-0001) |
| Domain Agents | Domain-specific execution |
| Runtime | Secure execution |
| Evaluation | Validation + Skill performance monitoring (ADR-0002) |
| Knowledge | Reference information |
| Skills | Reusable procedures (core / meta / user — ADR-0002) |

---

## Presentation Layer

**Responsibility:** Provides interaction between users and the platform.
The presentation layer contains no business logic.

Responsibilities:
- UI rendering
- User authentication
- File upload
- Progress display
- Result presentation

Never performs:
- Statistical reasoning
- Workflow definition
- Code generation
- Security decisions

---

## Intent Layer

**Responsibility:** Transforms user requests into structured research intent.

Input:
- Natural language
- Uploaded datasets
- Research metadata

Output: Intent Object (analysis-request.schema.json)

**ADR-0001 clarification:** The Intent Layer (Planner Agent) produces
`intent_object` only. It does NOT set `workflow_id`.
Workflow selection belongs exclusively to the Orchestrator.

---

## Workflow Engine

**Responsibility:** Defines execution order. Owns business processes.
Never performs execution.

All workflow DAGs are statically defined in spec/workflow.yaml.
No agent may add, remove, or modify DAG nodes at runtime (ADR-0001).

---

## Orchestrator

**Responsibility:** Coordinates system execution.

The orchestrator owns:
- workflow_id determination from intent_object (ADR-0001)
- task scheduling
- dependency resolution
- agent invocation
- error propagation
- retry policy

The orchestrator never performs analysis.

---

## Domain Agents

Every domain agent owns one business capability. Agents are isolated.

### Data Quality Agent
- Schema validation, missing value detection, outlier inspection
- Variable classification, PII detection
- Produces: Validated Dataset, Quality Report

### Statistics Agent
- Method selection, assumption checking, statistical planning, R script generation
- Produces: Analysis Plan, Statistical Report, Execution Request

### Visualization Agent
- Figure generation, theme selection, publication formatting
- Produces: Figures, Graph Metadata

### Reporting Agent
- Report composition, result explanation
- APA / CONSORT / STROBE / TRIPOD+AI formatting
- Produces: Clinical Report, Publication Draft

### Reviewer Agent
- Statistical review, internal consistency, completeness checking
- Publication readiness
- Produces: Review Report, Quality Score

### Security Agent
- Permission validation, security policy enforcement
- PII review, runtime authorization
- Produces: Authorization Decision, Security Report

---

## Runtime Provider

Runtime Provider abstracts execution.

Supported implementations:
- Local Restricted Runtime
- Docker Runtime
- Future Remote Runtime

Agents never communicate directly with runtime implementations.

---

## Knowledge Layer

Knowledge is read-only.
Knowledge includes: Clinical Guidelines, Statistical References,
Writing Standards, Package Documentation, Medical Terminology.
Knowledge never executes.

---

## Skill Layer

Skills define reusable procedures.
**Updated per ADR-0002:** Three namespaces.

```
skills/
  core/          Official CIE Skills (immutable without SkillLifecycle)
    statistics/  t-test/, anova/, regression/, survival/, correlation/
    visualization/ group-comparison/, survival/
    reporting/   table-one/, manuscript-section/
  meta/          Self-improvement infrastructure
    skill-evaluator/, skill-proposer/, skill-scaffolder/
  user/          User-defined Skills (Human Authority required)
    REGISTRY.yaml
```

Each skill contains: `SKILL.md`, `examples/`, `tests/`, `versions/` (core only)

**Priority:** user/ > core/ when skill_id conflicts.
**meta/** cannot be overridden.

---

## Evaluation Harness

Evaluates every important artifact.

Evaluation dimensions:
- Scientific correctness
- Statistical validity
- Security
- Schema compliance
- Workflow consistency
- Reproducibility
- Explainability
- Skill performance (ADR-0002: regression.yaml skill_performance_monitoring)

---

## Configuration Layer

Stores: Runtime selection, LLM provider, Evaluation thresholds,
Permission policies, Feature flags.
Configuration contains no business logic.

---

## Communication Model

Every component communicates through schemas.

Allowed:
```
Component → Schema → Component
```

Forbidden:
```
Component → Internal State → Component
```

---

## Dependency Graph

Allowed:
```
Presentation → Intent → Workflow → Orchestrator → Agents → Runtime → Evaluation
```

Forbidden:
- Runtime → Presentation
- Agent → Agent Internal State
- Workflow → Runtime
- Knowledge → Runtime
- Planner → workflow_id (ADR-0001)

---

## Component Lifecycle

Every component follows:
```
Initialize → Validate Input → Execute Responsibility
→ Validate Output → Publish Result → Dispose Resources
```

No component retains mutable state beyond its execution
unless explicitly defined by architecture.

---

## Failure Handling

Each component must declare:
- Recoverable failures
- Non-recoverable failures
- Retry policy
- Fallback strategy
- Logging requirements

Failure information is propagated upward through the orchestrator.

---

## Extensibility Rules

New functionality shall be introduced by:
- Adding new agents
- Adding new workflows (via ADR + spec/workflow.yaml)
- Adding new skills (core via SkillLifecycle; user via REGISTRY)
- Adding new knowledge modules
- Adding new runtime providers

Core components should remain unchanged.

---

## Component Quality Requirements

Every component shall satisfy:
- Single Responsibility
- Explicit Interface
- Schema Validation
- Permission Declaration
- Evaluation Support
- Observability
- Testability
- Replaceability

Any component failing these requirements shall not be accepted
into the platform architecture.
