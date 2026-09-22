import React, { useState, useRef, useEffect } from 'react';
import { speak as jarvisSpeak, stopSpeaking as jarvisStopSpeaking } from '../voice/jarvisVoice';
import { startRecognition } from '../voice/recognition';
import type { RecognitionSession, RecognitionState } from '../voice/recognition';
import VoiceCallScreen from './VoiceCallScreen';
import MicWaveform from './MicWaveform';
import MessageContent from './MessageContent';
import ThinkingSteps from './ThinkingSteps';
import EffortMenu from './EffortMenu';
import type { ThinkingStep } from './ThinkingSteps';
import { streamThinking } from './ExtendedThinking';
import { Loader2 } from 'lucide-react';
import { api } from '../api/client';
import '../styles/jarvis-home.css';
import {
  Send,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Clock,
  Check,
  CheckCheck,
  Copy,
  Mic,
  MicOff,
  Brain,
  AudioLines,
  Plus,
  ArrowUp,
  Volume2,
  RefreshCw,
  History,
  Shield,
  HelpCircle,
  Radio,
  Paperclip,
} from 'lucide-react';
import { ChatMessage, AppTheme } from '../types';
import { AudioStreamClient } from '../api/audioStream';

interface UserChatViewProps {
  theme: AppTheme;
  activeSessionId: string;
  activeSessionTitle: string;
  messages: ChatMessage[];
  onSendMessage: (
    text: string,
    thinkingSteps?: { stage: string; content: string; duration_ms?: number; ok?: boolean }[],
    deferReplyUntil?: Promise<any>,
    groundingSummary?: { current: string },
    // Real upload_id(s) from api.uploadFile() picked for THIS message
    // (2026-09-21) -- see pendingAttachmentIds below and
    // client.ts's sendChat() doc comment for why these travel as
    // their own argument, never folded into `text`.
    attachmentUploadIds?: string[],
  ) => Promise<void>;
  // PERSISTS the live thinking-step panel onto the message it belongs to
  // (2026-09-17). onSendMessage is called BEFORE streaming even starts
  // (see handleSend's own comment on why -- so the user's bubble
  // appears immediately), so it can never carry the final steps. This
  // fires separately, once streaming AND the reply have both finished,
  // and attaches steps to the JARVIS message that was actually just
  // added -- without folding them into its text (UK was explicit that
  // steps must stay their own panel, not become part of the reply).
  onAttachThinkingSteps?: (
    steps: { stage: string; content: string; duration_ms?: number; ok?: boolean; chunk_id?: number }[],
    narratives?: { content: string; chunk_id: number }[],
  ) => void;
  onLoadEarlierMessages: () => void;
  hasOlderMessages: boolean;
  isThinking: boolean;
  thinkingSeconds: number;
  isAdmin?: boolean;
  onUnlockOperator?: () => void;
  /** Mirrors a completed voice-call exchange into the open thread. */
  onVoiceExchange?: (userText: string, jarvisText: string) => void;
}

export function UserChatView({
  theme,
  activeSessionId,
  activeSessionTitle,
  messages,
  onSendMessage,
  onAttachThinkingSteps,
  onLoadEarlierMessages,
  hasOlderMessages,
  isThinking,
  thinkingSeconds,
  isAdmin = false,
  onUnlockOperator,
  onVoiceExchange,
}: UserChatViewProps) {
  const [inputVal, setInputVal] = useState('');
  const [expandedThoughtIds, setExpandedThoughtIds] = useState<Record<string, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [streamStatus, setStreamStatus] = useState<'idle' | 'connecting' | 'streaming' | 'processing' | 'error'>('idle');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // EXTENDED THINKING toggle. Cycles off -> auto -> on and persists for
  // the session, so it means the same thing across reloads and matches
  // the CLI's /think setting. AUTO lets JARVIS decide per message.
  const [thinkingMode, setThinkingMode] = useState<'normal' | 'extended'>(() => {
    try {
      // Two modes only -- 'auto' removed (see EffortMenu.tsx). Anything
      // stored from the old three-mode version falls back to 'normal',
      // so an old sessionStorage value cannot resurrect auto.
      return sessionStorage.getItem('jarvis_thinking_mode') === 'extended' ? 'extended' : 'normal';
    } catch {
      return 'normal';
    }
  });

  useEffect(() => {
    try { sessionStorage.setItem('jarvis_thinking_mode', thinkingMode); } catch { /* private mode */ }
  }, [thinkingMode]);

  // EFFORT LEVEL -- same dial that drives thinking.py's stage count AND
  // task_loop.py's step cap/retries on the backend (effort_levels.py).
  // Persisted the same way as thinking mode, and cycling "off" thinking
  // does not reset it -- the level survives being toggled off and back
  // on, since UK is picking a working style, not a one-shot choice.
  const [effort, setEffort] = useState<'low' | 'medium' | 'high' | 'aggressive' | 'deep'>(() => {
    try {
      return (sessionStorage.getItem('jarvis_effort') as any) || 'medium';
    } catch {
      return 'medium';
    }
  });

  useEffect(() => {
    try { sessionStorage.setItem('jarvis_effort', effort); } catch { /* private mode */ }
  }, [effort]);

  // Live voice engine, opened from the talking icon in the header.
  const [voiceEngineOpen, setVoiceEngineOpen] = useState(false);
  const [micNote, setMicNote] = useState<string | null>(null);

  // Streamed reasoning stages for the ThinkingSteps panel. Populated
  // only by real server events -- never seeded with placeholders.
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([]);
  // Mirrors thinkingSteps state so its FINAL value is readable after
  // `await replyPromise` below without a stale closure -- state set
  // inside the streaming callbacks isn't visible to handleSend's own
  // scope by the time the stream finishes.
  const thinkingStepsRef = useRef<ThinkingStep[]>([]);
  const narrativesRef = useRef<{ content: string; chunk_id: number }[]>([]);
  const [thinkingStage, setThinkingStage] = useState<string | null>(null);
  const [thinkingReason, setThinkingReason] = useState<string | null>(null);
  const [thinkingError, setThinkingError] = useState<string | null>(null);
  // REAL CONCLUSION (2026-09-19). TaskLoop's "done" event carries a
  // conclusion string built from the actual step record (see
  // task_loop.py's _conclude() docstring: "a written conclusion could
  // otherwise claim success the steps do not support"). This was
  // received and then thrown away -- onDone only cleared the spinner
  // -- so ThinkingSteps always showed a generic hardcoded line instead
  // of what JARVIS actually found. Now captured and passed through.
  const [taskConclusion, setTaskConclusion] = useState<string | null>(null);
  const [taskComplete, setTaskComplete] = useState<boolean | null>(null);
  const [taskStepCounts, setTaskStepCounts] = useState<{ completed: number; total: number } | null>(null);
  // NARRATIVE + LIVE STEP (2026-09-19). task_loop.py now yields prose
  // commentary between step chunks (its stream() docstring explains
  // why) and tags every step with a chunk_id -- this is the frontend
  // half of that: narratives collected in arrival order, and
  // runningStepMeta tracking WHICH step is currently in flight (set on
  // stage_start, cleared the instant that step's own "stage"
  // completion event arrives) so ThinkingSteps can show a genuine
  // live-highlight, not a guess.
  const [narratives, setNarratives] = useState<{ content: string; chunk_id: number }[]>([]);
  const [runningStepMeta, setRunningStepMeta] = useState<
    { stage: string; index?: number; description?: string; chunk_id?: number } | null
  >(null);
  const cancelThinkingRef = useRef<(() => void) | null>(null);
  const [interimText, setInterimText] = useState('');
  // The recogniser needs a moment before it is genuinely listening.
  // Showing "listening" immediately meant the first word was regularly
  // lost -- UK started talking while it was still initialising.
  const [micState, setMicState] = useState<RecognitionState>('idle');
  const [micLevel, setMicLevel] = useState(0);
  const recognitionRef = useRef<RecognitionSession | null>(null);
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const chatFileInputRef = useRef<HTMLInputElement>(null);

  // THE REAL upload_id(s) FOR THE NEXT MESSAGE SENT (2026-09-21,
  // root-cause pass -- see backend/routes_frontend_v6.py's attachment-
  // grounding comment and upload_guard.py's read_uploaded_file()
  // docstring for the full bug this closes). Previously accept_upload()'s
  // result.upload_id was read only to decide ok/error and then thrown
  // away -- the chat text box got nothing but the filename typed into
  // a sentence ("Yeh file dekho: X"), so JARVIS had a sentence CLAIMING
  // a file existed with no real path or content behind it, which is
  // exactly why it started inventing plausible-sounding locations.
  // Kept as a small pending list (not folded into inputVal) so several
  // files can be attached to one message and so the ID travels to
  // handleSend as real structured data, never as text the model has to
  // re-parse back out of a sentence.
  const [pendingAttachments, setPendingAttachments] = useState<{ id: string; name: string }[]>([]);

  // Real upload, same guarded endpoint as the landing page.
  const handleChatFilePick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setUploadNote(`${file.name} bhej raha hun...`);
    try {
      const result = await api.uploadFile(file);
      setUploadNote(result?.ok ? (result.note ?? `${file.name} aa gayi.`) : (result?.error ?? 'Upload fail hua.'));
      if (result?.ok && result?.upload_id) {
        setPendingAttachments(prev => [...prev, { id: result.upload_id, name: file.name }]);
        // Still shown in the box so the person sees what they're
        // sending and can add their own instruction around it --
        // but this text is now a human-readable LABEL, not the only
        // thing carrying the reference: the real upload_id rides
        // alongside in pendingAttachments and reaches the backend as
        // its own field (see handleSend below), so nothing has to
        // guess a path back out of this sentence.
        setInputVal(v => (v ? `${v}\n(attached: ${file.name})` : `Attached: ${file.name}`));
      }
    } catch (err: any) {
      setUploadNote(err?.message ?? 'Upload fail hua.');
    }
  };

  const removePendingAttachment = (id: string) => {
    setPendingAttachments(prev => prev.filter(a => a.id !== id));
  };

  // When the voice engine is open, JARVIS's replies are spoken aloud as
  // they arrive. Only while it is open -- speaking every reply during a
  // normal typed conversation would be intrusive.
  const lastSpokenRef = useRef<string | null>(null);
  useEffect(() => {
    if (!voiceEngineOpen) return;
    const last = messages[messages.length - 1];
    if (!last || last.sender === 'user') return;
    const text = (last.text || '').trim();
    if (!text || text === lastSpokenRef.current) return;
    lastSpokenRef.current = text;
    const pushToScreen = (window as any).__jarvisSpeakReply;
    if (typeof pushToScreen === 'function') pushToScreen(text);
    else jarvisSpeak(text);
  }, [messages, voiceEngineOpen]);

  const isFirstLoadRef = useRef(true);
  const audioStreamerRef = useRef<AudioStreamClient | null>(null);

  const isDark = theme === 'dark';

  // Audio Streamer setup for /ws/audio FastAPI Server-side STT
  useEffect(() => {
    audioStreamerRef.current = new AudioStreamClient({
      onPartialText: (partial) => {
        // Live interim text, shown as it is recognised. Kept separate
        // from committed text so a partial never overwrites something
        // already finalised in the box.
        setInterimText(partial);
      },
      onFinalText: (final) => {
        // DO NOT SEND (fixed 2026-09-13). The mic used to call
        // handleSend() the moment a phrase went final, so a short pause
        // mid-sentence fired the message off before UK had finished
        // speaking. In CHAT the mic is dictation: the text lands in the
        // box, he reads it, edits it, and presses send himself.
        // Auto-send-on-pause is the CALL screen's behaviour, and it
        // lives there now.
        if (final.trim()) {
          setInputVal(prev => {
            const base = prev.trim();
            return base ? `${base} ${final.trim()}` : final.trim();
          });
        }
        textareaRef.current?.focus();
      },
      onStatusChange: (status) => {
        setStreamStatus(status);
        setIsRecording(status === 'streaming' || status === 'connecting');
      },
      onError: (err) => {
        console.warn('[UserChat] Audio stream error:', err);
        setIsRecording(false);
      },
    });

    return () => {
      audioStreamerRef.current?.stopStreaming();
    };
  }, []);

  // Scroll to bottom on initial load, session switch, and when new messages arrive (WhatsApp-style systematic loading)
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: isFirstLoadRef.current ? 'auto' : 'smooth',
      });
      isFirstLoadRef.current = false;
    }
  }, [messages.length, activeSessionId, isThinking]);

  // Adjust textarea height dynamically without jumping or clipping
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const scrollH = textareaRef.current.scrollHeight;
      textareaRef.current.style.height = `${Math.min(Math.max(scrollH, 28), 160)}px`;
    }
  }, [inputVal]);

  const toggleThought = (id: string) => {
    setExpandedThoughtIds(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleSend = async (customText?: string) => {
    const text = (customText !== undefined ? customText : inputVal).trim();
    if (!text || isThinking) return;

    // Reset the panel for this turn. An earlier turn's steps lingering
    // under a new question would read as reasoning about the new one.
    cancelThinkingRef.current?.();
    setThinkingSteps([]);
    thinkingStepsRef.current = [];
    setNarratives([]);
    narrativesRef.current = [];
    setThinkingStage(null);
    setThinkingReason(null);
    setThinkingError(null);
    setTaskConclusion(null);
    setTaskComplete(null);
    setTaskStepCounts(null);
    setNarratives([]);
    setRunningStepMeta(null);

    // CLEAR THE BOX AND SHOW THE MESSAGE FIRST (fixed 2026-09-16).
    // UK's report: with Extended Thinking on, his own chat bubble did
    // not appear until every step had finished -- so he typed, and the
    // screen sat there showing nothing of what he had just sent.
    //
    // The cause was mine: handleSend awaited the entire thinking
    // stream BEFORE calling onSendMessage, so the user message (which
    // onSendMessage adds) could not render until the work was over.
    // That is backwards. The order a person expects is the order
    // Claude uses: your message appears, then the thinking appears
    // under it, then the steps stream in, then the answer.
    //
    // So onSendMessage is now called immediately and NOT awaited
    // before the stream starts. The two run alongside each other,
    // which is also what keeps the steps visually SEPARATE from the
    // reply instead of collapsing into it.
    setInputVal('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    // THINKING-COMPLETE GATE (2026-09-17, UK's screenshots: some
    // thinking steps rendered a while AFTER the final answer, the
    // reverse of Claude's order). Built BEFORE starting either call,
    // resolved from streamThinking's own onDone/onAborted/onError
    // below, and passed to onSendMessage so its reply fetch (in
    // App.tsx) waits for the WHOLE thinking panel to finish before
    // asking for the answer -- while the user's own message bubble
    // (added synchronously, at the top of handleSendMessage) still
    // appears immediately, unaffected. Only built for extended mode;
    // off mode has no thinking stream to wait for, so the reply fires
    // exactly as before.
    let resolveThinkingDone: (() => void) | null = null;
    const thinkingDonePromise = thinkingMode === 'extended'
      ? new Promise<void>((resolve) => {
          resolveThinkingDone = resolve;
          // SAFETY TIMEOUT (2026-09-17): if the thinking stream never
          // reaches onDone/onAborted/onError at all -- a dropped
          // connection before the first event, say -- this promise
          // would otherwise hang forever and the reply would never
          // arrive, which is a far worse failure than a late-rendering
          // panel. 45s covers even a deep-effort run's full step
          // budget with margin; past that, proceed with the reply
          // regardless of what became of the thinking stream.
          setTimeout(() => resolve(), 45000);
        })
      : undefined;

    // GROUNDING SUMMARY -- a MUTABLE holder, not a plain string
    // (2026-09-18). onSendMessage is called right now, synchronously,
    // before any thinking step has arrived -- a plain string argument
    // would freeze at "" forever. This object is passed by reference:
    // onStage/onDone below fill in .current as real steps arrive, and
    // App.tsx reads groundingRef.current only AFTER it has awaited
    // deferReplyUntil (i.e. after thinking has actually finished), so
    // it sees the complete summary despite being handed the (still
    // empty) object earlier. See App.tsx's own comment on why this
    // grounding exists at all -- the reply pipeline previously had no
    // idea what Extended Thinking had just done and could describe a
    // completely different, independently-attempted outcome.
    const groundingRef: { current: string } = { current: '' };

    // Snapshot and clear NOW, synchronously with everything else above
    // (same reasoning as setInputVal('') just above: this message's
    // attachments belong to THIS send, not to whatever gets picked
    // next while the reply is still in flight).
    const attachmentIdsForThisMessage = pendingAttachments.map(a => a.id);
    setPendingAttachments([]);

    const replyPromise = onSendMessage(
      text, undefined, thinkingDonePromise, groundingRef,
      attachmentIdsForThisMessage.length ? attachmentIdsForThisMessage : undefined,
    );

    if (thinkingMode === 'extended') {
      // The server decides whether this turn actually warrants
      // deliberation (mode 'auto'), and reports back. If it decides no,
      // no stages arrive and the panel stays hidden -- which is correct:
      // there was nothing to show.
      cancelThinkingRef.current = streamThinking(
        { message: text, mode: thinkingMode, effort },
        {
          onDecision: (d) => {
            setThinkingReason(d.reason);
            if (d.think) setThinkingStage('understand');
          },
          onEffort: (e) => {
            // task_loop announces its cap up front -- surfaced as the
            // reason line so the panel header reads "8 steps allowed,
            // aggressive" rather than staying blank until the first
            // step arrives. The retry count is deliberately NOT shown
            // any more: retries were removed entirely on 2026-09-17
            // (verify_retries=0 at every effort level), so printing
            // "1 retry allowed" described behaviour that no longer
            // exists -- exactly the stale line UK spotted.
            setThinkingReason(`${e.label} effort -- ${e.max_steps} step tak.`);
          },
          onStageStart: (e) => {
            setThinkingStage(e.stage);
            setRunningStepMeta(e);
          },
          onNarrative: (n) => {
            setNarratives((prev) => [...prev, n]);
            narrativesRef.current = [...narrativesRef.current, n];
          },
          onStage: (stage: any) => {
            // The step this event describes just finished -- clear the
            // live-running marker unconditionally (whatever was running
            // is, by definition, not running any more the instant its
            // own completion event arrives).
            setRunningStepMeta(null);
            // NORMALIZE (2026-09-14). thinking.py's stages carry
            // `content`; task_loop.py's steps carry `output`, `kind`
            // instead of a plain stage name, and extra fields
            // (executed/held/index/description/chunk_id). Both now
            // render through the same ThinkingSteps panel, so whichever
            // shape arrives is flattened to the one the panel expects.
            const normalized: ThinkingStep = {
              stage: stage.stage || stage.kind || 'step',
              content: stage.content ?? stage.output ?? stage.description ?? '',
              duration_ms: stage.duration_ms,
              ok: stage.ok,
              chunk_id: typeof stage.chunk_id === 'number' ? stage.chunk_id : undefined,
            };
            setThinkingSteps((prev) => [...prev, normalized]);
            thinkingStepsRef.current = [...thinkingStepsRef.current, normalized];
            setThinkingStage(null);
          },
          onRetry: (reason) => {
            const retryStep: ThinkingStep = {
              stage: 'retry', content: `Verify fail hua, ek baar phir try kar raha hun: ${reason}`, ok: false,
            };
            setThinkingSteps((prev) => [...prev, retryStep]);
            thinkingStepsRef.current = [...thinkingStepsRef.current, retryStep];
          },
          // CAPABILITY DECISION (2026-09-19). Conversation Intelligence
          // Layer's classify_capability() announces which of
          // discussion/research/planning/full_build it chose for this
          // turn -- surfaced as the panel's "reason" line so it's
          // visible WHY a particular path was taken, the same way
          // onEffort's line already explains the step cap.
          onCapability: (c) => {
            const label = c.capability === 'full_build' ? 'building it'
              : c.capability === 'planning' ? 'planning only, no code yet'
              : c.capability === 'research' ? 'researching, no code yet'
              : 'just discussing';
            setThinkingReason(`Decided: ${label}`);
          },
          // RESEARCH/PLANNING CAPABILITY RESULT (2026-09-19). Previously
          // silently dropped -- streamThinking() had no case for this
          // event type at all, so a research-only or planning-only run
          // (UK's explicit ask: "extended thinking is not equal to
          // coding agent") completed on the server with a real finding
          // or plan, and the UI showed... nothing. Now formatted into a
          // readable step and a real conclusion line.
          onCapabilityComplete: (c) => {
            const isPlanning = c.capability === 'planning';
            const content = c.content || {};
            const understanding = content.understanding || content;
            const goal = understanding.goal ? `Goal: ${understanding.goal}` : '';
            const doneWhen = Array.isArray(understanding.done_when) && understanding.done_when.length
              ? `\n\nDone when:\n${understanding.done_when.map((d: string) => `- ${d}`).join('\n')}`
              : '';
            let text = `${goal}${doneWhen}`;
            if (isPlanning && Array.isArray(content.plan)) {
              text += `\n\nPlan:\n${content.plan
                .map((s: any, i: number) => `${i + 1}. [${s.kind}] ${s.description}`)
                .join('\n')}`;
            }
            const step: ThinkingStep = {
              stage: isPlanning ? 'planning' : 'research',
              content: text.trim() || 'No details returned.',
              ok: true,
            };
            setThinkingSteps((prev) => [...prev, step]);
            thinkingStepsRef.current = [...thinkingStepsRef.current, step];
            setTaskConclusion(
              isPlanning
                ? 'Plan taiyar hai -- code abhi nahi likha gaya, jaisa aapne kaha tha.'
                : 'Research poori hui -- koi code nahi likha gaya.'
            );
            setTaskComplete(true);
          },
          onAborted: (reason) => {
            setThinkingError(reason);
            setThinkingStage(null);
            setRunningStepMeta(null);
            // Terminal state -- same reasoning as onError above: the
            // reply must not wait forever on a thinking run that has
            // already stopped. Also grounds the reply in whatever DID
            // run before the stop (e.g. a budget-exhaustion abort still
            // leaves real steps behind) plus the abort reason itself,
            // so the reply can say "ran out of budget partway through"
            // truthfully instead of inventing an unrelated excuse.
            if (thinkingStepsRef.current.length > 0 || reason) {
              groundingRef.current = [
                ...thinkingStepsRef.current.map((s) => `[${s.stage}]${s.ok === false ? ' (fail)' : ''} ${s.content}`),
                `[stopped] ${reason}`,
              ].join('\n');
            }
            resolveThinkingDone?.();
          },
          onDone: (result) => {
            setThinkingStage(null);
            setRunningStepMeta(null);
            cancelThinkingRef.current = null;
            // REAL CONCLUSION (2026-09-19) -- see taskConclusion state
            // doc comment above. result.conclusion is task_loop.py's
            // _conclude() output, built strictly from the actual step
            // record; result.complete/total_steps/completed_steps are
            // the same real counts, not re-derived in the browser.
            if (result && typeof result === 'object') {
              if (typeof result.conclusion === 'string') setTaskConclusion(result.conclusion);
              if (typeof result.complete === 'boolean') setTaskComplete(result.complete);
              if (typeof result.total_steps === 'number') {
                setTaskStepCounts({ completed: result.completed_steps ?? 0, total: result.total_steps });
              }
            }
            // STEPS STAY ON SCREEN (2026-09-16). They are NOT cleared
            // and NOT folded into the reply. UK: "steps bhi dikhe jaise
            // Claude mein dikhte hain... steps baad mein summary mein
            // convert ho ja rahe hain, yeh nahi chahiye."
            //
            // Previously this resolved a promise that handleSend was
            // awaiting, the collected steps were attached to the reply
            // message, and the live panel was wiped -- which is exactly
            // the "steps turned into a summary" behaviour he is
            // describing. Now the panel is its own persistent block
            // above the answer, the way Claude shows its work.
            //
            // groundingRef IS filled in here, though (2026-09-18) --
            // that is a DIFFERENT thing from the panel display: a
            // plain-text digest handed to the reply pipeline so it
            // knows what actually happened, per App.tsx's comment.
            // Built from thinkingStepsRef.current, which already holds
            // every real step normalized by onStage above -- nothing
            // new is fabricated here, just joined into one string.
            if (thinkingStepsRef.current.length > 0) {
              groundingRef.current = thinkingStepsRef.current
                .map((s) => `[${s.stage}]${s.ok === false ? ' (fail)' : ''} ${s.content}`)
                .join('\n');
            }
            resolveThinkingDone?.();
          },
          onError: (err) => {
            setThinkingError(err);
            setThinkingStage(null);
            setRunningStepMeta(null);
            // Reply must still proceed even if thinking itself failed
            // -- an error in the deliberation panel is not a reason to
            // withhold the actual answer forever.
            resolveThinkingDone?.();
          },
        },
      );
    }

    // The reply is awaited here, AFTER the stream is already running
    // and after the user's own message is on screen.
    await replyPromise;

    // NOW attach the finished panel to the message it belongs to (see
    // onAttachThinkingSteps's own doc comment for why this can't
    // happen any earlier). Only fires when there is something real to
    // attach -- an ordinary turn with no coding/extended-thinking
    // activity leaves the message with no thinkingSteps at all, which
    // is the honest state, not an empty array pretending to be one.
    if (thinkingStepsRef.current.length > 0) {
      onAttachThinkingSteps?.(thinkingStepsRef.current, narrativesRef.current);
      // CLEAR THE LIVE PANEL NOW (2026-09-17, UK: "ek response ke
      // pehle create hota hai aur dusra response ke baad generate hona
      // shuru karta hai... refresh ke baad gayab ho jata hai").
      //
      // Two panels were rendering for one turn: this component's own
      // live `thinkingSteps` block (React state, above the input) AND
      // the copy just attached to the reply message. They showed the
      // same steps twice, and only the attached one survives a refresh
      // -- so after reload the "second" panel silently disappeared,
      // which is what made it look like a retry re-running.
      //
      // The 2026-09-16 note above is still honoured: the steps are NOT
      // being folded into a summary and NOT lost -- they now live on
      // the message itself (persisted via onAttachThinkingSteps ->
      // /api/history/attach_thinking_steps), rendered by the same
      // ThinkingSteps panel. Clearing the live copy removes the
      // DUPLICATE, not the steps.
      setThinkingSteps([]);
      thinkingStepsRef.current = [];
      setNarratives([]);
      narrativesRef.current = [];
      setThinkingReason(null);
      setThinkingError(null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFocus = () => {
    // When mobile virtual keyboard pops up, keep input visible
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 250);
  };

  // CHAT MIC = DICTATION. One recognition engine, one microphone.
  // No separate level meter: a second getUserMedia stream kills the
  // recogniser on Android (see voice/recognition.ts), which is exactly
  // why the input box stayed empty while the waveform animated happily
  // -- the meter was reading the stream that had killed transcription.
  const toggleMic = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
      // Fold trailing interim text in, so a phrase that never went
      // final is not silently lost on stop.
      setInterimText(cur => {
        if (cur.trim()) {
          setInputVal(prev => (prev.trim() ? `${prev.trim()} ${cur.trim()}` : cur.trim()));
        }
        return '';
      });
      setIsRecording(false);
      setMicState('idle');
      setMicLevel(0);
      return;
    }

    setMicNote(null);
    setIsRecording(true);

    const session = startRecognition({
      onState: (state) => {
        setMicState(state);
        if (state === 'idle' || state === 'error') setIsRecording(false);
      },
      onLevel: setMicLevel,
      onInterim: (text) => setInterimText(text),
      onFinal: (text) => {
        // REPLACE, do not append. recognition.ts now merges cumulative
        // results and hands over the WHOLE utterance; appending it on
        // top of the previous one is what produced
        // "हेलो हेलो जार्विस हेलो जार्विस तुम..." in the box.
        setInterimText('');
        setInputVal(text);
      },
      onError: (msg) => {
        setMicNote(msg);
        setIsRecording(false);
        setMicState('error');
      },
    }, { continuous: true });

    recognitionRef.current = session;
    if (!session) setIsRecording(false);
  };

  // Chat bubble playback now uses JARVIS's ONE voice (see
  // src/voice/jarvisVoice.ts). This used to build its own utterance at
  // rate 1.05 / pitch 0.95 while the call screen and Termux TTS each
  // used different numbers -- three voices for one character, and any
  // tuning meant editing all three.
  const speakText = (text: string) => {
    jarvisSpeak(text);
  };

  // WhatsApp-style Grouping by Date
  const groupedMessages: { dateLabel: string; msgs: ChatMessage[] }[] = [];
  messages.forEach(msg => {
    const label = msg.dateLabel || 'Today';
    const lastGroup = groupedMessages[groupedMessages.length - 1];
    if (lastGroup && lastGroup.dateLabel === label) {
      lastGroup.msgs.push(msg);
    } else {
      groupedMessages.push({ dateLabel: label, msgs: [msg] });
    }
  });

  return (
    <div className="h-full flex flex-col relative overflow-hidden">
      {voiceEngineOpen && (
        <VoiceCallScreen
          onClose={() => { jarvisStopSpeaking(); setVoiceEngineOpen(false); }}
          onExchange={(userText, jarvisText) => {
            // The call posts to /api/chat itself, so the turn is already
            // persisted server-side. This only mirrors it into the open
            // thread so closing the call does not look like the
            // conversation never happened.
            onVoiceExchange?.(userText, jarvisText);
          }}
        />
      )}
      {/* ------------------------------------------------------------- */}
      {/* CHAT SESSION SUB-HEADER (Current thread topic indicator)       */}
      {/* ------------------------------------------------------------- */}
      <div
        className={`h-11 px-3 sm:px-6 border-b flex items-center justify-between shrink-0 z-10 transition-colors ${
          isDark
            ? 'bg-[#080b14]/95 backdrop-blur-md border-white/10 text-slate-200'
            : 'bg-white/95 backdrop-blur-md border-slate-200 text-slate-800'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
          <span className="w-2 h-2 rounded-full bg-brand-500 shrink-0" />
          <h2 className="font-semibold text-xs tracking-tight truncate">
            {activeSessionTitle}
          </h2>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400 font-mono shrink-0">
          <span className="hidden md:inline">Groq openai/gpt-oss-120b & Native Pipeline</span>

          {/* Live voice engine. Opens the dedicated speaking surface --
              separate from the push-to-talk mic in the composer, which
              only dictates a single message. */}
          <button
            type="button"
            onClick={() => setVoiceEngineOpen(true)}
            title="JARVIS voice engine -- live baat karo"
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full border font-semibold text-xs whitespace-nowrap transition ${
              isDark
                ? 'bg-brand-500/15 text-brand-300 border-brand-500/30 hover:bg-brand-500/25'
                : 'bg-brand-500/10 text-brand-600 border-brand-500/25 hover:bg-brand-500/20'
            }`}
          >
            <AudioLines className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">VOICE</span>
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* SCROLLABLE CHAT CANVAS (WhatsApp-like Date Grouped Stream)     */}
      {/* ------------------------------------------------------------- */}
      <div
        ref={chatContainerRef}
        className={`flex-1 min-h-0 overflow-y-auto px-3 sm:px-6 py-4 space-y-4 ${
          isDark ? 'bg-[#060810]' : 'bg-[#F8FAFC]'
        }`}
      >
        {/* Load Earlier Messages Button (WhatsApp History Style) */}
        {hasOlderMessages && (
          <div className="flex justify-center pt-2 pb-1">
            <button
              onClick={onLoadEarlierMessages}
              className={`px-3 py-1.5 rounded-full border text-xs font-medium flex items-center gap-1.5 transition cursor-pointer shadow-xs ${
                isDark
                  ? 'bg-white/[0.04] hover:bg-white/[0.08] border-white/10 text-brand-300'
                  : 'bg-white hover:bg-slate-50 border-slate-200 text-slate-700'
              }`}
            >
              <History className="w-3.5 h-3.5 text-brand-500" />
              <span>Load earlier conversation messages</span>
            </button>
          </div>
        )}

        {/* Empty state when no messages */}
        {messages.length === 0 && (
          <div className="max-w-md mx-auto my-auto py-10 text-center space-y-5">
            <div className="relative w-20 h-20 mx-auto flex items-center justify-center">
              <div
                className="absolute inset-0 rounded-full border-2 border-brand-400/30 animate-spin"
                style={{ animationDuration: '8s' }}
              />
              <div
                className="absolute inset-2 rounded-full border border-dashed border-brand-300/40 animate-spin"
                style={{ animationDuration: '14s', animationDirection: 'reverse' }}
              />
              <div className="w-10 h-10 rounded-full bg-brand-500/20 border border-brand-400 flex items-center justify-center shadow-[0_0_20px_rgba(34,211,238,0.4)]">
                <div className="w-4 h-4 rounded-full bg-brand-400 shadow-[0_0_10px_#22d3ee] animate-pulse" />
              </div>
            </div>

            <div className="space-y-1.5">
              <h2 className="text-lg font-bold tracking-tight text-slate-800 dark:text-slate-100">
                Good day. How may I assist you?
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto leading-relaxed">
                Autonomous cognitive organism with vector memory, Hinglish phonetic tolerance, and local neural intelligence.
              </p>
            </div>

            {/* Interactive Starter Prompts (Rich guest questions about JARVIS) */}
            <div className="grid grid-cols-1 gap-2 text-left max-w-sm mx-auto pt-2">
              {[
                'Tell me about JARVIS and what you can do',
                'Explain your 10 internal cognitive organs',
                'What is your current cognitive status and memory health?',
                'Tell me about personal developer preferences & setup',
              ].map((starter, i) => (
                <button
                  key={i}
                  onClick={() => handleSend(starter)}
                  className={`p-2.5 rounded-xl border text-xs text-left transition cursor-pointer group ${
                    isDark
                      ? 'bg-white/[0.02] hover:bg-brand-500/10 border-white/10 hover:border-brand-400/40 text-slate-300 hover:text-brand-200'
                      : 'bg-white hover:bg-slate-50 border-slate-200 text-slate-700 shadow-xs'
                  }`}
                >
                  <span className="font-medium">{starter}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Date Grouped Stream */}
        {groupedMessages.map((group, groupIdx) => (
          <div key={`group-${groupIdx}`} className="space-y-3">
            {/* Clean Floating Date Divider Badge */}
            <div className="flex justify-center relative my-4 z-0">
              <span
                className={`px-3 py-0.5 rounded-full text-xs font-semibold tracking-wide uppercase shadow-xs ${
                  isDark
                    ? 'bg-[#121829] border border-white/10 text-slate-300'
                    : 'bg-slate-200 border border-slate-300 text-slate-700'
                }`}
              >
                {group.dateLabel}
              </span>
            </div>

            {/* Group's Messages */}
            {group.msgs.map(msg => {
              const isUser = msg.sender === 'user';
              // OPEN BY DEFAULT WHEN THERE ARE REAL STEPS (2026-09-16).
              // UK: "woh thinking step hide ho ja raha hai, woh nahi
              // chahiye -- thinking step bhi show ho, uske neeche
              // conclusion aaye." Collapsing by default hid exactly the
              // part he wanted to watch. An explicit collapse still
              // works; only the default changed.
              const isExpanded = msg.id in expandedThoughtIds
                ? !!expandedThoughtIds[msg.id]
                : !!(msg.thinkingProcess && msg.thinkingProcess.length);
              const isCopied = copiedId === msg.id;

              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${
                    isUser ? 'items-end' : 'items-start'
                  } max-w-2xl ${isUser ? 'ml-auto' : 'mr-auto'} space-y-1`}
                >
                  {/* PERSISTED, RICH thinking panel (2026-09-17) -- the
                      SAME ThinkingSteps component the live in-flight
                      bubble below uses, now also rendered for a
                      COMPLETED, persisted message (done=true, no
                      spinner). This is what survives a refresh: real
                      stage headings (bold, uppercase) and MessageContent
                      rendering for bold/code inside each step's content
                      -- not a fabricated re-creation, the actual
                      recorded steps from trace_log via /api/history. */}
                  {!isUser && msg.thinkingSteps && msg.thinkingSteps.length > 0 && (
                    <div className="w-full max-w-xl">
                      <ThinkingSteps
                        steps={msg.thinkingSteps.map((s) => ({ ...s, ok: s.ok ?? undefined }))}
                        narratives={msg.thinkingNarratives}
                        done={true}
                        isDark={isDark}
                      />
                    </div>
                  )}

                  {/* Legacy flat renderer -- kept ONLY for messages saved
                      before this fix (thinkingProcess: string[], no stage
                      labels). Never shown alongside the rich panel above. */}
                  {!isUser && !msg.thinkingSteps?.length && msg.thinkingProcess && (
                    <div className="w-full max-w-xl">
                      <button
                        onClick={() => toggleThought(msg.id)}
                        className={`px-2.5 py-1 rounded-xl border text-xs font-mono flex items-center gap-2 transition cursor-pointer ${
                          isDark
                            ? 'bg-white/[0.03] hover:bg-white/[0.06] border-white/10 text-brand-300'
                            : 'bg-slate-100 hover:bg-slate-200/80 border-slate-200 text-slate-700'
                        }`}
                      >
                        <Sparkles className="w-3.5 h-3.5 text-brand-500" />
                        <span>Thought for {msg.thinkingDurationSeconds || 1.1}s</span>
                        {isExpanded ? (
                          <ChevronUp className="w-3.5 h-3.5 ml-auto text-slate-400" />
                        ) : (
                          <ChevronDown className="w-3.5 h-3.5 ml-auto text-slate-400" />
                        )}
                      </button>

                      {isExpanded && (
                        <div
                          className={`mt-1 p-3 rounded-xl border text-xs font-mono space-y-1.5 leading-relaxed ${
                            isDark
                              ? 'bg-black/50 border-white/10 text-slate-300'
                              : 'bg-slate-100/90 border-slate-200 text-slate-700'
                          }`}
                        >
                          <div className="text-xs uppercase font-bold tracking-wider text-brand-500 mb-1">
                            Cognitive Deliberation Steps:
                          </div>
                          {msg.thinkingProcess.map((step, idx) => (
                            <div key={idx} className="flex items-start gap-2">
                              <span className="text-brand-500 font-bold">&bull;</span>
                              <span>{step}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* BUBBLE FOR USER ONLY (2026-09-15, UK's explicit
                      instruction: "user ka chat bubble rakho, JARVIS ka
                      chat bubble udaa do"). JARVIS's messages now flow
                      as plain content -- no background, no border, no
                      rounded-corner box -- which is also what makes
                      code blocks (via MessageContent below) render
                      properly instead of being clipped inside a
                      WhatsApp-style bubble sized for a sentence. */}
                  <div
                    className={
                      isUser
                        ? `relative px-4 py-2.5 text-sm leading-relaxed max-w-[92%] sm:max-w-xl break-words [overflow-wrap:anywhere] ${
                            isDark
                              ? 'bg-brand-600 text-white rounded-2xl rounded-br-xs shadow-md shadow-brand-950/40'
                              : 'bg-brand-700 text-white rounded-2xl rounded-br-xs shadow-xs font-normal'
                          }`
                        : `relative text-sm leading-relaxed max-w-full sm:max-w-2xl break-words [overflow-wrap:anywhere] ${
                            isDark ? 'text-slate-100' : 'text-slate-900'
                          }`
                    }
                  >
                    {isUser ? (
                      <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{msg.text}</p>
                    ) : (
                      <MessageContent text={msg.text} isDark={isDark} />
                    )}

                    {/* Bubble Bottom Metas: Timestamp & WhatsApp Double Checkmarks */}
                    <div
                      className={`mt-1 flex items-center justify-end gap-1.5 text-xs select-none ${
                        isUser
                          ? 'text-brand-100'
                          : 'text-slate-500 dark:text-slate-400 font-mono'
                      }`}
                    >
                      <span>{msg.timestamp}</span>

                      {/* WhatsApp Double Checkmark (for user sent messages) */}
                      {isUser && (
                        <CheckCheck className="w-3.5 h-3.5 text-brand-200 stroke-[2.5]" />
                      )}

                      {/* Jarvis Action buttons */}
                      {!isUser && (
                        <div className="flex items-center gap-1.5 ml-2">
                          <button
                            onClick={() => speakText(msg.text)}
                            className="hover:text-brand-500 transition cursor-pointer p-0.5"
                            title="Read aloud"
                          >
                            <Volume2 className="w-3 h-3" />
                          </button>
                          <button
                            onClick={() => handleCopy(msg.id, msg.text)}
                            className="hover:text-brand-500 transition cursor-pointer p-0.5"
                            title="Copy text"
                          >
                            {isCopied ? (
                              <Check className="w-3 h-3 text-emerald-500" />
                            ) : (
                              <Copy className="w-3 h-3" />
                            )}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ))}

        {/* Live Claude-like Thinking Bubble (During response generation) */}
        {/* THINKING STEPS. Shows real streamed stages when extended
            thinking ran, and a plain waiting line when it did not --
            rather than a spinner that implies reasoning either way. */}
        {(isThinking || thinkingSteps.length > 0) && (
          <div className="max-w-md mr-auto">
            {thinkingSteps.length > 0 || thinkingStage ? (
              <ThinkingSteps
                steps={thinkingSteps}
                currentStage={thinkingStage}
                done={!isThinking}
                reason={thinkingReason ?? undefined}
                error={thinkingError}
                conclusion={taskConclusion ?? undefined}
                complete={taskComplete ?? undefined}
                stepCounts={taskStepCounts ?? undefined}
                narratives={narratives}
                liveStep={runningStepMeta}
                isDark={isDark}
              />
            ) : (
              <div
                className={`p-3 rounded-2xl border flex items-center gap-2.5 text-xs font-mono ${
                  isDark
                    ? 'bg-brand-950/20 border-brand-500/30 text-brand-300'
                    : 'bg-brand-50 border-brand-200 text-brand-800'
                }`}
              >
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Jawab bana raha hun ({thinkingSeconds.toFixed(1)}s)...</span>
              </div>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ------------------------------------------------------------- */}
      {/* LOCKED WHATSAPP & AI STUDIO-INSPIRED BOTTOM INPUT BAR         */}
      {/* ------------------------------------------------------------- */}
      <footer
        className={`p-2.5 sm:p-3.5 border-t shrink-0 z-20 transition-colors ${
          isDark
            ? 'bg-[#080b14]/95 backdrop-blur-md border-white/10'
            : 'bg-white/95 backdrop-blur-md border-slate-200 shadow-[0_-2px_10px_rgba(0,0,0,0.03)]'
        }`}
      >
        <div className="max-w-3xl mx-auto space-y-2">
          {/* Listening indicator. The old version printed
              "Streaming raw audio to server Whisper STT (Termux/FastAPI)"
              -- internal plumbing detail that told UK nothing about
              whether it was actually hearing him. Replaced with a
              waveform driven by the real mic level, and an honest
              "ready" state so he knows when to start talking. */}
          {isRecording && (
            <MicWaveform state={micState} level={micLevel} onAbort={toggleMic} />
          )}

          {/* COMPOSER -- the landing page's composer, used verbatim.
              UK asked for the home screen input box to REPLACE the chat
              one, not sit beside a look-alike. So this is the same JSX
              structure and the same jarvis-home.css classes
              (.jarvis-composer / .jarvis-input-wrap / .jarvis-prompt-input
              / .jarvis-composer-footer). One stylesheet drives both, so
              they cannot drift apart again. */}
          <form
            onSubmit={e => { e.preventDefault(); handleSend(); }}
            className={`jarvis-composer jarvis-composer-inchat ${isDark ? 'jarvis-home-dark' : 'jarvis-home-light'}`}
          >
            {/* PENDING ATTACHMENT CHIPS (2026-09-21). Visible proof that a
                real upload_id is attached to the NEXT message -- not
                just a filename in the text box. Removable individually
                (a person may pick the wrong file) without having to
                edit the sentence in the box by hand. */}
            {pendingAttachments.length > 0 && (
              <div className="jarvis-pending-attachments" role="list">
                {pendingAttachments.map(a => (
                  <span key={a.id} className="jarvis-attachment-chip" role="listitem">
                    <Paperclip size={12} />
                    <span className="jarvis-attachment-chip-name">{a.name}</span>
                    <button
                      type="button"
                      onClick={() => removePendingAttachment(a.id)}
                      aria-label={`Remove ${a.name}`}
                      className="jarvis-attachment-chip-remove"
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="jarvis-input-wrap">
              <textarea
                ref={textareaRef}
                value={interimText ? (inputVal.trim() ? `${inputVal.trim()} ${interimText}` : interimText) : inputVal}
                onChange={e => { setInterimText(''); setInputVal(e.target.value); }}
                onKeyDown={handleKeyDown}
                onFocus={handleFocus}
                rows={2}
                maxLength={4000}
                placeholder="Message JARVIS..."
                aria-label="Message JARVIS"
                aria-multiline="true"
                disabled={isThinking}
                className="jarvis-prompt-input"
              />
            </div>

            <div className="jarvis-composer-footer">
              <div className="jarvis-composer-tools">
                <button
                  type="button"
                  onClick={() => chatFileInputRef.current?.click()}
                  aria-label="Upload file"
                  title="Upload file"
                  className="jarvis-composer-icon jarvis-upload-button"
                >
                  <Plus size={17} />
                </button>
                <input ref={chatFileInputRef} type="file" hidden onChange={handleChatFilePick} />
              </div>

              <div className="jarvis-command-actions">
                <EffortMenu
                  thinkingMode={thinkingMode}
                  onThinkingModeChange={setThinkingMode}
                  effort={effort}
                  onEffortChange={setEffort}
                  isDark={isDark}
                />

                <button
                  type="button"
                  onClick={toggleMic}
                  aria-label={isRecording ? 'Stop listening' : 'Voice input'}
                  className={`jarvis-composer-icon jarvis-mic-button ${isRecording ? 'is-listening' : ''}`}
                >
                  <Mic size={16} />
                </button>

                <button
                  type="submit"
                  disabled={!inputVal.trim() || isThinking}
                  aria-label="Send"
                  className="jarvis-send-button"
                >
                  <ArrowUp size={17} />
                </button>
              </div>
            </div>
          </form>

          {(micNote || uploadNote) && (
            <p className="jarvis-composer-note" role="status">{micNote ?? uploadNote}</p>
          )}
        </div>
      </footer>
    </div>
  );
}
