import { defineConfig } from "vite";
import { teacherOsNotionPlugin } from "./server/notionBridge.mjs";

export default defineConfig({ plugins: [teacherOsNotionPlugin()] });
