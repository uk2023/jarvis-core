import React from 'react';
import { Activity, Brain, Database, Moon, Zap } from 'lucide-react';
import { AppTheme, LiveStateResponse } from '../types';

interface Props { liveState: LiveStateResponse | null; theme: AppTheme; }
type StateKey = 'IDLE' | 'PERCEIVING' | 'INDEXING' | 'CONSOLIDATING' | 'EXECUTING';
const STATES: Array<{key:StateKey; icon:React.ElementType; accent:string}> = [
 {key:'IDLE',icon:Moon,accent:'#64748b'}, {key:'PERCEIVING',icon:Activity,accent:'#5b8def'},
 {key:'INDEXING',icon:Database,accent:'#22c55e'}, {key:'CONSOLIDATING',icon:Brain,accent:'#06b6d4'},
 {key:'EXECUTING',icon:Zap,accent:'#a855f7'},
];

export function CognitivePipelineCard({liveState,theme}:Props){
 const dark=theme==='dark';
 const raw=String(liveState?.stage||'IDLE').toUpperCase();
 const current=(STATES.some(s=>s.key===raw)?raw:'IDLE') as StateKey;
 const active=STATES.find(s=>s.key===current)!;
 const inactive=STATES.filter(s=>s.key!==current);
 return <section id="card-cognitive-pipeline" className={`trace-root ${dark?'trace-dark':'trace-light'} w-full overflow-hidden`}>
  <div className="px-3 py-3 sm:px-4">
   <div className="trace-flow-label !mb-1"><Activity size={13}/> COGNITIVE STATE <span>· LIVE SYSTEM POSITION</span></div>
   <div className="relative mx-auto mt-1 h-[286px] w-full max-w-[420px] overflow-hidden">
    <div className="absolute left-1/2 top-1/2 h-[230px] w-[230px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/5 shadow-[0_0_40px_rgba(91,141,239,.06)]" />
    <div className="absolute left-1/2 top-1/2 h-[196px] w-[196px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-dashed animate-[spin_18s_linear_infinite]" style={{borderColor:`${active.accent}24`}} />
    <div className="absolute left-1/2 top-1/2 h-[166px] w-[166px] -translate-x-1/2 -translate-y-1/2 rounded-full border animate-[spin_9s_linear_infinite_reverse]" style={{borderColor:`${active.accent}14`,boxShadow:`0 0 28px ${active.accent}10`}} />
    <div className="cognitive-orbit absolute left-1/2 top-1/2 h-[220px] w-[220px] -translate-x-1/2 -translate-y-1/2 rounded-full">
      {inactive.map((s,i)=>{const Icon=s.icon;return <div key={s.key} className={`cognitive-orbit-node cognitive-orbit-node-${i} absolute flex h-[45px] w-[45px] items-center justify-center rounded-full border shadow-xl`} style={{background:`radial-gradient(circle at 30% 24%, ${s.accent}75 0%, ${s.accent}32 34%, ${s.accent}12 64%, transparent 82%)`,borderColor:`${s.accent}70`,boxShadow:`inset -6px -7px 12px rgba(0,0,0,.55), inset 3px 3px 8px rgba(255,255,255,.22), 0 7px 20px rgba(0,0,0,.38), 0 0 22px ${s.accent}35`}} title={s.key}><span className="cognitive-orbit-node-core"><Icon size={13} style={{color:s.accent,opacity:.98,filter:`drop-shadow(0 0 5px ${s.accent})`}}/></span></div>})}
    </div>
    <div className="absolute left-1/2 top-1/2 h-[102px] w-[102px] -translate-x-1/2 -translate-y-1/2 flex items-center justify-center rounded-full border transition-all duration-700 ease-out" style={{borderColor:`${active.accent}b0`,background:`radial-gradient(circle at 31% 26%, ${active.accent}82 0%, ${active.accent}36 30%, ${active.accent}12 58%, #02040a 78%, #000 100%)`,boxShadow:`inset -16px -18px 30px rgba(0,0,0,.72), inset 7px 7px 16px rgba(255,255,255,.18), 0 10px 30px rgba(0,0,0,.5), 0 0 42px ${active.accent}70, 0 0 105px ${active.accent}28`}}>
      <div className="absolute -inset-[15px] rounded-full border animate-[spin_5s_linear_infinite]" style={{borderColor:`${active.accent}32`,borderTopColor:`${active.accent}d5`,borderRightColor:`${active.accent}78`,boxShadow:`0 0 22px ${active.accent}35`}}/>
      <div className="absolute -inset-[6px] rounded-full border animate-pulse" style={{borderColor:`${active.accent}42`}}/>
      <div className="absolute inset-[13px] rounded-full bg-black/25 animate-[pulse_2.4s_ease-in-out_infinite]" />
      <active.icon size={26} style={{color:active.accent,filter:`drop-shadow(0 0 10px ${active.accent})`,zIndex:2}}/>
    </div>
   </div>
   <div className="mt-1 flex items-center justify-center gap-2 text-[9px] uppercase tracking-[.14em] text-slate-500"><span>CURRENT STATE:</span><b style={{color:active.accent}}>{current}</b></div>
  </div>
 </section>;
}
