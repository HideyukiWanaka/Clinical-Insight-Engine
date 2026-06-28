# PROJECT_RULES.md
# CIE Platform Project Constitution
# Version: 2.1.0
# Status: Draft
# Changelog v2.1.0:
#   - Section 11: Skills updated to reflect ADR-0002 3-namespace structure
#   - Section 17: Definition of Done updated (skill_lifecycle_defined)
#   - Section 18: Long-Term Compatibility updated (User Skills, ADR-0001/0002)

---

## 1. Purpose

CIE is an AI-native platform for clinical research support.

The objective is not to generate code.
The objective is to produce reproducible, statistically valid, explainable,
and secure clinical analyses.

Every architectural decision must support this objective.

---

## 2. Core Philosophy

The platform is built around the following priorities.

1. Scientific correctness
2. Patient privacy
3. Reproducibility
4. Explainability
5. Maintainability
6. Extensibility
7. User experience
8. Performance

Performance must never compromise scientific correctness.

---

## 3. Architecture Principles

The architecture shall follow these principles.

### 3.1 Intent Driven
User intent is the primary input.
The system shall never optimize only for prompt completion.

### 3.2 Workflow First
Business workflows are first-class objects.
Agents execute workflows.
Agents never define workflows.

### 3.3 Agent Oriented
Each agent owns one responsibility.
Agents must remain independent.
Agents communicate only through defined contracts.

### 3.4 Offline First
The platform must operate without Internet connectivity.
Internet access is optional.
Internet access is never required.

### 3.5 Security By Design
Security is designed into every layer.
Security is never added later.

### 3.6 Evaluation Driven
Every generated artifact shall be evaluated.
Generated outputs are not trusted by default.

### 3.7 Human Oversight
Critical decisions require human approval.
The system assists.
The human decides.

---

## 4. Responsibility Rules

Every component owns exactly one responsibility.
No component may own multiple business domains.

**GOOD**
```
Statistics Agent → Statistics only
```

**BAD**
```
Statistics Agent → Statistics + Visualization + Reporting
```

---

## 5. Dependency Rules

**Allowed**
```
UI → Workflow → Agents → Runtime
```

**Forbidden**
```
UI → Runtime
Agents → UI
Knowledge → Workflow
Circular dependencies
```

---

## 6. Communication Rules

Components communicate through contracts.
Never through implementation.

**Allowed:** Schema / Interface / Contract

**Forbidden:** Internal variables / Hidden state / Prompt injection /
Undocumented behavior

---

## 7. Runtime Rules

Every execution environment is abstracted.
Runtime implementations may include:
- Local Restricted Runtime
- Docker Runtime
- Future Remote Runtime

No business logic may depend on runtime implementation.

---

## 8. Security Rules

**Default policy:** Deny first. Allow explicitly.
Every permission must be declared.
Nothing is implicitly trusted.

- Internet access: Denied
- Filesystem access: Restricted
- Shell execution: Restricted
- Package installation: Approval required
- External APIs: Approval required
- Skill file updates: Approval required (ADR-0002)
- User Skill registration: Approval required (ADR-0002)

---

## 9. Agent Rules

Each agent must define:
- Goal
- Responsibilities
- Inputs
- Outputs
- Dependencies
- Permissions
- Evaluation metrics
- Failure handling
- Retry policy

No agent may exceed its responsibility.

---

## 10. Workflow Rules

Workflows are declarative.
Agents execute workflows.
Agents never modify workflow definitions.
Workflow changes require architecture review.

**ADR-0001 addition:**
Planner Agent produces `intent_object` only.
Orchestrator selects `workflow_id` via deterministic rules (WS-001 to WS-004).
No agent may add or remove DAG nodes at runtime.

---

## 11. Skill Rules

Skills contain:
- Knowledge
- Best practices
- Procedures
- Examples
- Validation

**ADR-0002: Three-namespace structure**

| Namespace | Location | Who updates | Governance |
|-----------|----------|-------------|------------|
| core | skills/core/ | CIE team | SkillLifecycle process + Human approval |
| meta | skills/meta/ | CIE team | CIE team only |
| user | skills/user/ | Users | Human approval + REGISTRY.yaml |

**Core Skills** never contain project-specific business logic.

**User Skills** may contain project-specific procedures (施設固有手順)
under Human Authority control. They must not contain:
- Hardcoded patient data
- Workflow definition mutations (ADR-0001 violation)
- Security policy bypasses
- External network access code
- Direct dependencies on other User Skills

Skill update priority: user/ > core/
meta/ cannot be overridden.

---

## 12. Knowledge Rules

Knowledge is immutable during execution.
Knowledge never contains executable code.
Knowledge is versioned.
Knowledge is traceable.

---

## 13. Schema Rules

Everything crossing component boundaries must have a schema.
Schemas are the source of truth.
No undocumented payloads are permitted.

---

## 14. Coding Rules

- Readable over clever
- Explicit over implicit
- Composition over inheritance
- Configuration over hardcoding
- Small modules
- Pure functions where possible
- Business logic separated from infrastructure

---

## 15. AI Development Rules

Before implementation an AI must:
1. Read MANIFEST.yaml
2. Read PROJECT_RULES.md
3. Read relevant ADR (decisions/)
4. Load required architecture
5. Load related specifications
6. Validate schemas
7. Load affected agent definitions
8. Load workflow definitions
9. Check skill namespace (core/meta/user) before any skill change

Only then generate code.

---

## 16. Forbidden Behaviors

- Never modify architecture silently
- Never bypass security
- Never ignore schemas
- Never skip evaluation
- Never disable validation
- Never hardcode permissions
- Never duplicate business logic
- Never introduce circular dependencies
- Never create hidden workflows
- Never set workflow_id from Planner Agent (ADR-0001)
- Never mutate DAG nodes at runtime (ADR-0001)
- Never update core Skills without SkillLifecycle process (ADR-0002)
- Never register User Skills without human approval (ADR-0002)

---

## 17. Definition of Done

A task is complete only when:

- Architecture remains consistent
- Schemas validate
- Unit tests pass
- Integration tests pass
- Evaluation passes
- Security checks pass
- Documentation updated
- Affected ADR created if architecture changed
- No warnings remain unresolved
- Skill lifecycle process followed if any Skill was updated (ADR-0002)

---

## 18. Long-Term Compatibility

All architectural decisions must remain compatible with:
- New LLM providers
- New runtime providers
- Additional agents
- Additional workflows (via ADR + spec/workflow.yaml)
- Additional core Skills (via SkillLifecycle)
- Additional User Skills (via REGISTRY.yaml)
- Future cloud deployment
- Future distributed execution
- Future MCP-compatible services
- Future A2A-compatible services

No design shall lock the platform to a specific AI vendor.

---

## 19. Final Principle

The platform exists to produce trustworthy clinical research.

If any implementation choice conflicts with this objective,
the implementation shall change,
never the objective.
