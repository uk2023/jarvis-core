import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, Maximize2, Minimize2, Mic, Plus, Paperclip } from 'lucide-react';
import { AppTheme } from '../types';
import { api } from '../api/client';
import { startRecognition } from '../voice/recognition';
import type { RecognitionSession } from '../voice/recognition';
import '../styles/dashboard-tables.css';
import '../styles/jarvis-home.css';
import '../styles/jarvis-home-mobile.css';

interface HomeScreenProps {
  theme: AppTheme;
  onNavigateToView: (view: 'user_chat' | 'dashboard' | 'cli' | 'inspector') => void;
  // attachmentUploadIds (2026-09-21): real upload_id(s) picked on the
  // landing composer before the first message of a session is sent --
  // same fix as UserChatView.tsx's pendingAttachments, applied here so
  // the FIRST message of a chat doesn't lose an attachment the same
  // way every later message used to.
  onStartChatWithPrompt: (prompt: string, attachmentUploadIds?: string[]) => void;
  isAdmin: boolean;
  onOpenAuth: () => void;
}

export function HomeScreen({ theme, onStartChatWithPrompt }: HomeScreenProps) {
  const isDark = theme === 'dark';
  const [prompt, setPrompt] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [isKeyboardOpen, setIsKeyboardOpen] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [showExpand, setShowExpand] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const composerRef = useRef<HTMLFormElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Same real-id tracking as UserChatView.tsx's pendingAttachments
  // (2026-09-21) -- see that file's comment for the bug this closes.
  const [pendingAttachments, setPendingAttachments] = useState<{ id: string; name: string }[]>([]);

  useEffect(() => {
    const viewport = window.visualViewport;
    const isMobile = window.matchMedia('(max-width: 640px)').matches;
    if (!isMobile) return;

    let settleTimer = 0;
    const update = () => {
      const visualHeight = viewport?.height ?? window.innerHeight;
      const keyboardOffset = Math.max(0, window.innerHeight - visualHeight);
      // The visual viewport is the single source of truth. Do not latch the
      // compact state to focus: Android can keep an input focused after Back,
      // which otherwise leaves the hero permanently stuck in keyboard mode.
      const open = keyboardOffset > 80;

      setIsKeyboardOpen(open);
      document.documentElement.style.setProperty('--jarvis-keyboard-offset', `${open ? keyboardOffset : 0}px`);
      document.documentElement.style.setProperty('--jarvis-visual-height', `${visualHeight}px`);
      const composerHeight = composerRef.current?.getBoundingClientRect().height ?? 0;
      document.documentElement.style.setProperty('--jarvis-composer-height', `${Math.ceil(composerHeight)}px`);
      document.documentElement.style.setProperty('--jarvis-keyboard-hero-scale', open ? '0.40' : '1');
    };

    const settleAfterKeyboard = () => {
      window.clearTimeout(settleTimer);
      let attempts = 0;
      const settle = () => {
        update();
        attempts += 1;
        if (attempts < 12) settleTimer = window.setTimeout(settle, 80);
      };
      settle();
    };

    update();
    viewport?.addEventListener('resize', update);
    viewport?.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    window.addEventListener('orientationchange', settleAfterKeyboard);
    window.addEventListener('pageshow', update);
    document.addEventListener('visibilitychange', update);
    textareaRef.current?.addEventListener('blur', settleAfterKeyboard);

    return () => {
      window.clearTimeout(settleTimer);
      viewport?.removeEventListener('resize', update);
      viewport?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      window.removeEventListener('orientationchange', settleAfterKeyboard);
      window.removeEventListener('pageshow', update);
      document.removeEventListener('visibilitychange', update);
      textareaRef.current?.removeEventListener('blur', settleAfterKeyboard);
      document.documentElement.style.removeProperty('--jarvis-keyboard-offset');
      document.documentElement.style.removeProperty('--jarvis-visual-height');
      document.documentElement.style.removeProperty('--jarvis-composer-height');
      document.documentElement.style.removeProperty('--jarvis-keyboard-hero-scale');
    };
  }, []);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    if (isExpanded) {
      el.style.removeProperty('height');
      el.style.removeProperty('overflow-y');
      setShowExpand(true);
      return;
    }
    const lineHeight = 24;
    const minHeight = lineHeight * 2;
    const maxHeight = lineHeight * 6;
    el.style.setProperty('height', `${minHeight}px`, 'important');
    el.style.setProperty('overflow-y', 'hidden', 'important');
    const contentHeight = el.scrollHeight;
    const nextHeight = Math.min(Math.max(contentHeight, minHeight), maxHeight);
    el.style.setProperty('height', `${nextHeight}px`, 'important');
    el.style.setProperty('overflow-y', contentHeight > maxHeight ? 'auto' : 'hidden', 'important');
    setShowExpand(contentHeight > lineHeight * 3 + 1);
  }, [prompt, isExpanded]);

  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    const update = () => {
      const height = el.getBoundingClientRect().height;
      document.documentElement.style.setProperty('--jarvis-composer-height', `${Math.ceil(height)}px`);
      const viewport = window.visualViewport;
      if (viewport) {
        const keyboardOffset = Math.max(0, window.innerHeight - viewport.height);
        const open = keyboardOffset > 80;
        document.documentElement.style.setProperty('--jarvis-keyboard-hero-scale', open ? '0.40' : '1');
      }
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    window.addEventListener('resize', update);
    return () => { observer.disconnect(); window.removeEventListener('resize', update); };
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    const ids = pendingAttachments.map(a => a.id);
    onStartChatWithPrompt(prompt.trim(), ids.length ? ids : undefined);
    setPrompt('');
    setPendingAttachments([]);
    setIsExpanded(false);
    setShowExpand(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isKeyboardOpen && window.innerWidth > 640) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  // REAL microphone (fixed 2026-09-13).
  //
  // This button was theatre: it set a timer for 1800ms and then typed
  // the hardcoded string 'JARVIS, check system status' into the box. It
  // never requested microphone access and never transcribed anything,
  // which is why the mic "kaam nahi karta" on the landing page -- there
  // was nothing to work.
  const recogRef = useRef<RecognitionSession | null>(null);

  const toggleMic = () => {
    if (recogRef.current) {
      recogRef.current.stop();
      recogRef.current = null;
      setIsListening(false);
      return;
    }

    setMicError(null);
    // ONE microphone. An analyser stream alongside SpeechRecognition
    // kills the recogniser on Android -- see voice/recognition.ts.
    const session = startRecognition({
      onState: (state) => setIsListening(state === 'ready' || state === 'hearing'),
      onInterim: (text) => setPrompt(text),
      onFinal: (text) => {
        setPrompt(text);
        textareaRef.current?.focus();
      },
      onError: (msg) => {
        setMicError(msg);
        setIsListening(false);
      },
    }, { continuous: false });

    recogRef.current = session;
    if (!session) setIsListening(false);
  };

  // REAL upload (fixed 2026-09-13). This used to append the filename to
  // the prompt text and nothing else -- the file never left the browser.
  // It now goes through /api/upload, which extracts archives safely and
  // scans the contents (see core/skills/upload_guard.py).
  const handleFilePick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setUploadNote(`${file.name} bhej raha hun...`);
    try {
      const result = await api.uploadFile(file);
      if (!result?.ok) {
        setUploadNote(result?.error ?? 'Upload fail hua.');
        return;
      }
      setUploadNote(result.note ?? `${file.name} sandbox mein aa gayi.`);
      if (result?.upload_id) {
        setPendingAttachments(prev => [...prev, { id: result.upload_id, name: file.name }]);
      }
      setPrompt(current =>
        current ? `${current}\n(attached: ${file.name})` : `Attached: ${file.name}`);
    } catch (err: any) {
      setUploadNote(err?.message ?? 'Upload fail hua.');
    }
    textareaRef.current?.focus();
  };

  const removePendingAttachment = (id: string) => {
    setPendingAttachments(prev => prev.filter(a => a.id !== id));
  };

  const toggleExpand = () => {
    setIsExpanded(value => !value);
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <div className={`jarvis-home ${isKeyboardOpen ? 'keyboard-open' : ''} ${isExpanded ? 'composer-expanded' : ''} ${isDark ? 'jarvis-home-dark' : 'jarvis-home-light'}`}>
      <style>{`@media (max-width:640px){
        .jarvis-home:not(.keyboard-open) .jarvis-hero{transform:translate(-50%,-50%) scale(.972)!important;}
        .jarvis-home:not(.keyboard-open) .jarvis-identity h1{font-size:37px!important;}
        .jarvis-home:not(.keyboard-open) .jarvis-identity p{font-size:26px!important;}
      }`}</style>
      <div className="jarvis-space-field" aria-hidden="true"><span className="jarvis-star s1" /><span className="jarvis-star s2" /><span className="jarvis-star s3" /><span className="jarvis-star s4" /><span className="jarvis-nebula n1" /><span className="jarvis-nebula n2" /></div>
      <main className="jarvis-home-main"><div className="jarvis-home-content"><section className="jarvis-hero"><div className="jarvis-black-hole" aria-label="JARVIS cognitive core"><div className="jarvis-orbit orbit-a" /><div className="jarvis-orbit orbit-b" /><div className="jarvis-orbit orbit-c" /><div className="jarvis-accretion" /><div className="jarvis-core-glow" /><div className="jarvis-core-void"><span /><span /><span /></div></div><div className="jarvis-identity"><h1>नमस्ते</h1><p>Aaj, Kya HELP Karu?</p></div></section><section className="jarvis-command-zone"><form ref={composerRef} onSubmit={handleSubmit} className="jarvis-composer">{pendingAttachments.length > 0 && (<div className="jarvis-pending-attachments" role="list">{pendingAttachments.map(a => (<span key={a.id} className="jarvis-attachment-chip" role="listitem"><Paperclip size={12} /><span className="jarvis-attachment-chip-name">{a.name}</span><button type="button" onClick={() => removePendingAttachment(a.id)} aria-label={`Remove ${a.name}`} className="jarvis-attachment-chip-remove">&times;</button></span>))}</div>)}<div className="jarvis-input-wrap"><textarea ref={textareaRef} value={prompt} onChange={e => setPrompt(e.target.value)} onKeyDown={handleKeyDown} rows={2} maxLength={4000} placeholder="Message JARVIS..." aria-label="Message JARVIS" aria-multiline="true" className="jarvis-prompt-input" /></div><div className="jarvis-composer-footer"><div className="jarvis-composer-tools"><button type="button" onClick={() => fileInputRef.current?.click()} aria-label="Upload file" title="Upload file" className="jarvis-composer-icon jarvis-upload-button"><Plus size={17} /></button><input ref={fileInputRef} type="file" hidden onChange={handleFilePick} /></div><div className="jarvis-command-actions"><button type="button" onClick={toggleExpand} aria-label={isExpanded ? 'Close expanded message box' : 'Expand message box'} title={isExpanded ? 'Close expanded composer' : 'Expand composer'} className={`jarvis-composer-icon jarvis-expand-button ${isExpanded ? 'is-active' : ''} ${!showExpand && !isExpanded ? 'is-placeholder' : ''}`} tabIndex={showExpand || isExpanded ? 0 : -1} aria-hidden={!showExpand && !isExpanded}>{isExpanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button><button type="button" onClick={toggleMic} aria-label={isListening ? 'Stop listening' : 'Voice input'} className={`jarvis-composer-icon jarvis-mic-button ${isListening ? 'is-listening' : ''}`}><Mic size={16} /></button><button type="submit" disabled={!prompt.trim()} aria-label="Send" className="jarvis-send-button"><ArrowUp size={17} /></button></div></div></form>{(micError || uploadNote) && (<p className="jarvis-composer-note" role="status">{micError ?? uploadNote}</p>)}</section></div></main>
    </div>
  );
}
