// ── Auth (ADR-0011) ────────────────────────────────────────────────────────
// When the backend has OPSPILOT_API_TOKEN set, every request needs a Bearer
// token. The token is kept in localStorage (set from the sidebar) and
// attached here so call sites stay unchanged.

const TOKEN_KEY = 'opspilot_api_token';

export function getApiToken(): string {
  return typeof localStorage !== 'undefined' ? (localStorage.getItem(TOKEN_KEY) ?? '') : '';
}

export function setApiToken(token: string): void {
  if (typeof localStorage === 'undefined') return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getApiToken();
  if (token) {
    init.headers = { ...(init.headers ?? {}), Authorization: `Bearer ${token}` };
  }
  return fetch(input, init);
}

export interface RunRequest {
  input: Record<string, unknown>;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface WorkItemClassification {
  work_item_type: string;
  confidence: number;
  rationale: string;
}

export interface RunResponse {
  session_id: string;
  artifact_id: string | null;
  schema_valid: boolean;
  result: TicketSummary;
  error: string | null;
  usage: TokenUsage | null;
  // #6 — present when the type was inferred. needs_confirmation means the run
  // was withheld for a human pick; re-submit with an explicit playbookId.
  classification?: WorkItemClassification | null;
  needs_confirmation?: boolean;
}

// A work-item artifact: incident_summary_v1 or request_fulfillment_v1.
export interface TicketSummary {
  schema_version: string;
  work_item_ref?: string;
  work_item_type?: string;
  summary: string;
  symptoms?: string[];
  scope?: string;
  tried_steps?: string[];
  missing_fields: string[];
  tasks?: Task[];
  severity_suggested?: string;
  escalation_hint?: string;
  // service_request (request_fulfillment_v1) extension
  requested_item?: string;
  approval_needed?: boolean;
  citations: Citation[];
}

export interface Task {
  ref: string;
  action: string;
  rationale: string;
  tier: 'L1' | 'L2' | 'L3';
  citations?: string[];
}

export interface Citation {
  id: string;
  chunk_id: string;
  document_id: string;
  source_path: string;
  line_start: number;
  line_end: number;
  heading_path?: string[];
}

export interface ConfigResponse {
  active_model_ref: string;
  modules: Record<string, boolean>;
  embed_provider?: string;
  embed_warning?: string | null;
}

export interface ModelOption {
  id: string;
  label: string;
  provider_id: string;
  kind: string;
  name: string;
  retrieval_mode: string;
}

export interface ModelsResponse {
  models: ModelOption[];
  default_id: string;
}

export async function getConfig(): Promise<ConfigResponse> {
  const res = await apiFetch('/api/config');
  if (!res.ok) throw new Error(`Config fetch failed: ${res.status}`);
  return res.json();
}

export async function getModels(): Promise<ModelsResponse> {
  const res = await apiFetch('/api/models');
  if (!res.ok) throw new Error(`Models fetch failed: ${res.status}`);
  return res.json();
}

export async function runTicket(
  input: Record<string, unknown>,
  modelId?: string,
  playbookId?: string
): Promise<RunResponse> {
  const res = await apiFetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input, model_id: modelId ?? null, playbook_id: playbookId ?? null })
  });
  if (!res.ok) throw new Error(`Run failed: ${res.status}`);
  return res.json();
}

export type StreamEvent =
  | { type: 'status'; message: string }
  | { type: 'result'; data: RunResponse }
  | { type: 'error'; message: string };

export async function* runTicketStream(
  input: Record<string, unknown>,
  modelId?: string,
  playbookId?: string
): AsyncGenerator<StreamEvent> {
  const res = await apiFetch('/api/run/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input, model_id: modelId ?? null, playbook_id: playbookId ?? null })
  });
  if (!res.ok) throw new Error(`Run stream failed: ${res.status}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = 'message';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        const payload = JSON.parse(line.slice(6));
        if (currentEvent === 'status') {
          yield { type: 'status', message: payload.message };
        } else if (currentEvent === 'result') {
          yield { type: 'result', data: payload };
        } else if (currentEvent === 'error') {
          yield { type: 'error', message: payload.message };
        }
        currentEvent = 'message';
      }
    }
  }
}

export interface SessionSummary {
  session_id: string;
  created_at: string;
  status: string;
  artifact_id: string | null;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const res = await apiFetch('/api/sessions');
  if (!res.ok) throw new Error(`Sessions fetch failed: ${res.status}`);
  const data = await res.json();
  return data.sessions;
}

export async function getSession(sessionId: string): Promise<RunResponse> {
  const res = await apiFetch(`/api/sessions/${sessionId}`);
  if (!res.ok) throw new Error(`Session fetch failed: ${res.status}`);
  return res.json();
}

export interface LineageVersion {
  version: string;
  parent: string | null;
  iteration: string | null;
  promoted_at: string;
  promoted_by: string;
  summary: string;
  promoted_variant_id: string | null;
  losing_variant_ids: string[];
  rollback_window_until: string | null;
  rolled_back: boolean;
}

export interface SkillLineage {
  skill_name: string;
  versions: LineageVersion[];
}

export async function getLineage(): Promise<SkillLineage[]> {
  const res = await apiFetch('/api/iteration/lineage');
  if (!res.ok) throw new Error(`Lineage fetch failed: ${res.status}`);
  const data = await res.json();
  return data.lineages;
}

// ── KB ──────────────────────────────────────────────────────────────────────

export interface KBStats {
  docs_total: number;
  chunks_total: number;
  open_conflicts: number;
  corrections_total: number;
}

export interface KBCorrection {
  id: string;
  chunk_id: string;
  corrected_by: string;
  reason: string;
  old_content: string;
  new_content: string;
  created_at: string;
}

export interface KBDoc {
  doc_id: string;
  title: string;
  language: string;
  chunk_count: number;
  namespace: string;
  ingested_at: string;
}

export interface KBHit {
  chunk_id: string;
  document_id: string;
  score: number;
  rank_vector: number | null;
  rank_fts: number | null;
  valid_from: string | null;
  has_open_conflicts: boolean;
  // A human overrode this chunk's content in place, so it is not what the
  // source file says. Marked because an overridden chunk otherwise looks
  // exactly like an ingested one (#159).
  has_correction: boolean;
  source_authority: string | null;
  content: string;
}

export interface KBConflict {
  id: string;
  conflict_type: string;
  similarity: number;
  status: string;
  doc_a_id: string;
  doc_b_id: string;
  doc_a_title: string;
  doc_b_title: string;
  doc_a_valid_from: string | null;
  doc_b_valid_from: string | null;
  chunk_a_content: string;
  chunk_b_content: string;
  detected_at: string;
  resolved_by: string | null;
  resolution_note: string | null;
}

export async function getKBStats(): Promise<KBStats> {
  const res = await apiFetch('/api/kb/stats');
  if (!res.ok) throw new Error(`KB stats fetch failed: ${res.status}`);
  return res.json();
}

export async function listKBDocs(): Promise<KBDoc[]> {
  const res = await apiFetch('/api/kb/docs');
  if (!res.ok) throw new Error(`KB docs fetch failed: ${res.status}`);
  const data = await res.json();
  return data.docs;
}

export async function listCorrections(chunkId?: string, limit = 50): Promise<KBCorrection[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (chunkId) params.set('chunk_id', chunkId);
  const res = await apiFetch(`/api/kb/corrections?${params}`);
  if (!res.ok) throw new Error(`Corrections fetch failed: ${res.status}`);
  const data = await res.json();
  return data.corrections;
}

export async function searchKB(query: string, topK = 5): Promise<KBHit[]> {
  const params = new URLSearchParams({ q: query, top_k: String(topK) });
  const res = await apiFetch(`/api/kb/search?${params}`);
  if (!res.ok) throw new Error(`KB search failed: ${res.status}`);
  const data = await res.json();
  return data.hits;
}

export type SourceAuthority = 'official' | 'vendor' | 'internal' | 'unverified';

export async function ingestKB(
  paths: string[],
  sourceAuthority: SourceAuthority = 'internal'
): Promise<{ docs_succeeded: number; docs_failed: number; chunks_total: number }> {
  const res = await apiFetch('/api/kb/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths, source_authority: sourceAuthority })
  });
  if (!res.ok) throw new Error(`KB ingest failed: ${res.status}`);
  return res.json();
}

export async function listConflicts(status = 'open'): Promise<KBConflict[]> {
  const params = new URLSearchParams({ status });
  const res = await apiFetch(`/api/kb/conflicts?${params}`);
  if (!res.ok) throw new Error(`Conflicts fetch failed: ${res.status}`);
  const data = await res.json();
  return data.conflicts;
}

export async function resolveConflict(
  conflictId: string,
  resolution: string,
  note = ''
): Promise<void> {
  const res = await apiFetch(`/api/kb/conflicts/${conflictId}/resolve`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resolution, note })
  });
  if (!res.ok) throw new Error(`Resolve failed: ${res.status}`);
}

export async function correctChunk(
  chunkId: string,
  newContent: string,
  reason: string
): Promise<{ corr_id: string; chunk_id: string; ok: boolean }> {
  const res = await apiFetch(`/api/kb/chunks/${encodeURIComponent(chunkId)}/correct`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_content: newContent, reason })
  });
  if (!res.ok) throw new Error(`Correct failed: ${res.status}`);
  return res.json();
}

// ── Vendor Doc ───────────────────────────────────────────────────────────────

export interface VendorDocSection {
  heading: string;
  content: string;
  citations: string[];
}

export interface VendorDoc {
  schema_version: string;
  doc_ref: string;
  template_id: string;
  title: string;
  sections: VendorDocSection[];
  scope_note?: string;
  citations: Citation[];
}

export interface DocGenRequest {
  topic: string;
  template_id: string;
  vendor_name: string;
  language: string;
  model_id?: string | null;
}

export async function generateVendorDoc(req: DocGenRequest): Promise<RunResponse & { result: VendorDoc }> {
  const res = await apiFetch('/api/doc/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req)
  });
  if (!res.ok) throw new Error(`Doc generate failed: ${res.status}`);
  return res.json();
}

export async function* generateVendorDocStream(req: DocGenRequest): AsyncGenerator<StreamEvent> {
  const res = await apiFetch('/api/doc/generate/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req)
  });
  if (!res.ok) throw new Error(`Doc generate stream failed: ${res.status}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = 'message';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        const payload = JSON.parse(line.slice(6));
        if (currentEvent === 'status') {
          yield { type: 'status', message: payload.message };
        } else if (currentEvent === 'result') {
          yield { type: 'result', data: payload };
        } else if (currentEvent === 'error') {
          yield { type: 'error', message: payload.message };
        }
        currentEvent = 'message';
      }
    }
  }
}

// ── Wiki ─────────────────────────────────────────────────────────────────────

export interface WikiIngestResult {
  page_id: string;
  slug: string;
  page_path: string;
  pages_created: number;
  pages_updated: number;
}

export interface WikiPage {
  slug: string;
  page_id: string;
}

export interface WikiLintIssue {
  id: string;
  issue_type: string;
  severity: string;
  summary: string;
  page_slug: string;
}

export async function wikiIngest(docId: string, model = 'qwen2.5:7b'): Promise<WikiIngestResult> {
  const res = await apiFetch('/api/wiki/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc_id: docId, model })
  });
  if (!res.ok) throw new Error(`Wiki ingest failed: ${res.status}`);
  return res.json();
}

export async function wikiQueryToPage(sessionId?: string): Promise<{ pages_created: number; pages: WikiPage[] }> {
  const res = await apiFetch('/api/wiki/query-to-page', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId ?? null })
  });
  if (!res.ok) throw new Error(`Wiki query-to-page failed: ${res.status}`);
  return res.json();
}

export async function wikiLint(): Promise<WikiLintIssue[]> {
  const res = await apiFetch('/api/wiki/lint');
  if (!res.ok) throw new Error(`Wiki lint failed: ${res.status}`);
  const data = await res.json();
  return data.issues;
}

export async function wikiPromote(slug: string): Promise<{ old_state: string; new_state: string; new_version: string; skipped: boolean; skip_reason: string }> {
  const res = await apiFetch(`/api/wiki/promote/${encodeURIComponent(slug)}`, { method: 'POST' });
  if (!res.ok) throw new Error(`Wiki promote failed: ${res.status}`);
  return res.json();
}

export interface WikiPageSummary {
  page_id: string;
  slug: string;
  kind: string;
  title: string;
  summary: string;
  lifecycle_state: string;
  language: string;
  tags: string[];
  updated_at: string;
}

export async function listWikiPages(): Promise<WikiPageSummary[]> {
  const res = await apiFetch('/api/wiki/pages');
  if (!res.ok) throw new Error(`Wiki pages fetch failed: ${res.status}`);
  const data = await res.json();
  return data.pages;
}

export interface WikiPageDetail extends WikiPageSummary {
  body: string;
  outbound_links: string[];
  derived_from: Record<string, unknown>;
  owner: string;
}

export async function getWikiPage(slug: string): Promise<WikiPageDetail> {
  const res = await apiFetch(`/api/wiki/pages/${encodeURIComponent(slug)}`);
  if (!res.ok) throw new Error(`Wiki page fetch failed: ${res.status}`);
  return res.json();
}

export interface VendorDocSummary {
  filename: string;
  doc_ref: string;
  template_id: string;
  title: string;
  scope_note: string | null;
  sections_count: number;
  citations_count: number;
}

export async function listVendorDocs(): Promise<VendorDocSummary[]> {
  const res = await apiFetch('/api/vendor-docs');
  if (!res.ok) throw new Error(`Vendor docs fetch failed: ${res.status}`);
  const data = await res.json();
  return data.docs;
}

export async function getVendorDoc(filename: string): Promise<VendorDoc> {
  const res = await apiFetch(`/api/vendor-docs/${encodeURIComponent(filename)}`);
  if (!res.ok) throw new Error(`Vendor doc fetch failed: ${res.status}`);
  return res.json();
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatCitation {
  chunk_id: string;
  document_id: string | null;
  source_path: string | null;
  heading_path: string[];
  snippet: string;
  // What the citation rests on. It never reorders results (ADR-0037), which is
  // exactly why it has to be visible — descriptive and invisible is absent.
  source_authority: string | null;
}

export interface ChatResult {
  content: string;
  citations: ChatCitation[];
  usage: { input_tokens: number; output_tokens: number; cost_usd: number };
  // The Consultation this turn was written into — pass it back on the next turn.
  consultation_id?: string | null;
}

export type ChatStreamEvent =
  | { type: 'status'; message: string }
  | { type: 'tool_call'; tool: string; query: string }
  | { type: 'tool_result'; tool: string; hits: number }
  | { type: 'skill_loaded'; skill: string }
  | { type: 'routing'; tier: string }
  // A Working set closed by the inactivity fallback owes its owner one notice,
  // or they misread why the assistant lost the thread (ADR-0032).
  | { type: 'notice'; message: string }
  | { type: 'result'; data: ChatResult }
  | { type: 'error'; message: string };

export async function* chatStream(
  messages: ChatMessage[],
  modelId?: string,
  deepThinking = false,
  consultationId?: string | null
): AsyncGenerator<ChatStreamEvent> {
  const res = await apiFetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages,
      model_id: modelId ?? null,
      deep_thinking: deepThinking,
      consultation_id: consultationId ?? null
    })
  });
  if (!res.ok) throw new Error(`Chat stream failed: ${res.status}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = 'message';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        const payload = JSON.parse(line.slice(6));
        if (currentEvent === 'status') {
          yield { type: 'status', message: payload.message };
        } else if (currentEvent === 'tool_call') {
          yield { type: 'tool_call', tool: payload.tool, query: payload.query };
        } else if (currentEvent === 'tool_result') {
          yield { type: 'tool_result', tool: payload.tool, hits: payload.hits };
        } else if (currentEvent === 'skill_loaded') {
          yield { type: 'skill_loaded', skill: payload.skill };
        } else if (currentEvent === 'routing') {
          yield { type: 'routing', tier: payload.tier };
        } else if (currentEvent === 'notice') {
          yield { type: 'notice', message: payload.message };
        } else if (currentEvent === 'result') {
          yield { type: 'result', data: payload };
        } else if (currentEvent === 'error') {
          yield { type: 'error', message: payload.message };
        }
        currentEvent = 'message';
      }
    }
  }
}

// ── Memory, Consultation, Working set ────────────────────────────────────────
//
// Memory is OpsPilot's second owned domain (ADR-0031/0035): standing facts about
// the environment that have no table of their own. An entry is *admitted* — a
// human writes the sentence and the reason — and the actor comes from the
// session, never from anything sent here.

export interface MemoryEntry {
  id: string;
  statement: string;
  reason: string;
  actor: string;
  created_at: string;
  review_after: string | null;
  scope: string | null;
  asset_id: string | null;
  source_ref: string | null;
  superseded_by: string | null;
  archived_at: string | null;
  is_live: boolean;
}

export async function listMemory(opts: {
  scope?: string;
  assetId?: string;
  includeRetired?: boolean;
} = {}): Promise<{ entries: MemoryEntry[]; includeRetiredIgnored: boolean }> {
  const q = new URLSearchParams();
  if (opts.scope) q.set('scope', opts.scope);
  if (opts.assetId) q.set('asset_id', opts.assetId);
  if (opts.includeRetired) q.set('include_retired', 'true');
  const res = await apiFetch(`/api/memory?${q}`);
  if (!res.ok) throw new Error(`List memory failed: ${res.status}`);
  const data = await res.json();
  // An anchored read is "what applies here", which retired entries are not.
  // Surfaced rather than dropped in silence.
  return { entries: data.entries, includeRetiredIgnored: !!data.include_retired_ignored };
}

export async function listMemoryScopes(): Promise<string[]> {
  const res = await apiFetch('/api/memory/scopes');
  if (!res.ok) throw new Error(`List scopes failed: ${res.status}`);
  return (await res.json()).scopes;
}

export async function admitMemory(body: {
  statement: string;
  reason: string;
  scope?: string | null;
  asset_id?: string | null;
  review_after?: string | null;
}): Promise<MemoryEntry> {
  const res = await apiFetch('/api/memory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `Admit failed: ${res.status}`);
  return res.json();
}

export async function supersedeMemory(
  id: string,
  body: { statement: string; reason: string }
): Promise<MemoryEntry> {
  const res = await apiFetch(`/api/memory/${id}/supersede`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `Supersede failed: ${res.status}`);
  return res.json();
}

export async function archiveMemory(id: string): Promise<void> {
  const res = await apiFetch(`/api/memory/${id}/archive`, { method: 'POST' });
  if (!res.ok) throw new Error(`Archive failed: ${res.status}`);
}

export interface WorkingSet {
  id: string;
  title: string;
  scope: string | null;
  asset_id: string | null;
  opened_at: string;
  last_active_at: string;
}

export async function getWorkingSet(): Promise<{
  working_set: WorkingSet | null;
  notice: string | null;
}> {
  const res = await apiFetch('/api/working-set');
  if (!res.ok) throw new Error(`Working set failed: ${res.status}`);
  return res.json();
}

export async function openWorkingSet(body: {
  title: string;
  scope?: string | null;
  asset_id?: string | null;
}): Promise<WorkingSet> {
  const res = await apiFetch('/api/working-set', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `Open failed: ${res.status}`);
  return res.json();
}

export async function closeWorkingSet(): Promise<void> {
  const res = await apiFetch('/api/working-set', { method: 'DELETE' });
  if (!res.ok) throw new Error(`Close failed: ${res.status}`);
}

export async function pinMessage(
  consultationId: string,
  messageId: string,
  body: { reason: string; statement?: string; scope?: string | null }
): Promise<MemoryEntry> {
  const res = await apiFetch(
    `/api/consultations/${consultationId}/messages/${messageId}/pin`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
  );
  if (!res.ok) throw new Error((await res.json()).detail ?? `Pin failed: ${res.status}`);
  return res.json();
}

export interface ConsultationMessage {
  id: string;
  seq: number;
  role: string;
  content: string;
  at: string;
}

export async function getConsultation(
  id: string
): Promise<{ id: string; title: string; messages: ConsultationMessage[] }> {
  const res = await apiFetch(`/api/consultations/${id}`);
  if (!res.ok) throw new Error(`Consultation failed: ${res.status}`);
  return res.json();
}

// ── Memory ↔ KB conflicts ────────────────────────────────────────────────────
//
// Detected when an answer is composed, not when an entry is written: at write
// time the human just confirmed the entry and would dismiss the prompt. The
// moment worth interrupting is months later, when the assistant holds both a
// recorded constraint and a document that contradicts it (ADR-0031/0035).

export interface MemoryConflict {
  id: string;
  memory_id: string;
  chunk_id: string;
  note: string;
  detected_in: string | null;
  detected_at: string;
  status: string;
  resolved_by: string | null;
  resolution_note: string | null;
}

// `merged` is deliberately absent: merging would mean editing a Memory entry in
// place, and an entry is superseded by appending.
export const CONFLICT_RESOLUTIONS = [
  { id: 'chunk_superseded', label: 'The constraint is right', hint: 'the document is stale or describes intended rather than actual behaviour' },
  { id: 'entry_superseded', label: 'The document is right', hint: 'replace the constraint by appending a new one' },
  { id: 'dismissed', label: 'They only appeared to disagree', hint: '' },
] as const;

export async function listMemoryConflicts(status = 'open'): Promise<MemoryConflict[]> {
  const res = await apiFetch(`/api/memory/conflicts?status=${encodeURIComponent(status)}`);
  if (!res.ok) throw new Error(`List conflicts failed: ${res.status}`);
  return (await res.json()).conflicts;
}

export async function resolveMemoryConflict(
  id: string,
  body: { resolution: string; note: string }
): Promise<void> {
  const res = await apiFetch(`/api/memory/conflicts/${id}/resolve`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `Resolve failed: ${res.status}`);
}

// ── Proposed actions (ADR-0028) ──────────────────────────────────────────────
//
// A Session proposes; a human executes. The first batch is read-only
// diagnostics — `intent` is a const in the artifact schema, so a mutation cannot
// be expressed at all.

export interface ProposedAction {
  ref: string;
  intent: string;
  type: string;
  command: string;
  target: string;
  why: string;
  expected_output?: string;
}

export interface ActionPreview {
  ref: string;
  command: string;
  target: string;
  why: string;
  approval_required: boolean;
  dry_run_status: string;
  dry_run_stdout: string;
}

export interface ActionOutcome {
  ref: string;
  executed_by: string;
  status: string;
  exit_code: number | null;
  stdout: string;
  stderr: string;
}

export async function listProposedActions(sessionId: string): Promise<ProposedAction[]> {
  const res = await apiFetch(`/api/sessions/${sessionId}/actions`);
  if (!res.ok) throw new Error(`List actions failed: ${res.status}`);
  return (await res.json()).actions;
}

export async function previewAction(sessionId: string, ref: string): Promise<ActionPreview> {
  const res = await apiFetch(`/api/sessions/${sessionId}/actions/${ref}/preview`, {
    method: 'POST'
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `Preview failed: ${res.status}`);
  return res.json();
}

export async function executeAction(sessionId: string, ref: string): Promise<ActionOutcome> {
  const res = await apiFetch(`/api/sessions/${sessionId}/actions/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref })
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `Execute failed: ${res.status}`);
  return res.json();
}

export async function escalateConsultation(
  consultationId: string,
  description: string
): Promise<{ session_id: string; artifact_id: string | null }> {
  const res = await apiFetch(`/api/consultations/${consultationId}/escalate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description })
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? `Escalate failed: ${res.status}`);
  return res.json();
}

// ── MCP ──────────────────────────────────────────────────────────────────────

export interface MCPServer {
  id: string;
  name: string;
  transport: string;
  enabled: boolean;
  tools_prefix: string;
  trust: string;
  tools: { name: string; description: string }[];
}

export async function listMCPServers(): Promise<MCPServer[]> {
  const res = await apiFetch('/api/mcp/servers');
  if (!res.ok) throw new Error(`MCP servers fetch failed: ${res.status}`);
  const data = await res.json();
  return data.servers;
}

// ── Inventory (ADR-0017) ───────────────────────────────────────────────────

export const ASSET_STATUSES = [
  'requested', 'ordered', 'shipped', 'received',
  'in_stock', 'deployed', 'in_repair', 'retired',
] as const;

export interface Asset {
  asset_id: string;
  asset_tag: string;
  category: string;
  brand_model: string;
  serial_number: string;
  specs: string;
  notes: string;
  work_item_ref: string;
  pr_number: string;
  order_number: string;
  tracking_number: string;
  vendor: string;
  cost: string;
  status: string;
  handler: string;
  assignee: string;
  location: string;
  warranty_until: string;
  procurement_id: string;
  created_at: string;
  updated_at: string;
}

export interface AssetEvent {
  event_id: number;
  ts: string;
  actor: string;
  change: string;
  note: string;
}

export interface AssetDetail extends Asset {
  events: AssetEvent[];
}

// Editable fields only (no ids/timestamps).
export type AssetFields = Omit<Asset, 'asset_id' | 'procurement_id' | 'created_at' | 'updated_at'>;

async function assetError(res: Response, verb: string): Promise<never> {
  let detail = '';
  try { detail = (await res.json()).detail ?? ''; } catch { /* non-JSON body */ }
  throw new Error(detail || `${verb} failed: ${res.status}`);
}

export async function listAssets(
  status = '',
  assignee = '',
  q = '',
  expiringDays = ''
): Promise<Asset[]> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (assignee) params.set('assignee', assignee);
  if (q) params.set('q', q);
  if (expiringDays) params.set('expiring_days', expiringDays);
  const qs = params.toString();
  const res = await apiFetch(`/api/inventory${qs ? `?${qs}` : ''}`);
  if (!res.ok) await assetError(res, 'Asset list');
  return (await res.json()).assets;
}

export async function getAsset(assetId: string): Promise<AssetDetail> {
  const res = await apiFetch(`/api/inventory/${encodeURIComponent(assetId)}`);
  if (!res.ok) await assetError(res, 'Asset fetch');
  return res.json();
}

export async function createAsset(fields: Partial<AssetFields>): Promise<Asset> {
  const res = await apiFetch('/api/inventory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields)
  });
  if (!res.ok) await assetError(res, 'Asset create');
  return res.json();
}

export async function updateAsset(assetId: string, changes: Partial<AssetFields>): Promise<Asset> {
  const res = await apiFetch(`/api/inventory/${encodeURIComponent(assetId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes)
  });
  if (!res.ok) await assetError(res, 'Asset update');
  return res.json();
}

export async function deleteAsset(assetId: string): Promise<void> {
  const res = await apiFetch(`/api/inventory/${encodeURIComponent(assetId)}`, { method: 'DELETE' });
  if (!res.ok) await assetError(res, 'Asset delete');
}

// ── Procurements (#87) ─────────────────────────────────────────────────────

export interface Procurement {
  procurement_id: string;
  pr_number: string;
  order_number: string;
  tracking_number: string;
  vendor: string;
  cost: string;
  created_at: string;
  updated_at: string;
  member_count: number;
}

export interface ProcurementDetail extends Procurement {
  members: Asset[];
}

export type ProcurementFields = Pick<
  Procurement, 'pr_number' | 'order_number' | 'tracking_number' | 'vendor' | 'cost'
>;

export async function createProcurement(assetIds: string[]): Promise<Procurement> {
  const res = await apiFetch('/api/inventory/procurements', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asset_ids: assetIds })
  });
  if (!res.ok) await assetError(res, 'Procurement create');
  return res.json();
}

export async function getProcurement(procurementId: string): Promise<ProcurementDetail> {
  const res = await apiFetch(`/api/inventory/procurements/${encodeURIComponent(procurementId)}`);
  if (!res.ok) await assetError(res, 'Procurement fetch');
  return res.json();
}

export async function updateProcurement(
  procurementId: string,
  changes: Partial<ProcurementFields>
): Promise<Procurement> {
  const res = await apiFetch(`/api/inventory/procurements/${encodeURIComponent(procurementId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes)
  });
  if (!res.ok) await assetError(res, 'Procurement update');
  return res.json();
}

export async function deleteProcurement(procurementId: string): Promise<void> {
  const res = await apiFetch(`/api/inventory/procurements/${encodeURIComponent(procurementId)}`, {
    method: 'DELETE'
  });
  if (!res.ok) await assetError(res, 'Procurement delete');
}

// ── Auth (ADR-0020) ─────────────────────────────────────────────────────────

export interface Me {
  name: string;
  role: 'viewer' | 'operator' | 'admin';
  is_service: boolean;
}

// Nav item → minimum role required to see it. Absent = viewer.
export const MODULE_MIN_ROLE: Record<string, Me['role']> = {
  run: 'operator',
  chat: 'operator',
  memory: 'viewer',
  inventory: 'viewer',
  kb: 'viewer',
  wiki: 'viewer',
  vendordoc: 'operator',
  mcp: 'admin',
  iteration: 'operator',
  admin: 'admin',
  guide: 'viewer',
};

const ROLE_RANK: Record<Me['role'], number> = { viewer: 0, operator: 1, admin: 2 };

export function roleAtLeast(role: Me['role'], required: Me['role']): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[required];
}

export async function getMe(): Promise<Me | null> {
  const res = await apiFetch('/api/auth/me');
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`auth check failed: ${res.status}`);
  return res.json();
}

export async function login(username: string, password: string, source = 'local'): Promise<Me> {
  const res = await apiFetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, source })
  });
  if (res.status === 401) throw new Error('Invalid username or password');
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  return res.json();
}

export async function logout(): Promise<void> {
  await apiFetch('/api/auth/logout', { method: 'POST' });
}

export async function oidcEnabled(): Promise<boolean> {
  try {
    const res = await apiFetch('/api/auth/oidc/enabled');
    return res.ok ? (await res.json()).enabled === true : false;
  } catch {
    return false;
  }
}

// ── Admin module (ADR-0020) ─────────────────────────────────────────────────

export interface AdminUser {
  username: string;
  role: 'viewer' | 'operator' | 'admin';
  auth_source: string;
  enabled: boolean;
}

export interface GroupRoleMapping {
  source: string;
  group_name: string;
  role: 'viewer' | 'operator' | 'admin';
}

export interface AuthSourceStatus {
  source: string;
  configured: boolean;
}

export interface LoginEvent {
  ts: string;
  username: string;
  source: string;
  outcome: string;
}

async function adminError(res: Response, verb: string): Promise<never> {
  let detail = '';
  try { detail = (await res.json()).detail ?? ''; } catch { /* non-JSON */ }
  throw new Error(detail || `${verb} failed: ${res.status}`);
}

export async function adminListUsers(): Promise<AdminUser[]> {
  const res = await apiFetch('/api/admin/users');
  if (!res.ok) await adminError(res, 'List users');
  return (await res.json()).users;
}

export async function adminCreateUser(username: string, password: string, role: string): Promise<AdminUser> {
  const res = await apiFetch('/api/admin/users', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role })
  });
  if (!res.ok) await adminError(res, 'Create user');
  return res.json();
}

export async function adminSetRole(username: string, role: string): Promise<AdminUser> {
  const res = await apiFetch(`/api/admin/users/${encodeURIComponent(username)}/role`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role })
  });
  if (!res.ok) await adminError(res, 'Set role');
  return res.json();
}

export async function adminSetEnabled(username: string, enabled: boolean): Promise<AdminUser> {
  const res = await apiFetch(`/api/admin/users/${encodeURIComponent(username)}/enabled`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled })
  });
  if (!res.ok) await adminError(res, 'Set enabled');
  return res.json();
}

export async function adminListGroupRoles(): Promise<GroupRoleMapping[]> {
  const res = await apiFetch('/api/admin/group-roles');
  if (!res.ok) await adminError(res, 'List mappings');
  return (await res.json()).mappings;
}

export async function adminSetGroupRole(m: GroupRoleMapping): Promise<void> {
  const res = await apiFetch('/api/admin/group-roles', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(m)
  });
  if (!res.ok) await adminError(res, 'Set mapping');
}

export async function adminDeleteGroupRole(source: string, group: string): Promise<void> {
  const res = await apiFetch(`/api/admin/group-roles/${encodeURIComponent(source)}/${encodeURIComponent(group)}`, { method: 'DELETE' });
  if (!res.ok) await adminError(res, 'Delete mapping');
}

export async function adminAuthStatus(): Promise<AuthSourceStatus[]> {
  const res = await apiFetch('/api/admin/auth-status');
  if (!res.ok) await adminError(res, 'Auth status');
  return (await res.json()).sources;
}

export async function adminTestConnection(source: string): Promise<{ ok: boolean; detail: string }> {
  const res = await apiFetch(`/api/admin/auth-status/${encodeURIComponent(source)}/test`, { method: 'POST' });
  if (!res.ok) await adminError(res, 'Test connection');
  return res.json();
}

export async function adminLoginAudit(): Promise<LoginEvent[]> {
  const res = await apiFetch('/api/admin/login-audit');
  if (!res.ok) await adminError(res, 'Login audit');
  return (await res.json()).events;
}

// ── Admin: LLM providers + default model (ADR-0020) ─────────────────────────

export interface ProviderStatus {
  id: string;
  label: string;
  env_var: string;
  configured: boolean;
}

export async function adminListProviders(): Promise<ProviderStatus[]> {
  const res = await apiFetch('/api/admin/providers');
  if (!res.ok) await adminError(res, 'List providers');
  return (await res.json()).providers;
}

export async function adminTestProvider(id: string): Promise<{ ok: boolean; detail: string }> {
  const res = await apiFetch(`/api/admin/providers/${encodeURIComponent(id)}/test`, { method: 'POST' });
  if (!res.ok) await adminError(res, 'Test provider');
  return res.json();
}

// ── Admin: MCP servers (remote add/edit; stdio read-only, ADR-0024) ──────────

export interface AdminMcpServer {
  id: string;
  name: string;
  transport: string;
  url: string | null;
  tools_prefix: string;
  enabled: boolean;
  trust: string;
  read_only: boolean;
}

export interface RemoteMcpUpsert {
  name: string;
  transport: 'http' | 'sse';
  url: string;
  tools_prefix: string;
  trust: string;
  enabled: boolean;
  description: string;
  auth_type: 'none' | 'api_key_header' | 'bearer_env' | 'oauth2';
  auth_env: string | null;
  auth_header: string | null;
}

export async function adminListMcpServers(): Promise<AdminMcpServer[]> {
  const res = await apiFetch('/api/admin/mcp/servers');
  if (!res.ok) await adminError(res, 'List MCP servers');
  return (await res.json()).servers;
}

export async function adminSaveMcpServer(id: string, payload: RemoteMcpUpsert): Promise<AdminMcpServer[]> {
  const res = await apiFetch(`/api/admin/mcp/servers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) await adminError(res, 'Save MCP server');
  return (await res.json()).servers;
}

export async function adminDeleteMcpServer(id: string): Promise<void> {
  const res = await apiFetch(`/api/admin/mcp/servers/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!res.ok) await adminError(res, 'Delete MCP server');
}

// ── Admin: runtime skills (edits agent_skills/<id>/SKILL.md, ADR-0022) ───────

export interface SkillSummary {
  id: string;
  name: string;
  trigger: string;
  trust: string;
  allowed_tools: string[];
}

export interface SkillDetail extends SkillSummary {
  body: string;
}

export async function adminListSkills(): Promise<SkillSummary[]> {
  const res = await apiFetch('/api/admin/skills');
  if (!res.ok) await adminError(res, 'List skills');
  return (await res.json()).skills;
}

export async function adminGetSkill(id: string): Promise<SkillDetail> {
  const res = await apiFetch(`/api/admin/skills/${encodeURIComponent(id)}`);
  if (!res.ok) await adminError(res, 'Get skill');
  return res.json();
}

export async function adminSaveSkill(
  id: string,
  payload: { name: string; trigger: string; body: string; allowed_tools: string[]; trust: string }
): Promise<SkillDetail> {
  const res = await apiFetch(`/api/admin/skills/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) await adminError(res, 'Save skill');
  return res.json();
}

export async function adminDraftSkill(description: string): Promise<SkillDetail> {
  const res = await apiFetch('/api/admin/skills/draft', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description })
  });
  if (!res.ok) await adminError(res, 'Draft skill');
  return res.json();
}

// ── Admin: playbook model list (edits playbook.yaml in place, ADR-0021) ──────

export interface PlaybookModelEntry {
  provider_id: string;
  kind: string;
  name: string;
  version: string;
  params: Record<string, unknown>;
  primary: boolean;
}

export async function adminGetPlaybookModels(): Promise<{ playbook_id: string; models: PlaybookModelEntry[] }> {
  const res = await apiFetch('/api/admin/playbook-models');
  if (!res.ok) await adminError(res, 'Get playbook models');
  return res.json();
}

export async function adminSetPlaybookModels(
  models: PlaybookModelEntry[]
): Promise<{ playbook_id: string; models: PlaybookModelEntry[] }> {
  const res = await apiFetch('/api/admin/playbook-models', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ models })
  });
  if (!res.ok) await adminError(res, 'Save playbook models');
  return res.json();
}

export interface ModelTiers {
  cheap_model_id: string | null;
  thinking_model_id: string | null;
}

export async function adminGetModelTiers(): Promise<ModelTiers> {
  const res = await apiFetch('/api/admin/model-tiers');
  if (!res.ok) await adminError(res, 'Get model tiers');
  return res.json();
}

export async function adminSetModelTiers(tiers: ModelTiers): Promise<ModelTiers> {
  const res = await apiFetch('/api/admin/model-tiers', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(tiers)
  });
  if (!res.ok) await adminError(res, 'Set model tiers');
  return res.json();
}

export async function adminGetDefaultModel(): Promise<string | null> {
  const res = await apiFetch('/api/admin/default-model');
  if (!res.ok) await adminError(res, 'Get default model');
  return (await res.json()).model_id;
}

export async function adminSetDefaultModel(modelId: string | null): Promise<void> {
  const res = await apiFetch('/api/admin/default-model', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId })
  });
  if (!res.ok) await adminError(res, 'Set default model');
}

// ── Admin: system logs (ADR-0020) ───────────────────────────────────────────

export interface LogRecord {
  ts: string;
  level: string;
  logger: string;
  msg: string;
  request_id: string | null;
}

export async function adminSystemLogs(level = '', limit = 200): Promise<{ records: LogRecord[]; available: boolean }> {
  const params = new URLSearchParams();
  if (level) params.set('level', level);
  params.set('limit', String(limit));
  const res = await apiFetch(`/api/admin/logs?${params.toString()}`);
  if (!res.ok) await adminError(res, 'System logs');
  return res.json();
}
