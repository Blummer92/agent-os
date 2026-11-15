// Local launcher for Teacher OS (#2801): loopback Vite app + authenticated loopback API.
//
// A fresh random session secret is generated for each launch and handed to the
// two child processes through their environment only. It is never printed,
// written to disk, or exposed to the browser: Vite adds it server-side when it
// proxies /api/teacher-os to the API (see vite.config.ts). Both listeners bind
// 127.0.0.1. Do not forward these ports publicly - forwarding is not
// authorization, and the session secret is not a multi-user teacher identity.
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const appDir = path.resolve(here, "..");

function port(name, fallback) {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isInteger(value) || value < 1024 || value > 65535) {
    console.error(`teacher-os: ${name} must be an integer port 1024-65535`);
    process.exit(2);
  }
  return value;
}

const apiPort = port("TEACHER_OS_API_PORT", 8787);
const webPort = port("TEACHER_OS_WEB_PORT", 5173);
if (apiPort === webPort) { console.error("teacher-os: API and web ports must differ"); process.exit(2); }
const secret = randomBytes(32).toString("base64url");
const python = process.env.TEACHER_OS_PYTHON ?? "python3";

const children = [];
function start(command, args, extraEnv) {
  const child = spawn(command, args, { cwd: appDir, env: { ...process.env, ...extraEnv }, stdio: ["ignore", "inherit", "inherit"] });
  children.push(child);
  child.on("exit", code => { if (!stopping) { console.error(`teacher-os: ${path.basename(command)} exited (${code}); stopping`); stop(code ?? 1); } });
  return child;
}

let stopping = false;
function stop(code = 0) {
  stopping = true;
  for (const child of children) if (child.exitCode === null) child.kill("SIGTERM");
  setTimeout(() => process.exit(code), 300);
}
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));

start(python, ["-I", path.join(here, "teacher_os_api.py"), "--port", String(apiPort),
  "--allowed-origin", `http://127.0.0.1:${webPort}`, "--allowed-origin", `http://localhost:${webPort}`],
  { TEACHER_OS_API_SESSION_SECRET: secret });
start(process.execPath, [path.join(appDir, "node_modules", "vite", "bin", "vite.js"), "--host", "127.0.0.1", "--port", String(webPort), "--strictPort"],
  { TEACHER_OS_API_PORT: String(apiPort), TEACHER_OS_API_SESSION_SECRET: secret });
console.error(`teacher-os: open http://127.0.0.1:${webPort}/ (loopback only; API on 127.0.0.1:${apiPort})`);
