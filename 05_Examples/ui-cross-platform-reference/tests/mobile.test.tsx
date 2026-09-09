import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { describe, expect, it, vi } from "vitest";
import { TaskScreen } from "../mobile/TaskScreen";

describe("mobile reference", () => {
  it("uses a mocked permission seam and exposes denial truthfully", async () => {
    const requestPhotoAccess = vi.fn().mockResolvedValue("denied");
    render(<TaskScreen state={{ kind: "empty" }} capability={{ requestPhotoAccess }} />);
    fireEvent.press(screen.getByRole("button", { name: "Check photo permission" }));
    await waitFor(() => expect(screen.getByText("Photo access denied.")).toBeTruthy());
    expect(requestPhotoAccess).toHaveBeenCalledOnce();
  });

  it("supports a bounded native screen transition", () => {
    render(<TaskScreen state={{ kind: "empty" }} capability={{ requestPhotoAccess: async () => "unavailable" }} />);
    fireEvent.press(screen.getByRole("button", { name: "Open task details" }));
    expect(screen.getByText("Task details")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Back to tasks" })).toBeTruthy();
  });
});
