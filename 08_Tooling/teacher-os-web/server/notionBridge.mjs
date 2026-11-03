// Server-side seam from Teacher OS to the governed Notion reader (#2801/#3580/#2283).
// Runs inside the Vite dev/preview server process only. The browser receives sanitized
// JSON; NOTION_TOKEN is read by the Python reader from this process's environment and is
// never forwarded to a response. There is no cache, store or fallback content here.
import { execFile } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const UUID = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;
const ROUTE = /^\/api\/teacher-os\/units(?:\/([^/]+)\/lessons)?$/;
const KINDS = "agent-os-teacher-os-read-result";

export function runReader(args) {
  return new Promise(resolveRun => {
    execFile(
      process.env.TEACHER_OS_PYTHON ?? "python3",
      ["-I", "-m", "scripts.agent_os_notion_read_request.teacher_os", ...args],
      {
        cwd: REPO_ROOT, timeout: 45_000, maxBuffer: 1_048_576,
        env: { ...process.env, PYTHONPATH: ["src", "08_Tooling/workflow-scheduler/src", "."].join(":") },
      },
      (_error, stdout) => resolveRun(String(stdout ?? "")),
    );
  });
}

const failure = (status, reason_code) => ({ status, reason_code });

export function createBridge({ run = runReader, now = () => new Date() } = {}) {
  return async function bridge(req, res, next) {
    const match = ROUTE.exec((req.url ?? "").split("?")[0]);
    if (!match) return next();
    const send = (code, body) => {
      res.statusCode = code;
      res.setHeader("content-type", "application/json");
      res.setHeader("cache-control", "no-store");
      res.end(JSON.stringify(body));
    };
    if (req.method !== "GET") return send(405, failure("error", "invalid-request"));
    const unitId = match[1];
    if (unitId !== undefined && !UUID.test(unitId)) return send(400, failure("error", "invalid-request"));
    const args = ["--generated-at", now().toISOString(), ...(unitId ? ["lessons", "--unit-id", unitId] : ["units"])];
    let body;
    try {
      body = JSON.parse(await run(args));
    } catch {
      return send(503, failure("unavailable", "reader-unavailable"));
    }
    if (body?.result_kind !== KINDS || typeof body.status !== "string") return send(503, failure("unavailable", "reader-unavailable"));
    return send(body.status === "ok" || body.status === "empty" ? 200 : body.status === "unavailable" ? 503 : 502, body);
  };
}

export function teacherOsNotionPlugin() {
  const bridge = createBridge();
  return {
    name: "teacher-os-notion-bridge",
    configureServer(server) { server.middlewares.use(bridge); },
    configurePreviewServer(server) { server.middlewares.use(bridge); },
  };
}
