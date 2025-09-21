export type Beat = 'BANter' | 'PIVOT' | 'PAYOFF'

export type DirectorEvent = { ts:string; event:'director'; run_id:string; turn:number; beat:Beat; cut_cue?:string|null }
export type SpeakEvent    = { ts:string; event:'speak';    run_id:string; turn:number; speaker:'A'|'B'; text:string; beat?:Beat }
export type RAGEvent      = { ts:string; event:'rag_select'; run_id:string; turn:number;
  canon?:   { path?:string; preview?:string|null } | null;
  lore?:    { path?:string; preview?:string|null } | null;
  pattern?: { path?:string; preview?:string|null } | null;
}
export type PromptDbg     = { ts:string; event:'prompt_debug'; run_id:string; turn:number; prompt_tail:string }
export type RunStartEnd   = { ts:string; event:'run_start'|'run_end'; run_id:string; model?:string; topic?:string }

export type EventRow = DirectorEvent | SpeakEvent | RAGEvent | PromptDbg | RunStartEnd

