// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TaskPanel } from "../web/TaskPanel";

describe("web reference", () => {
  it("renders semantic empty and validation states", () => {
    render(<TaskPanel state={{ kind: "empty" }} />);
    expect(screen.getByRole("heading", { name: "Tasks" })).toBeTruthy();
    expect(screen.getByText("No tasks yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    expect(screen.getByRole("alert").textContent).toContain("Enter a task title.");
  });

  it("opens an accessible dialog and exposes a keyboard dismissal path", () => {
    render(<TaskPanel state={{ kind: "empty" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Open help" }));
    const dialog = screen.getByRole("dialog", { name: "Task help" });
    expect(dialog).toBeTruthy();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
