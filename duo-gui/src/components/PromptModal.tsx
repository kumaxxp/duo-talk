import React, { useEffect } from "react";
import { useKeypress } from "../hooks/useKeypress";
import { highlightUtter } from "../lib/highlight";
import type { Beat } from "../lib/types";
import { covRate } from "../hooks/useCov";
import { leakCheck } from "../lib/leakcheck";

export type PromptModalProps = {
  open: boolean;
  onClose: () => void;
  turn?: {
    turn: number;
    speaker: "A" | "B";
    beat?: Beat;
    rag?: {
      canon?: { preview?: string | null } | null;
      lore?: { preview?: string | null } | null;
      pattern?: { preview?: string | null } | null;
    };
    prompt_tail?: string; // prompt_debug の末尾
    text?: string; // speak.text
    // Director情報
    directorStatus?: string;
    directorReason?: string;
    directorSuggestion?: string;
    directorGuidance?: string;  // 次ターンへの指示
  };
};

export default function PromptModal({ open, onClose, turn }: PromptModalProps) {
  useKeypress("Escape", () => open && onClose());
  useKeypress("Enter", (e) => {
    if (!open) return;
    if ((e as KeyboardEvent).ctrlKey || (e as KeyboardEvent).metaKey) onClose();
  });

  useEffect(() => {
    if (open) document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  if (!open || !turn) return null;

  const canon = turn.rag?.canon?.preview ?? "";
  const lore = turn.rag?.lore?.preview ?? "";
  const pattern = turn.rag?.pattern?.preview ?? "";
  const utter = turn.text ?? "";
  const highlighted = highlightUtter(utter, [canon, lore, pattern].filter(Boolean) as string[]);
  const cov = {
    c: covRate(canon, utter),
    l: covRate(lore, utter),
    p: covRate(pattern, utter),
  };
  const lc = leakCheck(turn.prompt_tail || "", turn.text || "");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      {/* dialog */}
      <div className="relative bg-white shadow-xl rounded-2xl w-[min(1000px,96vw)] max-h-[88vh] overflow-hidden">
        <header className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            Prompt比較 — Turn {turn.turn} / Speaker {turn.speaker} / {turn.beat ?? "-"}
          </h3>
          <div className="flex items-center gap-3">
            {!lc.ok ? (
              <span className="text-xs px-2 py-1 rounded bg-red-100 text-red-700">Leak: {lc.found.join(", ")}</span>
            ) : (
              <span className="text-xs px-2 py-1 rounded bg-emerald-100 text-emerald-700">No leak</span>
            )}
            <button onClick={onClose} className="text-slate-500 hover:text-slate-800 text-sm">Escで閉じる</button>
          </div>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-0">
          {/* 左：ヒント */}
          <div className="p-4 md:border-r border-slate-200">
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Hints (RAG)</div>
            <HintRow label="pattern" value={pattern} highlight={turn.beat === "PAYOFF"} />
            <HintRow label="canon" value={canon} />
            <HintRow label="lore" value={lore} />
          </div>
          {/* 右：台詞 + ハイライト */}
          <div className="p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs uppercase tracking-wide text-slate-500">Utterance</div>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span>c {(cov.c * 100) | 0}%</span>
                <div className="h-1 w-10 bg-slate-200 rounded"><div className="h-1 bg-emerald-400 rounded" style={{width:`${cov.c*100}%`}}/></div>
                <span>l {(cov.l * 100) | 0}%</span>
                <div className="h-1 w-10 bg-slate-200 rounded"><div className="h-1 bg-emerald-400 rounded" style={{width:`${cov.l*100}%`}}/></div>
                <span>p {(cov.p * 100) | 0}%</span>
                <div className="h-1 w-10 bg-slate-200 rounded"><div className="h-1 bg-emerald-400 rounded" style={{width:`${cov.p*100}%`}}/></div>
              </div>
            </div>
            <div
              className="prose prose-sm max-w-none leading-relaxed"
              dangerouslySetInnerHTML={{ __html: highlighted }}
            />
          </div>
        </div>
        {/* Director判定セクション */}
        {turn.directorStatus && (
          <div className={`mx-4 my-3 p-4 rounded-lg border ${
            turn.directorStatus === 'PASS' ? 'bg-green-50 border-green-200' :
            turn.directorStatus === 'RETRY' ? 'bg-amber-50 border-amber-200' : 'bg-red-50 border-red-200'
          }`}>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-sm font-semibold ${
                turn.directorStatus === 'PASS' ? 'text-green-700' :
                turn.directorStatus === 'RETRY' ? 'text-amber-700' : 'text-red-700'
              }`}>
                {turn.directorStatus === 'PASS' ? '✓' : turn.directorStatus === 'RETRY' ? '🔄' : '⚠️'} Director: {turn.directorStatus}
              </span>
            </div>
            {turn.directorReason && (
              <div className="mb-2">
                <div className="text-xs font-medium text-slate-600 mb-1">判定理由:</div>
                <div className="text-sm text-slate-700 bg-white/60 p-2 rounded">{turn.directorReason}</div>
              </div>
            )}
            {turn.directorSuggestion && turn.directorStatus !== 'PASS' && (
              <div className="mb-2">
                <div className="text-xs font-medium text-slate-600 mb-1">修正提案:</div>
                <div className="text-sm text-slate-700 bg-white/60 p-2 rounded">{turn.directorSuggestion}</div>
              </div>
            )}
            {turn.directorGuidance && (
              <div>
                <div className="text-xs font-medium text-slate-600 mb-1">💡 次ターンへの指示:</div>
                <div className="text-sm text-slate-700 bg-white/60 p-2 rounded">{turn.directorGuidance}</div>
              </div>
            )}
          </div>
        )}
        {/* prompt_tail 折りたたみ */}
        {turn.prompt_tail && (
          <details className="mx-4 my-3 rounded-lg border border-slate-200">
            <summary className="px-3 py-2 text-sm cursor-pointer select-none">
              Prompt tail（末尾180字・内蔵ヒント含む）
            </summary>
            <pre className="px-3 py-2 text-xs whitespace-pre-wrap text-slate-700">{turn.prompt_tail}</pre>
          </details>
        )}
        <footer className="px-5 py-3 border-t border-slate-200 text-xs text-slate-500">
          Ctrl+Enter でも閉じる / ヒット箇所は <mark className="bg-yellow-200 px-1">この表示</mark>
        </footer>
      </div>
    </div>
  );
}

function HintRow({ label, value, highlight }: { label: string; value?: string; highlight?: boolean }) {
  const v = value && value.trim().length > 0 ? value : "—";
  return (
    <div
      className={`mb-2 p-2 rounded border ${
        highlight ? "ring-2 ring-violet-400 bg-violet-50" : "border-slate-200"
      }`}
    >
      <span className="text-[10px] font-mono bg-slate-100 px-1 py-0.5 rounded mr-2">{label}</span>
      <span className="text-sm">{v}</span>
    </div>
  );
}
