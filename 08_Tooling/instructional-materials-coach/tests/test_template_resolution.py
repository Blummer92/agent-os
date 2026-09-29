from instructional_materials_coach.template_resolution import TemplateCandidate, resolve_approved_template_pair

REQ=("title","objective_1","question_1")

def c(template_id,kind,approval="approved",access="verified",tokens=REQ):
    return TemplateCandidate(template_id,kind,approval,access,tokens)

def test_2969_photography_foundations_resolves_one_approved_compatible_pair():
    pair=resolve_approved_template_pair((c("slides-photo","slides"),c("docs-photo","docs")),required_placeholders=REQ)
    assert pair.slides_template_id=="slides-photo"
    assert pair.docs_template_id=="docs-photo"

def test_2969_title_similar_historical_and_prototype_candidates_never_become_live_templates():
    pair=resolve_approved_template_pair((c("slides-old","slides","historical"),c("slides-prototype","slides","prototype"),c("slides-current","slides"),c("docs-current","docs")),required_placeholders=REQ)
    assert pair.slides_template_id=="slides-current"

def test_2969_zero_multiple_stale_or_incompatible_candidates_fail_closed():
    bad_sets=((),(c("s1","slides"),c("s2","slides"),c("d","docs")),(c("s","slides",access="stale"),c("d","docs")),(c("s","slides",tokens=("title",)),c("d","docs")))
    for candidates in bad_sets:
        try:
            resolve_approved_template_pair(candidates,required_placeholders=REQ)
            assert False,"must fail closed"
        except ValueError:
            pass
