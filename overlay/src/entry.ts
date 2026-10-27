// The page every overlay window loads (ADR-015 §3): the main window runs main.ts (the backend
// connection and the presenter); a pane window ("pane-…") runs pane.ts and only draws.

import { getCurrentWindow } from "@tauri-apps/api/window";

if (getCurrentWindow().label.startsWith("pane-")) void import("./pane");
else void import("./main");
