// Scan feedback: a short WebAudio beep and a buzz where supported.

const SOUND_KEY = 'ga.scanSound';

export function soundEnabled(): boolean {
  try {
    return localStorage.getItem(SOUND_KEY) !== 'off';
  } catch {
    return true;
  }
}

export function setSoundEnabled(on: boolean): void {
  try {
    localStorage.setItem(SOUND_KEY, on ? 'on' : 'off');
  } catch {
    /* private mode: setting just won't stick */
  }
}

let ctx: AudioContext | null = null;

/** Call from a user gesture once so iOS lets us play later. */
export function unlockAudio(): void {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') void ctx.resume();
  } catch {
    ctx = null;
  }
}

export function beep(kind: 'ok' | 'new' | 'repeat' | 'error' = 'ok'): void {
  if (!soundEnabled()) return;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') void ctx.resume();
    const tones: Record<typeof kind, number[]> = {
      ok: [1760],
      new: [1320, 1760],
      repeat: [1760, 1760],
      error: [440],
    };
    let t = ctx.currentTime;
    for (const freq of tones[kind]) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.18, t + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.09);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.1);
      t += 0.11;
    }
  } catch {
    /* audio unavailable */
  }
}

export function buzz(pattern: number | number[] = 40): void {
  if ('vibrate' in navigator) {
    try {
      navigator.vibrate(pattern);
    } catch {
      /* ignored */
    }
  }
}
