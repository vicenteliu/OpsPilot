export interface RunRequest {
  input: Record<string, unknown>;
}

export interface RunResponse {
  session_id: string;
  artifact_id: string | null;
  schema_valid: boolean;
  result: TicketSummary;
  error: string | null;
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

export async function getConfig(): Promise<ConfigResponse> {
  const res = await fetch('/api/config');
  if (!res.ok) throw new Error(`Config fetch failed: ${res.status}`);
  return res.json();
}

export async function runTicket(input: Record<string, unknown>): Promise<RunResponse> {
  const res = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input })
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
