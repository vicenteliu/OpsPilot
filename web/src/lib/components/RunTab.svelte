<script lang="ts">
  // Run tab — ticket input, summary output cards, and session history.
  import {
    runTicketStream, listSessions, getSession,
    type RunResponse, type TicketSummary, type Task, type SessionSummary,
  } from '$lib/api';

  let { selectedModelId, modules }: { selectedModelId: string; modules: Record<string, boolean> } = $props();

  // --- Ticket Input ---
  let inputMode = $state<'nl' | 'json'>('nl');
  let nlInput = $state<string>('无法连接 VPN，从今早 09:00 起报错 Authentication failed，已重启客户端无效。');
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
  let statusLines = $state<string[]>([]);
  let result = $state<RunResponse | null>(null);
  let fetchError = $state<string | null>(null);

  // --- History ---
  let sessions = $state<SessionSummary[]>([]);
  let historyLoading = $state<boolean>(false);
  let expanded = $state<Record<string, boolean>>({});
  let sessionCache = $state<Record<string, RunResponse>>({});
  let sessionLoadingId = $state<string | null>(null);

  // --- Derived ---
  let summary = $derived(result?.result ?? null);
  let runError = $derived(result?.error ?? null);

  // --- Run Handlers ---
  function buildTicketFromNL(): Record<string, unknown> {
    const lines = nlInput.split('\n');
    const subject = lines[0]?.trim() || 'Untitled issue';
    return {
      ticket_id: `TKT-WEB-${Date.now()}`,
      channel: 'web',
      submitted_at: new Date().toISOString(),
      submitter_role: 'end_user',
      subject,
      body: nlInput.trim(),
    };
  }

  let lastRunInput = $state<Record<string, unknown> | null>(null);

  const PLAYBOOK_BY_TYPE: Record<string, string> = {
    incident: 'pb_ticket_summary_zh',
    service_request: 'pb_request_fulfillment_zh',
  };

  // Run-tab work-item-type selector. 'auto' omits playbook_id so the backend
  // classifies (and may ask for confirmation); the others force a playbook.
  let selectedWorkItemType = $state<'auto' | 'incident' | 'service_request'>('auto');

  function selectedPlaybookId(): string | undefined {
    return selectedWorkItemType === 'auto' ? undefined : PLAYBOOK_BY_TYPE[selectedWorkItemType];
  }

  async function runWith(input: Record<string, unknown>, playbookId?: string) {
    fetchError = null;
    result = null;
    statusLines = [];
    lastRunInput = input;
    loading = true;
    try {
      for await (const event of runTicketStream(input, selectedModelId || undefined, playbookId)) {
        if (event.type === 'status') {
          statusLines = [...statusLines, event.message];
        } else if (event.type === 'result') {
          result = event.data;
          if (modules.history && !event.data.needs_confirmation) await refreshHistory();
        } else if (event.type === 'error') {
          fetchError = event.message;
        }
      }
    } catch (e) {
      fetchError = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function handleRun() {
    let input: Record<string, unknown>;
    if (inputMode === 'nl') {
      if (!nlInput.trim()) { fetchError = 'Please describe the issue.'; return; }
      input = buildTicketFromNL();
    } else {
      try {
        input = JSON.parse(ticketInput);
      } catch {
        fetchError = 'Invalid JSON in ticket input.';
        return;
      }
    }
    await runWith(input, selectedPlaybookId());
  }

  function confirmWorkItemType(workItemType: string) {
    if (!lastRunInput) return;
    runWith(lastRunInput, PLAYBOOK_BY_TYPE[workItemType] ?? PLAYBOOK_BY_TYPE.incident);
  }

  function copyText(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  function summaryTasks(s: TicketSummary): Task[] {
    return s.tasks ?? [];
  }

  function formatTasks(tasks: Task[]): string {
    return tasks
      .map((t, i) => `${i + 1}. ${t.tier ? `[${t.tier}] ` : ''}**${t.action}**\n   ${t.rationale}`)
      .join('\n\n');
  }

  // --- History Handlers ---
  async function refreshHistory() {
    historyLoading = true;
    try { sessions = await listSessions(); }
    catch { sessions = []; }
    finally { historyLoading = false; }
  }

  async function toggleSession(sessionId: string) {
    if (expanded[sessionId]) { expanded = { ...expanded, [sessionId]: false }; return; }
    if (!sessionCache[sessionId]) {
      sessionLoadingId = sessionId;
      try {
        const res = await getSession(sessionId);
        sessionCache = { ...sessionCache, [sessionId]: res };
      } catch { sessionLoadingId = null; return; }
      sessionLoadingId = null;
    }
    expanded = { ...expanded, [sessionId]: true };
  }

  let _loaded = false;
  $effect(() => {
    if (_loaded) return;
    _loaded = true;
    if (modules.history) refreshHistory();
  });
</script>

<section class="input-section">
  <div class="input-section-header">
    <h2>Work Item Input</h2>
    <div class="mode-toggle">
      <button
        class="mode-btn {inputMode === 'nl' ? 'active' : ''}"
        onclick={() => inputMode = 'nl'}
      >Natural Language</button>
      <button
        class="mode-btn {inputMode === 'json' ? 'active' : ''}"
        onclick={() => inputMode = 'json'}
      >JSON</button>
    </div>
  </div>

  {#if inputMode === 'nl'}
    <textarea
      rows={5}
      bind:value={nlInput}
      placeholder="Describe the issue in plain text, e.g.: Cannot connect to VPN since 09:00, error: Authentication failed. Already restarted the client."
      disabled={loading}
      class="nl-textarea"
    ></textarea>
  {:else}
    <textarea
      rows={12}
      bind:value={ticketInput}
      placeholder="Paste work item JSON here..."
      disabled={loading}
    ></textarea>
  {/if}

  <div class="run-row">
    <label class="wi-type-label">
      Type
      <select class="wi-type-select" bind:value={selectedWorkItemType} disabled={loading}>
        <option value="auto">Auto-detect</option>
        <option value="incident">Incident</option>
        <option value="service_request">Service Request</option>
      </select>
    </label>
    <button class="btn-run" onclick={() => handleRun()} disabled={loading}>
      {#if loading}
        <span class="spinner"></span> Running...
      {:else}
        Run
      {/if}
    </button>
    {#if result?.usage}
      <span class="usage-badge">
        ↑ {result.usage.input_tokens.toLocaleString()} / ↓ {result.usage.output_tokens.toLocaleString()} tokens
        {#if result.usage.cost_usd > 0}· ${result.usage.cost_usd.toFixed(4)}{/if}
      </span>
    {/if}
  </div>
</section>

{#if statusLines.length > 0}
  <div class="status-log">
    {#each statusLines as line}
      <div class="status-line">› {line}</div>
    {/each}
    {#if loading}<div class="status-line status-line--active">…</div>{/if}
  </div>
{/if}

{#if fetchError}
  <div class="error-banner"><strong>Error:</strong> {fetchError}</div>
{/if}
{#if runError}
  <div class="error-banner"><strong>Run error:</strong> {runError}</div>
{/if}

{#snippet outputCards(s: TicketSummary)}
  <section class="cards">
    <div class="card">
      <div class="card-header">
        <h3>Summary</h3>
        <button class="btn-copy" onclick={() => copyText(s.summary ?? '')}>Copy</button>
      </div>
      <p>{s.summary}</p>
    </div>
    {#if s.requested_item}
    <div class="card">
      <div class="card-header">
        <h3>Requested Item</h3>
        <button class="btn-copy" onclick={() => copyText(s.requested_item ?? '')}>Copy</button>
      </div>
      <p>{s.requested_item}</p>
    </div>
    {/if}
    {#if s.symptoms?.length}
    <div class="card">
      <div class="card-header">
        <h3>Symptoms</h3>
        <button class="btn-copy" onclick={() => copyText((s.symptoms ?? []).join('\n'))}>Copy</button>
      </div>
      <ul>
        {#each s.symptoms as symptom}<li>{symptom}</li>{/each}
      </ul>
    </div>
    {/if}
    <div class="card">
      <div class="card-header">
        <h3>Tasks</h3>
        <button class="btn-copy" onclick={() => copyText(formatTasks(summaryTasks(s)))}>Copy</button>
      </div>
      <ol>
        {#each summaryTasks(s) as task}
          <li>
            {#if task.tier}<span class="tier-badge tier-{task.tier}">{task.tier}</span>{/if}
            <strong>{task.action}</strong>
            <p class="rationale">{task.rationale}</p>
          </li>
        {/each}
      </ol>
    </div>
    {#if s.severity_suggested}
    <div class="card">
      <div class="card-header">
        <h3>Severity</h3>
        <button class="btn-copy" onclick={() => copyText((s.severity_suggested ?? '') + (s.escalation_hint ? '\n' + s.escalation_hint : ''))}>Copy</button>
      </div>
      <span class="severity-badge">{s.severity_suggested}</span>
      {#if s.escalation_hint}<p class="escalation">{s.escalation_hint}</p>{/if}
    </div>
    {/if}
    {#if s.approval_needed !== undefined}
    <div class="card">
      <div class="card-header">
        <h3>Approval</h3>
        <button class="btn-copy" onclick={() => copyText(s.approval_needed ? 'Approval needed' : 'Auto-fulfill')}>Copy</button>
      </div>
      <span class="severity-badge">{s.approval_needed ? 'Approval needed' : 'Auto-fulfill'}</span>
    </div>
    {/if}
  </section>
{/snippet}

{#if result?.needs_confirmation && result.classification}
  <div class="confirm-banner">
    <p>
      <strong>Low confidence — please confirm the work item type.</strong>
      Best guess: <span class="wi-badge">{result.classification.work_item_type}</span>
      ({(result.classification.confidence * 100).toFixed(0)}%) —
      {result.classification.rationale}
    </p>
    <div class="confirm-actions">
      <button class="btn-confirm" onclick={() => confirmWorkItemType('incident')}>Run as Incident</button>
      <button class="btn-confirm" onclick={() => confirmWorkItemType('service_request')}>Run as Service Request</button>
    </div>
  </div>
{:else if result?.classification}
  <p class="classified-note">
    Classified as <span class="wi-badge">{result.classification.work_item_type}</span>
    ({(result.classification.confidence * 100).toFixed(0)}% confidence)
  </p>
{/if}

{#if summary}
  {@render outputCards(summary as TicketSummary)}
{/if}

<!-- History -->
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
          <tr><th>Time</th><th>Session ID</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {#each sessions as s}
            <tr>
              <td class="col-time">{new Date(s.created_at).toLocaleString()}</td>
              <td class="col-sid mono">{s.session_id.slice(0, 26)}…</td>
              <td><span class="status-badge status-{s.status}">{s.status}</span></td>
              <td>
                <button class="btn-view" onclick={() => toggleSession(s.session_id)}
                  disabled={sessionLoadingId === s.session_id}>
                  {#if sessionLoadingId === s.session_id}…
                  {:else if expanded[s.session_id]}▲ Hide
                  {:else}▼ View{/if}
                </button>
              </td>
            </tr>
            {#if expanded[s.session_id] && sessionCache[s.session_id]}
              {@const sd = sessionCache[s.session_id]}
              <tr class="expanded-row">
                <td colspan="4">
                  <div class="session-detail">
                    <div class="session-detail-meta">
                      <span class="mono dim">{sd.session_id}</span>
                      {#if sd.artifact_id}<span class="dim">· artifact <span class="mono">{sd.artifact_id}</span></span>{/if}
                      {#if sd.usage}
                        <span class="usage-badge">
                          ↑ {sd.usage.input_tokens.toLocaleString()} / ↓ {sd.usage.output_tokens.toLocaleString()} tokens
                          {#if sd.usage.cost_usd > 0}· ${sd.usage.cost_usd.toFixed(4)}{/if}
                        </span>
                      {/if}
                    </div>
                    {#if sd.error}
                      <div class="error-banner" style="margin:0.5rem 0"><strong>Error:</strong> {sd.error}</div>
                    {:else if sd.result}
                      {@render outputCards(sd.result as TicketSummary)}
                    {/if}
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    {/if}
  </section>
{/if}
