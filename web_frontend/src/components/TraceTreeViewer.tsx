import React, { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  ChevronDown, ChevronRight, Copy, Check, Terminal, Layers, CircleDot,
  Brain, Database, Route, Zap, ShieldCheck, GraduationCap,
  GitBranch, MessageSquare, Gauge, Activity, Code2, Clock3,
  CheckCircle2, AlertTriangle, XCircle
} from 'lucide-react';
import { TurnTrace, AppTheme } from '../types';

interface TraceTreeViewerProps {
  trace: TurnTrace;
  theme: AppTheme;
  initiallyExpanded?: boolean;
}

type StageKey =
  | 'perception' | 'indexing' | 'semantic'
  | 'routing' | 'budget' | 'execution' | 'response' | 'learning' | 'learningResult';

const stageMeta: Record<StageKey, {
  n: string; label: string; color: string; soft: string; icon: React.ElementType;
}> = {
  perception: { n: '01', label: 'PERCEPTION', color: '#5b8def', soft: 'rgba(91,141,239,.11)', icon: Activity },
  indexing: { n: '02', label: 'INDEXING', color: '#22c55e', soft: 'rgba(34,197,94,.10)', icon: Database },
  semantic: { n: '03', label: 'SEMANTIC UNDERSTANDING', color: '#06b6d4', soft: 'rgba(6,182,212,.10)', icon: Brain },
  routing: { n: '04', label: 'ROUTING', color: '#f59e0b', soft: 'rgba(245,158,11,.10)', icon: Route },
  budget: { n: '05', label: 'LLM BUDGET', color: '#5b8def', soft: 'rgba(91,141,239,.10)', icon: Gauge },
  execution: { n: '06', label: 'EXECUTION', color: '#a855f7', soft: 'rgba(168,85,247,.10)', icon: Zap },
  response: { n: '07', label: 'BRAIN → RESPONSE', color: '#14b8a6', soft: 'rgba(20,184,166,.10)', icon: MessageSquare },
  learning: { n: '08', label: 'LEARNING', color: '#e24d6b', soft: 'rgba(226,77,107,.09)', icon: GraduationCap },
  learningResult: { n: '09', label: 'LEARNING RESULT', color: '#8b5cf6', soft: 'rgba(139,92,246,.09)', icon: CheckCircle2 },
};

function fmtTime(v?: number) {
  return `${(v ?? 0).toFixed(2)}s`;
}
function pct(v?: number) {
  return v == null ? '—' : `${Math.round(v * 100)}%`;
}
function display(v: any) {
  if (v == null || v === '') return '—';
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  try { return JSON.stringify(v); } catch { return String(v); }
}

// Real perception.entities (see core/cognition/semantic_understanding/
// bridge_to_cognition.py's understand()) are dicts -- {text, type,
// entity_id} -- never plain strings. Rendering one directly as a React
// child throws "Objects are not valid as a React child", which is what
// was blanking the whole trace panel the moment any turn extracted at
// least one entity (i.e. almost every turn).
function entityLabel(e: any) {
  if (typeof e === 'string') return e;
  if (e && typeof e === 'object') return e.text ?? display(e);
  return display(e);
}

// Real semantic_understanding.provenance (see blueprint_brain.py's
// _perceive()) is an object -- {source, degraded?, reason?} -- not a
// bare string. Same crash risk as entities above if rendered directly.
function provenanceLabel(p: any) {
  if (p == null) return 'native';
  if (typeof p === 'string') return p;
  if (typeof p === 'object') return p.source ?? display(p);
  return display(p);
}

function formatIntent(v: any) {
  if (v == null || v === '') return 'question';
  if (typeof v === 'string') return v;
  if (typeof v === 'object') {
    return v.intent || v.name || v.action || v.domain || 'structured intent';
  }
  return String(v);
}

function Field({ label, value, mono = false, accent }: {
  label: string; value: React.ReactNode; mono?: boolean; accent?: string;
}) {
  return (
    <div className="trace-field">
      <span className="trace-field-label">{label}</span>
      <span className={`trace-field-value ${mono ? 'trace-mono' : ''}`} style={accent ? { color: accent } : undefined}>
        {value}
      </span>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: React.ReactNode; color: string }) {
  return (
    <div className="trace-metric">
      <span className="trace-metric-label">{label}</span>
      <strong style={{ color }}>{value}</strong>
    </div>
  );
}

function Schema({ data, color, copied, onCopy }: {
  data: any; color: string; copied: boolean; onCopy: () => void;
}) {
  return (
    <div className="trace-schema">
      <div className="trace-schema-head">
        <span><Code2 size={13} /> SCHEMA CONTRACT · JSON AST</span>
        <button onClick={onCopy} style={{ color }} className="trace-copy-btn">
          {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? 'COPIED' : 'COPY'}
        </button>
      </div>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}

export function TraceTreeViewer({ trace, theme, initiallyExpanded = true }: TraceTreeViewerProps) {
  const isDark = theme === 'dark';
  const t = trace.timings || ({} as TurnTrace['timings']);
  const totalElapsed = Number.isFinite(Number(t.total))
    ? Number(t.total)
    : Object.values(t).filter(v => typeof v === 'number').reduce((a, v) => a + Number(v), 0);
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => ({
    perception: initiallyExpanded, indexing: initiallyExpanded, semantic: initiallyExpanded,
    routing: initiallyExpanded, budget: initiallyExpanded,
    execution: initiallyExpanded, response: initiallyExpanded, learning: initiallyExpanded, learningResult: initiallyExpanded,
  }));
  const [schemas, setSchemas] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<string | null>(null);

  const calls = trace.llm_budget?.calls ?? 0;
  const maxCalls = trace.llm_budget?.max_calls ?? 0;
  const tokens = trace.llm_budget?.reserved_output_tokens ?? 0;
  const maxTokens = trace.llm_budget?.max_output_tokens ?? 0;
  const entities = trace.perception?.entities || [];

  const semantic: any = trace.perception?.semantic_understanding || (trace as any).semantic_understanding || (trace as any).semantic || {};
  const relationsCount: number = Array.isArray(semantic.relations) ? semantic.relations.length : (semantic.relations_extracted ?? 0);
  const indexing: any = (trace as any).indexing || {};
  const cognition: any = (trace as any).cognition || (trace as any).brain_cognition || {};
  const learning: any = (trace as any).learning_queue || (trace as any).learning || {};

  const schemasData = useMemo(() => ({
    perception: {
      type: 'PerceptionContract',
      source: trace.source,
      normalized_input: trace.perception?.normalized_text || trace.perception?.normalized_input,
      intent: trace.perception?.intent || trace.perception?.basic_intent,
      confidence: trace.perception?.confidence,
      language: trace.perception?.language,
      entities: entities,
    },
    indexing: {
      type: 'MemoryGraphContract',
      memory: indexing.memory ?? (trace as any).memory_count,
      knowledge: indexing.knowledge ?? (trace as any).knowledge_count,
      graph: indexing.graph ?? (trace as any).graph_count,
    },
    semantic: {
      type: 'SemanticUnderstandingContract',
      provenance: provenanceLabel(semantic.provenance),
      confidence: semantic.confidence,
      relations_extracted: relationsCount,
      entities: semantic.entities ?? entities,
      reason: semantic.provenance?.reason || semantic.reason,
    },
    cognition: {
      type: 'CognitionContract',
      mode: cognition.mode ?? trace.brain_decision?.mode,
      goal: cognition.goal,
      constraints: cognition.constraints,
      validator: cognition.validator,
    },
    routing: {
      type: 'CognitiveRouteContract',
      mode: trace.cognitive_route?.mode,
      confidence: trace.cognitive_route?.confidence,
      fallback_allowed: trace.cognitive_route?.fallback_allowed,
      rationale: trace.cognitive_route?.evidence,
    },
    budget: {
      type: 'LLMBudgetContract',
      calls_used: calls, calls_limit: maxCalls,
      tokens_used: tokens, tokens_limit: maxTokens,
    },
    execution: {
      type: 'ExecutionContract',
      mode: trace.action_response?.mode || trace.brain_decision?.mode,
      status: trace.action_response?.status || trace.brain_decision?.status,
      skill: trace.brain_decision?.skill,
      error: trace.action_response?.error || trace.brain_decision?.error,
    },
    response: {
      type: 'BrainGroundingContract',
      grounded: (trace as any).grounded ?? true,
      response: trace.action_response?.response || trace.response_preview,
    },
    learning: {
      type: 'LearningContract',
      queued: learning.queued,
      pending: learning.pending,
      processed: learning.processed,
      failed: learning.failed,
      knowledge_stored: learning.knowledge_stored,
      reason: learning.reason,
    },
  }), [trace, entities, calls, maxCalls, tokens, maxTokens, semantic, indexing, cognition, learning]);

  const toggle = (key: string) => setExpanded(s => ({ ...s, [key]: !s[key] }));
  const copy = (key: string) => {
    navigator.clipboard?.writeText(JSON.stringify((schemasData as any)[key], null, 2));
    setCopied(key); setTimeout(() => setCopied(null), 1600);
  };

  const stage = (key: StageKey, children: React.ReactNode, summary: React.ReactNode, extra?: React.ReactNode) => {
    const m = stageMeta[key];
    const Icon = m.icon;
    const open = !!expanded[key];
    return (
      <div className="trace-node" style={{ '--trace-accent': m.color, '--trace-soft': m.soft } as React.CSSProperties}>
        <div className="trace-node-rail" aria-hidden="true">
          <span className="trace-node-dot" />
        </div>
        <div className="trace-stage">
          <button className={`trace-stage-head ${open ? 'is-open' : ''}`} onClick={() => toggle(key)} aria-expanded={open}>
            <span className="trace-stage-index">{m.n}</span>
            <span className="trace-stage-icon"><Icon size={16} strokeWidth={2.2} /></span>
            <span className="trace-stage-title">{m.label}</span>
            <span className="trace-stage-time"><Clock3 size={12} /> {fmtTime(t[key] || undefined)}</span>
            <span className="trace-stage-summary">{summary}</span>
            <span className="trace-stage-status"><span /> {trace.pipeline_success ? 'Completed' : 'Failed'}</span>
            <span className="trace-chevron">{open ? <ChevronDown size={17} /> : <ChevronRight size={17} />}</span>
          </button>
          <AnimatePresence initial={false}>
            {open && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }} transition={{ duration: .18 }} className="trace-stage-body">
                <div className="trace-stage-content">{children}</div>
                {extra}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    );
  };

  const schemaExtra = (key: StageKey) => schemas[key] ? (
    <Schema data={(schemasData as any)[key]} color={stageMeta[key].color} copied={copied === key} onCopy={() => copy(key)} />
  ) : null;

  const semanticReason = semantic.provenance?.reason || semantic.reason || 'No relation extracted, nothing will be stored this turn';
  const learningStored = learning.knowledge_stored ?? (relationsCount > 0);

  return (
    <div className={`trace-root ${isDark ? 'trace-dark' : 'trace-light'}`}>
      <div className="trace-hero">
        <div className="trace-hero-top">
          <div className="trace-kicker"><Terminal size={15} /> JARVIS WORKFLOW</div>
        </div>
        <div className="trace-hero-title">
          <div>
            <h2>THIS TURN</h2>
            <p>{trace.turn_id || 'TRN-UNKNOWN'} <span>·</span> {trace.query || 'No query recorded'}</p>
          </div>
          <div className="trace-total" aria-label="Total elapsed time">
            <span>TOTAL ELAPSED</span>
            <strong>{fmtTime(totalElapsed)}</strong>
          </div>
        </div>
        <div className="trace-overview">
          <Metric label="SOURCE" value={trace.source || 'safe_fallback'} color="#4f7ed8" />
          <Metric label="INTENT" value={display(formatIntent(trace.perception?.intent || trace.perception?.basic_intent))} color="#7c58d6" />
          <Metric label="CONFIDENCE" value={pct(trace.perception?.confidence)} color="#0ca678" />
          <Metric label="LLM" value={trace.cognitive_route?.mode || 'llm'} color="#8b5cf6" />
          <Metric label="BUDGET" value={`${calls}/${maxCalls}`} color="#2aa7a0" />
          <Metric label="ELAPSED" value={fmtTime(totalElapsed)} color="#315fbe" />
        </div>
      </div>

      <div className="trace-flow">
        <div className="trace-flow-label"><GitBranch size={13} /> EXECUTION PATH <span>· 9 stages · sequential trace</span></div>

        {stage('perception',
          <div className="trace-grid">
            <Field label="Normalized input" value={trace.perception?.normalized_text || trace.perception?.normalized_input || trace.query} />
            <Field label="Intent" value={display(formatIntent(trace.perception?.intent || trace.perception?.basic_intent))} mono accent="#8b5cf6" />
            <Field label="Language" value={trace.perception?.language || 'unknown'} accent="#5b8def" />
            <Field label="Source" value={trace.source || 'safe_fallback'} mono />
            <Field label="Confidence" value={pct(trace.perception?.confidence)} accent="#22c55e" />
            <Field label="Safety / metadata" value={display(trace.perception?.metadata || 'passed')} />
            <div className="trace-wide">
              <div className="trace-subhead">ENTITIES</div>
              <div className="trace-chips">{entities.length ? entities.map((e, i) => <span key={i}>{entityLabel(e)}</span>) : <em>0 entities</em>}</div>
            </div>
          </div>,
          <span>{trace.source || 'Safe fallback'} · {pct(trace.perception?.confidence)} confidence</span>,
          schemaExtra('perception')
        )}

        {stage('indexing',
          <div className="trace-grid">
            <Metric label="MEMORY" value={indexing.memory ?? (trace as any).memory_count ?? '—'} color="#22c55e" />
            <Metric label="KNOWLEDGE" value={indexing.knowledge ?? (trace as any).knowledge_count ?? '—'} color="#22c55e" />
            <Metric label="GRAPH" value={indexing.graph ?? (trace as any).graph_count ?? '—'} color="#22c55e" />
            <Field label="Vector index" value={indexing.vector_index || (trace as any).vector_index || 'FAISS'} mono />
            <Field label="Retrieval" value={display(indexing.retrieval || indexing.results || 'completed')} />
          </div>,
          <span>{indexing.memory ?? (trace as any).memory_count ?? '—'} memory · {indexing.knowledge ?? (trace as any).knowledge_count ?? '—'} knowledge · {indexing.graph ?? (trace as any).graph_count ?? '—'} graph nodes</span>,
          schemaExtra('indexing')
        )}

        {stage('semantic',
          <div className="trace-grid">
            <Field label="Provenance" value={provenanceLabel(semantic.provenance)} mono accent="#06b6d4" />
            <Field label="Confidence" value={pct(semantic.confidence ?? trace.perception?.confidence)} accent="#22c55e" />
            <Field label="Relations extracted" value={relationsCount} mono />
            <Field label="Entities" value={semantic.entities?.length ?? entities.length} mono />
            <div className="trace-wide trace-callout">
              <ShieldCheck size={16} />
              <div><strong>{relationsCount ? 'Relations available' : 'No relation extracted'}</strong><p>{semanticReason}</p></div>
            </div>
          </div>,
          <span>{provenanceLabel(semantic.provenance)} provenance · {relationsCount} relations</span>,
          schemaExtra('semantic')
        )}

        {stage('routing',
          <div className="trace-grid">
            <Field label="Selected route" value={trace.cognitive_route?.mode || 'llm'} mono accent="#f59e0b" />
            <Field label="Confidence" value={pct(trace.cognitive_route?.confidence)} accent="#f59e0b" />
            <Field label="Fallback allowed" value={trace.cognitive_route?.fallback_allowed ? 'YES' : 'NO'} />
            <div className="trace-wide trace-callout amber"><Route size={16} /><div><strong>Routing rationale</strong><p>{display((trace.cognitive_route as any)?.rationale || (trace.cognitive_route as any)?.reason || trace.cognitive_route?.evidence || 'Cognition requires language cognition for this turn; no executable native capability was selected.')}</p></div></div>
          </div>,
          <span>{(trace.cognitive_route?.mode || 'llm').toUpperCase()} route · {pct(trace.cognitive_route?.confidence)} confidence</span>,
          schemaExtra('routing')
        )}

        {stage('budget',
          <div className="trace-grid">
            <Field label="Calls used" value={`${calls} / ${maxCalls}`} mono accent="#5b8def" />
            <Field label="Remaining" value={Math.max(0, maxCalls - calls)} mono />
            <Field label="Tokens used" value={`${tokens} / ${maxTokens}`} mono accent="#5b8def" />
            <Field label="Tokens remaining" value={Math.max(0, maxTokens - tokens)} mono />
            <div className="trace-wide trace-budget">
              <div><span>CALLS</span><b style={{ width: `${maxCalls ? Math.min(100, calls / maxCalls * 100) : 0}%` }} /></div>
              <div><span>TOKENS</span><b style={{ width: `${maxTokens ? Math.min(100, tokens / maxTokens * 100) : 0}%` }} /></div>
            </div>
            <div className="trace-wide trace-callout"><Zap size={16} /><div><strong>Why LLM?</strong><p>{(trace as any).llm_budget?.reason || 'Perception cascade exhausted; final response phrasing requires language synthesis.'}</p></div></div>
          </div>,
          <span>{calls}/{maxCalls} calls · {tokens}/{maxTokens} output tokens</span>,
          schemaExtra('budget')
        )}

        {stage('execution',
          <div className="trace-grid">
            <Field label="Mode" value={trace.action_response?.mode || trace.brain_decision?.mode || 'llm'} mono accent="#a855f7" />
            <Field label="Status" value={trace.action_response?.status || trace.brain_decision?.status || 'completed'} accent="#22c55e" />
            <Field label="Skill" value={trace.brain_decision?.skill || '—'} mono />
            <Field label="Error" value={trace.action_response?.error || trace.brain_decision?.error || 'none'} />
          </div>,
          <span>{(trace.action_response?.mode || trace.brain_decision?.mode || 'llm').toUpperCase()} execution · {(trace.action_response?.status || trace.brain_decision?.status || 'completed')}</span>,
          schemaExtra('execution')
        )}

        {stage('response',
          <div className="trace-grid">
            <div className="trace-wide trace-callout teal"><CheckCircle2 size={17} /><div><strong>Grounded response</strong><p>Response stayed within the structured brief Brain provided.</p></div></div>
            <div className="trace-wide trace-response">{trace.action_response?.response || trace.response_preview || 'No response text recorded.'}</div>
          </div>,
          <span>Grounded · response contract satisfied</span>,
          schemaExtra('response')
        )}

        {stage('learning',
          <div className="trace-grid">
            <Field label="Queue" value={`pending=${learning.pending ?? 0} processed=${learning.processed ?? 0}`} mono />
            <Field label="Processed" value={learning.processed ?? '—'} mono accent="#22c55e" />
            <Field label="Failed" value={learning.failed ?? 0} mono accent={learning.failed ? '#ef4444' : '#22c55e'} />
            <Field label="Knowledge stored" value={learningStored ? 'YES' : 'NO'} accent={learningStored ? '#22c55e' : '#f59e0b'} />
            <div className="trace-wide trace-callout rose"><GraduationCap size={16} /><div><strong>{learningStored ? 'Knowledge accepted' : 'No statement stored this turn'}</strong><p>{learning.reason || 'Question / greeting / command; not a fact to store.'}</p></div></div>
          </div>,
          <span>{learningStored ? 'Knowledge accepted' : 'No knowledge stored'} · {learning.pending ?? 0} pending</span>,
          schemaExtra('learning')
        )}

        {stage('learningResult',
          <div className="trace-grid">
            <Field label="Knowledge stored" value={learningStored ? 'YES' : 'NO'} accent={learningStored ? '#059669' : '#d97706'} />
            <Field label="Active rule" value={(trace as any).active_rule || learning.active_rule || 'Always UK'} />
            <Field label="Latest cycle" value={(trace as any).latest_cycle || learning.latest_cycle || (trace.action_response?.mode || trace.brain_decision?.mode || 'llm')} mono />
            <Field label="Native resolution" value={display((trace as any).native_resolution_rate ?? learning.native_resolution_rate ?? '0.0')} mono />
            <Field label="Retry value rate" value={display((trace as any).retry_value_rate ?? learning.retry_value_rate ?? '—')} mono />
            <div className="trace-wide trace-callout rose"><CheckCircle2 size={16} /><div><strong>{learningStored ? 'Learning result committed' : 'No statement stored this turn'}</strong><p>{learning.reason || 'Question / greeting / command; not a fact to store.'}</p></div></div>
          </div>,
          <span>{learningStored ? 'Stored' : 'Not stored'} · final learning decision</span>,
          schemaExtra('learningResult')
        )}

        <div className="trace-end">
          <div className="trace-end-line" />
          <span><CircleDot size={13} /> TRACE END · {trace.pipeline_success ? 'SUCCESS' : 'FAILED'}</span>
          <div className="trace-end-line" />
        </div>
      </div>
    </div>
  );
}
