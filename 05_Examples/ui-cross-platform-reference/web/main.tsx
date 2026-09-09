import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TaskPanel } from "./TaskPanel";

createRoot(document.getElementById("root")!).render(<StrictMode><TaskPanel state={{ kind: "empty" }} /></StrictMode>);
