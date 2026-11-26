"""Shared replay harness. It deliberately doesn't load gold.json."""
import copy
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import runpy
import sys

from agent_memory_context_manager import lesson_retrieval_orchestrator

root = Path(__file__).resolve().parent
version, ordering = sys.argv[1:]
# This standalone service module has no relative imports. Loading it directly
# keeps unrelated GitHub/runtime setup out of this offline retrieval replay.
tree = root.parent/'postmerge-4125-ckr'/version
path = tree/'08_Tooling/agent-os-execution-service/src/agent_os_execution_service/issue_start_lesson_preflight.py'
spec = spec_from_file_location('pinned_issue_start', path)
issue_start_lesson_preflight = module_from_spec(spec)
spec.loader.exec_module(issue_start_lesson_preflight)
for mod in (lesson_retrieval_orchestrator, issue_start_lesson_preflight):
    assert tree in Path(mod.__file__).resolve().parents, mod.__file__
convert=runpy.run_path(str(root/'row-source.py'))['to_row']
requests=json.loads((root/'requests.json').read_text())
panels=json.loads((root/'panels.json').read_text())
assert len(panels['archive']) == 35
assert len({query['case'] for query in requests}) == len(requests) == 22
for item in requests:
    args = item['request']
    assert 'known_knowledge_refs' not in args and 'LL-' not in args['task_reference']
    rows = [convert(x) for x in panels[item['panel']]]
    assert len(rows)==len({x['id'] for x in rows}) > 0
    if ordering == 'reverse':
        rows.reverse()
    attempts=[]
    def read(query):
        attempts.append(copy.deepcopy(query))
        assert 'or' not in query['filter'], 'unexpected known-ID route'
        assert query['page_size'] >= len(rows)
        assert 'start_cursor' not in query
        return {'results':copy.deepcopy(rows),'has_more':False}
    result=issue_start_lesson_preflight.activate_issue_start_lesson_preflight(
        repository='Blummer92/agent-os',issue_number=4026,execute_read=read,
        **{k:tuple(v) if isinstance(v,list) else v for k,v in args.items()})
    assert len(attempts)==int(args['specialized_knowledge_required'])  # one complete snapshot
    assert result['github_writes_authorized'] is False
    assert result['execution_authorized'] is False
    print(json.dumps({
        'case':item['case'],'panel':item['panel'],'status':result['lesson_retrieval_status'],
        'selected':result['selected_lesson_ids'],'selected_details':result['selected_lessons'],
        'basis':result['retrieval_diagnostics'].get('selection_basis'),
        'read_count':len(attempts),'reason_codes':result['selection_reason_codes'],
        'admissible':result['substantial_hypothesis_admissible'],
    },sort_keys=True))
