"""Canonical main-owned developer-validation profile catalog for DEVVAL5 (#1566)."""
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping
_PROFILE_ID=re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$",re.ASCII);_SAFE_PATH=re.compile(r"^[A-Za-z0-9._/-]+$",re.ASCII);MAX_TARGETS=32
class RunnerKind(str,Enum):
 PYTEST_TARGETS="pytest-targets";VITEST_TARGETS="vitest-targets";LEGACY_FIXED_SCRIPT="legacy-fixed-script";EIA_PADDLEOCR_QUALIFICATION="eia-paddleocr-qualification";DEPENDENCY_ARTIFACT_QUALIFICATION="dependency-artifact-qualification"
@dataclass(frozen=True,slots=True)
class DevValidationProfile:
 profile_id:str;runner_kind:RunnerKind;fixed_targets:tuple[str,...];fixed_working_directory:str|None;runtime_id:str;timeout_class:str;selector_requirements:tuple[str,...]
def _safe_path(value:str,*,allow_dot:bool=False)->str:
 if type(value)is not str or not value or len(value)>240:raise ValueError("profile path must be bounded non-empty text")
 if value.startswith(("/","~")) or ".." in value.split("/"):raise ValueError("profile path must be repository-relative")
 if not allow_dot and value in {".","./"}:raise ValueError("profile path must be specific")
 if _SAFE_PATH.fullmatch(value)is None or "//" in value or value.endswith("/"):raise ValueError("profile path contains unsafe syntax")
 return value
def _profile(profile_id:str,runner_kind:RunnerKind,fixed_targets:tuple[str,...],*,cwd:str|None=None,runtime_id:str,timeout_class:str="focused-120s",selector_requirements:tuple[str,...]=())->DevValidationProfile:
 if type(profile_id)is not str or _PROFILE_ID.fullmatch(profile_id)is None:raise ValueError("invalid developer-validation profile id")
 if type(runner_kind)is not RunnerKind:raise ValueError("unsupported developer-validation runner kind")
 if type(fixed_targets)is not tuple or not fixed_targets or len(fixed_targets)>MAX_TARGETS:raise ValueError("developer-validation profile targets must be a bounded tuple")
 targets=tuple(_safe_path(target) for target in fixed_targets)
 if len(set(targets))!=len(targets):raise ValueError("developer-validation profile targets must be unique")
 working_directory=None if cwd is None else _safe_path(cwd)
 if type(runtime_id)is not str or not runtime_id or len(runtime_id)>80:raise ValueError("developer-validation runtime id must be bounded text")
 if type(timeout_class)is not str or timeout_class not in {"focused-120s","artifact-300s"}:raise ValueError("unsupported developer-validation timeout class")
 requirements=tuple(sorted(set(selector_requirements)))
 if any(type(item)is not str or not item or len(item)>120 for item in requirements):raise ValueError("invalid selector requirement binding")
 return DevValidationProfile(profile_id,runner_kind,targets,working_directory,runtime_id,timeout_class,requirements)
_PROFILES=(
 _profile("remote-validation",RunnerKind.PYTEST_TARGETS,("tests/agent_os_remote_validation",),runtime_id="python-pytest-8.3.5"),
 _profile("pr-remediation",RunnerKind.PYTEST_TARGETS,("tests/agent_os_pr_remediation",),runtime_id="python-pytest-8.3.5",selector_requirements=("pr-remediation",)),
 _profile("workflow-scheduler",RunnerKind.PYTEST_TARGETS,("08_Tooling/workflow-scheduler/tests",),runtime_id="python-pytest-8.3.5",selector_requirements=("workflow-scheduler","workflow-scheduler-concrete-runtime-adapters")),
 _profile("issue-acceptance",RunnerKind.PYTEST_TARGETS,("tests/agent_os_issue_acceptance",),runtime_id="python-pytest-8.3.5",selector_requirements=("issue-acceptance",)),
 _profile("instructional-materials-current-curriculum",RunnerKind.PYTEST_TARGETS,("08_Tooling/instructional-materials-coach/tests/test_generation_context.py","08_Tooling/instructional-materials-coach/tests/test_content_spec.py","08_Tooling/instructional-materials-coach/tests/test_cli.py","tests/test_current_curriculum_state.py","tests/test_current_curriculum_evidence.py"),runtime_id="python-pytest-8.3.5-materials-imports"),
 _profile("picture-perfect",RunnerKind.VITEST_TARGETS,("src/overlayIntegrity.test.ts","src/exactComposite.test.ts","src/exactCompositeSuite.test.ts","src/framePlan.test.ts","src/executorContract.test.ts","src/provenanceValidator.test.ts"),cwd="08_Tooling/instructional-materials-coach/picture-perfect-coach",runtime_id="node22-vitest-4.1.10"),
 _profile("semantic-ownership-advisory",RunnerKind.LEGACY_FIXED_SCRIPT,("07_Agent_Tests/run-semantic-ownership-advisory-validation.py",),runtime_id="python-system-script-compat"),
 _profile("eia-paddleocr-runtime-qualification",RunnerKind.EIA_PADDLEOCR_QUALIFICATION,("08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/eia_paddleocr_runtime_qualification.py",),runtime_id="host-python-eia-paddleocr"),
 _profile("eia-paddleocr-cp311-wheelhouse-qualification",RunnerKind.DEPENDENCY_ARTIFACT_QUALIFICATION,("08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/dependency_artifact_qualification.py",),runtime_id="network-capable-ephemeral-python-resolver",timeout_class="artifact-300s"),
)
PROFILE_CATALOG:Mapping[str,DevValidationProfile]=MappingProxyType({p.profile_id:p for p in _PROFILES})
PROFILE_ALIASES:Mapping[str,str]=MappingProxyType({"remote-validation-suite":"remote-validation","instructional-materials-current-curriculum-suite":"instructional-materials-current-curriculum","ppux-picture-perfect-ts-vitest":"picture-perfect","semantic-ownership-advisory":"semantic-ownership-advisory"})
_SELECTOR_TO_PROFILE:Mapping[str,str]=MappingProxyType({"pr-remediation":"pr-remediation","workflow-scheduler":"workflow-scheduler","workflow-scheduler-concrete-runtime-adapters":"workflow-scheduler","issue-acceptance":"issue-acceptance"})
def canonical_profile_id(profile_id:object)->str:
 if type(profile_id)is not str or _PROFILE_ID.fullmatch(profile_id)is None:raise ValueError("unknown developer-validation profile")
 canonical=PROFILE_ALIASES.get(profile_id,profile_id)
 if canonical not in PROFILE_CATALOG:raise ValueError("unknown developer-validation profile")
 return canonical
def get_profile(profile_id:object)->DevValidationProfile:return PROFILE_CATALOG[canonical_profile_id(profile_id)]
def profile_argv(profile_id:object)->tuple[str,...]:
 p=get_profile(profile_id)
 if p.runner_kind is RunnerKind.PYTEST_TARGETS:return("python","-m","pytest",*p.fixed_targets)
 if p.runner_kind is RunnerKind.VITEST_TARGETS:return("node","vitest","run",*p.fixed_targets)
 if p.runner_kind is RunnerKind.LEGACY_FIXED_SCRIPT:return("python",*p.fixed_targets)
 if p.runner_kind is RunnerKind.EIA_PADDLEOCR_QUALIFICATION:return("python","-m","workflow_scheduler.governance.eia_paddleocr_runtime_qualification")
 if p.runner_kind is RunnerKind.DEPENDENCY_ARTIFACT_QUALIFICATION:return("python","-m","workflow_scheduler.governance.dependency_artifact_qualification")
 raise ValueError("unsupported developer-validation runner kind")
def project_selector_requirements(requirements:Iterable[str])->tuple[str,...]:
 if type(requirements)not in {tuple,list}:raise ValueError("selector requirements must be a tuple or list")
 result:set[str]=set()
 for requirement in requirements:
  if type(requirement)is not str or not requirement:raise ValueError("malformed selector requirement")
  profile_id=_SELECTOR_TO_PROFILE.get(requirement)
  if profile_id is None:raise ValueError(f"profile-unavailable:{requirement}")
  result.add(profile_id)
 return tuple(sorted(result))
