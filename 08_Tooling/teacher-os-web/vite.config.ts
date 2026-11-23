import { resolve } from "node:path";
import { defineConfig } from "vite";

// The /api/teacher-os proxy exists only when server/dev.mjs (or the integration
// test config) supplies the API port and a per-launch session secret through
// the environment. Vite adds the secret server-side on the proxied request; it
// is never part of the browser bundle (only VITE_* variables are exposed to
// client code, and this name deliberately has no VITE_ prefix). Without them,
// /api requests are not proxied and the app reports the reader as unavailable.
const apiPort = process.env.TEACHER_OS_API_PORT;
const secret = process.env.TEACHER_OS_API_SESSION_SECRET;

export default defineConfig({
  // Two entries: the live (fail-closed) Teacher OS and the clearly labelled
  // synthetic classroom fixture. They share no state and no data path.
  build: { rollupOptions: { input: { main: resolve(__dirname, "index.html"), fixture: resolve(__dirname, "fixture.html") } } },
  server: {
    host: "127.0.0.1",
    proxy: apiPort && secret
      ? { "/api/teacher-os": { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true, headers: { authorization: `Bearer ${secret}` } } }
      : undefined,
  },
});
