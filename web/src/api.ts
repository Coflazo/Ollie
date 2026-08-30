// Typed client for the local API. Same-origin in a built bundle; proxied in dev.

export type Probe = {
  hardware: {
    os: string
    cpu: string
    cores_physical: number
    ram_gb: number
    ram_available_gb: number
    disk_free_gb: number
    apple_silicon: boolean
  }
  summary: string
  tier: { name: string; context_cap: number; candidates: string[] }
  ollama: boolean
  model: string | null
  installed: string[]
  needs_pull: boolean
  suggested_pull: string | null
  resumable: {
    persona: Candidate
    episode: number
    session_id: string
    messages: number
  } | null
}

export type Question = { id: string; text: string }

export type Candidate = {
  id: string
  display_name: string
  adult_age: number
  pronouns: string
  archetype: string
  background: string
  stable_traits: string[]
  values: string[]
  special_interest: string
  tics: string[]
  pushback_style: string
  chemistry_reasons: string[]
  friction_points: string[]
  boundaries: string[]
}

export type Read = {
  summary: string
  dimensions: { name: string; score: number; confidence: number; evidence: string }[]
  texture: string[]
  dodges: string[]
  contradictions: string[]
}

export type Explanation = {
  prompt_hash: string
  attempts: number
  style_violations: { rule: string; why: string }[]
  memories_used: { id: string; kind: string; text: string; score: number }[]
  sources_used: { title: string; category: string; score: number }[]
}

export type Context = {
  used: number
  cap: number
  fraction: number
  stage: 'ok' | 'meter' | 'draft' | 'choose' | 'block'
  state?: Record<string, number | string | boolean>
  episode?: number
  consolidation?: {
    committed: number
    threads: string[]
    state: Record<string, number>
    delta: Record<string, number>
  }
}

export type TurnResponse = {
  reply: string
  message_id: string
  latency_ms: number
  explanation: Explanation
  context: Context
  state: Record<string, number | string>
}

export type MemoryRecord = {
  id: string
  kind: string
  subject: string
  predicate: string
  value: string
  confidence: number
  importance: number
  sensitivity: 'normal' | 'personal' | 'special_category'
  user_locked: number
  requires_confirmation: number
}

export type Capsule = {
  persona_name: string
  recent_summary: string
  unresolved_tension: string | null
  open_threads: string[]
  shared_moments: string[]
  carried_tics: string[]
  excluded_memory_ids: string[]
  interaction_state: Record<string, number>
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })

export const api = {
  probe: (model?: string) =>
    request<Probe>(`/v1/setup/probe${model ? `?model=${encodeURIComponent(model)}` : ''}`),

  questions: () =>
    request<{ items: Question[]; interview_turns: number }>('/v1/onboarding/questions'),

  submitQuestionnaire: (
    answers: Record<string, number>,
    preferences: Record<string, unknown>,
    displayName: string,
    knownType = '',
  ) =>
    post<{ profile_id: string; big_five: Record<string, number>; question: string; turn: number; total: number }>(
      '/v1/onboarding/questionnaire',
      { answers, preferences, display_name: displayName, known_type: knownType },
    ),

  answerInterview: (answer: string) =>
    post<
      | { done: false; question: string; turn: number; total: number }
      | { done: true; read: Read; candidates: Candidate[] }
    >('/v1/onboarding/interview', { answer }),

  selectPersona: (candidateId: string) =>
    post<{ persona_id: string; session_id: string; persona: Candidate; prompt_hash: string }>(
      '/v1/personas/select',
      { candidate_id: candidateId, edits: {} },
    ),

  send: (text: string) => post<TurnResponse>('/v1/sessions/messages', { text }),

  context: () => request<Context>('/v1/sessions/context'),

  history: () =>
    request<{
      episode: number
      messages: { id: string; role: string; content: string; meta: Record<string, unknown> }[]
    }>('/v1/sessions/messages'),

  memories: (provenance = false) =>
    request<{ memories: MemoryRecord[]; threads: { id: string; title: string }[] }>(
      `/v1/memories${provenance ? '?provenance=true' : ''}`,
    ),

  forget: (id: string) => request<{ ok: boolean }>(`/v1/memories/${id}`, { method: 'DELETE' }),

  lock: (id: string, lock: boolean) =>
    request<{ ok: boolean }>(`/v1/memories/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ lock }),
    }),

  correctMemory: (id: string, value: string) =>
    request<{ ok: boolean; replaced_by: string }>(`/v1/memories/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ value }),
    }),

  draftCapsule: () => post<{ capsule_id: string; capsule: Capsule }>('/v1/sessions/rollover/draft'),

  approveCapsule: (capsuleId: string, capsule: Capsule) =>
    post<{ session_id: string; episode: number; carried: string }>('/v1/sessions/rollover/approve', {
      capsule_id: capsuleId,
      capsule,
    }),

  marketPreview: () => post<Record<string, any>>('/v1/marketplace/preview'),

  marketAccept: (preview: Record<string, unknown>) =>
    post<{ receipt_id: string; path: string }>('/v1/marketplace/accept', preview),
}
