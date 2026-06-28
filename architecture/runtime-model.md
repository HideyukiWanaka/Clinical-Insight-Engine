# CIE Platform Runtime Model
# File: architecture/runtime-model.md
# Version: 2.0.0
# Status: Draft

## Purpose

This document defines how computational tasks are executed within the CIE Platform.
The runtime layer is responsible for executing code safely, reproducibly, and
independently of any specific execution technology.
Business logic shall never depend on runtime implementation.

---

## Design Goals

The Runtime Layer shall provide:
- secure execution
- reproducible execution
- isolated execution
- provider independence
- deterministic behavior
- execution monitoring

---

## Core Principle

The platform does not execute R, Python, or any other language directly.
The platform submits an Execution Request to a Runtime Provider.

The Runtime Provider determines:
- where execution occurs
- how execution occurs
- which security restrictions apply

---

## Runtime Architecture

```
        Execution Request
                │
                ▼
       Runtime Provider
                │
  ┌─────────────┼──────────────┐
  ▼             ▼              ▼
Local        Docker        Remote
Restricted   Runtime       Runtime
Runtime      (Optional)    (Future)
  │             │              │
  └─────────────┴──────────────┘
                │
                ▼
       Execution Result
```

---

## Runtime Providers

### Local Restricted Runtime (Default)

**Purpose:** Zero-configuration execution on standard user environments.

Requirements:
- No Docker installation required
- No administrator privileges required
- No virtualization required

Capabilities:
- Execute R
- Execute Python
- Read temporary project files
- Write approved output files

Restrictions:
- No unrestricted filesystem access
- No shell execution outside provider
- No unrestricted network access
- No registry modification
- No operating system configuration changes

### Docker Runtime (Optional)

**Purpose:** Increase execution isolation.

Requirements: Docker installed and available.
Capabilities: Equivalent to Local Runtime with additional isolation.
Used automatically when available and enabled. Never required.

### Remote Runtime (Future)

**Purpose:** Cloud execution.

Requirements: Authenticated execution, encrypted communication,
identical execution contract.

---

## Runtime Selection Algorithm

```
1. User override
        ↓
2. Project configuration
        ↓
3. Runtime availability detection
        ↓
4. Default: Local Restricted Runtime
```

Business logic never selects runtime directly.

---

## Execution Request

Every execution begins with a structured request.

```yaml
execution_request:
  runtime: auto
  language: R
  script: generated_script.R
  working_directory: workspace/
  timeout_seconds: 300
  memory_limit_mb: 4096
  cpu_limit: 2
  internet_access: false
  filesystem:
    read:
      - workspace/
    write:
      - output/
  packages:
    - tidyverse
    - survival
    - ggplot2
```

---

## Execution Result

Every execution produces:
- Execution Status
- Standard Output (sanitized — RT-004)
- Standard Error (sanitized)
- Generated Files
- Execution Metrics
- Exit Code
- Execution Duration
- Resource Consumption

```yaml
execution_result:
  status: success
  exit_code: 0
  duration_ms: 8243
  memory_peak_mb: 512
  output_files:
    - report.html
    - figure1.png
    - statistics.csv
```

---

## Resource Limits

Every runtime enforces:
- Maximum CPU
- Maximum Memory
- Maximum Runtime (default: 300 seconds)
- Maximum Output Size
- Maximum Temporary Storage

Resources are configurable per spec/runtime.yaml.

---

## Filesystem Model

Allowed:
- `workspace/`
- `output/`
- `temporary/`

Forbidden:
- System directories
- User home directories
- Operating system files
- Hidden application directories

Runtime providers enforce restrictions.
Agents never access filesystem directly.

---

## Network Model

Default: No Internet.
Allowed only after explicit authorization from Security Agent
(permissions.yaml: `net.allow.external_api`, `requires_human_approval: true`).

---

## Package Management

Required packages are declared in the Execution Request.
Runtime installs packages only when: Approved, Trusted, Compatible.
Package installation never occurs silently.
Installation requires Security Agent token + human approval.

---

## Workspace Lifecycle

```
Workspace creation
        ↓
Input Preparation
        ↓
Execution
        ↓
Validation (output schema)
        ↓
Artifact Collection
        ↓
Cleanup (temp files deleted)
```

---

## Failure Handling

Recoverable:
- timeout
- package missing
- temporary IO failure

Non-Recoverable:
- invalid script
- permission violation
- corrupted environment
- security violation

Recoverable failures may retry (maximum 3 attempts per spec/workflow.yaml).
Non-recoverable failures terminate execution immediately.

---

## Security Enforcement

Runtime validates:
- Filesystem permissions
- Network permissions
- Execution timeout
- Memory usage
- Package policy
- Environment variables

Any violation terminates execution.
See architecture/security-pii-filter.md for PII-specific enforcement.

---

## Observability

Every execution records:
- Execution ID
- Runtime Provider
- Runtime Version
- Language Version
- Package Versions
- Execution Duration
- Resource Usage
- Generated Artifacts
- Failure Events

Logs must never contain protected health information (RT-004 in agents/runtime.yaml).

---

## Runtime Configuration

```yaml
runtime:
  provider: auto
  timeout: 300
  memory_limit_mb: 4096
  cpu_limit: 2
  internet_access: false
  cleanup_workspace: true
  retain_logs: true
```

No runtime behavior is hardcoded.

---

## Runtime Quality Requirements

Every Runtime Provider shall satisfy:
- Provider Independence
- Deterministic Execution
- Explicit Resource Limits
- Observable Execution
- Policy Enforcement
- Automatic Cleanup
- Failure Reporting
- Version Traceability
- Reproducibility

A Runtime Provider that fails any requirement is not considered
compliant with the CIE Platform architecture.
