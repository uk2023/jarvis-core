// TypeScript definitions for JARVIS Organism Console & Cognitive OS

export type AppTheme = 'dark' | 'light';
export type UserRole = 'admin' | 'guest';
export type ConsoleView = 'home' | 'dashboard' | 'cli' | 'inspector' | 'user_chat' | 'codebox' | 'coding_agent' | 'call';

export type PipelineStage = 'IDLE' | 'PERCEIVING' | 'INDEXING' | 'EXECUTING';

export interface StageTransition {
  stage: PipelineStage;
  previous_stage: PipelineStage;
  timestamp: number;
  duration_in_previous: number;
  detail?: Record<string, any>;
}

export interface ExtractionAttempt {
  stage: 'primary' | 'refined' | 'safe_fallback';
  ok: boolean;
  reason: string | null;
  timestamp: number;
}

export interface ExtractionItem {
  schema: string;
  stage_used: 'primary' | 'refined' | 'safe_fallback';
  fallback_active: boolean;
  attempts: ExtractionAttempt[];
  timestamp: number;
}

export interface LearningQueueState {
  active: boolean;
  alive: boolean;
  pending: number;
  processed: number;
  failed: number;
  dropped: number;
}

export interface LogEntry {
  tag: string;
  message: string;
  level: 'warning' | 'error' | 'info' | 'debug';
  timestamp: number;
}

export interface LiveStateResponse {
  version: number;
  pid: number;
  updated_at: number;
  runtime: 'ONLINE' | 'OFFLINE';
  stage: PipelineStage;
  stage_detail: Record<string, any>;
  stage_since: number;
  fallback_active: boolean;
  pipeline_trace: StageTransition[];
  extractions: ExtractionItem[];
  learning: LearningQueueState;
  logs: LogEntry[];
  organs: Record<string, { type: string; attached: boolean }>;
  heartbeat: { running: boolean; beats: number; idle: boolean };
  llm_ready: boolean;
}

export interface ContractValidationEntry {
  schema: string;
  status: 'PASS' | 'FAIL';
  error?: string;
  timestamp: number;
}

export interface TurnTrace {
  turn_id?: string;
  source: string;
  query: string;
  response_preview: string;
  perception: {
    // Real field names from core/orchestration/blueprint_brain.py's
    // _perceive(). normalized_input/basic_intent are kept as optional
    // legacy aliases only -- the real pipeline writes normalized_text
    // and intent.
    normalized_text?: string;
    normalized_input?: string;
    language: string;
    confidence: number;
    intent?: Record<string, any>;
    basic_intent?: Record<string, any>;
    // Real entities are objects ({text, type, entity_id}), not plain
    // strings -- see core/cognition/semantic_understanding/
    // bridge_to_cognition.py's understand(). Never render one directly
    // as a React child; use entityLabel()/display() first.
    entities: Array<string | { text: string; type?: string; entity_id?: string }>;
    metadata?: {
      source: string;
      uncertainty: number;
      goal: string | null;
      reason: string;
    };
    // The full real semantic_understanding contract output lives here,
    // nested under perception -- NOT at the top level of TurnTrace.
    semantic_understanding?: {
      normalized_text: string;
      intent: Record<string, any>;
      entities: any[];
      relations: any[];
      events: any[];
      references: any[];
      confidence: number;
      // Object, not a string -- {source, degraded?, reason?}.
      provenance: { source: string; degraded?: boolean; reason?: string } | string;
      inferences: any[];
      unknowns: any[];
    };
    semantic_evidence?: Record<string, any>;
  };
  cognitive_route: {
    mode: string;
    confidence: number;
    fallback_allowed: boolean;
    evidence: Array<[string, any]>;
  };
  brain_decision: {
    mode: string;
    status: string;
    skill?: string;
    goal?: string;
    error?: string;
  };
  action_response: {
    mode: string;
    status: string;
    response: string;
    action_payload?: any;
    error?: string;
  };
  llm_available: boolean;
  pipeline_success: boolean;
  timings: {
    total: number;
    [stage: string]: number;
  };
  contract_validation_trace: ContractValidationEntry[];
  llm_budget: {
    active: boolean;
    calls: number;
    max_calls: number;
    reserved_output_tokens: number;
    max_output_tokens: number;
  };
  // Real supplementary data attached server-side by backend/trace_utils.py's
  // real_turn_trace() (from brain.last_context / brain.status()) -- the raw
  // trace object itself never carries these.
  indexing?: { memory: number; knowledge: number; graph: number };
  learning_queue?: { alive: boolean; pending: number; processed: number; failed: number; dropped: number; active: boolean };
}

export interface BackendStatusResponse {
  status: 'success' | 'error';
  organs: Record<string, { type: string; attached: boolean }>;
  heartbeat: { running: boolean; beat_count: number; is_idle: boolean };
  brain: {
    async_learning_queue: LearningQueueState;
    [key: string]: any;
  };
  goals?: Record<string, any>;
  scheduler?: Record<string, any>;
  last_turn_trace: TurnTrace;
}

export interface SystemResourcesData {
  timestamp: number;
  /** False when the real backend endpoint was unreachable and every
   *  field below is zeroed rather than real -- added 2026-09-14 so a
   *  down backend cannot look identical to a healthy one. */
  available?: boolean;
  process: {
    max_rss_mb: number;
    user_cpu_seconds: number;
    system_cpu_seconds: number;
    threads: number;
  };
  llm: {
    backend: string;
    ready: boolean;
    local_loaded: boolean;
    last_error: string | null;
    budget: { calls: number; max_calls: number };
  };
  self_evaluation: {
    evaluations: number;
    success_rate: number;
    average_score: number;
    last_evaluated_at: number;
  };
  knowledge: {
    built: number;
    accepted: number;
    rejected: number;
    pending: number;
    last_built_at: number;
  };
  evolution: {
    proposals: number;
    approved: number;
    applied: number;
    rejected: number;
    last_evolution_at: number;
  };
}

// Condensed per-turn trace shown inline in a chat bubble (see
// backend/trace_utils.py's turn_trace_summary()). Every field is
// sourced from the same real brain.last_turn_trace / brain.last_context
// the full TurnTrace/TraceTreeViewer uses -- just condensed for a
// compact widget instead of the full per-stage breakdown.
export interface TraceSummary {
  traceId: string;
  latencySeconds: number;
  mode: string;
  status: string;
  memoryMatches: number;
  knowledgeMatches: number;
  graphRelations: number;
  semanticRelations: Array<{ subject: string; predicate: string; value: any }>;
  llmAvailable: boolean;
  pipelineSuccess: boolean;
}

export interface ActivityHistoryItem {
  turnId: string;
  startTime: number;
  endTime: number | null; // null represents in-progress turn
  durationSeconds: number;
  stagePath: string[];
  query: string;
  responsePreview: string;
  success: boolean;
  trace: TurnTrace;
}

// Chat Models for User and CLI views
export interface ThinkingStepData {
  stage: string;
  content: string;
  duration_ms?: number;
  ok?: boolean | null;
  // CHUNKING (2026-09-19) -- see task_loop.py's stream() docstring.
  chunk_id?: number;
}

export interface ThinkingNarrativeData {
  content: string;
  chunk_id: number;
}

export interface ChatMessage {
  id: string;
  sessionId: string;
  sender: 'user' | 'jarvis';
  text: string;
  timestamp: string;
  dateLabel?: string;
  source: 'web' | 'cli' | 'autonomous';
  trace?: TurnTrace;
  traceLog?: TraceSummary;
  thinkingDurationSeconds?: number;
  thinkingProcess?: string[];
  // REAL, PERSISTED coding-agent/codebox step list (2026-09-17) --
  // backend/trace_utils.py's derive_thinking_steps(), baked into
  // trace_log at save time so it survives a refresh via /api/history.
  // Rendered by ThinkingSteps.tsx. Distinct from thinkingProcess above
  // (extended-thinking's understand/explore/critique/answer stages,
  // still string-only) -- this is specifically tool-call step data.
  thinkingSteps?: ThinkingStepData[];
  // PERSISTED NARRATIVE (2026-09-19) -- see database.py's
  // _attach_thinking_steps_to_last_message_impl docstring. The prose
  // commentary between step chunks, saved and read back the same way
  // thinkingSteps already is, so a reloaded past message shows the
  // same interleaved narrative as the live run did.
  thinkingNarratives?: ThinkingNarrativeData[];
  extractedFact?: {
    subject: string;
    predicate: string;
    value: string;
    confidence?: number;
  };
}

export interface SessionItem {
  sessionId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  pinned: boolean;
  msgCount: number;
  category: 'Today' | 'Yesterday' | 'Previous 7 Days' | 'Previous' | 'Older';
}

export type ChatSession = SessionItem;

export interface EngramFact {
  id: string;
  subject: string;
  predicate: string;
  value: string;
  confidence: number;
  importance: number;
  evidenceCount: number;
  source: string;
  tags: string[];
  createdAt: number;
  updatedAt: number;
  faissId: number;
  status: 'ACCEPTED' | 'CANDIDATE' | 'REJECTED';
}

export interface OrganStatusInfo {
  name: string;
  classType: string;
  isAttached: boolean;
  role: string;
  metrics: string;
  health: 'green' | 'yellow' | 'red';
}

export interface CuriosityGoal {
  id: string;
  text: string;
  priority: number;
  status: 'pending' | 'active' | 'completed';
  origin: 'user' | 'curiosity' | 'self';
  progress: string[];
  createdAt: number;
}

export interface EvolutionProposal {
  id: string;
  target: string;
  reason: string;
  status: 'PROPOSED' | 'VALIDATED' | 'APPROVED' | 'APPLIED' | 'REJECTED';
  score: number;
  createdAt: number;
}

export interface OrganismTelemetry {
  pulseState: string;
  beatCount: number;
  bpm: number;
  pulseWave: string;
  runtimeSeconds: number;
  isIdle: boolean;
  activeModel: string;
  ramUsageMB: number;
  totalTokensProcessed: number;
  avgLatencyMs: number;
  organs: OrganStatusInfo[];
}

export interface PythonCodeFile {
  filename: string;
  path: string;
  category: 'core' | 'memory' | 'learning' | 'orchestration' | 'autonomy' | 'backend' | 'config' | 'scripts';
  description: string;
  code: string;
}

export type ActiveTab = 'chat' | 'matrix' | 'memory' | 'autonomy' | 'code';

// ==========================================
// SECTION 4: NEW CAPABILITIES INTERFACES
// ==========================================

// 4a. Voice Control & Speech Settings
export interface VoiceSettings {
  pitch: number; // default 0.55
  rate: number; // default 1.1
  language: string; // default 'hi-IN'
  engine: string;
  spoken_replies: boolean;
  whisper_fallback: boolean; // opt-in fallback to Whisper-via-Groq
}

export interface TTSEngine {
  name: string;
  label?: string;
  default?: boolean;
}

// 4b. Organ Introspection (10 fixed questions)
export interface OrganIntrospectionAnswers {
  who_are_you: string;
  responsibility: string;
  received: string;
  produced: string;
  why: string;
  evidence: string;
  confidence: string;
  state_changed: string;
  persisted: string;
  unverified: string;
}

export interface OrganIntrospectionItem {
  organ_name: string;
  displayName: string;
  status: 'active' | 'standby' | 'degraded';
  lastTurnId?: string;
  answers: OrganIntrospectionAnswers;
}

// 4c. Overnight / Idle Learning Report
export interface OvernightFinding {
  id: string;
  pattern_or_vocab: string;
  evidence: string;
  sandbox_tested: boolean;
  test_passed: boolean;
  pass_count: number;
  fail_count: number;
}

export interface OvernightLogEntry {
  timestamp: number;
  reviewed_target: string;
  findings: OvernightFinding[];
  summary: string;
  evidence_threshold_met: boolean;
}

// 4d. Self-Improvement Requests
export interface ImprovementRequest {
  id: string;
  request_text: string;
  timestamp: number;
  scope: 'narrow' | 'broad'; // narrow: JARVIS can sandbox-test; broad: needs developer
  status: 'pending' | 'sandbox_testing' | 'applied' | 'rejected' | 'needs_operator';
  evidence?: string;
  sourceSessionId?: string;
}

// 4e. Runtime / Uptime Telemetry
export interface RuntimeInfo {
  session_uptime_seconds: number; // this process only
  cumulative_runtime_seconds: number; // all sessions ever, persisted
  age_seconds: number; // time since first boot, includes offline time
}

// 4f. Safety Check History (Llama Prompt Guard 2)
export interface SafetyCheckEntry {
  id: string;
  timestamp: number;
  query_preview: string;
  label: 'benign' | 'malicious';
  score?: number;
  action: 'flagged_only' | 'passed';
  notes?: string;
}
