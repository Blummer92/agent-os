"""OpenRouter bug-investigation pilot (#3637): opt-in provider adapter.

Disabled by default; see README.md. Reuses the pr-remediation evidence
kernel's ``ProposalAdapter`` seam and strict verifier without modifying it.
"""

from .adapter import (
    OpenRouterBudgetExhausted,
    OpenRouterBudgetTracker,
    OpenRouterMalformedResponse,
    OpenRouterProposalAdapter,
)
from .benchmark import (
    BenchmarkAggregate,
    BenchmarkReport,
    BugBenchmarkResult,
    CorpusError,
    LiveBenchmarkAggregate,
    LiveBenchmarkNotApproved,
    LiveBenchmarkReport,
    LiveBugResult,
    LiveModelResult,
    ModelBenchmarkResult,
    default_corpus_path,
    load_corpus,
    run_benchmark,
    run_live_benchmark,
)
from .config import (
    API_KEY_ENV_VAR,
    LIVE_BENCHMARK_ENV_VAR,
    MODEL_A_ENV_VAR,
    MODEL_B_ENV_VAR,
    PILOT_ENABLED_ENV_VAR,
    OpenRouterConfig,
)
from .pricing import (
    FreeModelPricingGate,
    OpenRouterPricingGateError,
    fetch_generation_record,
    fetch_models_catalog,
    is_zero_price,
)
from .investigation import (
    DualInvestigationResult,
    ModelInvestigationOutcome,
    run_dual_investigation,
    serialize_dual_investigation,
)

__all__ = [
    "API_KEY_ENV_VAR",
    "LIVE_BENCHMARK_ENV_VAR",
    "MODEL_A_ENV_VAR",
    "MODEL_B_ENV_VAR",
    "PILOT_ENABLED_ENV_VAR",
    "BenchmarkAggregate",
    "BenchmarkReport",
    "BugBenchmarkResult",
    "CorpusError",
    "DualInvestigationResult",
    "FreeModelPricingGate",
    "LiveBenchmarkAggregate",
    "LiveBenchmarkNotApproved",
    "LiveBenchmarkReport",
    "LiveBugResult",
    "LiveModelResult",
    "ModelBenchmarkResult",
    "ModelInvestigationOutcome",
    "OpenRouterBudgetExhausted",
    "OpenRouterBudgetTracker",
    "OpenRouterConfig",
    "OpenRouterMalformedResponse",
    "OpenRouterPricingGateError",
    "OpenRouterProposalAdapter",
    "default_corpus_path",
    "fetch_generation_record",
    "fetch_models_catalog",
    "is_zero_price",
    "load_corpus",
    "run_benchmark",
    "run_dual_investigation",
    "run_live_benchmark",
    "serialize_dual_investigation",
]
