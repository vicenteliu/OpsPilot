export interface RunRequest {
  input: Record<string, unknown>;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface RunResponse {
  session_id: string;
  artifact_id: string | null;
  schema_valid: boolean;
  result: TicketSummary;
  error: string | null;
  usage: TokenUsage | null;
}

export interface TicketSummary {
  schema_version: string;
  ticket_ref: string;
  summary: string;
  symptoms: string[];
  scope: string;
  tried_steps: string[];
  missing_fields: string[];
  next_actions: NextAction[];
  severity_suggested: string;
  escalation_hint?: string;
  citations: Citation[];
}

export interface NextAction {
  action: string;
  rationale: string;
  citations: string[];
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
  const res = await fetch('/api/config');
  if (!res.ok) throw new Error(`Config fetch failed: ${res.status}`);
  return res.json();
}

export async function getModels(): Promise<ModelsResponse> {
  const res = await fetch('/api/models');
  if (!res.ok) throw new Error(`Models fetch failed: ${res.status}`);
  return res.json();
}

export async function runTicket(
  input: Record<string, unknown>,
  modelId?: string
): Promise<RunResponse> {
  const res = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input, model_id: modelId ?? null })
  });
  if (!res.ok) throw new Error(`Run failed: ${res.status}`);
  return res.json();
}

export interface SessionSummary {
  session_id: string;
  created_at: string;
  status: string;
  artifact_id: string | null;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const res = await fetch('/api/sessions');
  if (!res.ok) throw new Error(`Sessions fetch failed: ${res.status}`);
  const data = await res.json();
  return data.sessions;
}

export async function getSession(sessionId: string): Promise<RunResponse> {
  const res = await fetch(`/api/sessions/${sessionId}`);
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
  const res = await fetch('/api/iteration/lineage');
  if (!res.ok) throw new Error(`Lineage fetch failed: ${res.status}`);
  const data = await res.json();
  return data.lineages;
}

// ── KB ──────────────────────────────────────────────────────────────────────

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

export async function listKBDocs(): Promise<KBDoc[]> {
  const res = await fetch('/api/kb/docs');
  if (!res.ok) throw new Error(`KB docs fetch failed: ${res.status}`);
  const data = await res.json();
  return data.docs;
}

export async function searchKB(query: string, topK = 5): Promise<KBHit[]> {
  const params = new URLSearchParams({ q: query, top_k: String(topK) });
  const res = await fetch(`/api/kb/search?${params}`);
  if (!res.ok) throw new Error(`KB search failed: ${res.status}`);
  const data = await res.json();
  return data.hits;
}

export async function ingestKB(paths: string[]): Promise<{ docs_succeeded: number; docs_failed: number; chunks_total: number }> {
  const res = await fetch('/api/kb/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths })
  });
  if (!res.ok) throw new Error(`KB ingest failed: ${res.status}`);
  return res.json();
}

export async function listConflicts(status = 'open'): Promise<KBConflict[]> {
  const params = new URLSearchParams({ status });
  const res = await fetch(`/api/kb/conflicts?${params}`);
  if (!res.ok) throw new Error(`Conflicts fetch failed: ${res.status}`);
  const data = await res.json();
  return data.conflicts;
}

export async function resolveConflict(
  conflictId: string,
  resolution: string,
  resolvedBy = 'web-user',
  note = ''
): Promise<void> {
  const res = await fetch(`/api/kb/conflicts/${conflictId}/resolve`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resolution, resolved_by: resolvedBy, note })
  });
  if (!res.ok) throw new Error(`Resolve failed: ${res.status}`);
}

export async function correctChunk(
  chunkId: string,
  newContent: string,
  reason: string,
  correctedBy = 'web-user'
): Promise<{ corr_id: string; chunk_id: string; ok: boolean }> {
  const res = await fetch(`/api/kb/chunks/${encodeURIComponent(chunkId)}/correct`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_content: newContent, reason, corrected_by: correctedBy })
  });
  if (!res.ok) throw new Error(`Correct failed: ${res.status}`);
  return res.json();
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
  const res = await fetch('/api/wiki/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc_id: docId, model })
  });
  if (!res.ok) throw new Error(`Wiki ingest failed: ${res.status}`);
  return res.json();
}

export async function wikiQueryToPage(sessionId?: string): Promise<{ pages_created: number; pages: WikiPage[] }> {
  const res = await fetch('/api/wiki/query-to-page', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId ?? null })
  });
  if (!res.ok) throw new Error(`Wiki query-to-page failed: ${res.status}`);
  return res.json();
}

export async function wikiLint(): Promise<WikiLintIssue[]> {
  const res = await fetch('/api/wiki/lint');
  if (!res.ok) throw new Error(`Wiki lint failed: ${res.status}`);
  const data = await res.json();
  return data.issues;
}

export async function wikiPromote(slug: string): Promise<{ old_state: string; new_state: string; new_version: string; skipped: boolean; skip_reason: string }> {
  const res = await fetch(`/api/wiki/promote/${encodeURIComponent(slug)}`, { method: 'POST' });
  if (!res.ok) throw new Error(`Wiki promote failed: ${res.status}`);
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
  const res = await fetch('/api/mcp/servers');
  if (!res.ok) throw new Error(`MCP servers fetch failed: ${res.status}`);
  const data = await res.json();
  return data.servers;
}
