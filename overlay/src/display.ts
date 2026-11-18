// A8, "How Swift shows things" (until the Swift window exists, in the tray menu). The owner's choices for how
// cards look and last, on this PC; each default follows Windows (motion: Windows' animation effects). Pure, with
// the storage passed in; a storage that fails keeps the defaults.

export type Display = {
  // How long an answer stays: its reading time times this, or "hold" (until the owner closes it).
  reading: "1" | "1.5" | "2" | "hold";
  text: "default" | "large";
  motion: "windows" | "less";
};

export const DEFAULTS: Display = { reading: "1", text: "default", motion: "windows" };
export const CHOICES: { [K in keyof Display]: { value: Display[K]; label: string }[] } = {
  reading: [{ value: "1", label: "1×" }, { value: "1.5", label: "1.5×" }, { value: "2", label: "2×" }, { value: "hold", label: "Until I close" }],
  text: [{ value: "default", label: "Default" }, { value: "large", label: "Large" }],
  motion: [{ value: "windows", label: "Like Windows" }, { value: "less", label: "Less" }],
};
const KEY = "swift.display";

export function load(store: Pick<Storage, "getItem">): Display {
  try {
    const raw = JSON.parse(store.getItem(KEY) ?? "{}") as Partial<Display>;
    const pick = <K extends keyof Display>(k: K): Display[K] =>
      CHOICES[k].some((c) => c.value === raw[k]) ? (raw[k] as Display[K]) : DEFAULTS[k];
    return { reading: pick("reading"), text: pick("text"), motion: pick("motion") };
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
