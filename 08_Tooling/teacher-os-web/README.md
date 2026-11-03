# Agent OS Teacher — first read-only React slice (#2801)

This is a **read-only** React/Vite Teacher OS slice (#2801) whose units and lessons come from **verified Notion evidence** through the existing governed reader (#2283/#3580). The repository holds no curriculum: `fixtures.ts` and every sample unit/lesson were removed. It does not write Notion or Drive, generate Slides/worksheets, or deploy.

## Behavior

- The Vite dev/preview server exposes `GET /api/teacher-os/units` and `/api/teacher-os/units/<id>/lessons` (`server/notionBridge.mjs`). Each call runs `python -m scripts.agent_os_notion_read_request.teacher_os` with a validated argv; `NOTION_TOKEN` stays in the server process and never reaches the browser (no `VITE_` secret exists).
- Units are discovered live from the verified `canonical-unit` source (Canonical Status = Active, no Human Review Required). A unit's lessons are read from the verified `daily-generation-packet` source only if that live list contains it, so adding an approved unit in Notion needs no code or catalog edit.
- The UI shows loading, empty, unavailable, error and stale (>15 min) states with provenance. There is no fallback content: if Notion is not configured the app says so and shows no lessons.
- Student-facing Slides, Docs and worksheets remain approved Google Drive artifacts and are not shown here.
- Local draft chat is session-only and mutates nothing.

## Run in a qualified Codespace or development environment

```sh
cd 08_Tooling/teacher-os-web
export NOTION_TOKEN=...   # server-side only; without it the app reports Notion unavailable
npm install
npm run dev
npm run build
npm run test:unit
npx playwright install chromium
npm test
```

The development server is available on port 5173 (forward that port in Codespaces). Playwright uses port 4174 and checks desktop and narrow phone Chromium emulation. Tests are not proof of actual iPhone Safari acceptance.

## Reused architecture

- #2225 sibling product and source-of-truth boundaries.
- #3517 preferred top-right View Assignment carousel.
- #3518 provisional design checkpoint (not a persistence store).
- #1892 contextual teacher actions (future governed consumer, not executed here).
- `01_Shared_Standards/global-engineering/typescript-react-development.md` and `react-web-development.md`.
- `05_Examples/ui-cross-platform-reference` semantic web, keyboard and Playwright patterns.

## Deliberately excluded

No Notion/Drive writes, no Figma sync (#3519), no Docs/Slides generation, no production worksheet editing (#3259), no approval engine, no backend store, no student data, no production deployment (the bridge runs in the Vite server only) and no merge authority. Per-unit entries in `notion_read_catalog.json` remain for the issue-comment reader and other consumers (#3690 follow-up).

## QA handoff

Run build, unit and Playwright tests on the **exact PR head** through the existing governed executor. Independently inspect phone, tablet, Chromebook/desktop, keyboard, contrast, reduced motion, and fixture-versus-live labels. Treat unavailable CI/executor, browser dependencies or a missing `NOTION_TOKEN` as a blocker; a mocked UI test is not live Notion verification.
