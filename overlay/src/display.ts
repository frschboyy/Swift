// A8, "How Swift shows things" (until the Swift window exists, in the tray menu). The owner's choices for how
// cards look and last, on this PC; each default follows Windows (motion: Windows' animation effects). Pure, with
// the storage passed in; a storage that fails keeps the defaults.

export type Display = {
  // How long an answer stays: its reading time times this, or "hold" (until the owner closes it).
  reading: "1" | "1.5" | "2" | "hold";
  text: "default" | "large";
  motion: "windows" | "less";
  // Whether answers are said aloud: "default" is config.yaml's speech.replies; the rest override it on this PC.
  speak: "default" | "always" | "auto" | "never";
  // When a request's watch opens by itself: only when asked ("show me", Watch), as soon as it writes into an app,
  // or once it has run LONG_RUN_MS.
  watch: "ask" | "writes" | "long";
};

export const DEFAULTS: Display = { reading: "1", text: "default", motion: "windows", speak: "default", watch: "ask" };
/** "Long requests": the watch opens once a request has worked this long. */
export const LONG_RUN_MS = 30_000;
export const CHOICES: { [K in keyof Display]: { value: Display[K]; label: string }[] } = {
  reading: [{ value: "1", label: "1×" }, { value: "1.5", label: "1.5×" }, { value: "2", label: "2×" }, { value: "hold", label: "Until I close" }],
  text: [{ value: "default", label: "Default" }, { value: "large", label: "Large" }],
  motion: [{ value: "windows", label: "Like Windows" }, { value: "less", label: "Less" }],
  speak: [{ value: "default", label: "Default" }, { value: "always", label: "Always" }, { value: "auto", label: "When I talk" }, { value: "never", label: "Never" }],
  watch: [{ value: "ask", label: "When I ask" }, { value: "writes", label: "When it writes" }, { value: "long", label: "Long requests" }],
};
const KEY = "swift.display";

export function load(store: Pick<Storage, "getItem">): Display {
  try {
    const raw = JSON.parse(store.getItem(KEY) ?? "{}") as Partial<Display>;
    const pick = <K extends keyof Display>(k: K): Display[K] =>
      CHOICES[k].some((c) => c.value === raw[k]) ? (raw[k] as Display[K]) : DEFAULTS[k];
    return { reading: pick("reading"), text: pick("text"), motion: pick("motion"), speak: pick("speak"), watch: pick("watch") };
  } catch {
    return { ...DEFAULTS };
  }
}

/** ``"reading:1.5"`` from the tray: the new choices, or the same ones for anything unknown. */
export function choose(d: Display, change: string): Display {
  const [k, v] = change.split(":") as [keyof Display, string];
  return k in CHOICES && CHOICES[k].some((c) => c.value === v) ? { ...d, [k]: v } : d;
}

export function save(d: Display, store: Pick<Storage, "setItem">): void {
  try {
    store.setItem(KEY, JSON.stringify(d));
  } catch {
    // kept until restart
  }
}

/** An answer's time on screen: its reading time scaled, or null (stays until closed). */
export const readingMs = (d: Display, ms: number): number | null => (d.reading === "hold" ? null : ms * Number(d.reading));

/** A8: whether a running request's watch opens by itself now (``writes``: it has written into an app; ``ranMs``: how
 * long it has worked). Never one the owner already opened or closed (``seen``). */
export function watchOpens(d: Display, writes: boolean, ranMs: number, seen: boolean): boolean {
  if (seen) return false;
  return (d.watch === "writes" && writes) || (d.watch === "long" && ranMs >= LONG_RUN_MS);
}
