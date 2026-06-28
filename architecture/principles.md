# CIE Platform Architecture Principles
# File: architecture/principles.md
# Version: 2.0.0
# Status: Draft
# Note: AP-015 updated in context of ADR-0002 (Meta-Skills / User Skills).
#       "Skills never contain project-specific implementation" applies to
#       skills/core/ namespace. skills/user/ holds project-specific procedures
#       under Human Authority control (see spec/skill-lifecycle.md).

## Purpose

This document defines the architectural principles that govern every design
decision within CIE Platform.

These principles have higher priority than implementation details.
When implementation conflicts with these principles, the implementation must change.

---

## AP-001 Intent First

User intent is the primary input of the system.
The platform shall reason about the user's research objective rather than literal prompts.
The architecture shall preserve user intent throughout every workflow stage.
Success is measured by intent satisfaction rather than prompt completion.

## AP-002 Separation of Responsibilities

Every component owns exactly one responsibility.
Each responsibility shall exist in one location only.
Business logic shall never be duplicated.
Violations indicate architectural debt.

## AP-003 Workflow-Centric Architecture

Business workflows define system behavior.
Agents execute workflows.
Agents never define workflows.
Changing workflows must not require changing agent implementations.

## AP-004 Agent Independence

Agents are autonomous execution units.
Each agent:
- owns one domain
- has explicit inputs
- has explicit outputs
- declares permissions
- exposes a stable interface

Agents shall never depend on internal implementation details of other agents.

## AP-005 Contract First

Every interaction between components must be governed by a formal contract.
Contracts include:
- JSON Schema
- YAML Specification
- Interface Definitions

Implicit contracts are prohibited.

## AP-006 Runtime Independence

Business logic shall never depend on execution environment.
The same workflow must execute correctly using:
- Local Restricted Runtime
- Docker Runtime
- Remote Runtime

Runtime providers are interchangeable.

## AP-007 AI Provider Independence

The architecture shall support multiple AI providers.
Examples include:
- OpenAI
- Anthropic
- Google
- Local LLMs
- Future providers

No business component may directly depend on a single vendor API.

## AP-008 Explainability

Every important decision shall be explainable.
The platform shall record:
- workflow decisions
- selected statistical methods
- validation outcomes
- execution history

Explanations are based on observable decisions rather than internal model reasoning.

## AP-009 Verification Before Trust

Generated outputs are hypotheses.
Verification precedes acceptance.
The platform shall validate:
- statistical assumptions
- schema compliance
- workflow integrity
- execution results

before presenting conclusions.

## AP-010 Human Authority

Humans remain the final authority.
AI recommends.
Humans approve.

Critical operations requiring approval include:
- exporting reports
- external communication
- package installation
- architecture modification
- irreversible operations
- Skill file updates (ADR-0002)
- User Skill registration (ADR-0002)

## AP-011 Security by Default

Default behavior is deny.
Permissions must be explicitly granted.
Security policies are enforced before execution.
Security shall exist independently from agent implementation.

## AP-012 Offline Capability

The platform shall remain functional without Internet connectivity.
Internet services enhance functionality but never define core functionality.
Offline execution is the reference architecture.

## AP-013 Progressive Context Loading

AI components shall load only the context required for the current task.
Context loading follows:
```
Task → Workflow → Agent → Skill → Knowledge → Execution
```
Entire repositories shall never be loaded unnecessarily.

## AP-014 Immutable Knowledge

Knowledge represents validated reference information.
Knowledge modules:
- are version controlled
- are reviewable
- are immutable during execution

Agents may read knowledge.
Agents may not modify knowledge.

## AP-015 Skills are Procedures

Skills define reusable execution procedures.
Skills contain:
- methodology
- examples
- best practices
- validation rules

**Core Skills** (skills/core/) never contain project-specific implementation.
**User Skills** (skills/user/) may contain project-specific procedures
under Human Authority control and SkillLifecycle governance (ADR-0002).

## AP-016 Architecture Before Code

Architecture defines implementation.
Implementation shall never redefine architecture.
Architecture changes require an Architecture Decision Record (ADR).

## AP-017 Evaluation Driven Development

Every generated artifact shall be evaluated.
Evaluation includes:
- correctness
- reproducibility
- statistical validity
- security
- usability
- performance

No artifact bypasses evaluation.

## AP-018 Observable Systems

The platform shall expose observable behavior.
Observable artifacts include:
- workflow execution
- tool invocation
- runtime selection
- validation reports
- evaluation reports

Hidden execution paths are prohibited.

## AP-019 Extensibility

Adding new functionality should require extension rather than modification.
Preferred extension points include:
- new agents
- new workflows
- new runtime providers
- new skills (core or user)
- new knowledge modules

Core architecture should remain stable.

## AP-020 Long-Term Stability

Architectural decisions should optimize for:
- maintainability
- adaptability
- interoperability
- scientific reliability

Short-term implementation convenience shall not compromise long-term platform quality.

---

## Architecture Decision Rule

When multiple designs satisfy functional requirements, select the design that:
1. minimizes coupling
2. maximizes clarity
3. maximizes testability
4. maximizes security
5. maximizes future extensibility

These priorities override implementation convenience.

---

## Principle Hierarchy

| Priority | Objective |
|---------|-----------|
| 1 | Scientific correctness |
| 2 | Patient privacy |
| 3 | Security |
| 4 | Reproducibility |
| 5 | Explainability |
| 6 | Maintainability |
| 7 | Performance |
| 8 | Developer convenience |

No lower-priority objective may compromise a higher-priority objective.
