// ponytail: mockup had no sound/gamification assets to port — these are
// synthesized on the fly (Web Audio oscillators), no audio files to ship.
let ctx: AudioContext | null = null;

function getContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!ctx) {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor();
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

function tone(freq: number, startAt: number, duration: number, gain: number, audioCtx: AudioContext) {
  const osc = audioCtx.createOscillator();
  const g = audioCtx.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  g.gain.setValueAtTime(0, startAt);
  g.gain.linearRampToValueAtTime(gain, startAt + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);
  osc.connect(g);
  g.connect(audioCtx.destination);
  osc.start(startAt);
  osc.stop(startAt + duration);
}

/** Short two-note upward chime — project/study/round created, import done. */
export function playSuccess(): void {
  const audioCtx = getContext();
  if (!audioCtx) return;
  const now = audioCtx.currentTime;
  tone(660, now, 0.12, 0.05, audioCtx);
  tone(880, now + 0.07, 0.16, 0.05, audioCtx);
}

/** Single soft tick — step advanced, selection made. */
export function playTick(): void {
  const audioCtx = getContext();
  if (!audioCtx) return;
  tone(520, audioCtx.currentTime, 0.06, 0.03, audioCtx);
}
