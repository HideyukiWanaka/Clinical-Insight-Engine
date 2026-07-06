"""CIE Platform — FastAPI route modules (Phase 1 / R1-2).

Each module exposes an ``APIRouter`` named ``router`` implementing one section
of ``spec/api/rest-api-contract.md``. Handlers are thin: they assemble a
payload and call the corresponding agent through ``cie.api.deps.invoke_agent``
(token issue → run → finally revoke).
"""
