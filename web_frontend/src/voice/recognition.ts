/**
 * SPEECH RECOGNITION -- one engine, one microphone.
 *
 * THE BUG THIS EXISTS TO FIX
 * ==========================
 * SpeechRecognition opens the microphone itself. Calling getUserMedia
 * separately -- which is what an analyser-based level meter needs --
 * opens a SECOND stream on the same device, and Android Chrome responds
 * by killing the recogniser. It does not throw. It does not fire
 * onerror. It simply stops producing results.
 *
 * I had written exactly that warning in audioStream.ts, and then in the
 * next edit added `listenWithLevel()` alongside recognition in the chat
 * composer, the call screen and the landing page. That is why the mic
 * light came on, the waveform moved (the analyser stream was fine), and
 * no text ever arrived: the waveform was reading the stream that had
 * just killed the thing meant to transcribe.
 *
 * So the level meter is gone. Amplitude is now inferred from the
 * recogniser's OWN events -- onspeechstart, onresult, onspeechend --
 * with a decay between them. That is a real signal (it only moves when
 * the engine is actually hearing speech), it costs no second stream,
 * and it cannot break recognition.
 *
 * It is coarser than a true analyser: it shows THAT speech is being
 * heard, not its exact loudness. Given the alternative is a precise
 * waveform attached to a recogniser that never works, coarse and
 * correct wins.
 */

export type RecognitionState = 'idle' | 'starting' | 'ready' | 'hearing' | 'error';

export interface RecognitionHandlers {
  onState?: (state: RecognitionState) => void;
  onLevel?: (level: number) => void;
  onInterim?: (text: string) => void;
  onFinal?: (text: string) => void;
  onError?: (message: string) => void;
}

export interface RecognitionSession {
  stop: () => void;
  isRunning: () => boolean;
  /**
   * Discard whatever has been committed so far WITHOUT stopping the
   * recogniser. Used when a genuine barge-in is detected: the audio
   * captured up to that instant may be JARVIS's own speaker output
   * bleeding into the mic, and reporting it as part of what the user
   * said would prepend garbage onto their real question. Recognition
   * keeps running; only the accumulated text is cleared.
   */
  resetBuffer: () => void;
}

function getSpeechRecognition(): any {
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
}

export function recognitionSupported(): boolean {
  return Boolean(getSpeechRecognition());
}

/**
 * Start continuous recognition.
 *
 * @param autoSendFinals  true  -> each finished phrase goes to onFinal
 *                                 immediately (the CALL behaviour)
 *                        false -> finals still fire, but the caller is
 *                                 expected to accumulate them in an
 *                                 input box rather than send (CHAT)
 */
/**
 * Merge a newly-final phrase into what has already been committed.
 *
 * THE JUMBLE BUG (fixed 2026-09-14). UK said one sentence and the input
 * box filled with:
 *
 *     हेलो हेलो हेलो जार्विस हेलो जार्विस तुम हेलो जार्विस तुम कैसे हो
 *
 * Android's recogniser in continuous mode emits CUMULATIVE finals --
 * each one is the whole utterance so far, not just the new words. The
 * consumer appended every final, so the phrase was re-added with one
 * more word each time.
 *
 * So finals are MERGED, not appended: if the new text extends what we
 * already have, it replaces it; if it is genuinely new speech, it is
 * appended. Overlap is detected from the tail so a partial restart
 * ("...tum kaise" then "tum kaise ho") joins cleanly instead of
 * repeating.
 */
export function mergeTranscript(committed: string, incoming: string): string {
  const prev = (committed || '').trim();
  const next = (incoming || '').trim();
  if (!next) return prev;
  if (!prev) return next;

  // Cumulative result: the new one contains everything we had.
  if (next.toLowerCase().startsWith(prev.toLowerCase())) return next;
  // Duplicate or a subset of what we already have.
  if (prev.toLowerCase().endsWith(next.toLowerCase())) return prev;
  // The recogniser restarted and re-sent the utterance from the top:
  // the new text CONTAINS everything we had, just not as a prefix.
  // Without this the old copy survives and the first word doubles.
  if (next.toLowerCase().includes(prev.toLowerCase())) return next;

  // Partial overlap: find the longest suffix of prev that is a prefix
  // of next, and stitch there.
  const prevWords = prev.split(/\s+/);
  const nextWords = next.split(/\s+/);
  const maxOverlap = Math.min(prevWords.length, nextWords.length);
  for (let n = maxOverlap; n > 0; n--) {
    const tail = prevWords.slice(-n).join(' ').toLowerCase();
    const head = nextWords.slice(0, n).join(' ').toLowerCase();
    if (tail === head) {
      return [...prevWords, ...nextWords.slice(n)].join(' ');
    }
  }
  return `${prev} ${next}`;
}

export function startRecognition(
  handlers: RecognitionHandlers,
  options: {
    lang?: string;
    continuous?: boolean;
    /**
     * Wait this long after speech stops before treating the utterance
     * as complete. Set for CALLS so a whole sentence is sent, not the
     * first phrase -- UK's report was that only one word reached JARVIS
     * however much he said, because each final fired a send.
     * Omit for dictation, where every final should land in the box
     * immediately.
     */
    utteranceSilenceMs?: number;
  } = {},
): RecognitionSession | null {
  const SR = getSpeechRecognition();
  if (!SR) {
    handlers.onError?.('Is browser mein speech recognition nahi hai.');
    handlers.onState?.('error');
    return null;
  }

  let running = true;
  let level = 0;
  let decayTimer = 0;
  let recognition: any = null;
  // Everything finalised in the CURRENT utterance, merged not appended.
  let committed = '';
  let utteranceTimer = 0;
  const silenceMs = options.utteranceSilenceMs ?? 0;

  const flushUtterance = () => {
    const text = committed.trim();
    committed = '';
    if (utteranceTimer) { clearTimeout(utteranceTimer); utteranceTimer = 0; }
    if (text) handlers.onFinal?.(text);
  };

  const scheduleFlush = () => {
    if (utteranceTimer) clearTimeout(utteranceTimer);
    utteranceTimer = window.setTimeout(flushUtterance, silenceMs);
  };

  const setLevel = (value: number) => {
    level = Math.max(0, Math.min(1, value));
    handlers.onLevel?.(level);
  };

  // Between events the level decays, so the wave settles instead of
  // freezing at whatever the last event set.
  const startDecay = () => {
    if (decayTimer) return;
    decayTimer = window.setInterval(() => {
      if (!running) return;
      if (level > 0.05) setLevel(level * 0.82);
    }, 90);
  };

  const stopDecay = () => {
    if (decayTimer) {
      clearInterval(decayTimer);
      decayTimer = 0;
    }
  };

  try {
    recognition = new SR();
    // en-IN, NOT hi-IN. hi-IN returns Devanagari ("हेलो जार्विस"), which
    // UK does not want and which costs noticeably more tokens
    // downstream. en-IN handles Indian-accented speech and returns
    // Latin script, so "hello jarvis tum kaise ho" comes back readable
    // as Hinglish.
    recognition.lang = options.lang ?? 'en-IN';
    recognition.interimResults = true;
    recognition.continuous = options.continuous ?? true;

    handlers.onState?.('starting');

    // Only claim readiness when the engine says it started. Announcing
    // it at button-press cost UK his first word every time.
    recognition.onstart = () => {
      handlers.onState?.('ready');
      startDecay();
    };

    recognition.onspeechstart = () => {
      handlers.onState?.('hearing');
      setLevel(0.75);
    };

    recognition.onspeechend = () => {
      handlers.onState?.('ready');
      setLevel(0.1);
    };

    recognition.onresult = (event: any) => {
      let interim = '';
      let final = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) final += event.results[i][0].transcript;
        else interim += event.results[i][0].transcript;
      }

      // Every result means the engine is hearing something right now.
      setLevel(0.5 + Math.random() * 0.4);

      if (final.trim()) {
        committed = mergeTranscript(committed, final);
        if (silenceMs > 0) {
          // CALL: keep collecting until UK actually stops talking.
          scheduleFlush();
          handlers.onInterim?.(committed);
        } else {
          // DICTATION: the merged text IS the box contents, so it is
          // sent as the whole utterance rather than a fragment to
          // append. The consumer replaces, it does not concatenate.
          handlers.onFinal?.(committed);
        }
      } else if (interim) {
        // Show committed text plus the live tail, so the box reads as
        // one growing sentence instead of a repeating one.
        handlers.onInterim?.(mergeTranscript(committed, interim));
        if (silenceMs > 0) scheduleFlush();
      }
    };

    recognition.onerror = (e: any) => {
      const code = e?.error;
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        running = false;
        handlers.onError?.('Mic permission deny ho gayi. Browser settings mein allow karo.');
        handlers.onState?.('error');
      }
      // 'no-speech' and 'aborted' are normal during a long session --
      // onend restarts, so surfacing them would be noise.
    };

    recognition.onend = () => {
      // Android ends the recogniser on its own during pauses. Restart
      // while the caller still wants it, or dictation dies mid-sentence.
      if (running) {
        try {
          recognition.start();
          return;
        } catch {
          /* already restarting */
        }
      }
      stopDecay();
      setLevel(0);
      // Do not lose a half-finished utterance when the engine stops.
      if (silenceMs > 0) flushUtterance();
      handlers.onState?.('idle');
    };

    recognition.start();
  } catch (err: any) {
    running = false;
    stopDecay();
    handlers.onError?.(err?.message ?? 'Recognition start nahi ho paya.');
    handlers.onState?.('error');
    return null;
  }

  return {
    stop: () => {
      running = false;
      stopDecay();
      if (silenceMs > 0) flushUtterance();
      committed = '';
      if (utteranceTimer) { clearTimeout(utteranceTimer); utteranceTimer = 0; }
      setLevel(0);
      try {
        recognition.onend = null;
        recognition.stop();
      } catch {
        /* already stopped */
      }
      handlers.onState?.('idle');
    },
    isRunning: () => running,
    resetBuffer: () => {
      committed = '';
      if (utteranceTimer) { clearTimeout(utteranceTimer); utteranceTimer = 0; }
    },
  };
}
