# Live Smoke Authorization Packet

This defines the authorization packet for a first live Gemini call. **No live
test runs as part of the change that introduced this file.** Running one
requires separate, explicit authorization recorded here.

The run produces **evidence only**. It grants no approval and no write
authority.

## Preconditions — all must hold

- [ ] `GENAI_LIVE=1` set deliberately for this run only.
- [ ] Selected model is **not past its shutdown date**. `DEFAULT_GEMINI_MODEL`
      is `gemini-2.5-flash`, shutdown `2026-10-16` (see
      `DEFAULT_GEMINI_MODEL_SHUTDOWN`). A run selecting a retired model **fails
      closed** — do not substitute another model at runtime.
- [ ] Installed `google-genai` inside the validated range (`>=1.0,<3.0`);
      `check_sdk_compatibility()` passes.
- [ ] One named **non-production** Notion page identified below.
- [ ] One **throwaway** Google Drive folder identified below.
- [ ] Credential present in the environment or Colab secret store only — never
      in a file, a cell, or this document.
- [ ] Offline suite green in both dependency states.

## Targets — fill in at authorization time

| Field | Value |
|---|---|
| Notion page ID (non-production) | `<TO BE SUPPLIED>` |
| Drive folder ID (throwaway) | `<TO BE SUPPLIED>` |
| Authorizing owner | `<TO BE SUPPLIED>` |
| Authorization date | `<TO BE SUPPLIED>` |

Leave placeholders until an owner supplies them. Never commit a real
production identifier here.

## Bounds

The run may: read the one named Notion page, call the model once, and write one
draft YAML into the throwaway folder or a local path.

The run may **not**: change readiness, approval, registry, governance, or
ownership records; write to GitHub; touch any production Drive folder or Notion
page; or reuse its output as acceptance evidence.

## Evidence to record

- Model name and resolved `google-genai` version
- UTC timestamp
- Input fixture or prompt identifier (not the full prompt)
- Output schema result: validated, or the `GenerationResponseError` raised
- Destination IDs used
- Whether any tool declaration was sent, and whether any dispatch occurred

## Redaction

Logs must carry no credentials, no full prompts, and no sensitive source
content. Adapter diagnostics are already bounded to 200 characters and are
asserted so by `test_error_diagnostics_are_bounded`. Redact page titles and
student-identifying content before attaching evidence anywhere.

## Cleanup — required, not optional

1. Unset `GENAI_LIVE`.
2. Delete the generated draft and any file created in the throwaway folder.
3. Delete the throwaway folder itself if it was created for this run.
4. Confirm the Notion page is unchanged — the read path performs no write, so
   any difference is a defect and stops further runs.
5. Rotate the credential if it was exposed in any log or terminal capture.

## After the run

Record the outcome against the governing issue. A successful run demonstrates
the contract works; it does not authorize production use, a wider rollout, or
any write surface. Each of those is a separate decision.
