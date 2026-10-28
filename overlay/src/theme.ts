// Dark or light (ADR-017, the Capsule redesign): the overlay follows Windows' app theme
// (``AppsUseLightTheme``), live. Rust reads the registry and tells every window when it changes
// (``theme``); without Rust (the dev harness, an older shell) the webview's own colour scheme
// stands in. ``?theme=light`` in the URL pins it, for the harness's screenshots.
//
// The theme is ``data-theme`` on ``#stage``: styles.css keys every token off it.

export type Theme = "dark" | "light";

export type ThemeSources = {
  // From Rust: true when Windows apps use the light theme; null or undefined: not known.
  windows?: boolean | null;
  // prefers-color-scheme: light.
  media?: boolean;
  // A pinned theme (the harness's ?theme=); anything else is ignored.
  override?: string | null;
};

/** The theme to show: a pinned one, else Windows', else the webview's, else dark. */
export function themeFrom(s: ThemeSources): Theme {
  if (s.override === "light" || s.override === "dark") return s.override;
  if (typeof s.windows === "boolean") return s.windows ? "light" : "dark";
  return s.media ? "light" : "dark";
}

type Hooks = {
  invoke: <T>(cmd: string) => Promise<T>;
  listen: <T>(event: string, handler: (e: { payload: T }) => void) => Promise<unknown>;
};

/** Keep ``node``'s data-theme current. ``onChange`` hears each change (the main window redraws nothing; CSS does it). */
export function followTheme(node: HTMLElement, hooks: Hooks, onChange: (t: Theme) => void = () => {}): void {
  const media = window.matchMedia?.("(prefers-color-scheme: light)");
  const override = new URLSearchParams(location.search).get("theme");
  let windows: boolean | null = null;
  const apply = (): void => {
    const t = themeFrom({ windows, media: media?.matches ?? false, override });
    if (node.dataset.theme !== t) {
      node.dataset.theme = t;
      onChange(t);
    }
  };
  apply();
  media?.addEventListener?.("change", apply);
  hooks
    .invoke<boolean | null>("get_theme")
    .then((light) => {
      windows = typeof light === "boolean" ? light : null;
      apply();
    })
    .catch(() => {});  // an older shell, or the harness: the webview's scheme
  void hooks
    .listen<boolean | string>("theme", ({ payload }) => {
      // Rust sends AppsUseLightTheme; the harness may send "light" / "dark".
      windows = payload === "light" ? true : payload === "dark" ? false : typeof payload === "boolean" ? payload : windows;
      apply();
    })
    .catch(() => {});
}
