# Global Engineering Standards

- Global engineering rules apply to every coding and automation agent.
- `reusable-capability-registry-standard.md` governs reusable capability discovery, evidence, ownership, lifecycle, and report-only validation.
- `agent-interaction-output-standard.md` is the canonical interaction-output contract: base report fields, conditional field groups, presentation profiles, visible ordering, and progress labeling. `final-report-standard.md` points to it.
- `typescript-react-development.md` governs the shared TypeScript + React foundation for UI work.
- `react-web-development.md` extends that shared foundation with browser-specific semantic HTML, CSS, accessibility, routing, rendering/framework selection, compatibility, performance, security, and browser acceptance guidance.
- `expo-react-native-development.md` extends the shared foundation with Expo + React Native mobile structure, navigation, accessibility, permissions/device APIs, storage, offline/error behavior, iOS/Android boundaries, testing, and upgrade guidance.

## Mobile Terminal And Cloud Shell UX

When Zachary is using a mobile terminal or Cloud Shell, provide the fastest safe route as one copy-and-paste command whenever practical.

- Give a brief natural-language explanation immediately before the command.
- Combine dependent shell operations with `&&` or an equivalently fail-closed construction.
- Detect common setup states where practical, including a missing repository directory, wrong working directory, missing local branch, remote branch fetch, inactive virtual environment, and optional tool authentication.
- Minimize command fragmentation and keep commands readable on narrow mobile displays.
- Do not present shell prompts, terminal output, heredoc continuation prompts such as `>`, incomplete heredocs, or Python source directly as Bash commands.
- Use multiple commands only when operator input is required between steps, separate authorization is required, a potentially destructive operation requires inspection first, or combining steps would materially reduce auditability.
- Preserve all authorization, repository verification, protected-branch, destructive-action, and stop-condition safeguards.

## Version
0.3.0
