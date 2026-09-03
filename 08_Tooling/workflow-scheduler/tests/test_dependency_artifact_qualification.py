from __future__ import annotations
import hashlib, zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from workflow_scheduler.governance import dependency_artifact_qualification as q
from workflow_scheduler.governance.dev_validation import REPOSITORY,build_dev_validation_request,validation_argv
from workflow_scheduler.governance.dev_validation_profiles import RunnerKind,get_profile,profile_argv

def wheel(root:Path,name:str,version:str,license_text:str="Apache-2.0")->Path:
 path=root/f"{name}-{version}-py3-none-any.whl";dist=f"{name}-{version}.dist-info/METADATA"
 with zipfile.ZipFile(path,"w") as z:z.writestr(dist,f"Name: {name}\nVersion: {version}\nLicense-Expression: {license_text}\n")
 return path

def test_profile_is_closed_and_fixed():
 p=get_profile(q.PROFILE_ID);assert p.runner_kind is RunnerKind.DEPENDENCY_ARTIFACT_QUALIFICATION;assert p.runtime_id=="network-capable-ephemeral-python-resolver";assert profile_argv(q.PROFILE_ID)==("python","-m","workflow_scheduler.governance.dependency_artifact_qualification")
 req=build_dev_validation_request(repository=REPOSITORY,issue_number=1783,branch="agent/1783-wheelhouse-lock-qualification",source_sha="a"*40,validation_id=q.PROFILE_ID)
 assert validation_argv(req)==profile_argv(q.PROFILE_ID);assert set(req.to_dict()).isdisjoint({"package","version","index","platform","abi","argv","requirements","cwd","env","url","network"})

def test_resolver_argv_is_exact_fixed_package_and_target(tmp_path):
 argv=q.resolver_argv(tmp_path);joined=" ".join(argv);assert all(package in argv for package in q.PACKAGES);assert "311" in argv;assert q.TARGET_PLATFORM in argv;assert q.TARGET_ABI in argv;assert "--only-binary=:all:" in argv;assert "--index-url" not in argv;assert "--extra-index-url" not in argv

def test_only_wheels_are_accepted(tmp_path):
 (tmp_path/"bad.tar.gz").write_bytes(b"x")
 with pytest.raises(ValueError,match="source-distribution"):q.inspect_wheelhouse(tmp_path)

def test_hash_lock_is_deterministic_and_exact(tmp_path):
 a=wheel(tmp_path,"demo_pkg","1.2.3");arts=q.inspect_wheelhouse(tmp_path);expected=hashlib.sha256(a.read_bytes()).hexdigest();assert arts[0].sha256==expected;assert q.hash_lock(arts)==(f"demo-pkg==1.2.3 --hash=sha256:{expected}",)

def test_conflicting_package_versions_fail_closed(tmp_path):
 wheel(tmp_path,"demo","1.0");wheel(tmp_path,"demo","2.0")
 with pytest.raises(ValueError,match="artifact-identity-conflict"):q.inspect_wheelhouse(tmp_path)

def test_missing_license_is_explicit_blocker(tmp_path,monkeypatch):
 calls=[]
 def runner(argv,timeout):
  calls.append(tuple(argv));dest=Path(argv[argv.index("--dest")+1]) if "--dest" in argv else None
  if dest is not None:wheel(dest,"demo","1.0","")
  return SimpleNamespace(returncode=0,stdout="",stderr="")
 result=q.qualify(runner=runner);assert result.status=="blocked";assert "license-metadata-incomplete" in result.reason_codes;assert result.execution_authorized is False;assert result.host_mutation_authorized is False

def test_resolver_failure_is_distinct_from_verification_failure():
 assert q.qualify(runner=lambda argv,timeout:SimpleNamespace(returncode=1,stdout="",stderr="")).reason_codes==("resolver-download-failed",)

def test_offline_verification_uses_no_index(tmp_path):
 argv=q.offline_verify_argv(tmp_path,tmp_path/"target",tmp_path/"lock");assert "--no-index" in argv;assert "--require-hashes" in argv;assert "--only-binary=:all:" in argv

def test_bounds_are_finite():
 assert q.MAX_ARTIFACTS<=128;assert q.MAX_TOTAL_BYTES<=2*1024**3;assert q.RESOLVE_TIMEOUT_SECONDS<=300;assert q.VERIFY_TIMEOUT_SECONDS<=300
