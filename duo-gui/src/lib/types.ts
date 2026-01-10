export type Beat = string

export type DirectorEvent = { ts: string; event: 'director'; run_id: string; turn: number; beat: Beat; cut_cue?: string | null; status?: string; reason?: string; guidance?: string | null }
export type SpeakEvent = { ts: string; event: 'speak'; run_id: string; turn: number; speaker: 'A' | 'B'; text: string; beat?: Beat }
export type RAGEvent = {
  ts: string; event: 'rag_select'; run_id: string; turn: number;
  canon?: { path?: string; preview?: string | null } | null;
  lore?: { path?: string; preview?: string | null } | null;
  pattern?: { path?: string; preview?: string | null } | null;
}
export type PromptDbg = { ts: string; event: 'prompt_debug'; run_id: string; turn: number; prompt_tail: string }
export type RunStartEnd = { ts: string; event: 'run_start' | 'run_end'; run_id: string; model?: string; topic?: string }
export type ThoughtEvent = {
  ts: string;
  event: 'thought';
  run_id: string;
  status: 'generating' | 'reviewing' | 'reviewed' | 'retrying';
  speaker: 'A' | 'B';
  speaker_name?: string;
  attempt: number;
  max_retry?: number;
  result?: string;
  reason?: string;
  suggestion?: string;
  turn?: number;
}

export type EventRow = DirectorEvent | SpeakEvent | RAGEvent | PromptDbg | RunStartEnd | ThoughtEvent

// v2.1 Types
export type SignalsState = {
  jetracer_mode: string
  current_speed: number
  steering_angle: number
  distance_sensors: Record<string, number>
  scene_facts: Record<string, string>
  turn_count: number
  topic_depth: number
  is_stale: boolean
  timestamp: string
}

export type NoveltyStatus = {
  history_length: number
  recent_strategies: string[]
  current_nouns: string[]
}

export type SilenceInfo = {
  type: string
  duration: number
  allow_short: boolean
  sfx: string | null
  bgm_intensity: number
}

export type LiveDialogue = {
  speaker: string
  content: string
  debug?: {
    loop_detected?: boolean
    strategy?: string
    unfilled_slots?: string[]
    few_shot_used?: boolean
  }
}

// Intervention Types
export type InterventionState = 'running' | 'paused' | 'processing' | 'query_back' | 'resuming'

export type QueryBack = {
  from_character: 'yana' | 'ayu'
  question: string
  context: string
  options: string[] | null
}

export type InterventionInterpretation = {
  target_character: 'yana' | 'ayu' | 'both' | null
  instruction_type: string
  instruction_content: string
  confidence: number
}

export type InterventionStatus = {
  state: InterventionState
  session: {
    session_id: string
    run_id: string
    created_at: string
    message_count: number
    has_query_back: boolean
  } | null
}

export type InterventionResult = {
  success: boolean
  state: InterventionState
  needs_clarification: boolean
  next_action: 'wait_input' | 'wait_answer' | 'resume' | 'continue'
  error: string | null
  query_back?: QueryBack
  interpretation?: InterventionInterpretation
}

export type InterventionLogEntry = {
  timestamp: string
  type: 'owner' | 'director' | 'character' | 'system'
  content: string
  character?: string | null
  metadata?: Record<string, unknown> | null
}

// ========== Unified Pipeline Types ==========

/**
 * 対話ターン（UnifiedPipeline）
 */
export interface UnifiedDialogueTurn {
  turn_number: number
  speaker: 'A' | 'B'
  speaker_name: string  // "やな" or "あゆ"
  text: string
  evaluation_status?: 'PASS' | 'RETRY' | 'MODIFY'
  evaluation_action?: 'NOOP' | 'INTERVENE'
  rag_hints?: string[]
  timestamp?: string
}

/**
 * 対話結果（UnifiedPipeline）
 */
export interface UnifiedDialogueResult {
  status: 'success' | 'paused' | 'error'
  run_id: string
  dialogue: UnifiedDialogueTurn[]
  error?: string | null
}

/**
 * Unified API リクエスト
 */
export interface UnifiedRunRequest {
  text?: string
  topic?: string
  imagePath?: string
  imageUrl?: string
  useJetRacerCam?: boolean
  jetracerCamId?: 0 | 1
  useJetRacerSensor?: boolean
  jetracerUrl?: string
  maxTurns?: number
}

/**
 * Unified API ステータスレスポンス
 */
export interface UnifiedRunStatus {
  running: boolean
  run_id: string | null
  status: string | null
}

/**
 * Unified API SSE イベント
 */
export type UnifiedSSEEventType =
  | 'narration_start'
  | 'speak'
  | 'director'
  | 'interrupt'
  | 'narration_complete'
  | 'complete'
  | 'error'

export interface UnifiedSSEEvent {
  type: UnifiedSSEEventType
  data: Record<string, unknown>
}

/**
 * 入力ソースタイプ（フロントエンド用）
 */
export type InputSourceType =
  | 'text'
  | 'image_file'
  | 'image_url'
  | 'jetracer_cam0'
  | 'jetracer_cam1'
  | 'jetracer_sensor'

/**
 * 入力ソース設定（UI用）
 */
export interface InputSourceConfig {
  type: InputSourceType
  enabled: boolean
  value?: string  // text content or file path
}
