import { createRoot } from "react-dom/client";
import App from "./App";
import { installCursors } from "./ui/cursors";
import "./index.css";

installCursors();
createRoot(document.getElementById("app")).render(<App />);
