# Instructional ImageIntent

Use this template to define the canonical provider-neutral image intent before any provider-specific prompt is assembled.

Canonical schema source: `src/instructional_workflow_contracts/image_intent.py`.

Provider-ready prompt prose is derived working output, not canonical evidence. Approval, rights, provenance, privacy, classroom readiness, source-of-truth, and write authorization remain governed by the canonical repository policies in `00_Governance/ownership-and-source-of-truth.md` and `00_Governance/write-authorization-policy.md` rather than by this template.

## Identity

- **Contract version:** required; `curriculum-image-intent-v1`
- **Intent ID:** required stable ImageIntent ID
- **Asset ID:** optional stable ID if already assigned; use `null` when absent
- **Concept:** what are we making?
- **Purpose:** what does it teach?

## Scene

- **Subject:** what must be pictured?
- **Action:** optional action or relationship; use `null` when absent
- **Environment:** optional setting or context; use `null` when absent

## Visual Direction

- **Composition:** how should the visual elements be arranged?
- **Viewpoint:** where is the viewer positioned?
- **Look:** realistic, documentary, technical, illustrative, or other concise visual direction

## Control

- **Must show:** the evidence that must be visible for the image to teach the intended idea; at least one item is required.
- **Creative freedom:** details that may vary without weakening the instructional purpose; use an empty list when no creative freedom is specified.
- **Avoid:** only relevant failure modes or unwanted content; do not repeat generic boilerplate unless it materially affects this image; use an empty list when no avoid constraints are specified.

## Output

- **Orientation:** `portrait`, `landscape`, `square`, `wide`, `tall`, or `unspecified`
- **Aspect target:** provider-neutral ratio or target such as `3:2`, `4:5`, or `16:9`
- **Add later:** grids, arrows, labels, axes, highlights, crops, or other derivative overlays that should not be baked into the clean master; use an empty list when none are needed

## Library Handoff

Keep this metadata separate from provider-generation prose.

- **Unit / lesson:** optional; use `null` when absent
- **Asset role:** optional; use `null` when absent
- **Intended reuse:** list; use an empty list when none is supplied
- **Candidate status:** optional; use `null` when absent
- **Review notes:** optional; use `null` when absent

## ImportedAssetContext

Use this separate working record when an image was uploaded or imported and no canonical ImageIntent exists.

- **Contract version:** required; `curriculum-imported-asset-context-v1`
- **Context ID:** required stable ImportedAssetContext ID
- **Source mode:** `upload` or `import`
- **Provider claim:** `gemini`, `meta`, `firefly`, `canva`, `other`, or `unknown`
- **Prompt claim:** supplied prompt or `null` when not supplied
- **Model claim:** supplied model/version or `null` when not supplied
- **Generation date claim:** supplied date or `null` when not supplied
- **Original filename:** supplied filename or `null` when not supplied
- **Source note:** optional user-supplied context or `null`

`provider_claim="unknown"` is the explicit schema value when the provider itself is unknown. Optional prompt, model, date, filename, and source-note claims use `null` when no value was supplied.

User-supplied provider, prompt, model, date, or source statements are provenance claims only. Do not infer missing generation history from pixels, metadata, filenames, or appearance.

## Gemini Manual Handoff

For the current manual workflow, render the validated ImageIntent into concise natural-language prompt prose that:

- states the concept, subject, scene, and teaching purpose first;
- preserves composition, viewpoint, and look;
- includes must-show evidence;
- includes creative freedom only when useful;
- includes avoid constraints only when present;
- states orientation/aspect target;
- keeps add-later instructional overlays out of the clean master when practical;
- excludes Library Handoff metadata from provider prose.

Current workflow:

`Teacher request -> ImageIntent -> Gemini-ready prompt -> teacher manually generates candidates in Gemini -> teacher uploads selected candidates to ChatGPT -> Visual Asset Intake`

Direct provider APIs are future work and are not authorized by this template.

## Supersession

This template supersedes the monolithic `IMAGE PROMPT` record proposed in #950 / PR #951. Preserve its useful readability, avoid/add-later, and clean-master ideas, but treat structured ImageIntent as canonical instead of provider prose.
