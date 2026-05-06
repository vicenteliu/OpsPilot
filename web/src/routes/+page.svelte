<script lang="ts">
  import '../app.css';
  import {
    getConfig, getModels, runTicket, listSessions, getSession, getLineage,
    getKBStats, listKBDocs, searchKB, wikiIngest, wikiQueryToPage, wikiLint, wikiPromote, listMCPServers,
    listConflicts, resolveConflict, correctChunk, listCorrections, generateVendorDoc,
    type RunResponse, type TicketSummary, type NextAction, type SessionSummary, type ModelOption, type SkillLineage,
    type KBDoc, type KBHit, type KBConflict, type KBStats, type KBCorrection, type WikiLintIssue, type MCPServer,
    type VendorDoc, type VendorDocSection
  } from '$lib/api';

  // --- Theme ---
  let theme = $state<'light' | 'dark'>(
    typeof localStorage !== 'undefined'
      ? (localStorage.getItem('theme') as 'light' | 'dark') ?? 'light'
      : 'light'
  );

  $effect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  });

  function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
  }

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

  // KB state
  let kbStats = $state<KBStats | null>(null);
  let kbDocs = $state<KBDoc[]>([]);
  let kbDocsLoading = $state<boolean>(false);
  let kbSearchQuery = $state<string>('');
  let kbSearchResults = $state<KBHit[]>([]);
  let kbSearchLoading = $state<boolean>(false);
  let kbSearchError = $state<string | null>(null);
  let kbSection = $state<'docs' | 'search' | 'conflicts' | 'corrections'>('docs');

  // Corrections state
  let kbCorrections = $state<KBCorrection[]>([]);
  let correctionsLoading = $state<boolean>(false);
  let correctionsError = $state<string | null>(null);

  // Conflict state
  let kbConflicts = $state<KBConflict[]>([]);
  let conflictsLoading = $state<boolean>(false);
  let conflictsError = $state<string | null>(null);
  let conflictStatusFilter = $state<'open' | 'all'>('open');
  let resolving = $state<Record<string, boolean>>({});

  // Correction state
  let correctingChunkId = $state<string | null>(null);
  let correctReason = $state<string>('');
  let correctContent = $state<string>('');
  let correctLoading = $state<boolean>(false);
  let correctError = $state<string | null>(null);

  // Wiki state
  let wikiDocId = $state<string>('');
  let wikiSessionId = $state<string>('');
  let wikiLoading = $state<boolean>(false);
  let wikiMsg = $state<string | null>(null);
  let wikiError = $state<string | null>(null);
  let wikiLintIssues = $state<WikiLintIssue[]>([]);
  let wikiLintLoading = $state<boolean>(false);

  // Vendor Doc state
  let vendorDocTopic = $state<string>('');
  let vendorDocTemplateId = $state<string>('sop_summary');
  let vendorDocVendorName = $state<string>('');
  let vendorDocLoading = $state<boolean>(false);
  let vendorDocResult = $state<VendorDoc | null>(null);
  let vendorDocError = $state<string | null>(null);
  let vendorDocUsage = $state<RunResponse['usage'] | null>(null);

  // MCP state
  let mcpServers = $state<MCPServer[]>([]);
  let mcpLoading = $state<boolean>(false);
  let mcpError = $state<string | null>(null);

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
      await loadKBDocs();
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

  // ── KB handlers ────────────────────────────────────────────────────────────
  async function loadKBStats() {
    try { kbStats = await getKBStats(); } catch { /* stats are non-critical */ }
  }

  async function loadKBDocs() {
    kbDocsLoading = true;
    try {
      [kbDocs] = await Promise.all([listKBDocs(), loadKBStats()]);
    } catch {
      kbDocs = [];
    } finally {
      kbDocsLoading = false;
    }
  }

  async function loadCorrections() {
    correctionsLoading = true;
    correctionsError = null;
    try {
      kbCorrections = await listCorrections();
      await loadKBStats();
    } catch (e) {
      correctionsError = e instanceof Error ? e.message : String(e);
    } finally {
      correctionsLoading = false;
    }
  }

  async function handleKBSearch() {
    if (!kbSearchQuery.trim()) return;
    kbSearchLoading = true;
    kbSearchError = null;
    kbSearchResults = [];
    try {
      kbSearchResults = await searchKB(kbSearchQuery.trim());
    } catch (e) {
      kbSearchError = e instanceof Error ? e.message : String(e);
    } finally {
      kbSearchLoading = false;
    }
  }

  async function handleCorrect(chunkId: string) {
    if (!correctReason.trim() || !correctContent.trim()) return;
    correctLoading = true;
    correctError = null;
    try {
      await correctChunk(chunkId, correctContent.trim(), correctReason.trim());
      // Refresh search results and stats so the updated content shows
      if (kbSearchQuery.trim()) kbSearchResults = await searchKB(kbSearchQuery.trim());
      await loadKBStats();
      correctingChunkId = null;
      correctReason = '';
      correctContent = '';
    } catch (e) {
      correctError = e instanceof Error ? e.message : String(e);
    } finally {
      correctLoading = false;
    }
  }

  // ── Wiki handlers ───────────────────────────────────────────────────────────
  async function handleWikiIngest() {
    if (!wikiDocId.trim()) return;
    wikiLoading = true;
    wikiMsg = null;
    wikiError = null;
    try {
      const r = await wikiIngest(wikiDocId.trim());
      wikiMsg = `✓ Created wiki page: ${r.slug}`;
    } catch (e) {
      wikiError = e instanceof Error ? e.message : String(e);
    } finally {
      wikiLoading = false;
    }
  }

  async function handleWikiQueryToPage() {
    wikiLoading = true;
    wikiMsg = null;
    wikiError = null;
    try {
      const r = await wikiQueryToPage(wikiSessionId.trim() || undefined);
      wikiMsg = `✓ ${r.pages_created} page(s) created`;
    } catch (e) {
      wikiError = e instanceof Error ? e.message : String(e);
    } finally {
      wikiLoading = false;
    }
  }

  async function handleWikiLint() {
    wikiLintLoading = true;
    try {
      wikiLintIssues = await wikiLint();
    } catch {
      wikiLintIssues = [];
    } finally {
      wikiLintLoading = false;
    }
  }

  async function handleWikiPromote(slug: string) {
    wikiLoading = true;
    wikiMsg = null;
    wikiError = null;
    try {
      const r = await wikiPromote(slug);
      wikiMsg = r.skipped ? `Skipped: ${r.skip_reason}` : `✓ ${slug}: ${r.old_state} → ${r.new_state}`;
    } catch (e) {
      wikiError = e instanceof Error ? e.message : String(e);
    } finally {
      wikiLoading = false;
    }
  }

  // ── Conflict handlers ───────────────────────────────────────────────────────
  async function loadConflicts() {
    conflictsLoading = true;
    conflictsError = null;
    try {
      kbConflicts = await listConflicts(conflictStatusFilter);
    } catch (e) {
      conflictsError = e instanceof Error ? e.message : String(e);
      kbConflicts = [];
    } finally {
      conflictsLoading = false;
    }
  }

  async function handleResolve(conflictId: string, resolution: string) {
    resolving = { ...resolving, [conflictId]: true };
    try {
      await resolveConflict(conflictId, resolution);
      await loadConflicts();
    } catch (e) {
      conflictsError = e instanceof Error ? e.message : String(e);
    } finally {
      resolving = { ...resolving, [conflictId]: false };
    }
  }

  // ── Vendor Doc handlers ──────────────────────────────────────────────────────
  async function handleGenerateVendorDoc() {
    if (!vendorDocTopic.trim()) return;
    vendorDocLoading = true;
    vendorDocError = null;
    vendorDocResult = null;
    vendorDocUsage = null;
    try {
      const res = await generateVendorDoc({
        topic: vendorDocTopic.trim(),
        template_id: vendorDocTemplateId,
        vendor_name: vendorDocVendorName.trim(),
        language: 'en',
      });
      vendorDocResult = res.result as VendorDoc;
      vendorDocUsage = res.usage;
      if (res.error) vendorDocError = res.error;
    } catch (e) {
      vendorDocError = e instanceof Error ? e.message : String(e);
    } finally {
      vendorDocLoading = false;
    }
  }

  function copyVendorDoc() {
    if (!vendorDocResult) return;
    const text = [
      `# ${vendorDocResult.title}`,
      vendorDocResult.scope_note ? `\n_${vendorDocResult.scope_note}_` : '',
      '',
      ...vendorDocResult.sections.map(s => `## ${s.heading}\n\n${s.content}`),
    ].join('\n\n');
    navigator.clipboard.writeText(text).catch(() => {});
  }

  // ── MCP handlers ────────────────────────────────────────────────────────────
  async function loadMCPServers() {
    mcpLoading = true;
    mcpError = null;
    try {
      mcpServers = await listMCPServers();
    } catch (e) {
      mcpError = e instanceof Error ? e.message : String(e);
      mcpServers = [];
    } finally {
      mcpLoading = false;
    }
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
    <button class="theme-toggle" onclick={toggleTheme} title="Toggle dark mode" aria-label="Toggle dark mode">
      {theme === 'dark' ? '☀' : '☾'}
    </button>
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

    <!-- KB module -->
    <section class="kb-section">
      <div class="section-header">
        <h2>Knowledge Base</h2>
        <div class="section-tabs">
          <button class="tab-btn {kbSection === 'docs' ? 'active' : ''}" onclick={() => kbSection = 'docs'}>Docs</button>
          <button class="tab-btn {kbSection === 'search' ? 'active' : ''}" onclick={() => kbSection = 'search'}>Search</button>
          <button class="tab-btn {kbSection === 'conflicts' ? 'active' : ''}" onclick={() => { kbSection = 'conflicts'; loadConflicts(); }}>
            Conflicts {#if kbStats && kbStats.open_conflicts > 0}<span class="conflict-badge">{kbStats.open_conflicts}</span>{/if}
          </button>
          <button class="tab-btn {kbSection === 'corrections' ? 'active' : ''}" onclick={() => { kbSection = 'corrections'; loadCorrections(); }}>
            Corrections {#if kbStats && kbStats.corrections_total > 0}<span class="corr-badge">{kbStats.corrections_total}</span>{/if}
          </button>
        </div>
        <button class="btn-refresh" onclick={loadKBDocs} disabled={kbDocsLoading}>↻</button>
      </div>

      {#if kbStats}
        <div class="kb-stats-bar">
          <span class="stat-item"><strong>{kbStats.docs_total}</strong> docs</span>
          <span class="stat-sep">·</span>
          <span class="stat-item"><strong>{kbStats.chunks_total}</strong> chunks</span>
          <span class="stat-sep">·</span>
          <span class="stat-item {kbStats.open_conflicts > 0 ? 'stat-warn' : ''}">
            <strong>{kbStats.open_conflicts}</strong> open conflicts
          </span>
          <span class="stat-sep">·</span>
          <span class="stat-item"><strong>{kbStats.corrections_total}</strong> corrections</span>
        </div>
      {/if}

      {#if kbSection === 'docs'}
        {#if kbDocsLoading}
          <p class="section-empty">Loading…</p>
        {:else if kbDocs.length === 0}
          <p class="section-empty">No documents ingested yet. Use <code>opspilot ingest &lt;file&gt;</code> or the TUI.</p>
        {:else}
          <table class="data-table">
            <thead><tr><th>Doc ID</th><th>Title</th><th>Lang</th><th>Chunks</th><th>Ingested</th></tr></thead>
            <tbody>
              {#each kbDocs as doc}
                <tr>
                  <td class="mono">{doc.doc_id}</td>
                  <td>{doc.title || '—'}</td>
                  <td>{doc.language || '—'}</td>
                  <td class="num">{doc.chunk_count}</td>
                  <td class="dim">{doc.ingested_at.slice(0, 10)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      {:else if kbSection === 'search'}
        <div class="search-row">
          <input
            class="search-input"
            bind:value={kbSearchQuery}
            placeholder="Search KB…"
            onkeydown={(e) => e.key === 'Enter' && handleKBSearch()}
          />
          <button class="btn-action" onclick={handleKBSearch} disabled={kbSearchLoading || !kbSearchQuery.trim()}>
            {kbSearchLoading ? '…' : 'Search'}
          </button>
        </div>
        {#if kbSearchError}
          <p class="section-error">{kbSearchError}</p>
        {:else if kbSearchResults.length > 0}
          <table class="data-table">
            <thead><tr><th>Chunk</th><th>Doc</th><th>Score</th><th>Valid From</th><th>Snippet</th><th></th></tr></thead>
            <tbody>
              {#each kbSearchResults as h}
                <tr class="{h.has_open_conflicts ? 'row-conflict' : ''}">
                  <td class="mono">{h.chunk_id.slice(0, 20)}</td>
                  <td class="mono">
                    {h.document_id.slice(0, 20)}
                    {#if h.has_open_conflicts}<span class="warn-badge" title="Source document has open conflicts">⚠</span>{/if}
                  </td>
                  <td class="num">{h.score.toFixed(4)}</td>
                  <td class="dim">{h.valid_from ? h.valid_from.slice(0, 10) : '—'}</td>
                  <td class="snippet">{h.content.slice(0, 100)}</td>
                  <td>
                    <button class="btn-correct-toggle" title="Correct this chunk"
                      onclick={() => {
                        correctingChunkId = correctingChunkId === h.chunk_id ? null : h.chunk_id;
                        correctReason = '';
                        correctContent = h.content;
                        correctError = null;
                      }}>
                      {correctingChunkId === h.chunk_id ? '✕' : '✎'}
                    </button>
                  </td>
                </tr>
                {#if correctingChunkId === h.chunk_id}
                  <tr class="correct-row">
                    <td colspan="6">
                      <div class="correct-form">
                        <label class="correct-label">Reason
                          <input class="correct-input" bind:value={correctReason} placeholder="Why is this content incorrect?" />
                        </label>
                        <label class="correct-label">Corrected content
                          <textarea class="correct-textarea" bind:value={correctContent} rows="4"></textarea>
                        </label>
                        {#if correctError}<p class="section-error">{correctError}</p>{/if}
                        <div class="correct-actions">
                          <button class="btn-action" onclick={() => handleCorrect(h.chunk_id)}
                            disabled={correctLoading || !correctReason.trim() || !correctContent.trim()}>
                            {correctLoading ? '…' : 'Apply correction'}
                          </button>
                          <button class="btn-secondary" onclick={() => correctingChunkId = null}>Cancel</button>
                        </div>
                      </div>
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        {:else if !kbSearchLoading && kbSearchQuery}
          <p class="section-empty">No results.</p>
        {/if}
      {:else if kbSection === 'conflicts'}
        <!-- Conflicts tab -->
        <div class="conflict-toolbar">
          <label class="filter-label">
            Show:
            <select bind:value={conflictStatusFilter} onchange={loadConflicts}>
              <option value="open">Open only</option>
              <option value="all">All</option>
            </select>
          </label>
          <button class="btn-refresh" onclick={loadConflicts} disabled={conflictsLoading}>↻</button>
        </div>
        {#if conflictsError}
          <p class="section-error">{conflictsError}</p>
        {:else if conflictsLoading}
          <p class="section-empty">Loading…</p>
        {:else if kbConflicts.length === 0}
          <p class="section-empty">No {conflictStatusFilter === 'open' ? 'open ' : ''}conflicts found.</p>
        {:else}
          <table class="data-table conflict-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Sim</th>
                <th>Doc A</th>
                <th>Doc B</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {#each kbConflicts as c}
                <tr>
                  <td><span class="conflict-type-badge ctype-{c.conflict_type}">{c.conflict_type.replace('_', ' ')}</span></td>
                  <td class="num">{c.similarity.toFixed(3)}</td>
                  <td>
                    <div class="conflict-doc">{c.doc_a_title || c.doc_a_id}</div>
                    {#if c.doc_a_valid_from}<div class="dim" style="font-size:0.75rem">{c.doc_a_valid_from.slice(0,10)}</div>{/if}
                    {#if c.chunk_a_content}<div class="chunk-preview">{c.chunk_a_content.slice(0, 80)}…</div>{/if}
                  </td>
                  <td>
                    <div class="conflict-doc">{c.doc_b_title || c.doc_b_id}</div>
                    {#if c.doc_b_valid_from}<div class="dim" style="font-size:0.75rem">{c.doc_b_valid_from.slice(0,10)}</div>{/if}
                    {#if c.chunk_b_content}<div class="chunk-preview">{c.chunk_b_content.slice(0, 80)}…</div>{/if}
                  </td>
                  <td><span class="status-badge status-{c.status}">{c.status}</span></td>
                  <td>
                    {#if c.status === 'open'}
                      <div class="resolve-btns">
                        <button class="btn-sm btn-a-wins" onclick={() => handleResolve(c.id, 'a_wins')} disabled={resolving[c.id]}>A wins</button>
                        <button class="btn-sm btn-b-wins" onclick={() => handleResolve(c.id, 'b_wins')} disabled={resolving[c.id]}>B wins</button>
                        <button class="btn-sm" onclick={() => handleResolve(c.id, 'dismissed')} disabled={resolving[c.id]}>Dismiss</button>
                      </div>
                    {:else}
                      <span class="dim" style="font-size:0.8rem">{c.resolved_by || '—'}</span>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      {:else}
        <!-- Corrections tab -->
        <div class="conflict-toolbar">
          <button class="btn-refresh" onclick={loadCorrections} disabled={correctionsLoading}>↻ Refresh</button>
        </div>
        {#if correctionsError}
          <p class="section-error">{correctionsError}</p>
        {:else if correctionsLoading}
          <p class="section-empty">Loading…</p>
        {:else if kbCorrections.length === 0}
          <p class="section-empty">No corrections recorded.</p>
        {:else}
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Chunk</th>
                <th>By</th>
                <th>Reason</th>
                <th>Old content</th>
                <th>New content</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {#each kbCorrections as corr}
                <tr>
                  <td class="mono dim">{corr.id}</td>
                  <td class="mono">{corr.chunk_id}</td>
                  <td class="dim">{corr.corrected_by}</td>
                  <td>{corr.reason}</td>
                  <td class="chunk-preview dim">{corr.old_content.slice(0, 80)}</td>
                  <td class="chunk-preview">{corr.new_content.slice(0, 80)}</td>
                  <td class="dim">{corr.created_at.slice(0, 19)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      {/if}
    </section>

    <!-- Wiki module -->
    <section class="wiki-section">
      <div class="section-header">
        <h2>Wiki</h2>
      </div>

      <div class="action-row">
        <input class="short-input" bind:value={wikiDocId} placeholder="KB doc_id for ingest…" />
        <button class="btn-action" onclick={handleWikiIngest} disabled={wikiLoading || !wikiDocId.trim()}>
          Ingest KB Doc
        </button>
        <input class="short-input" bind:value={wikiSessionId} placeholder="Session ID (blank=scan all)" />
        <button class="btn-action" onclick={handleWikiQueryToPage} disabled={wikiLoading}>
          Query→Page
        </button>
        <button class="btn-action btn-secondary" onclick={handleWikiLint} disabled={wikiLintLoading}>
          {wikiLintLoading ? '…' : 'Lint'}
        </button>
      </div>

      {#if wikiMsg}
        <p class="section-ok">{wikiMsg}</p>
      {/if}
      {#if wikiError}
        <p class="section-error">{wikiError}</p>
      {/if}

      {#if wikiLintIssues.length > 0}
        <table class="data-table">
          <thead><tr><th>Severity</th><th>Type</th><th>Page</th><th>Summary</th><th></th></tr></thead>
          <tbody>
            {#each wikiLintIssues as issue}
              <tr>
                <td><span class="sev-badge sev-{issue.severity}">{issue.severity}</span></td>
                <td class="mono">{issue.issue_type}</td>
                <td class="mono">{issue.page_slug}</td>
                <td>{issue.summary.slice(0, 60)}</td>
                <td>
                  {#if issue.page_slug}
                    <button class="btn-sm" onclick={() => handleWikiPromote(issue.page_slug)}>Promote</button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else if !wikiLintLoading && wikiLintIssues !== null}
        <p class="section-empty">Run lint to check wiki pages.</p>
      {/if}
    </section>

    <!-- Vendor Doc module -->
    <section class="vendordoc-section">
      <div class="section-header">
        <h2>Vendor Document</h2>
        {#if vendorDocResult}
          <button class="btn-action btn-secondary" onclick={copyVendorDoc}>Copy as Markdown</button>
        {/if}
      </div>

      <div class="vd-form">
        <div class="vd-row">
          <label class="vd-label">
            Topic
            <input class="vd-input" bind:value={vendorDocTopic}
              placeholder="e.g. VPN authentication failure troubleshooting"
              disabled={vendorDocLoading} />
          </label>
          <label class="vd-label">
            Template
            <select class="vd-select" bind:value={vendorDocTemplateId} disabled={vendorDocLoading}>
              <option value="sop_summary">SOP Summary</option>
              <option value="maintenance_window">Maintenance Window</option>
              <option value="incident_report">Incident Report</option>
              <option value="handover">Handover Checklist</option>
            </select>
          </label>
          <label class="vd-label">
            Vendor (optional)
            <input class="vd-input vd-input-sm" bind:value={vendorDocVendorName}
              placeholder="e.g. SecureNet Ltd"
              disabled={vendorDocLoading} />
          </label>
        </div>
        <div class="vd-actions">
          <button class="btn-run" onclick={handleGenerateVendorDoc}
            disabled={vendorDocLoading || !vendorDocTopic.trim()}>
            {#if vendorDocLoading}
              <span class="spinner"></span> Generating…
            {:else}
              Generate
            {/if}
          </button>
          {#if vendorDocUsage}
            <span class="usage-badge">
              ↑ {vendorDocUsage.input_tokens.toLocaleString()} / ↓ {vendorDocUsage.output_tokens.toLocaleString()} tokens
              {#if vendorDocUsage.cost_usd > 0}· ${vendorDocUsage.cost_usd.toFixed(4)}{/if}
            </span>
          {/if}
        </div>
      </div>

      {#if vendorDocError}
        <p class="section-error" style="margin-top:0.5rem">{vendorDocError}</p>
      {/if}

      {#if vendorDocResult}
        <div class="vd-output">
          <div class="vd-doc-header">
            <div>
              <div class="vd-title">{vendorDocResult.title}</div>
              <div class="vd-meta">
                <span class="vd-ref mono dim">{vendorDocResult.doc_ref}</span>
                <span class="vd-template-badge">{vendorDocResult.template_id.replace('_', ' ')}</span>
              </div>
            </div>
          </div>
          {#if vendorDocResult.scope_note}
            <p class="vd-scope-note">{vendorDocResult.scope_note}</p>
          {/if}
          {#each vendorDocResult.sections as section}
            <div class="vd-section">
              <h4 class="vd-section-heading">{section.heading}</h4>
              <p class="vd-section-content">{section.content}</p>
              {#if section.citations.length > 0}
                <div class="vd-section-cits">
                  {#each section.citations as cit}
                    <span class="vd-cit-tag">{cit}</span>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
          {#if vendorDocResult.citations.length > 0}
            <details class="vd-citations">
              <summary class="vd-cit-summary">Sources ({vendorDocResult.citations.length})</summary>
              <ul class="vd-cit-list">
                {#each vendorDocResult.citations as c}
                  <li class="mono dim" style="font-size:0.78rem">
                    <strong>{c.id}</strong> — {c.source_path || c.document_id}
                    {#if c.line_start} L{c.line_start}–{c.line_end}{/if}
                  </li>
                {/each}
              </ul>
            </details>
          {/if}
        </div>
      {/if}
    </section>

    <!-- MCP servers module -->
    <section class="mcp-section">
      <div class="section-header">
        <h2>MCP Servers</h2>
        <button class="btn-refresh" onclick={loadMCPServers} disabled={mcpLoading}>↻</button>
      </div>
      {#if mcpError}
        <p class="section-error">{mcpError}</p>
      {:else if mcpLoading}
        <p class="section-empty">Loading…</p>
      {:else if mcpServers.length === 0}
        <p class="section-empty">Click ↻ to load MCP servers from mcp-config.yaml.</p>
      {:else}
        <table class="data-table">
          <thead><tr><th>ID</th><th>Transport</th><th>Enabled</th><th>Trust</th><th>Tools</th></tr></thead>
          <tbody>
            {#each mcpServers as s}
              <tr>
                <td class="mono">{s.id}</td>
                <td>{s.transport}</td>
                <td>{s.enabled ? '✓' : '—'}</td>
                <td>{s.trust}</td>
                <td class="num">{s.tools.length}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

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
    border-bottom: 2px solid var(--border);
    padding-bottom: 0.75rem;
  }

  header h1 {
    font-size: 1.8rem;
    color: var(--primary);
  }

  .model-ref {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.8rem;
    background: var(--primary-bg);
    color: var(--primary);
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    border: 1px solid var(--primary-border);
  }

  .model-select {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.8rem;
    background: var(--primary-bg);
    color: var(--primary);
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    border: 1px solid var(--primary-border);
    cursor: pointer;
  }

  .model-select:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .theme-toggle {
    background: none;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.25rem 0.55rem;
    font-size: 1rem;
    color: var(--text-muted);
    line-height: 1;
    cursor: pointer;
    margin-left: 0.5rem;
  }

  .theme-toggle:hover {
    background: var(--bg-muted);
    color: var(--text);
  }

  .input-section {
    margin-bottom: 1.5rem;
  }

  .input-section h2 {
    margin-bottom: 0.5rem;
    font-size: 1.1rem;
    color: var(--text);
  }

  textarea {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--bg-surface);
    margin-bottom: 0.75rem;
  }

  .run-row {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .btn-run {
    padding: 0.6rem 1.5rem;
    background: var(--primary);
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
    color: var(--text-muted);
    background: var(--bg-muted);
    border: 1px solid var(--border);
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
    background: var(--error-bg);
    color: var(--error-text);
    border: 1px solid var(--error-border);
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
    background: var(--bg-surface);
    border: 1px solid var(--border);
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
    color: var(--text-muted);
  }

  .btn-copy {
    font-size: 0.75rem;
    padding: 0.2rem 0.6rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--text-sub);
  }

  .btn-copy:hover {
    background: var(--bg-hover);
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
    color: var(--text-muted);
    font-size: 0.88rem;
  }

  .severity-badge {
    display: inline-block;
    padding: 0.3rem 0.8rem;
    border-radius: 9999px;
    font-weight: 700;
    font-size: 1.1rem;
    background: var(--warn-bg);
    color: var(--warn-text);
    border: 1px solid var(--warn-border);
  }

  .escalation {
    margin-top: 0.5rem;
    font-size: 0.9rem;
    color: var(--warn-text2);
  }

  .history-section {
    margin-top: 2rem;
    border-top: 1px solid var(--border);
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
    color: var(--text);
    margin: 0;
  }

  .btn-refresh {
    background: none;
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    padding: 0.15rem 0.5rem;
    font-size: 1rem;
    color: var(--text-muted);
    line-height: 1;
  }

  .btn-refresh:hover {
    background: var(--bg-muted);
  }

  .history-empty {
    color: var(--text-faint);
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
    color: var(--text-muted);
    font-weight: 600;
    border-bottom: 1px solid var(--border);
  }

  .history-table td {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border-faint);
    vertical-align: middle;
  }

  .col-time {
    color: var(--text-sub);
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
    background: var(--success-bg);
    color: var(--success-text);
  }

  .status-aborted {
    background: var(--error-bg);
    color: var(--error-text);
  }

  .status-active {
    background: var(--sev-medium-bg);
    color: var(--warn-text);
  }

  .btn-view {
    font-size: 0.8rem;
    padding: 0.2rem 0.6rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--primary);
  }

  .btn-view:hover {
    background: var(--bg-hover);
  }

  .expanded-row td {
    padding: 0.75rem;
    background: var(--bg-subtle);
    border-bottom: 2px solid var(--border);
  }

  /* ── Iteration module ── */
  .iteration-section {
    margin-top: 2rem;
    border-top: 1px solid var(--border);
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
    color: var(--text);
    margin: 0;
  }

  .iteration-empty,
  .iteration-error {
    color: var(--text-faint);
    font-size: 0.9rem;
  }

  .iteration-error {
    color: var(--error-text);
  }

  .skill-block {
    border: 1px solid var(--border);
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
    background: var(--bg-subtle);
    border: none;
    cursor: pointer;
    text-align: left;
    font-size: 0.95rem;
  }

  .skill-toggle:hover {
    background: var(--bg-muted);
  }

  .skill-name {
    font-family: 'Courier New', monospace;
    font-weight: 600;
    color: var(--primary);
    flex: 1;
  }

  .skill-count {
    font-size: 0.8rem;
    color: var(--text-muted);
  }

  .toggle-arrow {
    color: var(--text-faint);
    font-size: 0.8rem;
  }

  .lineage-tree {
    padding: 0.75rem 1rem;
    background: var(--bg-surface);
  }

  .lineage-row {
    padding: 0.5rem 0;
    border-left: 2px solid var(--border-strong);
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
    background: var(--info-bg);
    color: var(--info-text);
    padding: 0.1rem 0.5rem;
    border-radius: 4px;
  }

  .version-badge.rolled-back-badge {
    background: var(--error-bg);
    color: var(--error-text);
  }

  .rollback-flag {
    font-size: 0.72rem;
    color: var(--error-text);
    background: var(--error-bg);
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
  }

  .lineage-meta {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-size: 0.78rem;
    color: var(--text-muted);
    margin-bottom: 0.2rem;
  }

  .lineage-date {
    font-family: 'Courier New', monospace;
  }

  .itr-id {
    font-family: 'Courier New', monospace;
    background: var(--bg-muted);
    padding: 0.05rem 0.35rem;
    border-radius: 3px;
  }

  .itr-id.dim {
    color: var(--text-faint);
  }

  .variant-id {
    font-family: 'Courier New', monospace;
    color: var(--success-text);
    font-size: 0.75rem;
  }

  .lineage-summary {
    font-size: 0.88rem;
    color: var(--text);
    line-height: 1.4;
  }

  .lineage-connector {
    color: var(--border-strong);
    padding-left: 1rem;
    margin-left: 0.5rem;
    font-size: 0.9rem;
  }

  /* ── KB / Wiki / MCP sections ── */
  .kb-section, .wiki-section, .mcp-section {
    margin-top: 2rem;
    border-top: 1px solid var(--border);
    padding-top: 1.5rem;
  }

  .section-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .section-header h2 {
    font-size: 1.1rem;
    color: var(--text);
    margin: 0;
    flex: 1;
  }

  .section-tabs {
    display: flex;
    gap: 0.25rem;
  }

  .tab-btn {
    font-size: 0.8rem;
    padding: 0.2rem 0.7rem;
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    background: var(--bg-subtle);
    color: var(--text-sub);
    cursor: pointer;
  }

  .tab-btn.active {
    background: var(--primary);
    color: #fff;
    border-color: var(--primary);
  }

  .section-empty {
    color: var(--text-faint);
    font-size: 0.9rem;
  }

  .section-error {
    color: var(--error-text);
    font-size: 0.9rem;
  }

  .section-ok {
    color: var(--success-text);
    font-size: 0.9rem;
  }

  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }

  .data-table th {
    text-align: left;
    padding: 0.35rem 0.65rem;
    color: var(--text-muted);
    font-weight: 600;
    border-bottom: 1px solid var(--border);
  }

  .data-table td {
    padding: 0.4rem 0.65rem;
    border-bottom: 1px solid var(--border-faint);
    vertical-align: top;
  }

  .mono {
    font-family: 'Courier New', monospace;
    font-size: 0.82rem;
  }

  .num {
    text-align: right;
    font-family: 'Courier New', monospace;
  }

  .dim {
    color: var(--text-faint);
  }

  .snippet {
    color: var(--text-sub);
    font-size: 0.82rem;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .search-row {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }

  .search-input {
    flex: 1;
    padding: 0.45rem 0.75rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    font-size: 0.9rem;
  }

  .action-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 1rem;
    align-items: center;
  }

  .short-input {
    padding: 0.4rem 0.7rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    font-size: 0.85rem;
    width: 200px;
  }

  .btn-action {
    padding: 0.4rem 1rem;
    background: var(--primary);
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
  }

  .btn-action:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-action.btn-secondary {
    background: var(--bg-muted);
    color: var(--primary);
    border: 1px solid var(--border-strong);
  }

  .btn-sm {
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--primary);
    cursor: pointer;
  }

  .sev-badge {
    font-size: 0.72rem;
    font-weight: 700;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
  }

  .sev-critical { background: var(--error-bg); color: var(--error-text); }
  .sev-high { background: var(--sev-high-bg); color: var(--sev-high-text); }
  .sev-medium { background: var(--sev-medium-bg); color: var(--warn-text); }
  .sev-low { background: var(--success-bg); color: var(--success-text); }

  /* ── Conflicts ── */
  .conflict-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    background: var(--error-badge);
    color: #fff;
    border-radius: 9999px;
    font-size: 0.65rem;
    font-weight: 700;
    margin-left: 4px;
    vertical-align: middle;
  }

  .conflict-toolbar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .filter-label {
    font-size: 0.85rem;
    color: var(--text-sub);
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .filter-label select {
    font-size: 0.85rem;
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--border-strong);
    border-radius: 4px;
  }

  .conflict-table td {
    vertical-align: top;
    padding: 0.5rem 0.65rem;
  }

  .conflict-doc {
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--text);
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chunk-preview {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 0.2rem;
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .conflict-type-badge {
    font-size: 0.72rem;
    font-weight: 600;
    padding: 0.1rem 0.45rem;
    border-radius: 3px;
    white-space: nowrap;
  }

  .ctype-temporal_supersede { background: var(--info-bg); color: var(--info-text); }
  .ctype-direct_contradiction { background: var(--error-bg); color: var(--error-text); }
  .ctype-scope_overlap { background: var(--sev-medium-bg); color: var(--warn-text); }

  .resolve-btns {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .btn-a-wins { background: var(--success-bg); color: var(--success-text); border-color: var(--success-border); }
  .btn-b-wins { background: var(--info-bg); color: var(--info-text); border-color: var(--info-border); }

  .row-conflict {
    background: var(--row-conflict-bg);
  }

  .warn-badge {
    display: inline-block;
    margin-left: 4px;
    color: var(--warn-text2);
    font-size: 0.85rem;
    cursor: help;
  }

  .status-open { background: var(--warn-bg); color: var(--warn-text); }
  .status-a_wins { background: var(--success-bg); color: var(--success-text); }
  .status-b_wins { background: var(--info-bg); color: var(--info-text); }
  .status-merged { background: var(--status-merged-bg); color: var(--status-merged-text); }
  .status-dismissed { background: var(--bg-muted); color: var(--text-muted); }

  .kb-stats-bar {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 10px; background: var(--bg-subtle); border: 1px solid var(--border);
    border-radius: 6px; font-size: 0.8rem; color: var(--text-sub); margin-bottom: 10px;
  }
  .stat-item strong { color: var(--text); }
  .stat-sep { color: var(--border-strong); }
  .stat-warn strong { color: var(--warn-text2); }

  .corr-badge {
    display: inline-block; background: var(--info-bg); color: var(--info-text);
    border-radius: 10px; font-size: 0.7rem; padding: 0 6px; margin-left: 4px;
    font-weight: 600; line-height: 1.6;
  }

  .btn-correct-toggle {
    background: none; border: 1px solid var(--border-strong); border-radius: 4px;
    cursor: pointer; padding: 1px 6px; font-size: 0.85rem; color: var(--text-sub);
  }
  .btn-correct-toggle:hover { background: var(--bg-muted); }

  .correct-row td { background: var(--bg-subtle); padding: 8px 12px; }
  .correct-form { display: flex; flex-direction: column; gap: 8px; max-width: 700px; }
  .correct-label { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; color: var(--text-muted); }
  .correct-input { padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 0.85rem; }
  .correct-textarea { padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 0.8rem; font-family: monospace; resize: vertical; }
  .correct-actions { display: flex; gap: 8px; }
  .btn-secondary { padding: 4px 10px; background: var(--bg-muted); border: 1px solid var(--border-strong); border-radius: 4px; cursor: pointer; font-size: 0.8rem; }

  /* ── Vendor Doc ── */
  .vendordoc-section {
    margin-top: 2rem;
    border-top: 1px solid var(--border);
    padding-top: 1.5rem;
  }

  .vd-form { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1rem; }
  .vd-row { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end; }
  .vd-label { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; color: var(--text-muted); flex: 1; min-width: 180px; }
  .vd-input { padding: 0.4rem 0.7rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.9rem; background: var(--bg-surface); color: var(--text); }
  .vd-input-sm { min-width: 140px; max-width: 200px; }
  .vd-select { padding: 0.4rem 0.7rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.9rem; background: var(--bg-surface); color: var(--text); }
  .vd-actions { display: flex; align-items: center; gap: 1rem; }

  .vd-output { margin-top: 1rem; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .vd-doc-header { padding: 1rem 1.25rem 0.75rem; background: var(--bg-subtle); border-bottom: 1px solid var(--border); }
  .vd-title { font-size: 1.1rem; font-weight: 700; color: var(--text); margin-bottom: 0.3rem; }
  .vd-meta { display: flex; align-items: center; gap: 0.6rem; }
  .vd-template-badge { font-size: 0.72rem; font-weight: 600; background: var(--info-bg); color: var(--info-text); border-radius: 3px; padding: 0.1rem 0.45rem; text-transform: capitalize; }
  .vd-scope-note { font-size: 0.85rem; color: var(--text-sub); font-style: italic; padding: 0.5rem 1.25rem 0; margin: 0; }
  .vd-section { padding: 0.75rem 1.25rem; border-bottom: 1px solid var(--border-faint); }
  .vd-section:last-of-type { border-bottom: none; }
  .vd-section-heading { font-size: 0.9rem; font-weight: 700; color: var(--text); margin: 0 0 0.4rem; }
  .vd-section-content { font-size: 0.88rem; color: var(--text); margin: 0; line-height: 1.6; white-space: pre-wrap; }
  .vd-section-cits { display: flex; gap: 0.35rem; flex-wrap: wrap; margin-top: 0.4rem; }
  .vd-cit-tag { font-size: 0.7rem; background: var(--primary-bg); color: var(--primary); border: 1px solid var(--primary-border); border-radius: 3px; padding: 0 0.4rem; }
  .vd-citations { padding: 0.6rem 1.25rem; background: var(--bg-subtle); }
  .vd-cit-summary { font-size: 0.8rem; color: var(--text-muted); cursor: pointer; }
  .vd-cit-list { margin: 0.4rem 0 0; padding-left: 1rem; display: flex; flex-direction: column; gap: 0.2rem; list-style: disc; }
</style>
