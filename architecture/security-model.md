# CIE Platform Security Model
# File: architecture/security-model.md
# Version: 2.0.0
# Status: Draft
# Related: architecture/security-pii-filter.md (PII Detection — detailed spec)

## Purpose

This document defines the security architecture of the CIE Platform.
Security is treated as a core architectural capability rather than an
implementation feature. Every component must comply with this model.

---

## Security Objectives

The platform shall ensure:
- Confidentiality
- Integrity
- Availability
- Reproducibility
- Traceability
- Least Privilege
- Safe AI Operation

---

## Security Philosophy

**Default Trust Level:** Nothing is trusted. Everything is verified.

Every action must be:
- authenticated
- authorized
- validated
- audited

before execution.

---

## Security Layers

```
User
  ↓
Authentication
  ↓
Authorization
  ↓
Policy Engine
  ↓
Workflow Engine
  ↓
Agent Layer
  ↓
Runtime Provider
  ↓
Operating System
```

Every layer enforces security independently.
No layer assumes lower layers are secure.

---

## Core Security Principles

**SP-001 Default Deny**
Nothing is allowed unless explicitly permitted.

**SP-002 Least Privilege**
Every component receives only the permissions required.
No implicit permissions exist.

**SP-003 Separation of Duties**
Security decisions shall not be made by business agents.
```
Security Agent → Policy Engine → Authorization
```
Business agents request permission. They never grant permission.

**SP-004 Zero Trust**
Internal components are treated as untrusted.
Every request, payload, and response is validated.

---

## Permission Model

Permissions are capability-based (spec/permissions.yaml).

```yaml
capabilities:
  dataset.proxy_metadata
  dataset.read_validated
  dataset.read_raw          # HIGH risk — requires human approval
  r_code.generate_template
  r_code.restore_variables  # Security Agent only
  runtime.invoke_execution
  report.compile_manuscript
  report.export_external    # requires human approval
  human.request_approval
  audit.write_entry
```

Permissions are granted explicitly.
No wildcard permissions.

---

## Agent Permission Matrix

Every agent declares allowed and denied capabilities.
See spec/permissions.yaml for the complete matrix.

Key restrictions:
- Planner: `dataset.proxy_metadata` only (no raw access)
- Statistics: `r_code.generate_template` only (cannot restore var_n)
- Security Agent: sole holder of `r_code.restore_variables`
- Runtime: `runtime.invoke_execution` only (no dataset access)

---

## PII Detection

The platform detects PII across 3 layers (see architecture/security-pii-filter.md):

- **Layer 1:** Regex + dictionary matching (column names, category labels)
- **Layer 2:** Statistical anomaly detection (unique_count, inferred_type)
- **Layer 3:** Lightweight offline ML — spaCy NER, embedding similarity (optional)

Applied at 4 timing points:
1. Planner Agent prompt input
2. Context construction (before LLM call)
3. Data Quality Agent metadata processing
4. Final report output

Detection triggers:
- CRITICAL → immediate block + Security Agent notification + human approval
- WARNING → auto-masking proposal + var_n alias recommendation + log

---

## var_n Alias System

Patient privacy is protected by systematic column name aliasing:

```
Original column name ("患者ID")
        ↓
var_n alias ("var_1")        ← used throughout all Agents
        ↓
var_n_alias_map              ← held by Security Agent only
        ↓
r_code.restore_variables     ← Security Agent permission required
        ↓
Original name restored       ← only in final output
```

---

## Capability Token Lifecycle

Every Agent invocation uses an ephemeral Capability Token:

```
Orchestrator → Security Agent → issues token
        ↓ (bound to execution_id + agent_id + step_id)
Agent executes within token scope
        ↓
Token revoked immediately on node completion
        ↓
Audit log records full token lifecycle
```

Token TTL: 300 seconds maximum.
Tokens are never reused or shared.

---

## Context Hygiene

AI components receive only the minimum information required.
Before context construction:
- Remove unnecessary columns
- Apply PII filter (all 3 layers)
- Replace raw values with var_n aliases
- Normalize metadata

`inject_raw_data_rows = const: false` in all agent definitions (agent.schema.json).

---

## Runtime Isolation

Execution occurs inside Runtime Providers.
Runtime Providers enforce:
- Filesystem boundaries (workspace/ and output/ only)
- Memory limits (4096 MB default)
- CPU limits (2 cores default)
- Timeouts (300 seconds default)
- Network policy (deny_all by default)

Business agents never execute code directly.

---

## Audit Logging

Every security event records:
- Timestamp
- Component (agent_id)
- Workflow / Execution ID
- Decision
- Policy Applied
- Resource
- Result

Logs are immutable (`orchestrator.yaml: audit_policy.immutability: true`).
`capture_reasoning_spans: false` — LLM internal thinking is never logged.

---

## Human Approval Requirements

Mandatory approval before:
- External API calls
- Package installation
- Data export
- Cloud execution
- Architecture modification
- Policy modification
- Skill file updates (ADR-0002)
- User Skill registration (ADR-0002)

Approval events are logged with timestamp and approver action.

---

## Incident Classification

| Level | Response |
|-------|---------|
| INFO | Log only |
| WARNING | Notify + log |
| CRITICAL | Block operation + escalate |
| BREACH | IMMEDIATE_ABORT + revoke all tokens + lock workspace |

---

## Security Quality Requirements

Every security component shall satisfy:
- Independent Enforcement
- Explicit Policies
- Immutable Audit
- Capability-Based Authorization
- Runtime Isolation
- Policy Traceability
- Schema Validation
- Minimal Privilege
- Human Oversight
- Zero Trust Compliance

---

## Security Architecture Rule

Business logic must never weaken security.

If usability conflicts with security,
the architecture shall introduce a safer workflow,
never reduce security guarantees.
