"""CIE Platform — shared backend service container (DI assembly).

This module owns the single source of truth for wiring up every backend
service (agents, token_manager, schema_registry, audit, reference_library,
runtime_agent, orchestrator, …).  It was extracted verbatim from
``cie/ui/app.py:_get_services()`` (Phase 1 / R1-1) so that **both** the
Streamlit UI *and* the FastAPI API layer construct the exact same dependency
graph from one place.

- ``cie/ui/app.py`` wraps :func:`build_services` in ``@st.cache_resource`` so a
  Streamlit server process builds the graph at most once.
- ``cie/api`` builds it once at application startup (see ``cie/api/main.py``).

Design constraints:
- The returned ``dict`` structure is identical to the original ``_get_services``
  contract — callers depend on the exact key set below.
- No Streamlit import here: this must remain importable from the headless API.
- All async DB setup runs synchronously via ``asyncio.run``; therefore this
  function must be called from a context with **no running event loop**
  (the API startup path uses ``asyncio.to_thread`` for this reason).
"""

from __future__ import annotations

import asyncio
from pathlib import Path


def build_services() -> dict:
    """Initialise and return the full backend service container.

    Returns:
        A dict wiring every backend service.  The key set is the shared
        contract consumed by both the Streamlit UI and the FastAPI handlers.
    """
    from cie.agents.base import AgentInput  # noqa: F401 — re-exported for handlers
    from cie.agents.data_quality import DataQualityAgent
    from cie.agents.evaluation import EvaluationAgent
    from cie.agents.planner import PlannerAgent
    from cie.agents.reporting import ReportingAgent
    from cie.agents.reviewer import ReviewerAgent
    from cie.agents.runtime import RuntimeAgent
    from cie.agents.statistics import StatisticsAgent
    from cie.agents.visualization import VisualizationAgent
    from cie.cache.r_script_cache import RScriptCache
    from cie.core.audit import AuditService
    from cie.core.config import CIEConfig
    from cie.core.database import get_engine, get_session, init_db
    from cie.core.llm_client import llm_client_from_env
    from cie.knowledge.embedding_index import EmbeddingReferenceLibrary
    from cie.knowledge.ingestion_agent import KnowledgeIngestionAgent
    from cie.knowledge.ingestion_guard import IngestionGuard
    from cie.knowledge.lifecycle import KnowledgeLifecycleService
    from cie.knowledge.loader import KnowledgeLoader
    from cie.knowledge.parsers.base import DocumentParserRegistry
    from cie.knowledge.parsers.pymupdf_parser import PlainTextParser, PyMuPDFParser
    from cie.runtime.r_executor import LocalRExecutor
    from cie.runtime.runtime_provider import RuntimeProvider
    from cie.schemas.validator import SchemaRegistry
    from cie.security.capability_token import CapabilityTokenManager
    from cie.security.context_guard import ContextGuard
    from cie.security.pii_filter import PIIFilter
    from cie.security.policy_engine import PolicyEngine
    from cie.workflow.orchestrator import Orchestrator
    from cie.workflow.registry import WorkflowRegistry
    from cie.workflow.states import WorkflowStateMachine
    from cie.workflow.system_registry import SystemWorkflowRegistry

    config = CIEConfig()

    # DB — create tables if missing (idempotent)
    engine = asyncio.run(get_engine(config))
    asyncio.run(init_db(engine))

    # Core services
    pii_filter = PIIFilter()
    token_manager = CapabilityTokenManager()
    audit = AuditService(session_factory=lambda: get_session(engine))
    context_guard = ContextGuard(pii_filter, audit)
    policy_engine = PolicyEngine(token_manager, audit)
    schema_registry = SchemaRegistry(schema_dir=Path("schemas/"))

    # LLM — provider selected via CIE_ACTIVE_AI_PROVIDER (.env). Pass
    # config.active_ai_provider explicitly rather than letting
    # llm_client_from_env() read os.environ directly: CIEConfig loads .env
    # through pydantic-settings, which does NOT populate the real process
    # environment, so os.environ.get("CIE_ACTIVE_AI_PROVIDER") is empty even
    # when .env has it set — every restart would otherwise silently fall back
    # to "anthropic" regardless of a provider switch made via the settings UI.
    llm_client = llm_client_from_env(provider=config.active_ai_provider)

    # Semantic cache (ADR-0004)
    from cie.cache.store import CacheStore
    cache_store = CacheStore()

    # Agents
    planner = PlannerAgent(
        policy_engine, schema_registry, audit, context_guard, llm_client,
        cache_store=cache_store,
    )

    # Knowledge directories
    knowledge_root = Path("knowledge")
    workspace = Path(config.workspace_directory)
    official_dir = knowledge_root / "official"
    institutional_dir = knowledge_root / "institutional"
    pending_dir = knowledge_root / "pending"
    source_dir = workspace / "knowledge_sources"
    source_dir.mkdir(parents=True, exist_ok=True)

    parsers = [PyMuPDFParser(), PlainTextParser()]
    parser_registry = DocumentParserRegistry(parsers)
    ingestion_guard = IngestionGuard()

    knowledge_ingestion = KnowledgeIngestionAgent(
        ingestion_guard, parser_registry, pending_dir, source_dir
    )
    knowledge_lifecycle = KnowledgeLifecycleService(institutional_dir, pending_dir, audit)
    knowledge_loader = KnowledgeLoader(official_dir, institutional_dir)

    # Downstream analysis agents
    data_quality  = DataQualityAgent(policy_engine, schema_registry, audit, pii_filter)
    # Statistics generates the executable R script via the LLM, grounded in the
    # knowledge reference library (RAG), with a token-saving cache for
    # structurally-identical analyses. ADR-0005 Phase 5: keyword search is
    # replaced by a fully-local embedding retriever (same retrieve() signature,
    # so statistics/visualization/reporting call sites are unchanged). Indexes
    # all of official/**/*.md plus approved institutional/ entries; the store is
    # persisted under the workspace so the knowledge tree stays read-only.
    reference_library = EmbeddingReferenceLibrary(
        knowledge_root,
        store_path=workspace / "embedding_index" / "index.json",
    )
    r_script_cache = RScriptCache()
    # SkillLoader: user/ > core/ priority (ADR-0002 Principle 3)
    from cie.skills.loader import SkillLoader
    skill_loader = SkillLoader(Path("skills"))
    statistics    = StatisticsAgent(
        policy_engine, schema_registry, audit,
        llm_client=llm_client,
        reference_library=reference_library,
        script_cache=r_script_cache,
        skill_loader=skill_loader,
    )
    viz_output_dir = workspace / "viz_output"
    viz_output_dir.mkdir(parents=True, exist_ok=True)
    viz_local_executor = LocalRExecutor(
        workspace_dir=workspace, output_dir=viz_output_dir, context_guard=context_guard
    )
    viz_runtime_provider = RuntimeProvider(local_executor=viz_local_executor)
    visualization = VisualizationAgent(
        policy_engine, schema_registry, audit,
        llm_client=llm_client,
        reference_library=reference_library,
        script_cache=r_script_cache,
        runtime_provider=viz_runtime_provider,
        workspace_dir=workspace / "viz_scripts",
        output_dir=viz_output_dir,
        skill_loader=skill_loader,
    )
    reporting     = ReportingAgent(
        policy_engine, schema_registry, audit,
        llm_client=llm_client,
        reference_library=reference_library,
        skill_loader=skill_loader,
    )
    reviewer      = ReviewerAgent(policy_engine, schema_registry, audit)
    # Evaluation agent — final DAG stage (correctness/statistical/security/usability)
    evaluation    = EvaluationAgent(policy_engine, schema_registry, audit)

    # Runtime agent — executes upstream-generated R scripts in the sandbox
    r_output_dir = workspace / "r_output"
    r_output_dir.mkdir(parents=True, exist_ok=True)
    local_r_executor = LocalRExecutor(
        workspace_dir=workspace, output_dir=r_output_dir, context_guard=context_guard
    )
    runtime_provider = RuntimeProvider(local_executor=local_r_executor)
    runtime_agent = RuntimeAgent(
        policy_engine, schema_registry, audit, runtime_provider,
        workspace_dir=workspace / "r_scripts",
        output_dir=r_output_dir,
    )

    agent_registry = {
        "planner":       planner,
        "data_quality":  data_quality,
        "statistics":    statistics,
        "visualization": visualization,
        "reporting":     reporting,
        "reviewer":      reviewer,
        "runtime":       runtime_agent,
        "evaluation":    evaluation,
    }

    # Workflow engine
    workflow_registry = WorkflowRegistry.load_from_yaml(Path("spec/workflow.yaml"))
    system_registry   = SystemWorkflowRegistry(Path("spec/system-workflow.yaml"))
    state_machine     = WorkflowStateMachine()

    orchestrator = Orchestrator(
        workflow_registry=workflow_registry,
        state_machine=state_machine,
        token_manager=token_manager,
        policy_engine=policy_engine,
        context_guard=context_guard,
        audit_service=audit,
        agent_registry=agent_registry,
        system_registry=system_registry,
        knowledge_loader=knowledge_loader,
    )

    # Phase 8: Skill self-improvement service (ADR-0002)
    from cie.evaluation.regression import RegressionChecker
    from cie.skills.lifecycle import SkillLifecycleService
    from cie.skills.registry_manager import RegistryManager

    regression_checker = RegressionChecker(db_session_factory=lambda: get_session(engine))
    registry_manager = RegistryManager(Path("REGISTRY.yaml"))
    skill_lifecycle = SkillLifecycleService(
        skill_loader=skill_loader,
        registry_manager=registry_manager,
        regression_checker=regression_checker,
        token_manager=token_manager,
        audit_service=audit,
        db_session_factory=lambda: get_session(engine),
    )

    return {
        "token_manager": token_manager,
        "audit": audit,
        "planner": planner,
        "knowledge_ingestion": knowledge_ingestion,
        "knowledge_lifecycle": knowledge_lifecycle,
        "knowledge_loader": knowledge_loader,
        "reference_library": reference_library,
        "orchestrator": orchestrator,
        "cache_store": cache_store,
        "skill_loader": skill_loader,
        # Phase 7: exposed for continuation mini-pipeline
        "statistics": statistics,
        "runtime_agent": runtime_agent,
        "visualization": visualization,
        "reporting": reporting,
        "r_output_dir": r_output_dir,
        "viz_output_dir": viz_output_dir,
        # Phase 1 (API): shared services need the sanitizer + workspace root
        "context_guard": context_guard,
        "workspace_dir": workspace,
        # /api/settings/storage: display-only, current-process values (a
        # change only takes effect after restart — see build_dataset_context).
        "database_filepath": config.database_filepath,
        # Phase 8: Skill self-improvement
        "skill_lifecycle": skill_lifecycle,
        "session_factory": lambda: get_session(engine),
        # Exposed so /api/settings/llm can live-swap provider/key on the one
        # shared instance every agent already holds a reference to (§ below).
        "llm_client": llm_client,
    }
