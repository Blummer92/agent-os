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
    LiveBenchmarkNotApproved,
    LiveBenchmarkNotExecuted,
    ModelBenchmarkResult,
    default_corpus_path,
    load_corpus,
    run_benchmark,
)
from .config import (
    API_KEY_ENV_VAR,
    LIVE_BENCHMARK_ENV_VAR,
    MODEL_A_ENV_VAR,
    MODEL_B_ENV_VAR,
    PILOT_ENABLED_ENV_VAR,
    OpenRouterConfig,
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
    "LiveBenchmarkNotApproved",
    "LiveBenchmarkNotExecuted",
    "ModelBenchmarkResult",
    "ModelInvestigationOutcome",
    "OpenRouterBudgetExhausted",
    "OpenRouterBudgetTracker",
    "OpenRouterConfig",
    "OpenRouterMalformedResponse",
    "OpenRouterProposalAdapter",
    "default_corpus_path",
    "load_corpus",
    "run_benchmark",
    "run_dual_investigation",
    "serialize_dual_investigation",
]
