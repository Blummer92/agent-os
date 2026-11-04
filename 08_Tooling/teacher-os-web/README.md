# Agent OS Teacher — first read-only React slice (#2801)

This is a **read-only** React/Vite Teacher OS slice (#2801). The repository holds no curriculum: `fixtures.ts` and every sample unit/lesson were removed. It does not write Notion or Drive, generate Slides/worksheets, or deploy.

## Behavior

- **Live Notion reads are currently fail-closed, by design.** The unauthenticated Vite bridge from the reviewed PR (`server/notionBridge.mjs`, which exposed credential-backed reads as unauthenticated GETs on a `0.0.0.0`-bound dev server) was removed, not hardened with a synthetic token: there is no approved authenticated/admitted boundary for browser-initiated Teacher OS reads in this repository, and Codespaces port forwarding does not grant authorization. The UI's `/api/teacher-os/*` fetches therefore report unavailable and show no lessons until a separately owner-admitted live path exists (see the reader README).
- The governed Python seam (`scripts/agent_os_notion_read_request/teacher_os.py`) still composes unit discovery and lesson reads from the verified sources, but only for a caller that already holds a `NotionReadAdmission` with `secret_dispatch_authorized is True`. Units are approved only when Canonical Status = Active **and** Human Review Required is a checkbox explicitly set to `false`; a unit's lessons are read from the verified `daily-generation-packet` source only if that live list contains it, so adding an approved unit in Notion needs no code or catalog edit once an admitted path exists.
- The UI shows loading, empty, unavailable, error and stale (>15 min) states with provenance. There is no fallback content: if no admitted live path is available the app says so and shows no lessons. The lesson carousel index is derived and clamped to the list actually on screen, so a refresh that shrinks the list can never render an impossible position such as "3 of 1".
- Student-facing Slides, Docs and worksheets remain approved Google Drive artifacts and are not shown here.
- Local draft chat is session-only and mutates nothing.

## Run in a qualified Codespace or development environment

```sh
cd 08_Tooling/teacher-os-web
npm install
npm run dev
npm run build
npx playwright install chromium
npm test
```

The development server binds loopback only (`127.0.0.1`, port 5173); do not forward it publicly — forwarding is not authorization, and there is no live bridge to forward to. Playwright uses port 4174 and checks desktop and narrow phone Chromium emulation. Tests are not proof of actual iPhone Safari acceptance. Playwright API payloads are mocked in-test and are not live Notion evidence.

## Reused architecture

- #2225 sibling product and source-of-truth boundaries.
- #3517 preferred top-right View Assignment carousel.
- #3518 provisional design checkpoint (not a persistence store).
- #1892 contextual teacher actions (future governed consumer, not executed here).
- `01_Shared_Standards/global-engineering/typescript-react-development.md` and `react-web-development.md`.
- `05_Examples/ui-cross-platform-reference` semantic web, keyboard and Playwright patterns.

## Deliberately excluded

No Notion/Drive writes, no Figma sync (#3519), no Docs/Slides generation, no production worksheet editing (#3259), no approval engine, no backend store, no student data, no production deployment, no live browser-initiated Notion bridge, and no merge authority. Per-unit entries in `notion_read_catalog.json` remain for the issue-comment reader and other consumers (#3690 follow-up).

## QA handoff

Run build and Playwright tests on the **exact PR head** through the existing governed executor. Independently inspect phone, tablet, Chromebook/desktop, keyboard, contrast, reduced motion, and fixture-versus-live labels. Treat unavailable CI/executor or browser dependencies as a blocker; a mocked UI test is not live Notion verification, and the current fail-closed UI must not be reported as live discovery.
