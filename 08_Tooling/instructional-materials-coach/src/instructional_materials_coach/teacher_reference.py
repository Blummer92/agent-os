"""Bounded teacher-facing Unit Alignment reference projections for #1417.

This module does not create a new curriculum, vocabulary, visual, prompt, or PDF
system. It projects already-current supplied Unit Alignment / Teacher Modeling
rows plus exact governed #944 visual assignments into deterministic,
renderer-ready teacher reference documents. Rendering/storage remains owned by
the existing artifact/PDF execution surface and is separately authorized.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

MAX_ROWS = 96
MAX_TEXT = 2_000
_EXPECTATIONS = frozenset({"core", "supporting", "exposure", "review", "transfer", "future", "unspecified"})
_ICON_REQUIREMENTS = frozenset({"required", "useful", "not-needed"})
_EXAMPLE_ROLES = frozenset({"worked-example", "non-example", "comparison", "model", "unspecified"})
_TEACHER_REFERENCE_MATERIAL_TYPE = "teacher-reference"


class TeacherReferenceError(ValueError):
    """Fail-closed error for incomplete or incompatible reference evidence."""


def build_unit_vocabulary_reference(*, unit_title: str, vocabulary_rows: object, governed_visual_assignments: object = ()) -> dict[str, Any]:
    title = _text(unit_title, "unit_title"); rows = _rows(vocabulary_rows, "vocabulary_rows"); assignments = _assignments(governed_visual_assignments)
    projected=[]; excluded_scaffolds=[]
    for index,row in enumerate(rows,start=1):
        kind=_optional_text(row.get("kind"),f"vocabulary_rows[{index}].kind") or "vocabulary"
        if kind=="scaffold": excluded_scaffolds.append(_text(row.get("term"),f"vocabulary_rows[{index}].term")); continue
        if kind!="vocabulary": raise TeacherReferenceError(f"vocabulary_rows[{index}].kind is unsupported")
        term=_text(row.get("term"),f"vocabulary_rows[{index}].term"); definition=_text(row.get("student_friendly_definition"),f"vocabulary_rows[{index}].student_friendly_definition")
        expectation=(_optional_text(row.get("expectation"),f"vocabulary_rows[{index}].expectation") or "unspecified").lower()
        if expectation not in _EXPECTATIONS: raise TeacherReferenceError(f"vocabulary_rows[{index}].expectation is unsupported")
        icon_requirement=(_optional_text(row.get("icon_requirement"),f"vocabulary_rows[{index}].icon_requirement") or "not-needed").lower()
        if icon_requirement not in _ICON_REQUIREMENTS: raise TeacherReferenceError(f"vocabulary_rows[{index}].icon_requirement is unsupported")
        role_id=_optional_text(row.get("icon_role_id"),f"vocabulary_rows[{index}].icon_role_id"); matched=assignments.get(role_id) if role_id else None
        icon=_icon_projection(icon_requirement,_authorized_assignment(matched,required_role_type="icon"))
        projected.append({"day_lesson":_optional_text(row.get("day_lesson"),f"vocabulary_rows[{index}].day_lesson"),"term":term,"student_friendly_definition":definition,"expectation":expectation,"icon_status":icon["status"],"icon_preview":icon["preview"],"source_reference":_optional_text(row.get("source_reference"),f"vocabulary_rows[{index}].source_reference")})
    return {"reference_type":"unit-vocabulary-map","unit_title":title,"key":{"approved-existing":"Approved reusable icon identity is resolved and must be reused.","useful-but-missing":"An icon would help, but no approved reusable icon is resolved.","no-icon-needed":"An icon is not instructionally necessary."},"rows":projected,"excluded_scaffolds":excluded_scaffolds,"authority":_authority_false()}


def build_worked_examples_reference(*,unit_title:str,modeling_rows:object,visual_prompt_rows:object=(),governed_visual_assignments:object=())->dict[str,Any]:
    title=_text(unit_title,"unit_title"); rows=_rows(modeling_rows,"modeling_rows"); prompts=_prompt_index(visual_prompt_rows); assignments=_assignments(governed_visual_assignments); projected=[]
    for index,row in enumerate(rows,start=1):
        role=(_optional_text(row.get("example_role"),f"modeling_rows[{index}].example_role") or "unspecified").lower()
        if role not in _EXAMPLE_ROLES: raise TeacherReferenceError(f"modeling_rows[{index}].example_role is unsupported")
        visual_role_id=_optional_text(row.get("visual_role_id"),f"modeling_rows[{index}].visual_role_id"); ui_visual=row.get("software_ui") is True; prompt=prompts.get(visual_role_id) if visual_role_id else None
        if ui_visual and prompt is not None: raise TeacherReferenceError("software UI must not carry a generative visual prompt")
        assignment=assignments.get(visual_role_id) if visual_role_id else None; required_role_type="current-ui-reference" if ui_visual else role; authorized=_authorized_assignment(assignment,required_role_type=required_role_type)
        if ui_visual: visual_status="current-ui-reference-required"; visual_identity=_selected_identity(authorized) if authorized else None
        elif authorized is not None: visual_status="approved-existing"; visual_identity=_selected_identity(authorized)
        else: visual_status="explicit-gap"; visual_identity=None
        projected.append({"day_lesson":_optional_text(row.get("day_lesson"),f"modeling_rows[{index}].day_lesson"),"skill_learning_purpose":_text(row.get("skill_learning_purpose"),f"modeling_rows[{index}].skill_learning_purpose"),"example_role":role,"teacher_modeling_purpose":_text(row.get("teacher_modeling_purpose"),f"modeling_rows[{index}].teacher_modeling_purpose"),"artifact_location":_optional_text(row.get("artifact_location"),f"modeling_rows[{index}].artifact_location"),"tutorial_step":_optional_text(row.get("tutorial_step"),f"modeling_rows[{index}].tutorial_step"),"visual_status":visual_status,"visual_preview":visual_identity,"visual_prompt":None if prompt is None else prompt["prompt"],"expected_visual_description":_optional_text(row.get("expected_visual_description"),f"modeling_rows[{index}].expected_visual_description"),"source_reuse_safe_use_constraints":_constraints(row,authorized,prompt),"software_ui":ui_visual})
    return {"reference_type":"worked-examples-visual-prompts","unit_title":title,"rows":projected,"authority":_authority_false()}


def render_teacher_reference_markdown(reference:object)->str:
    if type(reference) is not dict: raise TeacherReferenceError("reference must be a built-in mapping")
    reference_type=reference.get("reference_type"); unit_title=_text(reference.get("unit_title"),"unit_title"); authority=reference.get("authority")
    if type(authority) is not dict or any(authority.values()): raise TeacherReferenceError("reference authority must remain false")
    lines=[f"# {unit_title}"]
    if reference_type=="unit-vocabulary-map":
        lines.extend(["","## Unit Vocabulary Map","","| Day / lesson | Word / term | Student-friendly definition | Expectation | Icon status | Icon preview |","|---|---|---|---|---|---|"])
        for row in _rows(reference.get("rows"),"rows"):
            preview=_preview_text(row.get("icon_preview")); lines.append("| "+" | ".join(_cell(v) for v in (row.get("day_lesson") or "—",row.get("term"),row.get("student_friendly_definition"),row.get("expectation"),row.get("icon_status"),preview))+" |")
        lines.extend(["","**Icon key:** approved-existing = reuse resolved approved icon; useful-but-missing = explicit gap; no-icon-needed = no icon required."])
        excluded=reference.get("excluded_scaffolds")
        if isinstance(excluded,list) and excluded: lines.extend(["","**Instructional scaffolds kept out of vocabulary:** "+", ".join(_cell(item) for item in excluded)])
    elif reference_type=="worked-examples-visual-prompts":
        lines.extend(["","## Worked Examples + Visual Prompt Reference",""])
        for row in _rows(reference.get("rows"),"rows"):
            lines.extend([f"### {_cell(row.get('day_lesson') or 'Unplaced')} — {_cell(row.get('skill_learning_purpose'))}",f"- Example role: {_cell(row.get('example_role'))}",f"- Teacher modeling purpose: {_cell(row.get('teacher_modeling_purpose'))}",f"- Artifact location: {_cell(row.get('artifact_location') or 'Not resolved')}",f"- Tutorial step: {_cell(row.get('tutorial_step') or 'Not applicable')}",f"- Visual status: {_cell(row.get('visual_status'))}",f"- Approved visual identity: {_preview_text(row.get('visual_preview'))}",f"- Existing visual prompt: {_cell(row.get('visual_prompt') or 'None / not generative')}",f"- Expected visual role: {_cell(row.get('expected_visual_description') or 'Not resolved')}",f"- Source / reuse / safe-use: {_cell(row.get('source_reuse_safe_use_constraints') or 'No additional supplied constraint')}",""])
    else: raise TeacherReferenceError("unsupported reference_type")
    lines.extend(["","_Teacher reference only. This projection grants no readiness, approval, source, publication, production, or external-write authority._"]); return "\n".join(lines).rstrip()+"\n"


def _assignments(value:object)->dict[str,Mapping[str,Any]]:
    if value in (None,(),[]): return {}
    if isinstance(value,str):
        try: value=json.loads(value)
        except json.JSONDecodeError as exc: raise TeacherReferenceError("governed visual assignments are not valid JSON") from exc
    rows=_rows(value,"governed_visual_assignments"); result={}
    for index,assignment in enumerate(rows,start=1):
        role_id=_text(assignment.get("role_id"),f"governed_visual_assignments[{index}].role_id")
        if role_id in result: raise TeacherReferenceError(f"duplicate governed visual role_id: {role_id}")
        result[role_id]=assignment
    return result


def _authorized_assignment(assignment:Mapping[str,Any]|None,*,required_role_type:str)->Mapping[str,Any]|None:
    if assignment is None: return None
    evidence=assignment.get("compatibility_evidence")
    if not isinstance(evidence,Mapping): return None
    approved=evidence.get("approved_use")
    if not isinstance(approved,Mapping) or approved.get("state")!="approved": return None
    material_types=approved.get("material_types"); role_types=approved.get("role_types")
    if type(material_types) not in (list,tuple) or _TEACHER_REFERENCE_MATERIAL_TYPE not in material_types: return None
    if type(role_types) not in (list,tuple) or required_role_type not in role_types: return None
    if assignment.get("role_type")!=required_role_type: return None
    return assignment


def _prompt_index(value:object)->dict[str,dict[str,str]]:
    if value in (None,(),[]): return {}
    rows=_rows(value,"visual_prompt_rows"); result={}
    for index,row in enumerate(rows,start=1):
        role_id=_text(row.get("visual_role_id"),f"visual_prompt_rows[{index}].visual_role_id")
        if role_id in result: raise TeacherReferenceError(f"duplicate visual prompt role_id: {role_id}")
        if row.get("generative") is not True: raise TeacherReferenceError("only explicitly generative prompt evidence may be projected")
        result[role_id]={"prompt":_text(row.get("prompt"),f"visual_prompt_rows[{index}].prompt"),"source_constraints":_optional_text(row.get("source_constraints"),f"visual_prompt_rows[{index}].source_constraints") or ""}
    return result


def _icon_projection(requirement:str,assignment:Mapping[str,Any]|None)->dict[str,Any]:
    if requirement=="not-needed": return {"status":"no-icon-needed","preview":None}
    if assignment is None: return {"status":"useful-but-missing","preview":None}
    return {"status":"approved-existing","preview":_selected_identity(assignment)}


def _selected_identity(assignment:Mapping[str,Any]|None)->dict[str,str]|None:
    if assignment is None:return None
    selected=assignment.get("selected_candidate")
    if type(selected) is not dict: raise TeacherReferenceError("governed visual assignment is missing selected_candidate")
    asset=selected.get("asset_reference"); manifest=selected.get("manifest_reference")
    if type(asset) is not dict or type(manifest) is not dict: raise TeacherReferenceError("governed visual identity is incomplete")
    return {"role_id":_text(assignment.get("role_id"),"assignment.role_id"),"role_type":_text(assignment.get("role_type"),"assignment.role_type"),"asset_id":_text(asset.get("asset_id"),"asset_reference.asset_id"),"stable_ref":_text(asset.get("stable_ref"),"asset_reference.stable_ref"),"external_file_id":_text(manifest.get("external_file_id"),"manifest_reference.external_file_id")}


def _constraints(row:Mapping[str,Any],assignment:Mapping[str,Any]|None,prompt:Mapping[str,str]|None)->str:
    parts=[]; supplied=_optional_text(row.get("source_constraints"),"modeling_row.source_constraints")
    if supplied:parts.append(supplied)
    if assignment is not None:
        evidence=assignment.get("compatibility_evidence")
        if isinstance(evidence,Mapping):
            approved=evidence.get("approved_use")
            if isinstance(approved,Mapping): parts.append("approved_use="+json.dumps({"state":approved.get("state"),"material_types":approved.get("material_types"),"role_types":approved.get("role_types")},sort_keys=True,separators=(",",":")))
    if prompt and prompt.get("source_constraints"):parts.append(prompt["source_constraints"])
    return " | ".join(parts)


def _rows(value:object,name:str)->list[Mapping[str,Any]]:
    if type(value) not in (list,tuple):raise TeacherReferenceError(f"{name} must be a bounded list or tuple")
    if len(value)>MAX_ROWS:raise TeacherReferenceError(f"{name} exceeds {MAX_ROWS} rows")
    result=[]
    for item in value:
        if type(item) is not dict:raise TeacherReferenceError(f"{name} rows must be built-in mappings")
        result.append(item)
    return result


def _text(value:object,name:str)->str:
    if not isinstance(value,str) or not value.strip():raise TeacherReferenceError(f"{name} is required")
    text=value.strip()
    if len(text)>MAX_TEXT:raise TeacherReferenceError(f"{name} exceeds {MAX_TEXT} characters")
    return text


def _optional_text(value:object,name:str)->str|None:
    if value is None:return None
    return _text(value,name)


def _cell(value:object)->str:return str(value).replace("\n"," ").replace("|","\\|").strip()

def _preview_text(value:object)->str:
    if value is None:return "—"
    if not isinstance(value,Mapping):raise TeacherReferenceError("visual preview must be an identity mapping")
    return _cell(" / ".join(str(value[key]) for key in ("asset_id","stable_ref","external_file_id") if value.get(key)))

def _authority_false()->dict[str,bool]:return {"readiness":False,"approval":False,"source":False,"publication":False,"production":False,"external_write":False}
