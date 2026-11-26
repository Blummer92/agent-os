import json
from pathlib import Path
p=Path(__file__).parent
archive=json.loads((p/'archive.json').read_text())
def row(i,title,guidance,guard,ap=None):
 return dict(id=i,t=title,n=guidance,g=guard,area='Governance',lt='QA feedback',st='Applied',ap=ap or [],s='https://github.com/Blummer92/agent-os/issues/4026',ss=[],le='2026-11-20T00:00:00.000Z')
a=row(901,'Notion writer persistence readback','After a Notion write, use an independent readback to verify the persisted revision.','Preserve canonical source proof.',['Notion'])
b={**a,'id':902,'n':'Before a Notion write, use an independent readback to verify the persisted revision.'}
c={**a,'id':903,'n':'Use an independent readback to verify the persisted revision, then perform the Notion write.'}
d=row(904,'GitHub issue comment pagination','Reject duplicate GitHub issue comment IDs across all pages.','Do not bypass canonical evidence.')
e={**d,'id':905,'g':'Keep duplicate GitHub issue comment IDs across pages.'}
f=row(906,'GitHub HTTP GET response size and timestamp provenance','Reject oversized GitHub HTTP GET response bytes and verify timestamp provenance.','Keep exact SHA evidence.')
g={**f,'id':907,'g':'Accept oversized GitHub HTTP GET response bytes.'}
panels=dict(archive=archive,writer=[a],writer_before=[b],writer_reversed=[c],pagination=[d,e],pagination_opposite=[e],receipts=[f,g],receipts_opposite=[g])
cases=[]
def add(i,panel,task,hints=(),ecos=('python',),libraries=(),material=True):
 cases.append(dict(case=i,panel=panel,task=task,request=dict(task_reference=task,capability_keywords=hints,ecosystem_hints=ecos,library_hints=libraries,specialized_knowledge_required=material)))
add('A01','archive','Find whether the build already has valid results for the current commit before asking CI to rerun.',('testing','exact-head evidence','validation'))
add('A02','archive','Our focused tests pass but the full validation fails. Determine if a clean checkout of main already fails before changing this branch.',('testing','aggregate validation','CI failure'))
add('A03','archive','Issue #123 is cited inside a quoted example. Find the real closure target without treating the example as an instruction.',('testing','linked-issue parsing','closing keyword'))
add('A04','archive','A parser encounters a closing reference for another repository. Retain that repository identity and do not automatically close a local issue.',('testing','linked-issue parsing','repository identity'))
add('A05','archive','The executor cannot interpret optional fields from a newer evidence packet. Preserve them during round-trip serialization.',('testing','compatibility','unknown fields'))
add('A06','archive','Design a property-based parser test with generated cases and shrinking rather than just a fixed table.',('property-based testing','shrinking','strategy design'),libraries=('Hypothesis',))
add('A07','archive','A prior repair failed. Preserve that attempt and re-enter coding lessons preflight before choosing the next repair.',('failure-avoidance','failed repair','CKR6 re-entry'))
add('A08','archive','The collector got the first page. Prove it has actually reached the final page for the repository and revision being audited.',('testing','pagination','retrieval completeness'))
add('A09','archive','The pull request API says the branch cannot merge. Determine whether it can be refreshed without conflict before rejecting it.',('git branch refresh','rebase rejection','merge-tree conflict detection','bounded recovery'),ecos=('git',))
add('A10','archive','Reject a contract with an unsupported major version instead of silently treating it as the current version.',('testing','compatibility','major contract version'))
add('A11','archive','Read the failed CI job and find its first actionable error. Do not report the red status itself as the cause.',('testing','CI diagnostics'))
add('A12','archive','Choose a line spacing and font size for a printable student worksheet.',('print typography','worksheet layout'),ecos=('instructional design',))
add('A13','archive','Decide how to jitter reconnect intervals for a WebSocket heartbeat.',('websocket heartbeat','timeout policy'),ecos=('networking',))
add('A14','archive','Check a single fixed wheel import and version with the ordinary local assertions already supplied by the repository.',('testing','packaging'),material=False)
w='Find guidance for checking that a newly written Notion revision actually persisted, using a read independent of the write response.'
wh=('notion writer','persistence readback','failure receipts')
for i,panel in enumerate(('writer','writer_before','writer_reversed'),1):add(f'W{i:02}',panel,w,wh,ecos=('agent-os','python'))
add('W04','writer','Find guidance on choosing formatting for text in a Notion dashboard, not on proving persistence.',('dashboard typography',),ecos=('agent-os',))
t='Find guidance on rejecting repeated GitHub issue-comment IDs across paginated GET responses.'
h=('github issue comment pagination','duplicate record detection')
for i,panel in enumerate(('pagination','pagination_opposite'),1):add(f'P{i:02}',panel,t,h,ecos=('python','github rest api'))
t='Find guidance for rejecting oversized GitHub REST GET bodies and verifying timestamp provenance.'
h=('bounded http get response limits','timestamp provenance')
for i,panel in enumerate(('receipts','receipts_opposite'),1):add(f'R{i:02}',panel,t,h,ecos=('python','github rest api'))
for name,data in [('panels.json',panels),('requests.json',cases)]: (p/name).write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
