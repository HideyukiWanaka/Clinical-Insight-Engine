"""CIE Platform — Runtime package.

Provides the runtime provider abstraction layer.

Supported providers (spec/system.yaml):
    - local_restricted_runtime (default)
    - docker_runtime (optional)
    - remote_runtime (future)
    - distributed_runtime (future)

No business logic may depend on a specific runtime implementation
(PROJECT_RULES.md Section 7).
"""
