import { CheckCircle2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type {
  ChatHistoryCandidateKind,
  ImportedHistoryCandidate,
} from '@/types/chat-history-import'
import { candidateKindLabels } from './chat-history-candidate-catalog-model'

function candidateText(
  kind: ChatHistoryCandidateKind,
  candidate: ImportedHistoryCandidate
): { title: string; detail: string } {
  if (kind === 'expressions') {
    const expression = candidate as Extract<ImportedHistoryCandidate, { situation: string }>
    return { title: expression.situation, detail: expression.style }
  }
  if (kind === 'behaviors') {
    const behavior = candidate as Extract<ImportedHistoryCandidate, { action: string }>
    return { title: behavior.action, detail: behavior.outcome }
  }
  if (kind === 'jargons') {
    const jargon = candidate as Extract<
      ImportedHistoryCandidate,
      { content: string; meaning: string }
    >
    return { title: jargon.content, detail: jargon.meaning }
  }
  if (kind === 'memories') {
    const memory = candidate as Extract<
      ImportedHistoryCandidate,
      { atom_type: string; content: string }
    >
    return { title: memory.content, detail: `${memory.atom_type} · ${memory.subject_id || '群体'}` }
  }
  const profile = candidate as Extract<ImportedHistoryCandidate, { name: string; value: string }>
  return { title: profile.name, detail: `${profile.value} · ${profile.subject_id}` }
}

function candidateEvidenceLabel(candidate: ImportedHistoryCandidate): string {
  const provenanceCount = candidate.provenance?.length ?? 0
  if (provenanceCount > 0) return `${provenanceCount} 个窗口`
  return `${candidate.evidence_ids?.length ?? 0} 条证据`
}

export function ChatHistoryCandidateRows({
  kind,
  candidates,
}: {
  kind: ChatHistoryCandidateKind
  candidates: ImportedHistoryCandidate[]
}) {
  if (!candidates.length) {
    return (
      <div className="ios-empty-state" role="status">
        <CheckCircle2 className="h-9 w-9 text-muted-foreground/50" aria-hidden="true" />
        <p>这一类暂时没有可展示的候选</p>
      </div>
    )
  }

  return (
    <div
      className="divide-y divide-border/60"
      role="list"
      aria-label={`${candidateKindLabels[kind]}候选`}
    >
      {candidates.map((candidate, index) => {
        const text = candidateText(kind, candidate)
        const confidence = Math.min(100, Math.max(0, Math.round((candidate.confidence ?? 0) * 100)))
        return (
          <div
            key={candidate.candidate_id ?? `${kind}-${index}`}
            className="flex min-h-16 items-start gap-3 px-4 py-3"
            role="listitem"
          >
            <div className="min-w-0 flex-1">
              <p className="break-words text-[15px] font-medium leading-5">{text.title}</p>
              <p className="mt-1 break-words text-[13px] leading-5 text-muted-foreground">
                {text.detail}
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1 text-[11px] text-muted-foreground">
              <Badge variant="outline">{confidence}%</Badge>
              <span>{candidateEvidenceLabel(candidate)}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
