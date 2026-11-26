from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
TASK = ("PR #4067 exact head 5346d30962f0ee0004ed5ab12f9d3dce4b253f57: validate tests-only "
        "CKR2 LL-51 unrelated packaging negative control, explicit mutation-boundary positive, "
        "provenance, pagination, and mutation-discrimination tests. No merge, issue closure, "
        "or Notion write authorization.")
REQ = CodingKnowledgeRequest(
    task_reference=TASK, ecosystem_hints=("python",),
    capability_keywords=("testing", "lesson-selection"), specialized_knowledge_required=True,
)


def rt(text, kind="rich_text"):
    return {"type": kind, kind: [{"plain_text": text}]}


def to_row(l):
    props = {
        "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": l["id"]}},
        "Lesson Learned": rt(l["t"], "title"),
        "Status": {"type": "select", "select": {"name": l["st"]}},
        "Surface Before Work?": {"type": "checkbox", "checkbox": True},
        "Area": {"type": "select", "select": {"name": l["area"]}},
        "Learning Type": {"type": "select", "select": {"name": l["lt"]}},
        "Applies To": {"type": "multi_select", "multi_select": [{"name": a} for a in l["ap"]]},
        "Source Link": {"type": "url", "url": l["s"]},
        "Guardrail": rt(l["g"]),
        "What To Do Next Time": rt(l["n"]),
    }
    if l["ss"]:
        props["Supporting Source Links"] = {"type": "rich_text", "rich_text": [
            {"plain_text": u, "href": u} for u in l["ss"]]}
    return {"object": "page", "id": f"p{l['id']}", "url": f"https://www.notion.so/p{l['id']}",
            "last_edited_time": l["le"], "properties": props}


