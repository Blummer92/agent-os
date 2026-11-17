"""Ledger-guided 2026-11-17 CKR2 controls: 25 positive, 25 negative, 10 integration.

These are explicit synthetic test oracles, not human-labeled relevance accuracy.
"""
import pytest
from agent_memory_context_manager import coding_knowledge_selection as mod
from agent_memory_context_manager.lesson_preflight import FailedRepairAttempt, LessonRetrievalStatus, RetryReentryOutcome
from agent_memory_context_manager.repair_lesson_activation import activate_repair_retry_lessons

REF="https://github.com/Blummer92/agent-os/issues/1362"
TITLE="CKR6 mutation gate must use verified lesson preflight"
GUIDE=("Check CKR6 mutation boundary admission on the exact head.",)
ORDINARY=("Review ordinary tests.",)

def req(m=mod, **kw):
    d=dict(task_reference="synthetic CKR2 campaign", ecosystem_hints=("GitHub Actions",),
           language_hints=("Python",), library_hints=(),
           capability_keywords=("CKR6 mutation boundary",), target_path_hints=(),
           specialized_knowledge_required=True)
    d.update(kw)
    return m.CodingKnowledgeRequest(**d)

def cand(m=mod, **kw):
    d=dict(knowledge_id="LL-51", source_system="notion-lessons-learned",
           source_revision="2026-11-15T02:52:00.000Z",
           currentness=m.KnowledgeCurrentness.CURRENT, name=TITLE, ecosystem="notion",
           library_name=None, capability_kind="testing", keywords=(), use_when=GUIDE,
           canonical_github_refs=(REF,))
    d.update(kw)
    return m.CodingKnowledgeCandidate(**d)

# id, request overrides, candidate overrides, expected exact matching reason
POS=[
("literal-boundary",{"capability_keywords":("CKR6 mutation boundary",)},{"use_when":ORDINARY},"verified-ckr6-mutation-context-match"),
("literal-gate",{"capability_keywords":("CKR6 mutation gate",)},{"use_when":ORDINARY},"verified-ckr6-mutation-context-match"),
("literal-boundary-gate",{"capability_keywords":("CKR6 mutation boundary gate",)},{"use_when":ORDINARY},"verified-ckr6-mutation-context-match"),
]
for i,phrase in enumerate(("ckr6 mutation boundary","CKR6 MUTATION GATE","CKR6 MUTATION BOUNDARY GATE",
                           "  CKR6 mutation boundary  "," CKR6 mutation gate "," ckr6 mutation boundary gate ")):
    POS.append(("normalized-"+str(i),{"capability_keywords":(phrase,)},{"use_when":ORDINARY},"verified-ckr6-mutation-context-match"))
for i in range(4):
    name="safe-library-"+str(i)
    POS.append(("library-"+str(i),{"library_hints":(name,),"capability_keywords":("unrelated",)},
                {"name":"ordinary reference","library_name":name,"use_when":ORDINARY},"exact-library-match"))
for i in range(4):
    name="safe-library-"+str(i)
    POS.append(("path-"+str(i),{"target_path_hints":("08_Tooling/"+name+"/src/file.py",),"capability_keywords":("unrelated",)},
                {"name":"ordinary reference","library_name":name,"use_when":ORDINARY},"target-path-match"))
for i in range(4):
    word="registered-capability-"+str(i)
    POS.append(("eco-"+str(i),{"capability_keywords":(word,)},
                {"name":"ordinary reference","ecosystem":"python","keywords":(word,),"use_when":ORDINARY},"ecosystem-capability-match"))
for i in range(4):
    word="bounded-capability-"+str(i)
    POS.append(("keyword-"+str(i),{"capability_keywords":(word,),"ecosystem_hints":("other",),"language_hints":("other",)},
                {"name":"ordinary reference","ecosystem":"python","keywords":(word,),"use_when":ORDINARY},"keyword-overlap"))

# id, request overrides, candidate overrides, special collection, status, exact reason
NEG=[]
for i,title in enumerate(("CKR6 lifecycle reference","Mutation testing coverage","preckr6 mutation guidance",
                           "CKR6 premutation reference","CKR6 safety policy","Generic unrelated testing")):
    NEG.append(("one-anchor-"+str(i),{},{"name":title,"use_when":ORDINARY},None,"insufficient","no-relevant-candidate"))
for i,phrase in enumerate(("CKR6 mutation approval","CKR6 mutation evaluation",
                           "CKR6 mutation audit","mutation gate CKR6")):
    NEG.append(("unsupported-hint-"+str(i),{"capability_keywords":(phrase,)},
                {"use_when":ORDINARY},None,"insufficient","no-relevant-candidate"))
NEG.extend([
("stale",{},{"currentness":"STALE"},None,"manual-review","stale-relevant-candidate"),
("unverifiable",{},{"currentness":"UNVERIFIABLE"},None,"manual-review","unverifiable-relevant-candidate"),
("conflict",{},{"authority_conflict":True},None,"manual-review","canonical-authority-conflict"),
("missing-provenance",{},{"canonical_github_refs":()},None,"insufficient","canonical-reference-missing"),
("uncovered-library",{"library_hints":("missing-required-library",)},{},None,"insufficient","required-library-uncovered"),
])
for field in ("source_revision","name","keywords"):
    NEG.append(("duplicate-"+field,{},{},field,"manual-review","duplicate-identity-conflict"))
for i in range(2):
    NEG.append(("budget-"+str(i),{},{}, "six", "manual-review","candidate-budget-exceeded"))
NEG.extend([
("false-with-relevant",{"specialized_knowledge_required":False},{},None,"not-needed","knowledge-not-needed"),
("false-with-empty-hints",{"specialized_knowledge_required":False,"capability_keywords":()},{"use_when":ORDINARY},None,"not-needed","knowledge-not-needed"),
("empty-corpus",{},{}, "empty","insufficient","no-relevant-candidate"),
("irrelevant-one",{"capability_keywords":("unrelated",)},{"name":"ordinary reference","use_when":ORDINARY},None,"insufficient","no-relevant-candidate"),
("implicit-not-needed",{"specialized_knowledge_required":None,"capability_keywords":()},{"name":"ordinary reference","use_when":ORDINARY},None,"not-needed","knowledge-not-needed"),
])
assert len(POS)==25 and len(NEG)==25,(len(POS),len(NEG))

def check_positive(m,case):
    name,r,c,reason=case
    output=m.select_coding_knowledge(req(m,**r),(cand(m,**c),))
    assert output.sufficiency_status is m.SufficiencyStatus.SUFFICIENT,name
    assert [x.candidate.knowledge_id for x in output.selected]==["LL-51"],name
    assert reason in output.selected[0].reason_codes,name

def check_negative(m,case):
    name,r,c,extra,status,reason=case
    c=dict(c)
    if isinstance(c.get("currentness"),str):
        c["currentness"]=getattr(m.KnowledgeCurrentness,c["currentness"])
    original=cand(m,**c)
    if extra=="empty": vals=()
    elif extra=="six": vals=tuple(cand(m,knowledge_id="LL-"+str(i)) for i in range(6))
    elif extra in ("source_revision","name","keywords"):
        replacement={"source_revision":"new-revision","name":"different title","keywords":("other",)}[extra]
        vals=(original,cand(m,**{**c,extra:replacement}))
    else: vals=(original,)
    output=m.select_coding_knowledge(req(m,**r),vals)
    assert output.sufficiency_status.value==status,name
    assert reason in output.reason_codes,name
    if reason not in ("required-library-uncovered","canonical-reference-missing"):
        assert output.selected_count==0 or status=="not-needed",name

@pytest.mark.parametrize("case",POS,ids=[x[0] for x in POS])
def test_positive_selector(case): check_positive(mod,case)

@pytest.mark.parametrize("case",NEG,ids=[x[0] for x in NEG])
def test_negative_selector(case): check_negative(mod,case)

def row(title=TITLE,guidance=GUIDE[0],link=REF):
    def rich(s):return {"type":"rich_text","rich_text":[{"plain_text":s}]}
    def title_value(s):return {"type":"title","title":[{"plain_text":s}]}
    def selected(s):return {"type":"select","select":{"name":s}}
    return {"object":"page","id":"notion-ll-51","url":"https://www.notion.so/lesson-51",
            "last_edited_time":"2026-11-15T02:52:00.000Z",
            "properties":{"Lesson ID":rich("LL-51"),"Lesson Learned":title_value(title),
              "Status":selected("Applied"),"Surface Before Work?":{"type":"checkbox","checkbox":True},
              "Area":selected("Testing"),"Applies To":{"type":"multi_select","multi_select":[{"name":"Notion"}]},
              "Learning Type":selected("Testing lesson"),"Source Link":{"type":"url","url":link},
              "Guardrail":rich("Keep retry admission gated."),"What To Do Next Time":rich(guidance)}}

INTEGRATIONS=[
("positive-boundary","CKR6 mutation boundary","good"),
("positive-gate","CKR6 mutation gate","good"),
("positive-boundary-gate","CKR6 mutation boundary gate","good"),
("positive-uppercase","CKR6 MUTATION GATE","good"),
("positive-whitespace"," ckr6 mutation boundary ","good"),
("negative-irrelevant","CKR6 mutation boundary","irrelevant"),
("negative-missing-ref","CKR6 mutation boundary","no-ref"),
("negative-terminal-cursor","CKR6 mutation boundary","malformed"),
("negative-unavailable","CKR6 mutation boundary","unavailable"),
("negative-explicit-false","CKR6 mutation boundary","false"),
]
assert len(INTEGRATIONS)==10

@pytest.mark.parametrize("name,word,kind",INTEGRATIONS,ids=[x[0] for x in INTEGRATIONS])
def test_ckr6_retry_through_ckr11_and_ckr2(name,word,kind):
    calls=[]
    def read(query):
        calls.append(query)
        value=row()
        if kind=="irrelevant":value=row(title="Generic unrelated test",guidance="Review ordinary tests.")
        if kind=="no-ref":value=row(link=None)
        return {"results":[value],"has_more":False,"next_cursor":"contradiction" if kind=="malformed" else None}
    r=req(capability_keywords=(word,),specialized_knowledge_required=False if kind=="false" else True)
    attempt=FailedRepairAttempt("attempt-"+name,"hypothesis","repair failed")
    result=activate_repair_retry_lessons(r,attempt,execute_read=None if kind=="unavailable" else read)
    if kind=="false":
        assert len(calls)==0
        assert result.lesson_result.lesson_retrieval_status is LessonRetrievalStatus.NOT_NEEDED
        assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.NOT_MATERIAL
        assert result.boundary.mutation_admissible
    elif kind=="good":
        assert len(calls)==1
        assert result.lesson_result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert result.lesson_result.selected_lesson_ids==("LL-51",)
        assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.CONSUMED
        assert result.boundary.mutation_admissible
    else:
        assert result.lesson_result.selected_lesson_ids==()
        assert result.lesson_result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
        assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.UNAVAILABLE_OR_FAILED
        assert not result.boundary.mutation_admissible
        if kind=="malformed":assert result.lesson_result.retrieval_diagnostics["incomplete_reason_code"]=="malformed-pagination"
        if kind=="unavailable":assert len(calls)==0
