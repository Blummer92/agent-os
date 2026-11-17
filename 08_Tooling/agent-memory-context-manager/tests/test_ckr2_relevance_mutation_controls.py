"""14 isolated semantic source mutations tested against the 50 contract cases.

No worktree modifications or external writes. Compile/import failures are INVALID,
not kills. Each mutant must change at least one baseline-green assertion.
"""
import importlib.util
from pathlib import Path
import sys
import pytest
from test_ckr2_relevance_campaign import POS, NEG, check_positive, check_negative

SOURCE=Path(__file__).resolve().parents[1]/"src"/"agent_memory_context_manager"/"coding_knowledge_selection.py"
MUTANTS=[
("M01-gate-alias", '        "ckr6 mutation gate",', '        "unsupported gate phrase",'),
("M02-boundary-gate", '        "ckr6 mutation boundary gate",', '        "unsupported boundary gate",'),
("M03-no-context", '    ci_request = bool(capability_hints & {', '    ci_request = bool(capability_hints & set() & {'),
("M04-only-ckr6", 'for term in ("ckr6", "mutation")):', 'for term in ("ckr6",)):'),
("M05-only-mutation", 'for term in ("ckr6", "mutation")):', 'for term in ("mutation",)):'),
("M06-drop-title", 'lesson_text = " ".join((candidate.name, *candidate.use_when)).casefold()', 'lesson_text = " ".join(candidate.use_when).casefold()'),
("M07-no-word-boundaries", 'r"(?<![a-z0-9])" + term + r"(?![a-z0-9])"', 'term'),
("M08-provenance", '    if _missing_candidate_provenance(selected):', '    if False:'),
("M09-stale", '    if any(item[2].currentness is KnowledgeCurrentness.STALE for item in best):', '    if False:'),
("M10-authority", '    if any(item[2].authority_conflict for item in best):', '    if False:'),
("M11-duplicate", '    if duplicate_conflict:', '    if False:'),
("M12-budget", '    if len(deduped) > MAX_CANDIDATES:', '    if False:'),
("M13-explicit-false", '    if request.specialized_knowledge_required is False:', '    if False:'),
("M14-library", '    uncovered = _uncovered_library_hints(request, selected)', '    uncovered = ()'),
]
assert len(MUTANTS)==14

@pytest.mark.parametrize("id,original,changed",MUTANTS,ids=[x[0] for x in MUTANTS])
def test_kill_semantic_mutant(tmp_path,id,original,changed):
    source=SOURCE.read_text(encoding="utf-8")
    assert source.count(original)==1,(id,"source drift / invalid mutant")
    modified=source.replace(original,changed,1)
    compile(modified,str(SOURCE),"exec")  # invalid source is NOT a kill
    filename=tmp_path/(id+".py")
    filename.write_text(modified,encoding="utf-8")
    module_id="_ckr2_campaign_"+id.replace("-","_")
    spec=importlib.util.spec_from_file_location(module_id,filename)
    assert spec and spec.loader
    mutant=importlib.util.module_from_spec(spec)
    sys.modules[module_id]=mutant
    try:
        spec.loader.exec_module(mutant)
        detectors=[]
        for item in POS:
            try:check_positive(mutant,item)
            except AssertionError:detectors.append("positive:"+item[0])
        for item in NEG:
            try:check_negative(mutant,item)
            except AssertionError:detectors.append("negative:"+item[0])
        assert detectors,id+" SURVIVED (0/50 detectors)"
    finally:
        sys.modules.pop(module_id,None)
