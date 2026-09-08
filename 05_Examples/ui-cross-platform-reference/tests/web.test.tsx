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
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a task title.");
  });

  it("opens an accessible dialog and restores its explicit close path", () => {
    render(<TaskPanel state={{ kind: "empty" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Open help" }));
    expect(screen.getByRole("dialog", { name: "Task help" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
