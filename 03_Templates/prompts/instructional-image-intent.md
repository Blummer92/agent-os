# Instructional ImageIntent

Use this template to define the canonical provider-neutral image intent before any provider-specific prompt is assembled.

Provider-ready prompt prose is derived working output, not canonical evidence. Asset approval, rights, provenance, privacy, and classroom readiness remain governed elsewhere.

## Identity

- **Asset ID:** optional stable ID if already assigned
- **Concept:** what are we making?
- **Purpose:** what does it teach?

## Scene

- **Subject:** what must be pictured?
- **Action:** optional action or relationship
- **Environment:** optional setting or context

## Visual Direction

- **Composition:** how should the visual elements be arranged?
- **Viewpoint:** where is the viewer positioned?
- **Look:** realistic, documentary, technical, illustrative, or other concise visual direction

## Control

### Must Show

- List the evidence that must be visible for the image to teach the intended idea.

### Creative Freedom

- List details that may vary without weakening the instructional purpose.

### Avoid

- List only relevant failure modes or unwanted content.
- Do not repeat generic boilerplate unless it materially affects this image.

## Output

- **Orientation:** portrait, landscape, square, wide, tall, or unspecified
- **Aspect target:** provider-neutral ratio or target such as `3:2`, `4:5`, or `16:9`
- **Add later:** grids, arrows, labels, axes, highlights, crops, or other derivative overlays that should not be baked into the clean master

## Library Handoff

Keep this metadata separate from provider-generation prose.

- **Unit / lesson:**
- **Asset role:**
- **Intended reuse:**
- **Candidate status:**
- **Review notes:**

## ImportedAssetContext

Use this separate working record when an image was uploaded or imported and no canonical ImageIntent exists.

- **Source mode:** upload or import
- **Provider claim:** Gemini, Meta, Firefly, Canva, other, or unknown
- **Prompt claim:** supplied prompt or unknown
- **Model claim:** supplied model/version or unknown
- **Generation date claim:** supplied date or unknown
- **Original filename:** supplied filename or unknown
- **Source note:** optional user-supplied context

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
