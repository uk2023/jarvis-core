import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import { ArrowUp, Maximize2, Minimize2, Mic, MicOff, Volume2, ChevronDown, ChevronUp, Cpu, Database, GitFork, CheckCircle2, Clock, SpellCheck, Bot, User, Zap, RotateCcw, Plus } from 'lucide-react';
import { ChatMessage, OrganismTelemetry, AppTheme } from '../types';
import { OrganismCore } from './OrganismCore';
import '../styles/jarvis-home.css';
import '../styles/jarvis-home-mobile.css';

interface NeuralChatProps { messages: ChatMessage[]; isThinking: boolean; onSendMessage: (text: string) => void; onOpenCLI: () => void; telemetry: OrganismTelemetry; onQuickPrompt: (prompt: string) => void; onClearChat?: () => void; theme?: AppTheme; }

export const NeuralChat: React.FC<NeuralChatProps> = ({ messages, isThinking, onSendMessage, onOpenCLI, telemetry, onQuickPrompt, onClearChat, theme = 'dark' }) => {
  const [inputText, setInputText] = useState('');
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);
  const [isListening, setIsListening] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [showExpand, setShowExpand] = useState(false);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const textareaTouchingRef = useRef(false);
  const isDark = theme === 'dark';

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => messagesEndRef.current?.scrollIntoView({ behavior, block: 'end' }), []);
  useEffect(() => { if (messages.length) scrollToBottom('auto'); }, []);
  useEffect(() => { if (messages.length) scrollToBottom('smooth'); }, [messages.length, scrollToBottom]);
  useEffect(() => { if (isThinking) scrollToBottom('smooth'); }, [isThinking, scrollToBottom]);

  // Keep the composer anchored to the layout viewport. On Android, calculating
  // a manual visualViewport keyboard offset double-counts the IME when the
  // browser already resizes the layout viewport, producing the large upward jump.
  useEffect(() => {
    const onStart = () => { textareaTouchingRef.current = true; };
    const onEnd = () => { textareaTouchingRef.current = false; };
    const el = textareaRef.current;
    if (!el) return;
    el.addEventListener('touchstart', onStart, { passive: true });
    el.addEventListener('touchend', onEnd, { passive: true });
    el.addEventListener('touchcancel', onEnd, { passive: true });
    return () => {
      el.removeEventListener('touchstart', onStart);
      el.removeEventListener('touchend', onEnd);
      el.removeEventListener('touchcancel', onEnd);
    };
  }, [isExpanded]);

  useEffect(() => {
    const html = document.documentElement;
    const body = document.body;
    const root = document.getElementById('root');
    const previous = { htmlOverflow: html.style.overflow, bodyOverflow: body.style.overflow, bodyOverscroll: body.style.overscrollBehavior, rootOverflow: root?.style.overflow || '' };
    html.style.overflow = 'hidden'; body.style.overflow = 'hidden'; body.style.overscrollBehavior = 'none';
    if (root) root.style.overflow = 'hidden';
    return () => { html.style.overflow = previous.htmlOverflow; body.style.overflow = previous.bodyOverflow; body.style.overscrollBehavior = previous.bodyOverscroll; if (root) root.style.overflow = previous.rootOverflow; };
  }, []);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el || isExpanded) return;
    const line = 24, min = line * 2, max = line * 5;
    el.style.setProperty('height', `${min}px`, 'important');
    el.style.setProperty('overflow-y', 'hidden', 'important');
    const content = el.scrollHeight;
    el.style.setProperty('height', `${Math.min(Math.max(content, min), max)}px`, 'important');
    el.style.setProperty('overflow-y', content > max ? 'auto' : 'hidden', 'important');
    setShowExpand(content > line * 3 + 1);
  }, [inputText, isExpanded]);

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = inputText.trim();
    if (!text || isThinking) return;
    onSendMessage(text); setInputText(''); setIsExpanded(false); setShowExpand(false);
    requestAnimationFrame(() => { if (textareaRef.current) textareaRef.current.style.setProperty('height', '48px', 'important'); });
  };
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && window.innerWidth > 640) { e.preventDefault(); handleSubmit(e); }
  };
  const autoResize = (e: React.ChangeEvent<HTMLTextAreaElement>) => setInputText(e.target.value);
  const toggleExpand = () => { setIsExpanded(v => !v); requestAnimationFrame(() => textareaRef.current?.focus()); };
  const toggleSpeechRecognition = () => {
    const SpeechRec = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRec) { alert('Speech Recognition is not supported by your current browser.'); return; }
    if (isListening) { setIsListening(false); return; }
    const recognition = new SpeechRec(); recognition.lang = 'en-IN'; // Latin script, not Devanagari recognition.interimResults = false;
    setIsListening(true); recognition.start();
    recognition.onresult = (event: any) => { const t = event.results[0][0].transcript; setInputText(v => v ? `${v} ${t}` : t); setIsListening(false); };
    recognition.onerror = () => setIsListening(false); recognition.onend = () => setIsListening(false);
  };
  const speakText = (text: string) => { if (!('speechSynthesis' in window)) return; speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.rate=1.05; u.pitch=.95; speechSynthesis.speak(u); };

  const composer = (
    <div className={`neural-composer-dock ${isDark?'bg-[#06080e]/95 border-white/10':'bg-white/95 border-slate-200'}`} style={{position:'fixed',left:0,right:0,bottom:0,width:'100vw',maxWidth:'100vw',margin:0,padding:0,zIndex:2147483000,flexShrink:0,overflow:'visible',transform:'translate3d(0,0,0)',contain:'layout paint',touchAction:'none',overscrollBehavior:'none',boxSizing:'border-box'}}>
      <form onSubmit={handleSubmit} className="neural-composer-form" style={{width:'100%',maxWidth:'100%',overflow:'visible',touchAction:'none'}}>
        <div className="neural-composer" style={{width:'min(100%, 820px)',maxWidth:'820px',margin:'0 auto',boxSizing:'border-box',padding:'10px',borderRadius:'22px',overflow:'visible',background:isDark?'rgba(6,8,14,.95)':'rgba(255,255,255,.95)',border:`1px solid ${isDark?'rgba(255,255,255,.10)':'rgba(226,232,240,1)'}`,boxShadow:'0 14px 42px rgba(0,0,0,.18),0 0 30px rgba(70,110,220,.08)',backdropFilter:'blur(20px)',WebkitBackdropFilter:'blur(20px)'}}>
          <div className="neural-input-wrap" style={{minWidth:0,maxWidth:'100%',overflow:'hidden',touchAction:'none'}}>
            <textarea ref={textareaRef} rows={2} value={inputText} onChange={autoResize} onKeyDown={handleKeyDown} onWheel={(e)=>{e.stopPropagation();}} onPointerDown={(e)=>e.stopPropagation()} onPointerMove={(e)=>e.stopPropagation()} style={{display:'block',width:'100%',minWidth:0,maxWidth:'100%',minHeight:'48px',maxHeight:'120px',boxSizing:'border-box',resize:'none',overflowX:'hidden',overflowY:'auto',padding:'3px 6px',border:0,outline:0,background:'transparent',fontSize:'15px',lineHeight:'24px',color:isDark?'#fff':'#0f172a',overscrollBehavior:'none',overscrollBehaviorY:'none',touchAction:'none',WebkitOverflowScrolling:'auto',scrollBehavior:'auto',scrollMargin:0,overflowAnchor:'none'}} className={`neural-prompt-input ${isDark?'text-white placeholder-white/40':'text-slate-900 placeholder-slate-400'}`} placeholder="Message JARVIS..." />
          </div>
          <div className="neural-composer-footer" style={{display:'flex',alignItems:'center',justifyContent:'space-between',minHeight:34,padding:'6px 0 0',marginTop:4,borderTop:0}}>
            <button type="button" className="neural-action neural-plus" title="Attach" style={{width:34,height:34,borderRadius:11,display:'flex',alignItems:'center',justifyContent:'center'}}><Plus size={17}/></button>
            <div className="neural-actions-right" style={{display:'flex',alignItems:'center',gap:5,flexShrink:0}}>
              {showExpand && <button type="button" onClick={toggleExpand} className={`neural-action neural-expand ${isExpanded?'is-active':''}`} title={isExpanded?'Close expanded composer':'Expand composer'} style={{width:34,height:34,borderRadius:11,display:'flex',alignItems:'center',justifyContent:'center'}}>{isExpanded?<Minimize2 size={16}/>:<Maximize2 size={16}/>}</button>}
              <button type="button" onClick={toggleSpeechRecognition} className={`neural-action neural-mic ${isListening?'is-listening':''}`} title="Voice input" style={{width:34,height:34,borderRadius:11,display:'flex',alignItems:'center',justifyContent:'center'}}>{isListening?<MicOff size={16}/>:<Mic size={16}/>}</button>
              <button type="submit" disabled={!inputText.trim()||isThinking} className="neural-send" title="Send" style={{width:34,height:34,borderRadius:11,display:'flex',alignItems:'center',justifyContent:'center'}}><ArrowUp size={17}/></button>
            </div>
          </div>
        </div>
        <div className={`neural-subtext ${isDark?'text-white/40':'text-slate-400'}`} style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'3px 4px 4px',fontSize:10}}><span>JARVIS 3B • Android 8GB RAM</span><button type="button" onClick={onOpenCLI} style={{display:'flex',alignItems:'center',gap:4}}><Cpu size={12}/> CLI Trace</button></div>
      </form>
    </div>
  );

  return <div id="neural-chat-container" className={`flex flex-col h-full w-full min-h-0 overflow-hidden relative neural-chat-shell ${isExpanded ? 'chat-composer-expanded' : ''}`}>
    <div ref={messagesContainerRef} className="flex-1 min-h-0 overflow-y-auto px-3 sm:px-6 py-4 space-y-4 overscroll-contain neural-messages-scroll">
      {messages.length === 0 ? <div className="h-full flex items-center justify-center"><OrganismCore telemetry={telemetry} onOpenCLI={onOpenCLI} onQuickPrompt={onQuickPrompt} theme={theme} /></div> :
      <div className="max-w-3xl mx-auto space-y-4 w-full pb-2">
        <div className={`flex items-center justify-between pb-2 border-b text-xs font-mono ${isDark?'border-white/5 text-white/40':'border-slate-200 text-slate-400'}`}><span className="flex items-center gap-1.5 font-medium"><span className="w-2 h-2 rounded-full bg-brand-400 animate-pulse"/><span>NEURAL THREAD ACTIVE</span></span>{onClearChat && <button onClick={onClearChat} className={`flex items-center gap-1 transition px-2.5 py-1 rounded-lg ${isDark?'hover:text-brand-300 hover:bg-white/5':'hover:text-brand-600 hover:bg-slate-100 text-slate-500'}`}><RotateCcw className="w-3 h-3"/>Reset Thread</button>}</div>
        {messages.map(msg => { const jarvis=msg.sender==='jarvis', trace=msg.traceLog, open=expandedTraceId===msg.id; return <motion.div key={msg.id} initial={{opacity:0,y:6}} animate={{opacity:1,y:0}} className={`flex gap-2.5 sm:gap-3 max-w-full ${jarvis?'mr-auto justify-start':'ml-auto justify-end'}`}>
          {jarvis && <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-xl flex items-center justify-center shrink-0 mt-0.5 ${isDark?'bg-brand-950/70 border border-brand-400/40 text-brand-300':'bg-slate-900 border border-slate-700 text-brand-300'}`}><Bot className="w-3.5 h-3.5"/></div>}
          <div className={`flex flex-col gap-1.5 max-w-[88%] sm:max-w-[80%] ${!jarvis?'items-end':'items-start'}`}><div className={`p-3.5 sm:p-4 rounded-2xl text-xs sm:text-sm leading-relaxed shadow-sm font-sans break-words ${jarvis?(isDark?'bg-[#0f121d] border border-white/10 text-white/90 rounded-tl-sm':'bg-white border border-slate-200 text-slate-800 rounded-tl-sm'):(isDark?'bg-[#152336] border border-brand-500/40 text-brand-50 rounded-tr-sm':'bg-slate-900 text-white rounded-tr-sm')}`}><p className="whitespace-pre-wrap break-words leading-relaxed">{msg.text}</p>{msg.extractedFact && <div className={`mt-2.5 pt-2 border-t flex items-start gap-1.5 text-xs font-mono p-2 rounded-xl ${isDark?'border-brand-400/30 bg-brand-400/10 text-brand-200':'border-sky-200 bg-sky-50 text-sky-800'}`}><Zap className="w-3.5 h-3.5 text-brand-400 shrink-0"/><span>Engram: <strong>{msg.extractedFact.subject}</strong> ➔ <em>{msg.extractedFact.predicate}</em> ➔ <u>{msg.extractedFact.value}</u></span></div>}{jarvis && <div className={`mt-2.5 flex items-center justify-between text-xs pt-1.5 border-t font-mono ${isDark?'border-white/5 text-white/40':'border-slate-100 text-slate-400'}`}><span>{msg.timestamp}</span><button onClick={()=>speakText(msg.text)} className="p-1 rounded-lg" title="Play voice"><Volume2 className="w-3.5 h-3.5"/></button></div>}</div>
            {/* Real per-turn summary from backend/trace_utils.py's turn_trace_summary()
                -- every field here is read from the actual brain.last_turn_trace +
                brain.last_context for this turn, never a fabricated placeholder. */}
            {jarvis && trace && <div className={`w-full border rounded-xl overflow-hidden font-mono text-xs ${isDark?'bg-black/40 border-white/10':'bg-slate-50 border-slate-200'}`}><button onClick={()=>setExpandedTraceId(open?null:msg.id)} className={`w-full flex items-center justify-between px-3 py-1.5 ${isDark?'bg-white/[0.02] text-brand-300':'bg-white text-brand-700'}`}><span className="flex items-center gap-1.5"><Cpu className="w-3 h-3"/>Cognitive Trace <span className="text-white/40">({Number(trace.latencySeconds||0).toFixed(2)}s)</span></span>{open?<ChevronUp className="w-3 h-3"/>:<ChevronDown className="w-3 h-3"/>}</button><AnimatePresence>{open && <motion.div initial={{height:0,opacity:1}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}} className={`p-3 space-y-2 border-t ${isDark?'border-white/10 text-white/80':'border-slate-200 text-slate-700'}`}><div className="grid grid-cols-2 gap-2 pb-1.5 border-b"><span className="flex items-center gap-1"><Cpu className="w-2.5 h-2.5"/>Mode: {trace.mode||'native'}</span><span className="flex items-center gap-1"><Clock className="w-2.5 h-2.5"/>Status: {trace.status||'—'}</span></div><div className="grid grid-cols-3 gap-2 pb-1.5 border-b"><span className="flex items-center gap-1"><Database className="w-2.5 h-2.5"/>Memory: {trace.memoryMatches??0}</span><span className="flex items-center gap-1"><Database className="w-2.5 h-2.5"/>Knowledge: {trace.knowledgeMatches??0}</span><span className="flex items-center gap-1"><GitFork className="w-2.5 h-2.5"/>Graph: {trace.graphRelations??0}</span></div>{trace.semanticRelations?.length>0 && <div><div className="font-bold flex items-center gap-1"><SpellCheck className="w-2.5 h-2.5"/>Facts Extracted ({trace.semanticRelations.length})</div>{trace.semanticRelations.map((r:any,i:number)=><div key={i} className="pl-2.5">{String(r?.subject)} ➔ {String(r?.predicate)} ➔ {String(r?.value)}</div>)}</div>}<div className="pt-1 flex justify-between"><span className={`flex items-center gap-1 ${trace.pipelineSuccess?'text-green-500':'text-amber-500'}`}><CheckCircle2 className="w-2.5 h-2.5"/>{trace.pipelineSuccess?'Pipeline Validated':'Pipeline Incomplete'}{!trace.llmAvailable && ' · native only'}</span><span>{trace.traceId}</span></div></motion.div>}</AnimatePresence></div>}
          </div>{!jarvis && <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-xl flex items-center justify-center shrink-0 mt-0.5 ${isDark?'bg-white/10 border border-white/20 text-white/80':'bg-slate-200 border border-slate-300 text-slate-700'}`}><User className="w-3.5 h-3.5"/></div>}
        </motion.div>; })}
        {isThinking && <motion.div initial={{opacity:0,y:4}} animate={{opacity:1,y:0}} className="flex gap-2.5 max-w-md mr-auto"><div className="w-7 h-7 rounded-xl flex items-center justify-center bg-brand-950/70 border border-brand-400/40 text-brand-300"><Bot className="w-3.5 h-3.5 animate-spin"/></div><div className={`px-3.5 py-2.5 rounded-2xl flex items-center gap-2.5 ${isDark?'bg-[#0f121d] border border-white/10 text-brand-200':'bg-white border border-slate-200 text-slate-700'}`}><span>JARVIS synthesizing response...</span></div></motion.div>}
        <div ref={messagesEndRef}/>
      </div>}
    </div>
    {typeof document !== 'undefined' ? createPortal(composer, document.body) : null}
  </div>;
};
