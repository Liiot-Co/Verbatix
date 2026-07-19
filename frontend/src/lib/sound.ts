// ponytail: mockup had no sound/gamification assets to port — these are
// synthesized on the fly (Web Audio oscillators), no audio files to ship.
let ctx: AudioContext | null = null;
let notificationUnlockCleanup: (() => void) | null = null;

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

/**
 * Los navegadores no permiten iniciar audio desde el callback de long polling.
 * Armamos el contexto con el primer gesto del usuario para que las alertas que
 * lleguen después sí puedan reproducirse desde segundo plano.
 */
export function prepareNotificationSound(): () => void {
  if (typeof window === "undefined" || notificationUnlockCleanup) {
    return notificationUnlockCleanup ?? (() => {});
  }

  const unlock = () => {
    const audioCtx = getContext();
    if (!audioCtx) return;
    // Un oscilador silencioso iniciado dentro del gesto hace el desbloqueo
    // consistente en Safari y navegadores móviles, igual que los sonidos de
    // las acciones de clasificación del producto.
    const oscillator = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    gain.gain.setValueAtTime(0, audioCtx.currentTime);
    oscillator.connect(gain);
    gain.connect(audioCtx.destination);
    oscillator.start();
    oscillator.stop(audioCtx.currentTime + 0.01);
    void audioCtx.resume().then(() => {
      if (audioCtx.state === "running") cleanup();
    }).catch(() => {
      // El siguiente gesto del usuario volverá a intentarlo.
    });
  };
  const cleanup = () => {
    window.removeEventListener("pointerdown", unlock, true);
    window.removeEventListener("keydown", unlock, true);
    window.removeEventListener("touchstart", unlock, true);
    notificationUnlockCleanup = null;
  };

  window.addEventListener("pointerdown", unlock, true);
  window.addEventListener("keydown", unlock, true);
  window.addEventListener("touchstart", unlock, true);
  notificationUnlockCleanup = cleanup;
  return cleanup;
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

/** Campanilla corta, cálida y compartida por todos los eventos in-app. */
export function playNotification(): void {
  const audioCtx = getContext();
  // No programar tonos en un contexto suspendido: al reanudarse ya habrían
  // terminado. `prepareNotificationSound` lo desbloquea con un gesto válido.
  if (!audioCtx || audioCtx.state !== "running") return;
  // Mismo patrón de dos osciladores que el aviso de procesamiento terminado:
  // es claramente audible sin depender de un archivo de audio externo.
  const lead = audioCtx.createOscillator();
  const harmony = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  const t = audioCtx.currentTime;

  lead.connect(gain);
  harmony.connect(gain);
  gain.connect(audioCtx.destination);
  lead.type = "sine";
  harmony.type = "triangle";
  lead.frequency.setValueAtTime(659.25, t);
  harmony.frequency.setValueAtTime(659.25, t);
  lead.frequency.setValueAtTime(783.99, t + 0.1);
  harmony.frequency.setValueAtTime(783.99, t + 0.1);
  lead.frequency.setValueAtTime(1046.5, t + 0.2);
  harmony.frequency.setValueAtTime(1046.5, t + 0.2);
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(0.1, t + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.001, t + 0.55);
  lead.start(t);
  harmony.start(t);
  lead.stop(t + 0.6);
  harmony.stop(t + 0.6);
}
