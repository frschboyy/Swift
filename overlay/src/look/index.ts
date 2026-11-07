// The look spike's switch (ADR-019, brief-halo.md Step A). Dev builds only: main.ts and pane.ts reach
// this behind ``import.meta.env.DEV``, so a release bundle holds none of it.
//
// ``?look=halo`` in the harness, or ``VITE_SWIFT_LOOK=halo`` for ``npm run tauri dev``. The URL wins, so
// ``?look=default`` shows today's look in a Halo session. Step B deletes this switch.

export type Look = "halo";

/** The look to show, or null for today's. Anything unknown is today's. */
export function lookFrom(search: string, env: string | undefined): Look | null {
  const asked = new URLSearchParams(search).get("look") ?? env;
  return asked === "halo" ? "halo" : null;
}

/** Puts ``stage`` in the look, if one is asked for. A pane window has no card: it takes the tokens only. */
export async function applyLook(stage: HTMLElement): Promise<void> {
  if (lookFrom(location.search, import.meta.env.VITE_SWIFT_LOOK as string | undefined) !== "halo") return;
  await import("./halo.css");
  stage.dataset.look = "halo";
  const { dressCards } = await import("./dress");
  dressCards(stage);
}
