import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TeacherApp } from "./TeacherApp";
import "./style.css";
const root = document.getElementById("root");
if (!root) throw new Error("Missing root element");
createRoot(root).render(<StrictMode><TeacherApp /></StrictMode>);

// NC16 recovery: retain frontend applicability after removing the intentional type defect.
