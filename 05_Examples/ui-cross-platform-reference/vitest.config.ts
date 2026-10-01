import { defineConfig, type Plugin } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const stub = fileURLToPath(
  new URL("./tests/react-native-stub.js", import.meta.url),
);

/**
 * Redirect `react-native` imports to the fixture's minimal stub.
 * The real `react-native` entry uses Flow type syntax (`import typeof ...`)
 * that Vitest's esbuild transform cannot parse. This handles ESM imports
 * through Vite's pipeline; the setup file additionally redirects Node's
 * native `require` for the CJS testing-library build.
 */
function reactNativeStub(): Plugin {
  return {
    name: "fixture-react-native-stub",
    enforce: "pre",
    resolveId(source) {
      if (source === "react-native") {
        return stub;
      }
      return null;
    },
  };
}

export default defineConfig({
  plugins: [reactNativeStub(), react()],
  test: {
    // Globals required: `@testing-library/react-native`'s `extend-expect`
    // matcher setup references the global `expect`.
    globals: true,
    setupFiles: ["./tests/setup.ts"],
  },
});
