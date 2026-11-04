# Teacher OS — read-only React app (#2801)

A teacher-facing React/Vite app that shows **approved units and their lessons read from verified Notion sources** through an authenticated local API. The repository holds no curriculum: there are no sample units or lessons, and nothing is ever shown in place of missing data. The app does not write Notion or Drive, generate Slides/worksheets, or deploy.

## What a teacher sees

- **Lesson overview** for the selected unit: lesson counter with previous/next, learning target, today's focus, key vocabulary (fields not recorded in Notion say so), provenance (source, verification, access, read time) and an honest **Approved materials** line. No Drive links are invented; the Notion record link appears only if it is an `https://` Notion URL.
- **View Assignment** (top right, #3517) to switch units and browse lessons in a carousel.
- **Complete lesson** view with every governed field and the Notion record link.
- **Local notes / focused edit** — clearly labelled *Unsaved · this session only*; nothing is sent anywhere.
- A **connection status** in the header and a specific explanation for every non-ready state: live reads not admitted, reader not running, session not authorized, malformed response, rate limited, empty, read failed, stale (>15 min). Each offers **Try again**.

## Run it

```sh
cd 08_Tooling/teacher-os-web
npm ci
npm run dev:app        # loopback Vite app + authenticated loopback API; open http://127.0.0.1:5173/
```

`npm run dev:app` starts `server/teacher_os_api.py` (Python stdlib, `127.0.0.1` only) and Vite (`127.0.0.1` only). A fresh random session secret is generated per launch and passed to both processes through their environment; Vite adds it server-side when proxying `/api/teacher-os`. It is never printed, logged, written to disk, or included in the browser bundle. **Do not forward these ports publicly** — forwarding is not authorization.

`npm run dev` starts the UI alone (no API); the app then reports the reader as not running.

## Live Notion status: closed until an owner admission exists

The API delegates every read to the governed seam `scripts/agent_os_notion_read_request/teacher_os.py`, which refuses dispatch without a scope-bound `NotionReadAdmission` (admitted, `secret_dispatch_authorized`, no single-unit binding, sources covering `canonical-unit` and `daily-generation-packet`) **before** any executor is built. The canonical admission path admits only GitHub issue-comment envelopes for the existing catalog request classes, none of which has that shape, so `canonical_teacher_os_admission()` returns nothing and the running app shows **"Live reads not admitted"** with no curriculum. `NOTION_TOKEN` alone is never permission.

**Owner decision needed to go live:** admit a Teacher OS discovery request class with exactly that shape through the canonical admission path (or explicitly decide otherwise). Once it exists, `canonical_teacher_os_admission()` obtains it from there; no other code path can supply an admission.

## API trust boundary (`server/teacher_os_api.py`)

Checked in this order, all before admission or executor work: loopback bind only → `GET` only, no body/query/percent-encoding → `Host` must be this listener (DNS-rebinding defence) → cross-site `Origin`/`Sec-Fetch-Site` refused, only the launcher's exact app origin accepted → `Authorization: Bearer <session secret>` (constant-time) → exact route and strict lowercase dashed UUID → read budget (30 reads/min) and one Notion read at a time. Responses are `no-store`, `nosniff`, no CORS, closed `reason_code` vocabulary, no provider text, and the access log records request lines only. The session secret proves a request came through this operator's local launcher — **it is not a multi-user teacher identity**; classroom deployment needs real identity and is out of scope.

The browser decodes every response at runtime (`src/apiContract.ts`): wrong shapes, foreign-unit lessons, unknown reasons and non-Notion links are refused or dropped, never trusted by type assertion.

## Tests

| Command | What it proves | Data |
|---|---|---|
| `npm run build` | `tsc --noEmit` + `vite build` | — |
| `npm run test:unit` | Runtime contract decoder (Node test runner on the TypeScript source). A guard fails the run on any failure/skip or fewer than 30 executed tests, because a bare `node --test` exits 0 when no file matches | synthetic |
| `npm test` | UI behaviour in desktop and phone Chromium with `page.route`-mocked API responses | synthetic, mocked |
| `npm run test:integration` | Real HTTP chain: browser → Vite proxy → authenticated API → governed reader → test-only stub executor; plus bypass attempts (no secret, cross-site, rebinding Host, bad ids) | synthetic, real processes |
| `pytest tests/teacher_os_web` (repo root) | API policy, admission fail-closed, real-process production server (refuses without secret; answers `admission-required`), synthetic fixture server | synthetic |

`npx playwright install chromium` provides the browser. None of these tests is live Notion evidence, and Chromium phone emulation is not iPhone Safari acceptance.

## Deliberately excluded

No Notion/Drive writes, no Docs/Slides generation, no backend store, no student data, no telemetry, no production deployment, no public bridge, no merge authority. Per-unit entries in `notion_read_catalog.json` remain for the issue-comment reader (#3690 follow-up).

## Reused architecture

#2225 boundaries · #3517 top-right View Assignment carousel · #3518 design checkpoint · #1892 contextual actions (not executed) · `01_Shared_Standards/global-engineering/typescript-react-development.md` and `react-web-development.md` · `05_Examples/ui-cross-platform-reference` keyboard/Playwright patterns.
