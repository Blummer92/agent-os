import { describe, expect, it } from "vitest";
import { loadTasks, projectTasks, validateTaskTitle } from "../shared/task";

describe("shared task domain", () => {
  it("validates without UI dependencies", () => {
    expect(validateTaskTitle("   ")).toBe("Enter a task title.");
    expect(validateTaskTitle("Grade examples")).toBeNull();
  });

  it("projects empty and success deterministically", () => {
    expect(projectTasks([])).toEqual({ kind: "empty" });
    expect(projectTasks([{ id: "1", title: "Grade examples", done: false }]).kind).toBe("success");
  });

  it("keeps repository failure explicit", async () => {
    const state = await loadTasks({ list: async () => { throw new Error("offline"); } });
    expect(state).toEqual({ kind: "error", message: "Tasks could not be loaded." });
  });
});
