<script lang="ts">
  import '../app.css';
  import { getConfig, getModels, runTicket, listSessions, getSession, getLineage, type RunResponse, type NextAction, type SessionSummary, type ModelOption, type SkillLineage } from '$lib/api';

  // --- State ---
  let modelRef = $state<string | null>(null);
  let modules = $state<Record<string, boolean>>({ run: true, history: true });
  let availableModels = $state<ModelOption[]>([]);
  let selectedModelId = $state<string>('');
  let modelsLoaded = $state<boolean>(false);
  let ticketInput = $state<string>(JSON.stringify(
    {
      "ticket_id": "TKT-DEMO-001",
      "channel": "email",
      "submitted_at": "2026-05-01T09:00:00Z",
      "submitter_role": "end_user",
      "subject": "无法连接 VPN",
      "body": "从今早 09:00 起无法连接公司 VPN，错误信息：Authentication failed。已尝试重启客户端，问题依旧。"
    },
    null,
    2
  ));
  let loading = $state<boolean>(false);
  let result = $state<RunResponse | null>(null);
  let fetchError = $state<string | null>(null);
  let sessions = $state<SessionSummary[]>([]);
  let historyLoading = $state<boolean>(false);
  let expanded = $state<Record<string, boolean>>({});
  let sessionCache = $state<Record<string, RunResponse>>({});
  let lineages = $state<SkillLineage[]>([]);
  let lineageLoading = $state<boolean>(false);
  let lineageError = $state<string | null>(null);
  let expandedSkill = $state<Record<string, boolean>>({});

  // --- Derived ---
  let summary = $derived(result?.result ?? null);
  let runError = $derived(result?.error ?? null);

  // $effect replaces onMount: onMount is unreliable in Svelte 5 runes mode.
  let _initialized = false;
  $effect(() => {
    if (_initialized) return;
    _initialized = true;
    (async () => {
      try {
        const cfg = await getConfig();
        modelRef = cfg.active_model_ref;
        modules = cfg.modules;
      } catch {
        modelRef = 'unknown';
      }
      try {
        const modelsRes = await getModels();
        availableModels = modelsRes.models;
        selectedModelId = modelsRes.default_id;
      } catch {
        // models unavailable; badge shows modelRef
      } finally {
        modelsLoaded = true;
      }
      if (modules.history) await refreshHistory();
      if (modules.iteration !== false) await refreshLineage();
    })();
  });

  // --- Handlers ---
  async function refreshLineage() {
    lineageLoading = true;
    lineageError = null;
    try {
      lineages = await getLineage();
    } catch (e) {
      lineageError = e instanceof Error ? e.message : String(e);
      lineages = [];
    } finally {
      lineageLoading = false;
    }
  }

  function toggleSkill(name: string) {
    expandedSkill = { ...expandedSkill, [name]: !expandedSkill[name] };
  }

  async function refreshHistory() {
    historyLoading = true;
    try {
      sessions = await listSessions();
    } catch {
      sessions = [];
    } finally {
      historyLoading = false;
    }
  }

  async function toggleSession(sessionId: string) {
    if (expanded[sessionId]) {
      expanded = { ...expanded, [sessionId]: false };
      return;
    }
    if (!sessionCache[sessionId]) {
      try {
        const res = await getSession(sessionId);
        sessionCache = { ...sessionCache, [sessionId]: res };
      } catch {
        return;
      }
    }
    expanded = { ...expanded, [sessionId]: true };
  }

  async function handleRun() {
    fetchError = null;
    result = null;
    let input: Record<string, unknown>;
    try {
      input = JSON.parse(ticketInput);
    } catch {
      fetchError = 'Invalid JSON in ticket input.';
      return;
    }
    loading = true;
    try {
      result = await runTicket(input, selectedModelId || undefined);
      if (modules.history) await refreshHistory();
    } catch (e) {
      fetchError = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function copyText(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  function formatNextActions(actions: NextAction[]): string {
    return actions
      .map((a, i) => `${i + 1}. **${a.action}**\n   ${a.rationale}`)
      .join('\n\n');
  }
</script>

<div class="app">
  <!-- Header -->
  <header>
    <h1>OpsPilot</h1>
    {#if !modelsLoaded}
      <span class="model-ref">Loading...</span>
    {:else if availableModels.length > 1}
      <select class="model-select" bind:value={selectedModelId} disabled={loading}>
        {#each availableModels as m}
          <option value={m.id}>{m.label}</option>
        {/each}
      </select>
    {:else}
      <span class="model-ref" title="Active model">{selectedModelId || modelRef || '—'}</span>
    {/if}
  </header>

  <!-- Ticket input section -->
  <main>
    <section class="input-section">
      <h2>Ticket Input</h2>
      <textarea
        rows={12}
        bind:value={ticketInput}
        placeholder="Paste ticket JSON here..."
        disabled={loading}
      ></textarea>
      <div class="run-row">
        <button class="btn-run" onclick={handleRun} disabled={loading}>
          {#if loading}
            <span class="spinner"></span> Running...
          {:else}
            Run
          {/if}
        </button>
        {#if result?.usage}
          <span class="usage-badge">
            ↑ {result.usage.input_tokens.toLocaleString()} / ↓ {result.usage.output_tokens.toLocaleString()} tokens
            {#if result.usage.cost_usd > 0}
              · ${result.usage.cost_usd.toFixed(4)}
            {/if}
          </span>
        {/if}
      </div>
    </section>

    <!-- Error display -->
    {#if fetchError}
      <div class="error-banner">
        <strong>Error:</strong> {fetchError}
      </div>
    {/if}

    {#if runError}
      <div class="error-banner">
        <strong>Run error:</strong> {runError}
      </div>
    {/if}

    <!-- Output cards -->
    {#snippet outputCards(s: TicketSummary)}
      <section class="cards">
        <div class="card">
          <div class="card-header">
            <h3>Summary</h3>
            <button class="btn-copy" onclick={() => copyText(s.summary ?? '')}>Copy</button>
          </div>
          <p>{s.summary}</p>
        </div>
        <div class="card">
          <div class="card-header">
            <h3>Symptoms</h3>
            <button class="btn-copy" onclick={() => copyText((s.symptoms ?? []).join('\n'))}>Copy</button>
          </div>
          <ul>
            {#each s.symptoms as symptom}
              <li>{symptom}</li>
            {/each}
          </ul>
        </div>
        <div class="card">
          <div class="card-header">
            <h3>Next Actions</h3>
            <button class="btn-copy" onclick={() => copyText(formatNextActions(s.next_actions ?? []))}>Copy</button>
          </div>
          <ol>
            {#each s.next_actions as action}
              <li>
                <strong>{action.action}</strong>
                <p class="rationale">{action.rationale}</p>
              </li>
            {/each}
          </ol>
        </div>
        <div class="card">
          <div class="card-header">
            <h3>Severity</h3>
            <button class="btn-copy" onclick={() => copyText(s.severity_suggested + (s.escalation_hint ? '\n' + s.escalation_hint : ''))}>Copy</button>
          </div>
          <span class="severity-badge">{s.severity_suggested}</span>
          {#if s.escalation_hint}
            <p class="escalation">{s.escalation_hint}</p>
          {/if}
        </div>
      </section>
    {/snippet}

    {#if summary}
      {@render outputCards(summary as TicketSummary)}
    {/if}
    <!-- History module -->
    {#if modules.history}
      <section class="history-section">
        <div class="history-header">
          <h2>History</h2>
          <button class="btn-refresh" onclick={refreshHistory} disabled={historyLoading}>
            {historyLoading ? '...' : '↻'}
          </button>
        </div>
        {#if sessions.length === 0}
          <p class="history-empty">No sessions yet.</p>
        {:else}
          <table class="history-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {#each sessions as s}
                <tr>
                  <td class="col-time">{new Date(s.created_at).toLocaleString()}</td>
                  <td>
                    <span class="status-badge status-{s.status}">{s.status}</span>
                  </td>
                  <td>
                    <button class="btn-view" onclick={() => toggleSession(s.session_id)}>
                      {expanded[s.session_id] ? '▲ Hide' : '▼ View'}
                    </button>
                  </td>
                </tr>
                {#if expanded[s.session_id] && sessionCache[s.session_id]}
                  <tr class="expanded-row">
                    <td colspan="3">
                      {@render outputCards(sessionCache[s.session_id].result as TicketSummary)}
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        {/if}
      </section>
    {/if}

    <!-- Iteration module -->
    {#if modules.iteration !== false}
      <section class="iteration-section">
        <div class="iteration-header">
          <h2>Iteration History</h2>
          <button class="btn-refresh" onclick={refreshLineage} disabled={lineageLoading}>
            {lineageLoading ? '...' : '↻'}
          </button>
        </div>

        {#if lineageError}
          <p class="iteration-error">{lineageError}</p>
        {:else if lineages.length === 0 && !lineageLoading}
          <p class="iteration-empty">No skill lineage found. Run <code>opspilot iteration promote</code> to create one.</p>
        {:else}
          {#each lineages as skill}
            <div class="skill-block">
              <button class="skill-toggle" onclick={() => toggleSkill(skill.skill_name)}>
                <span class="skill-name">{skill.skill_name}</span>
                <span class="skill-count">{skill.versions.length} version{skill.versions.length !== 1 ? 's' : ''}</span>
                <span class="toggle-arrow">{expandedSkill[skill.skill_name] ? '▲' : '▼'}</span>
              </button>
              {#if expandedSkill[skill.skill_name]}
                <div class="lineage-tree">
                  {#each [...skill.versions].reverse() as v, i}
                    <div class="lineage-row {v.rolled_back ? 'rolled-back' : ''}">
                      <div class="lineage-version">
                        <span class="version-badge {v.rolled_back ? 'rolled-back-badge' : ''}">v{v.version}</span>
                        {#if v.rolled_back}<span class="rollback-flag">rolled back</span>{/if}
                      </div>
                      <div class="lineage-meta">
                        <span class="lineage-date">{v.promoted_at.slice(0, 10)}</span>
                        {#if v.iteration}
                          <span class="itr-id" title={v.iteration}>{v.iteration.slice(0, 16)}…</span>
                        {:else}
                          <span class="itr-id dim">manual</span>
                        {/if}
                        {#if v.promoted_variant_id}
                          <span class="variant-id" title={v.promoted_variant_id}>↑ {v.promoted_variant_id}</span>
                        {/if}
                      </div>
                      <div class="lineage-summary">{v.summary}</div>
                      {#if i < skill.versions.length - 1}
                        <div class="lineage-connector">│</div>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        {/if}
      </section>
    {/if}
  </main>
</div>

<style>
  .app {
    max-width: 900px;
    margin: 0 auto;
    padding: 1.5rem;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.5rem;
    border-bottom: 2px solid #ddd;
    padding-bottom: 0.75rem;
  }

  header h1 {
    font-size: 1.8rem;
    color: #1a56db;
  }

  .model-ref {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.8rem;
    background: #e8f4fd;
    color: #1a56db;
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    border: 1px solid #bee3f8;
  }

  .model-select {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.8rem;
    background: #e8f4fd;
    color: #1a56db;
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    border: 1px solid #bee3f8;
    cursor: pointer;
  }

  .model-select:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .input-section {
    margin-bottom: 1.5rem;
  }

  .input-section h2 {
    margin-bottom: 0.5rem;
    font-size: 1.1rem;
    color: #444;
  }

  textarea {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid #ccc;
    border-radius: 6px;
    background: #fff;
    margin-bottom: 0.75rem;
  }

  .run-row {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .btn-run {
    padding: 0.6rem 1.5rem;
    background: #1a56db;
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 1rem;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }

  .btn-run:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .usage-badge {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.78rem;
    color: #64748b;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    padding: 0.2rem 0.6rem;
    white-space: nowrap;
  }

  .spinner {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255, 255, 255, 0.4);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .error-banner {
    background: #fee2e2;
    color: #991b1b;
    border: 1px solid #fca5a5;
    border-radius: 6px;
    padding: 0.75rem 1rem;
    margin-bottom: 1rem;
  }

  .cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }

  @media (max-width: 640px) {
    .cards {
      grid-template-columns: 1fr;
    }
  }

  .card {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 1rem;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
  }

  .card-header h3 {
    font-size: 0.95rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b;
  }

  .btn-copy {
    font-size: 0.75rem;
    padding: 0.2rem 0.6rem;
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    color: #475569;
  }

  .btn-copy:hover {
    background: #e2e8f0;
  }

  .card ul,
  .card ol {
    margin: 0;
    padding-left: 1.25rem;
  }

  .card li {
    margin-bottom: 0.4rem;
    font-size: 0.95rem;
  }

  .rationale {
    margin: 0.2rem 0 0.6rem;
    color: #64748b;
    font-size: 0.88rem;
  }

  .severity-badge {
    display: inline-block;
    padding: 0.3rem 0.8rem;
    border-radius: 9999px;
    font-weight: 700;
    font-size: 1.1rem;
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fcd34d;
  }

  .escalation {
    margin-top: 0.5rem;
    font-size: 0.9rem;
    color: #b45309;
  }

  .history-section {
    margin-top: 2rem;
    border-top: 1px solid #e2e8f0;
    padding-top: 1.5rem;
  }

  .history-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .history-header h2 {
    font-size: 1.1rem;
    color: #444;
    margin: 0;
  }

  .btn-refresh {
    background: none;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 0.15rem 0.5rem;
    font-size: 1rem;
    color: #64748b;
    line-height: 1;
  }

  .btn-refresh:hover {
    background: #f1f5f9;
  }

  .history-empty {
    color: #94a3b8;
    font-size: 0.9rem;
  }

  .history-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }

  .history-table th {
    text-align: left;
    padding: 0.4rem 0.75rem;
    color: #64748b;
    font-weight: 600;
    border-bottom: 1px solid #e2e8f0;
  }

  .history-table td {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid #f1f5f9;
    vertical-align: middle;
  }

  .col-time {
    color: #475569;
    white-space: nowrap;
  }

  .status-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .status-archived {
    background: #dcfce7;
    color: #15803d;
  }

  .status-aborted {
    background: #fee2e2;
    color: #b91c1c;
  }

  .status-active {
    background: #fef9c3;
    color: #854d0e;
  }

  .btn-view {
    font-size: 0.8rem;
    padding: 0.2rem 0.6rem;
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    color: #1a56db;
  }

  .btn-view:hover {
    background: #e2e8f0;
  }

  .expanded-row td {
    padding: 0.75rem;
    background: #f8fafc;
    border-bottom: 2px solid #e2e8f0;
  }

  /* ── Iteration module ── */
  .iteration-section {
    margin-top: 2rem;
    border-top: 1px solid #e2e8f0;
    padding-top: 1.5rem;
  }

  .iteration-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .iteration-header h2 {
    font-size: 1.1rem;
    color: #444;
    margin: 0;
  }

  .iteration-empty,
  .iteration-error {
    color: #94a3b8;
    font-size: 0.9rem;
  }

  .iteration-error {
    color: #b91c1c;
  }

  .skill-block {
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-bottom: 0.75rem;
    overflow: hidden;
  }

  .skill-toggle {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.65rem 1rem;
    background: #f8fafc;
    border: none;
    cursor: pointer;
    text-align: left;
    font-size: 0.95rem;
  }

  .skill-toggle:hover {
    background: #f1f5f9;
  }

  .skill-name {
    font-family: 'Courier New', monospace;
    font-weight: 600;
    color: #1a56db;
    flex: 1;
  }

  .skill-count {
    font-size: 0.8rem;
    color: #64748b;
  }

  .toggle-arrow {
    color: #94a3b8;
    font-size: 0.8rem;
  }

  .lineage-tree {
    padding: 0.75rem 1rem;
    background: #fff;
  }

  .lineage-row {
    padding: 0.5rem 0;
    border-left: 2px solid #cbd5e1;
    padding-left: 1rem;
    margin-left: 0.5rem;
  }

  .lineage-row.rolled-back {
    opacity: 0.55;
  }

  .lineage-version {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.2rem;
  }

  .version-badge {
    font-family: 'Courier New', monospace;
    font-size: 0.82rem;
    font-weight: 700;
    background: #dbeafe;
    color: #1e40af;
    padding: 0.1rem 0.5rem;
    border-radius: 4px;
  }

  .version-badge.rolled-back-badge {
    background: #fee2e2;
    color: #991b1b;
  }

  .rollback-flag {
    font-size: 0.72rem;
    color: #991b1b;
    background: #fee2e2;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
  }

  .lineage-meta {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-size: 0.78rem;
    color: #64748b;
    margin-bottom: 0.2rem;
  }

  .lineage-date {
    font-family: 'Courier New', monospace;
  }

  .itr-id {
    font-family: 'Courier New', monospace;
    background: #f1f5f9;
    padding: 0.05rem 0.35rem;
    border-radius: 3px;
  }

  .itr-id.dim {
    color: #94a3b8;
  }

  .variant-id {
    font-family: 'Courier New', monospace;
    color: #047857;
    font-size: 0.75rem;
  }

  .lineage-summary {
    font-size: 0.88rem;
    color: #374151;
    line-height: 1.4;
  }

  .lineage-connector {
    color: #cbd5e1;
    padding-left: 1rem;
    margin-left: 0.5rem;
    font-size: 0.9rem;
  }
</style>
