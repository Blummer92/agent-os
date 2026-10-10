# Agent OS Teacher — first read-only React slice (#2801)

This is a **fixture-backed, non-mutating** React/Vite demonstration of the teacher-preferred #3517 chat-first UX. It is not a production Teacher OS application, connected ChatGPT client, Notion curriculum reader, Drive artifact browser, Figma file, or approved worksheet generator.

## Behavior

- Main chat and hamburger navigation for session-only sample conversations.
- Top-right **View Assignment** dropdown with school year, course, unit and grade, plus unit/worksheet/slides carousel.
- Each card's **View** opens a full sample preview; **Edit** opens a dedicated local-only conversation for the selected material.
- Source-state switch exercises loading, empty, stale, unavailable and error illustrations without making network requests.
- All fixture content is labeled. No Notion, Google Drive, GitHub, Figma or AI mutation occurs.
- Existing #1892 `cta-v1.0.0` is the future contextual action vocabulary; this first slice **does not dispatch** those actions or claim production authority.

## Run in a qualified Codespace or development environment

```sh
cd 08_Tooling/teacher-os-web
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

No Figma synchronization or native comments (#3519), no real Notion enumeration (#2816/#3510), no real Docs/Slides generation, no production worksheet editing (#3259), no approval engine, no backend state store, no student data, no deployment or merge authority.

## QA handoff

Run build, unit and Playwright tests on the **exact PR head** through the existing governed executor. Independently inspect phone, tablet, Chromebook/desktop, keyboard, contrast, reduced motion, and fixture-versus-live labels. Treat unavailable CI/executor or browser dependencies as a blocker rather than claiming passing tests.
