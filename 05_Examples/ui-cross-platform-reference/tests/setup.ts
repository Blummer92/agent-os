/**
 * Fixture test setup.
 */
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { createRequire } from "node:module";

afterEach(() => {
  cleanup();
});

// The real `react-native` package entry uses Flow type syntax
// (`import typeof ...`) that Vitest's esbuild transform cannot parse, and
// the CJS `@testing-library/react-native` build `require`s it outside
// Vite's pipeline. Redirect Node's own resolution to the fixture's
// minimal stub so both the test file and the testing library get it.
const require = createRequire(import.meta.url);
const stubPath = require.resolve("./react-native-stub.js");
const Module = require("node:module") as typeof import("node:module");
const originalResolve = Module._resolveFilename;
(Module as unknown as { _resolveFilename: Function })._resolveFilename = function (
  request: string,
  ...args: unknown[]
) {
  if (request === "react-native") {
    return stubPath;
  }
  return originalResolve.call(this, request, ...args);
};
