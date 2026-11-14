// KOP arcade sound library — generated via Web Audio API (no assets)
// All sounds use square/sawtooth/triangle waves for chiptune arcade feel.

let CTX = null;

function ctx() {
  if (!CTX) {
    try {
      CTX = new (window.AudioContext || window.webkitAudioContext)();
    } catch (e) { return null; }
  }
  if (CTX && CTX.state === "suspended") {
    CTX.resume().catch(() => {});
  }
  return CTX;
}

// Resume audio context on first user gesture (browsers block autoplay)
if (typeof window !== "undefined") {
  const resumeOnce = () => {
    ctx();
    window.removeEventListener("click", resumeOnce);
    window.removeEventListener("touchstart", resumeOnce);
    window.removeEventListener("keydown", resumeOnce);
  };
  window.addEventListener("click", resumeOnce, { once: true });
  window.addEventListener("touchstart", resumeOnce, { once: true });
  window.addEventListener("keydown", resumeOnce, { once: true });
}

const MUTE_KEY = "kop_sound_muted";
const VOL_KEY = "kop_sound_volume";

export function isMuted() {
  return typeof localStorage !== "undefined" && localStorage.getItem(MUTE_KEY) === "1";
}

export function setMuted(v) {
  localStorage.setItem(MUTE_KEY, v ? "1" : "0");
  window.dispatchEvent(new CustomEvent("kop-sound-change", { detail: { muted: !!v } }));
}

export function getVolume() {
  const v = parseFloat(localStorage.getItem(VOL_KEY) || "0.7");
  return isNaN(v) ? 0.7 : Math.max(0, Math.min(1, v));
}

export function setVolume(v) {
  localStorage.setItem(VOL_KEY, String(v));
  window.dispatchEvent(new CustomEvent("kop-sound-change", { detail: { volume: v } }));
}

function play(seq, opts = {}) {
  if (isMuted()) return;
  const c = ctx();
  if (!c) return;
  try {
    const now = c.currentTime;
    const master = c.createGain();
    master.gain.value = (opts.volume ?? 0.18) * getVolume();
    master.connect(c.destination);
    seq.forEach(({ f, t, d, type = "square", peak = 1 }) => {
      const o = c.createOscillator();
      const g = c.createGain();
      o.type = type;
      o.frequency.setValueAtTime(f, now + t);
      g.gain.setValueAtTime(0.0001, now + t);
      g.gain.exponentialRampToValueAtTime(peak, now + t + 0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, now + t + d);
      o.connect(g).connect(master);
      o.start(now + t);
      o.stop(now + t + d + 0.05);
    });
  } catch (e) { /* noop */ }
}

function noise(duration = 0.15, opts = {}) {
  if (isMuted()) return;
  const c = ctx();
  if (!c) return;
  try {
    const bufSize = c.sampleRate * duration;
    const buffer = c.createBuffer(1, bufSize, c.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufSize; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / bufSize, 2);
    const src = c.createBufferSource();
    src.buffer = buffer;
    const g = c.createGain();
    g.gain.value = (opts.volume ?? 0.22) * getVolume();
    src.connect(g).connect(c.destination);
    src.start();
  } catch {}
}

export const sfx = {
  // Interface
  navigate: () => play([{ f: 520, t: 0, d: 0.04 }], { volume: 0.12 }),
  select:   () => play([{ f: 660, t: 0, d: 0.05 }, { f: 880, t: 0.04, d: 0.06 }], { volume: 0.14 }),
  confirm:  () => play([{ f: 660, t: 0, d: 0.08 }, { f: 990, t: 0.06, d: 0.10 }, { f: 1320, t: 0.14, d: 0.14 }], { volume: 0.18 }),
  back:     () => play([{ f: 480, t: 0, d: 0.05 }, { f: 320, t: 0.05, d: 0.09 }], { volume: 0.14 }),
  save:     () => play([{ f: 800, t: 0, d: 0.05 }, { f: 1200, t: 0.05, d: 0.06 }, { f: 1600, t: 0.11, d: 0.12 }], { volume: 0.16 }),
  success:  () => play([{ f: 660, t: 0, d: 0.08 }, { f: 880, t: 0.08, d: 0.08 }, { f: 1320, t: 0.16, d: 0.18 }], { volume: 0.18 }),
  error:    () => play([{ f: 200, t: 0, d: 0.12, type: "sawtooth" }, { f: 150, t: 0.1, d: 0.18, type: "sawtooth" }], { volume: 0.18 }),
  // Draw / team select
  reveal:   () => play([{ f: 440, t: 0, d: 0.06 }, { f: 660, t: 0.06, d: 0.06 }, { f: 880, t: 0.12, d: 0.06 }, { f: 1320, t: 0.18, d: 0.15 }], { volume: 0.18 }),
  teamReady:() => play([{ f: 523, t: 0, d: 0.08 }, { f: 659, t: 0.08, d: 0.08 }, { f: 784, t: 0.16, d: 0.08 }, { f: 1046, t: 0.24, d: 0.25 }], { volume: 0.2 }),
  // VS / match
  vs:       () => play([{ f: 220, t: 0, d: 0.1, type: "sawtooth" }, { f: 440, t: 0.1, d: 0.15, type: "sawtooth" }, { f: 110, t: 0.25, d: 0.3, type: "sawtooth" }], { volume: 0.24 }),
  countdown:() => play([{ f: 880, t: 0, d: 0.09 }], { volume: 0.22 }),
  fight:    () => { noise(0.15, { volume: 0.25 }); play([{ f: 220, t: 0, d: 0.1, type: "sawtooth" }, { f: 440, t: 0.1, d: 0.18 }, { f: 880, t: 0.28, d: 0.45 }], { volume: 0.28 }); },
  elim:     () => { noise(0.08, { volume: 0.2 }); play([{ f: 1200, t: 0, d: 0.04 }, { f: 380, t: 0.04, d: 0.17, type: "sawtooth" }], { volume: 0.24 }); },
  timeWarn: () => play([{ f: 1500, t: 0, d: 0.08 }, { f: 1500, t: 0.16, d: 0.08 }], { volume: 0.22 }),
  timeUp:   () => { noise(0.3, { volume: 0.22 }); play([{ f: 1600, t: 0, d: 0.2 }, { f: 1200, t: 0.2, d: 0.35, type: "sawtooth" }], { volume: 0.26 }); },
  // Outcomes
  winner:   () => play([
    { f: 523, t: 0, d: 0.12 }, { f: 659, t: 0.12, d: 0.12 },
    { f: 784, t: 0.24, d: 0.12 }, { f: 1046, t: 0.36, d: 0.45 },
  ], { volume: 0.24 }),
  draw:     () => play([{ f: 440, t: 0, d: 0.15 }, { f: 440, t: 0.2, d: 0.25, type: "triangle" }], { volume: 0.2 }),
  // Aviso disciplinar do telão: dois bipes graves, sem fanfarra.
  penalty:  () => play([
    { f: 196, t: 0, d: 0.16, type: "sawtooth" },
    { f: 147, t: 0.2, d: 0.34, type: "sawtooth" },
  ], { volume: 0.26 }),
  perfect:  () => play([
    { f: 523, t: 0, d: 0.07 }, { f: 659, t: 0.07, d: 0.07 },
    { f: 784, t: 0.14, d: 0.07 }, { f: 1046, t: 0.21, d: 0.07 },
    { f: 1319, t: 0.28, d: 0.07 }, { f: 1568, t: 0.35, d: 0.6 },
  ], { volume: 0.28 }),
  champion: () => play([
    { f: 523, t: 0, d: 0.18 }, { f: 659, t: 0.18, d: 0.18 },
    { f: 784, t: 0.36, d: 0.18 }, { f: 1046, t: 0.54, d: 0.2 },
    { f: 1319, t: 0.74, d: 0.7 },
  ], { volume: 0.3 }),
};

export function enableAudio() {
  ctx();
}
