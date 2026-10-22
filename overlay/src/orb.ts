// The listening orb. Animates only while listening or transcribing, so idle costs nothing.

export class Orb {
  private target = 0;
  private level = 0;
  private frame = 0;
  private mode: "off" | "listening" | "settling" = "off";

  constructor(private readonly node: HTMLElement) {}

  setLevel(rms: number): void {
    // sqrt lifts quiet speech so the orb visibly reacts to normal voices.
    this.target = Math.sqrt(Math.max(0, Math.min(1, rms)));
  }

  listen(): void {
    this.mode = "listening";
    this.run();
  }

  settle(): void {
    this.mode = "settling";
    this.target = 0;
    this.run();
  }

  stop(): void {
    this.mode = "off";
    this.target = 0;
    this.level = 0;
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.apply(0, 0);
  }

  private run(): void {
    if (this.frame) return;
    const tick = (t: number) => {
      // Fast attack, slow release, like a VU meter.
      const k = this.target > this.level ? 0.45 : 0.12;
      this.level += (this.target - this.level) * k;
      const breathe = this.mode === "settling" ? 0.04 * Math.sin(t / 380) : 0;
      this.apply(this.level, breathe);
      if (this.mode === "off") {
        this.frame = 0;
        return;
      }
      this.frame = requestAnimationFrame(tick);
    };
    this.frame = requestAnimationFrame(tick);
  }

  private apply(level: number, breathe: number): void {
    this.node.style.setProperty("--level", level.toFixed(3));
    this.node.style.setProperty("--breathe", breathe.toFixed(3));
  }
}
