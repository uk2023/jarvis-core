/**
 * JARVIS'S VOICE -- frontend side.
 *
 * One module, one voice. Before this, the chat bubble's speaker button
 * built its own utterance (rate 1.05, pitch 0.95), the call screen made
 * another, and the device TTS used a third set of numbers. Three voices
 * for one character, and any tuning meant hunting all three down.
 *
 * Everything that speaks now goes through speak() here, and the profile
 * comes from the server (/api/voice/profile), which reads the same
 * config/voice.json that the Python side uses. Tune it once, it changes
 * everywhere -- which is what "baad mein fine tune ho sake" requires.
 *
 * The amplitude callback is what drives the waveform on the voice
 * screen. It is derived from actual synthesis progress (boundary
 * events), not from a timer pretending to be audio -- a wave that
 * animates while nothing is speaking is the visual equivalent of fake
 * telemetry.
 */

export interface VoiceProfile {
  lang: string;
  pitch: number;
  rate: number;
  voice_hints: string[];
  pause_ms: number;
}

const FALLBACK_PROFILE: VoiceProfile = {
  // Matches VoiceProfile defaults in core/voice/jarvis_voice.py. Used
  // only if the server is unreachable, so the voice never silently
  // reverts to the browser's default chirp.
  lang: 'hi-IN',
  pitch: 0.75,
  rate: 0.94,
  voice_hints: ['hi-IN', 'en-IN', 'Google हिन्दी', 'Rishi', 'Veena'],
  pause_ms: 260,
};

let cachedProfile: VoiceProfile | null = null;
let cachedVoices: SpeechSynthesisVoice[] = [];
let unlocked = false;

/**
 * WHY THIS EXISTS (fixed 2026-09-13).
 *
 * Chrome and Safari, especially on mobile, silently refuse
 * speechSynthesis.speak() unless it happens in the same task as a real
 * user gesture. speak() used to `await` the profile fetch and the voice
 * list before speaking -- both awaits push the actual speak() call into
 * a later microtask, so the gesture context was gone and NOTHING was
 * ever heard. No error is raised; the utterance is just dropped, which
 * is why this looked like "TTS kaam hi nahi kar raha".
 *
 * Two fixes: warm the profile and voice list up front so speak() has
 * nothing to await, and speak one silent utterance on the first real
 * user interaction to unlock the engine for the rest of the session.
 */
export function unlockVoice(): void {
  if (unlocked || !('speechSynthesis' in window)) return;
  try {
    const primer = new SpeechSynthesisUtterance(' ');
    primer.volume = 0;
    window.speechSynthesis.speak(primer);
    unlocked = true;
  } catch {
    /* engine unavailable; speak() will no-op too */
  }
}

/** Call once at app start so speak() is synchronous when it matters. */
export function prewarmVoice(): void {
  loadProfile().catch(() => { /* defaults are already in place */ });
  if ('speechSynthesis' in window) {
    try {
      cachedVoices = window.speechSynthesis.getVoices();
      window.speechSynthesis.onvoiceschanged = () => {
        cachedVoices = window.speechSynthesis.getVoices();
      };
    } catch {
      /* nothing to warm */
    }
  }
}

type AmplitudeHandler = (level: number) => void;
type StateHandler = (speaking: boolean) => void;

const amplitudeListeners = new Set<AmplitudeHandler>();
const stateListeners = new Set<StateHandler>();

export function onAmplitude(fn: AmplitudeHandler): () => void {
  amplitudeListeners.add(fn);
  return () => amplitudeListeners.delete(fn);
}

export function onSpeakingChange(fn: StateHandler): () => void {
  stateListeners.add(fn);
  return () => stateListeners.delete(fn);
}

function emitAmplitude(level: number) {
  amplitudeListeners.forEach((fn) => {
    try { fn(level); } catch { /* a bad listener must not break speech */ }
  });
}

function emitSpeaking(speaking: boolean) {
  stateListeners.forEach((fn) => {
    try { fn(speaking); } catch { /* same */ }
  });
}

export async function loadProfile(): Promise<VoiceProfile> {
  if (cachedProfile) return cachedProfile;
  try {
    const res = await fetch('/api/voice/profile');
    if (res.ok) {
      const data = await res.json();
      const p = data?.profile;
      if (p) {
        cachedProfile = {
          lang: p.language ?? FALLBACK_PROFILE.lang,
          pitch: p.browser_pitch ?? FALLBACK_PROFILE.pitch,
          rate: p.browser_rate ?? FALLBACK_PROFILE.rate,
          voice_hints: p.browser_voice_hints ?? FALLBACK_PROFILE.voice_hints,
          pause_ms: p.pause_after_sentence_ms ?? FALLBACK_PROFILE.pause_ms,
        };
        return cachedProfile;
      }
    }
  } catch {
    // Server unreachable -- fall through to the matching defaults.
  }
  cachedProfile = FALLBACK_PROFILE;
  return cachedProfile;
}

/** Voices load asynchronously in most browsers; this waits for them. */
function getVoices(): Promise<SpeechSynthesisVoice[]> {
  return new Promise((resolve) => {
    if (cachedVoices.length) return resolve(cachedVoices);
    const existing = window.speechSynthesis.getVoices();
    if (existing.length) {
      cachedVoices = existing;
      return resolve(existing);
    }
    const timeout = setTimeout(() => resolve(window.speechSynthesis.getVoices()), 1200);
    window.speechSynthesis.onvoiceschanged = () => {
      clearTimeout(timeout);
      cachedVoices = window.speechSynthesis.getVoices();
      resolve(cachedVoices);
    };
  });
}

function pickVoice(voices: SpeechSynthesisVoice[], hints: string[]): SpeechSynthesisVoice | null {
  for (const hint of hints) {
    const match = voices.find(
      (v) => v.lang === hint || v.name.includes(hint) || v.lang.startsWith(hint.split('-')[0]),
    );
    if (match) return match;
  }
  return null;
}

/**
 * Strip what should not be read aloud. Mirrors prepare_for_speech() in
 * jarvis_voice.py -- a synthesiser reading "asterisk asterisk" or a URL
 * character by character makes the voice sound broken.
 */
function prepareText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' code block. ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/https?:\/\/\S+/g, ' link ')
    .replace(/[*_#>]+/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function chunkText(text: string, maxChars = 240): string[] {
  const prepared = prepareText(text);
  if (!prepared) return [];
  const sentences = prepared.split(/(?<=[.!?।])\s+/);
  const chunks: string[] = [];
  let buffer = '';
  for (const s of sentences) {
    if (!s.trim()) continue;
    if ((buffer + ' ' + s).trim().length <= maxChars) {
      buffer = (buffer + ' ' + s).trim();
    } else {
      if (buffer) chunks.push(buffer);
      buffer = s.trim();
    }
  }
  if (buffer) chunks.push(buffer);
  return chunks;
}

let currentUtterances: SpeechSynthesisUtterance[] = [];

/** Stop immediately. This is barge-in. */
export function stopSpeaking(): void {
  try { window.speechSynthesis.cancel(); } catch { /* nothing playing */ }
  currentUtterances = [];
  emitAmplitude(0);
  emitSpeaking(false);
}

export function isSpeaking(): boolean {
  try { return window.speechSynthesis.speaking; } catch { return false; }
}

/**
 * Speak text in JARVIS's voice. Chunked, so barge-in stops it quickly
 * instead of waiting for one long utterance to finish.
 */
/**
 * Speak on a CALL: lower pitch, slower pace, browser engine only.
 * Device TTS is flat -- acceptable for reading a chat bubble aloud,
 * wrong for a conversation, which is UK's distinction and a fair one.
 */
export async function speakForCall(text: string): Promise<void> {
  return speak(text, { pitchOffset: -0.08, rateOffset: -0.04 });
}

export async function speak(text: string, opts?: { pitchOffset?: number; rateOffset?: number }): Promise<void> {
  if (!('speechSynthesis' in window)) return;

  stopSpeaking();

  // NO awaits before the first speak() call -- see unlockVoice() above.
  // Use whatever is already cached; if the profile has not arrived yet
  // the fallback matches the Python defaults, so the voice is right
  // either way.
  const base = cachedProfile ?? FALLBACK_PROFILE;
  const profile = {
    ...base,
    pitch: Math.max(0.4, base.pitch + (opts?.pitchOffset ?? 0)),
    rate: Math.max(0.6, base.rate + (opts?.rateOffset ?? 0)),
  };
  const chunks = chunkText(text);
  if (!chunks.length) return;

  if (!cachedVoices.length) {
    try { cachedVoices = window.speechSynthesis.getVoices(); } catch { /* none yet */ }
  }
  const voice = pickVoice(cachedVoices, profile.voice_hints);

  // Chrome pauses the queue after long idle periods; resume() is a
  // no-op when it is not paused and costs nothing.
  try { window.speechSynthesis.resume(); } catch { /* ignore */ }

  emitSpeaking(true);

  return new Promise((resolve) => {
    let index = 0;

    const speakNext = () => {
      if (index >= chunks.length) {
        emitAmplitude(0);
        emitSpeaking(false);
        resolve();
        return;
      }

      const utterance = new SpeechSynthesisUtterance(chunks[index]);
      utterance.lang = profile.lang;
      utterance.pitch = profile.pitch;
      utterance.rate = profile.rate;
      if (voice) utterance.voice = voice;

      // Amplitude comes from real boundary events -- the synthesiser
      // fires one per word as it speaks. Not a timer pretending to be
      // audio.
      utterance.onboundary = () => {
        emitAmplitude(0.45 + Math.random() * 0.35);
      };

      utterance.onend = () => {
        emitAmplitude(0.1);
        index += 1;
        if (index < chunks.length) {
          setTimeout(speakNext, profile.pause_ms);
        } else {
          speakNext();
        }
      };

      utterance.onerror = () => {
        emitAmplitude(0);
        emitSpeaking(false);
        resolve();
      };

      currentUtterances.push(utterance);
      window.speechSynthesis.speak(utterance);
    };

    speakNext();
  });
}

/**
 * DEPRECATED -- do not use alongside speech recognition.
 *
 * This opens its own getUserMedia stream. SpeechRecognition also opens
 * the microphone, and on Android Chrome the second stream silently
 * kills the recogniser: no error, no onerror, results just stop. Every
 * "mic light is on but nothing transcribes" bug in this project traced
 * back to calling this next to recognition.
 *
 * Amplitude now comes from the recogniser's own events instead --
 * see voice/recognition.ts. Kept only for a future path that needs raw
 * audio WITHOUT recognition running.
 */
export async function listenWithLevel(
  onLevel: (level: number) => void,
): Promise<{ stream: MediaStream; stop: () => void } | null> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);

    const data = new Uint8Array(analyser.frequencyBinCount);
    let raf = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      onLevel(Math.min(1, Math.sqrt(sum / data.length) * 4));
      raf = requestAnimationFrame(tick);
    };
    tick();

    return {
      stream,
      stop: () => {
        cancelAnimationFrame(raf);
        stream.getTracks().forEach((t) => t.stop());
        ctx.close().catch(() => { /* already closed */ });
        onLevel(0);
      },
    };
  } catch {
    return null;
  }
}

/** Browser speech recognition, used when the server has no STT. */
export function recognizeOnce(
  onResult: (text: string, isFinal: boolean) => void,
  onError?: (msg: string) => void,
): (() => void) | null {
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!SR) {
    onError?.('Is browser mein speech recognition nahi hai.');
    return null;
  }
  try {
    const recognition = new SR();
    recognition.lang = 'en-IN';   // STT: Latin script. TTS lang stays hi-IN above.
    recognition.interimResults = true;
    recognition.continuous = false;

    recognition.onresult = (event: any) => {
      let interim = '';
      let final = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) final += event.results[i][0].transcript;
        else interim += event.results[i][0].transcript;
      }
      if (interim) onResult(interim, false);
      if (final) onResult(final, true);
    };
    recognition.onerror = (e: any) => onError?.(e?.error ?? 'Speech recognition error');
    recognition.start();
    return () => { try { recognition.stop(); } catch { /* already stopped */ } };
  } catch (e: any) {
    onError?.(e?.message ?? 'Recognition start fail hua');
    return null;
  }
}
