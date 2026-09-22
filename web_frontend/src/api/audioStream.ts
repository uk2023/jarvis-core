// Audio Streaming Client for FastAPI Server-Side STT (/ws/audio)
// Streams raw microphone audio chunks to server-side Whisper / Faster-Whisper pipeline
// Emits partial and final transcription events without client-side model dependencies.

import { api } from './client';

export interface AudioStreamCallbacks {
  onPartialText?: (partial: string) => void;
  onFinalText?: (final: string) => void;
  onError?: (error: string) => void;
  onStatusChange?: (status: 'idle' | 'connecting' | 'streaming' | 'processing' | 'error') => void;
  /** Fires when the recogniser genuinely starts hearing, not when it
   *  was merely asked to. Was called in the class body without being
   *  declared here. */
  onReady?: () => void;
}

export class AudioStreamClient {
  private ws: WebSocket | null = null;
  private mediaStream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private isRecording = false;
  // Handle to the browser recogniser, so stopStreaming() can actually
  // stop it. Without this the recogniser kept running after the user
  // pressed stop and the mic indicator stayed on.
  private recognition: any = null;
  private callbacks: AudioStreamCallbacks;

  constructor(callbacks: AudioStreamCallbacks = {}) {
    this.callbacks = callbacks;
  }

  setCallbacks(callbacks: AudioStreamCallbacks) {
    this.callbacks = { ...this.callbacks, ...callbacks };
  }

  async startStreaming(): Promise<boolean> {
    // WHY BROWSER-FIRST (fixed 2026-09-13).
    //
    // The previous order was: open /ws/audio, stream webm/opus chunks,
    // and only fall back to the browser if the socket errored. Once
    // /ws/audio actually existed, that became WORSE, not better: the
    // socket connected, so the fallback never triggered, and the server
    // only replies after the recording stops. The user saw the green
    // mic indicator, spoke, and NOTHING appeared in the box the whole
    // time -- exactly the symptom reported.
    //
    // Browser SpeechRecognition gives live interim results as you
    // speak, which is what an input box needs. So we ask the server
    // what it can actually do, and only stream audio to it when it has
    // a real STT engine. Otherwise we use the browser immediately.
    try {
      this.callbacks.onStatusChange?.('connecting');

      if (!navigator.mediaDevices?.getUserMedia) {
        this.callbacks.onError?.('Is browser mein microphone support nahi hai.');
        this.callbacks.onStatusChange?.('error');
        return false;
      }

      let serverHasStt = false;
      try {
        const res = await fetch('/api/voice/capabilities');
        if (res.ok) {
          const caps = await res.json();
          serverHasStt = Boolean(caps?.stt_available);
        }
      } catch {
        serverHasStt = false;
      }

      if (!serverHasStt) {
        // No server STT -- browser recognition, live interim text.
        // No getUserMedia call here: SpeechRecognition opens the mic
        // itself, and grabbing a second stream makes some Android
        // builds refuse the recogniser.
        this.startFallbackRecognition();
        return true;
      }

      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 16000,
        },
      });

      const rawBase = api.getBackendUrl() || (typeof window !== 'undefined' ? window.location.origin : '');
      const origin = rawBase || 'http://localhost:8000';
      let wsUrl = origin.replace(/^http/, 'ws');
      if (!wsUrl.includes('/ws/audio')) {
        wsUrl = `${wsUrl.replace(/\/+$/, '')}/ws/audio`;
      }

      try {
        this.ws = new WebSocket(wsUrl);
        this.ws.binaryType = 'arraybuffer';
      } catch {
        this.startFallbackRecognition();
        return true;
      }

      this.ws.onopen = () => {
        this.callbacks.onStatusChange?.('streaming');
        this.startMediaRecorder();
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'stt_partial' || data.type === 'partial') {
            this.callbacks.onPartialText?.(data.text || '');
          } else if (data.type === 'stt_final' || data.type === 'final') {
            this.callbacks.onFinalText?.(data.text || '');
            this.stopStreaming();
          } else if (data.type === 'stt_error' || data.type === 'error') {
            if (data.use_browser_fallback) {
              this.cleanupWebSocket();
              this.startFallbackRecognition();
            } else {
              this.callbacks.onError?.(data.message || 'STT processing error');
            }
          }
        } catch {
          if (typeof event.data === 'string') {
            this.callbacks.onPartialText?.(event.data);
          }
        }
      };

      this.ws.onerror = () => {
        this.cleanupWebSocket();
        this.startFallbackRecognition();
      };

      this.ws.onclose = () => {
        if (this.isRecording) {
          this.callbacks.onStatusChange?.('idle');
          this.isRecording = false;
        }
      };

      this.isRecording = true;
      return true;
    } catch (err: any) {
      // getUserMedia rejection lands here -- most often a denied
      // permission, which the user CAN act on, so say so plainly.
      const message = err?.name === 'NotAllowedError'
        ? 'Mic permission deny ho gayi. Browser settings mein allow karo.'
        : (err?.message || 'Mic shuru nahi ho paya');
      this.callbacks.onError?.(message);
      this.callbacks.onStatusChange?.('error');
      this.stopStreaming();
      return false;
    }
  }

  private startMediaRecorder() {
    if (!this.mediaStream) return;

    try {
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')
        ? 'audio/ogg;codecs=opus'
        : '';

      this.mediaRecorder = new MediaRecorder(this.mediaStream, mimeType ? { mimeType } : undefined);

      this.mediaRecorder.ondataavailable = async (e) => {
        if (e.data && e.data.size > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
          const arrayBuffer = await e.data.arrayBuffer();
          this.ws.send(arrayBuffer);
        }
      };

      // Stream chunks every 250ms for low latency
      this.mediaRecorder.start(250);

      // On stop, signal the server to flush and transcribe. Previously
      // the socket just closed and the buffered audio was discarded.
      this.mediaRecorder.onstop = () => {
        try {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'stop' }));
          }
        } catch {
          /* socket already gone */
        }
      };
    } catch (err) {
      console.warn('[AudioStream] MediaRecorder error, falling back:', err);
      this.startFallbackRecognition();
    }
  }

  // Fallback for browsers or offline previews without active FastAPI /ws/audio server
  private startFallbackRecognition() {
    // The fallback must claim the recording flag too. Without it the
    // component thinks it is recording while this object thinks it is
    // not, and stopStreaming() becomes a no-op -- the mic button then
    // appears stuck on.
    this.isRecording = true;
    this.callbacks.onStatusChange?.('streaming');
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      this.callbacks.onError?.('Local speech recognition not supported in browser.');
      this.callbacks.onStatusChange?.('idle');
      return;
    }

    try {
      const recognition = new SpeechRecognition();
      recognition.lang = 'hi-IN'; // Hinglish / Indian English
      recognition.interimResults = true;
      // continuous keeps the recogniser alive through natural pauses.
      // With continuous=false Android ended the session at the first
      // short gap, so a normal sentence was cut in half.
      recognition.continuous = true;
      this.recognition = recognition;

      // Fires when the engine is genuinely capturing, not when we asked
      // it to. UK was losing his first word because the UI said
      // "listening" the instant the button was pressed, while the
      // recogniser was still initialising.
      recognition.onstart = () => {
        this.callbacks.onReady?.();
      };

      recognition.onresult = (event: any) => {
        let interim = '';
        let final = '';
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            final += event.results[i][0].transcript;
          } else {
            interim += event.results[i][0].transcript;
          }
        }
        if (interim) {
          this.callbacks.onPartialText?.(interim);
        }
        if (final) {
          this.callbacks.onFinalText?.(final);
          this.stopStreaming();
        }
      };

      recognition.onerror = (e: any) => {
        console.warn('[AudioStream] Fallback speech error:', e);
        this.callbacks.onError?.('Speech recognition timed out');
        this.stopStreaming();
      };

      recognition.onend = () => {
        // Only tear down if the user actually stopped. Android ends the
        // recogniser on its own after a pause; restarting keeps the mic
        // usable instead of dying silently mid-sentence.
        if (this.isRecording) {
          try { recognition.start(); return; } catch { /* fall through */ }
        }
        this.stopStreaming();
      };

      recognition.start();
    } catch (e: any) {
      this.callbacks.onError?.(e.message || 'Speech recognition initialization failed');
      this.stopStreaming();
    }
  }

  stopStreaming() {
    this.isRecording = false;
    if (this.recognition) {
      try { this.recognition.stop(); } catch { /* already stopped */ }
      this.recognition = null;
    }
    this.callbacks.onStatusChange?.('idle');

    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      try {
        this.mediaRecorder.stop();
      } catch {}
    }
    this.mediaRecorder = null;

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }

    this.cleanupWebSocket();
  }

  private cleanupWebSocket() {
    if (this.ws) {
      if (this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: 'stream_end' }));
          this.ws.close();
        } catch {}
      }
      this.ws = null;
    }
  }

  getIsStreaming(): boolean {
    return this.isRecording;
  }
}
