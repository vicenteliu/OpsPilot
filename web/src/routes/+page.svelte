<script lang="ts">
  import '../app.css';
  import {
    getConfig, getModels, runTicketStream, listSessions, getSession,
    getKBStats, listKBDocs, searchKB, wikiIngest, wikiQueryToPage, wikiLint, wikiPromote,
    listConflicts, resolveConflict, correctChunk, listCorrections, generateVendorDocStream,
    listWikiPages, listVendorDocs, getWikiPage, getVendorDoc, chatStream,
    type RunResponse, type TicketSummary, type Task, type SessionSummary, type ModelOption,
    type KBDoc, type KBHit, type KBConflict, type KBStats, type KBCorrection, type WikiLintIssue,
    type VendorDoc, type VendorDocSection, type WikiPageSummary, type VendorDocSummary, type WikiPageDetail,
    type ChatMessage,
  } from '$lib/api';
  import GuideTab from '$lib/components/GuideTab.svelte';
  import MCPTab from '$lib/components/MCPTab.svelte';
  import IterationTab from '$lib/components/IterationTab.svelte';

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

  // --- Active Tab ---
  type Tab = 'run' | 'kb' | 'wiki' | 'vendordoc' | 'mcp' | 'iteration' | 'chat' | 'guide';
  let activeTab = $state<Tab>('run');

  // --- Core State ---
  let modelRef = $state<string | null>(null);
  let modules = $state<Record<string, boolean>>({ run: true, history: true });
  let availableModels = $state<ModelOption[]>([]);
  let selectedModelId = $state<string>('');
  let modelsLoaded = $state<boolean>(false);

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

  // --- KB ---
  let kbStats = $state<KBStats | null>(null);
  let kbDocs = $state<KBDoc[]>([]);
  let kbDocsLoading = $state<boolean>(false);
  let kbSearchQuery = $state<string>('');
  let kbSearchResults = $state<KBHit[]>([]);
  let kbSearchLoading = $state<boolean>(false);
  let kbSearchError = $state<string | null>(null);
  let kbSection = $state<'docs' | 'search' | 'conflicts' | 'corrections'>('docs');
  let kbCorrections = $state<KBCorrection[]>([]);
  let correctionsLoading = $state<boolean>(false);
  let correctionsError = $state<string | null>(null);
  let kbConflicts = $state<KBConflict[]>([]);
  let conflictsLoading = $state<boolean>(false);
  let conflictsError = $state<string | null>(null);
  let conflictStatusFilter = $state<'open' | 'all'>('open');
  let resolving = $state<Record<string, boolean>>({});
  let correctingChunkId = $state<string | null>(null);
  let correctReason = $state<string>('');
  let correctContent = $state<string>('');
  let correctLoading = $state<boolean>(false);
  let correctError = $state<string | null>(null);

  // --- Wiki ---
  let wikiDocId = $state<string>('');
  let wikiSessionId = $state<string>('');
  let wikiLoading = $state<boolean>(false);
  let wikiMsg = $state<string | null>(null);
  let wikiError = $state<string | null>(null);
  let wikiLintIssues = $state<WikiLintIssue[]>([]);
  let wikiLintLoading = $state<boolean>(false);
  let wikiPages = $state<WikiPageSummary[]>([]);
  let wikiPagesLoading = $state<boolean>(false);
  let wikiPageDetail = $state<WikiPageDetail | null>(null);
  let wikiPageDetailSlug = $state<string | null>(null);
  let wikiPageDetailLoading = $state<boolean>(false);

  // --- Vendor Doc ---
  let vendorDocList = $state<VendorDocSummary[]>([]);
  let vendorDocListLoading = $state<boolean>(false);
  let vendorDocDetail = $state<VendorDoc | null>(null);
  let vendorDocDetailFilename = $state<string | null>(null);
  let vendorDocDetailLoading = $state<boolean>(false);
  let vendorDocTopic = $state<string>('');
  let vendorDocTemplateId = $state<string>('sop_summary');
  let vendorDocVendorName = $state<string>('');
  let vendorDocLoading = $state<boolean>(false);
  let vendorDocStatusLines = $state<string[]>([]);
  let vendorDocResult = $state<VendorDoc | null>(null);
  let vendorDocError = $state<string | null>(null);
  let vendorDocUsage = $state<RunResponse['usage'] | null>(null);

  // --- Chat ---
  let chatMessages = $state<ChatMessage[]>([]);
  let chatInput = $state<string>('');
  let chatLoading = $state<boolean>(false);
  let chatStatusLines = $state<string[]>([]);
  let chatError = $state<string | null>(null);
  let chatUsage = $state<{ input_tokens: number; output_tokens: number; cost_usd: number } | null>(null);

  // --- Derived ---
  let summary = $derived(result?.result ?? null);
  let runError = $derived(result?.error ?? null);

  // --- Init ---
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
        // models unavailable
      } finally {
        modelsLoaded = true;
      }
      if (modules.history) await refreshHistory();
      await loadKBDocs();
    })();
  });

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

  // --- KB Handlers ---
  async function loadKBStats() {
    try { kbStats = await getKBStats(); } catch { /* non-critical */ }
  }

  async function loadKBDocs() {
    kbDocsLoading = true;
    try { [kbDocs] = await Promise.all([listKBDocs(), loadKBStats()]); }
    catch { kbDocs = []; }
    finally { kbDocsLoading = false; }
  }

  async function loadCorrections() {
    correctionsLoading = true;
    correctionsError = null;
    try { kbCorrections = await listCorrections(); await loadKBStats(); }
    catch (e) { correctionsError = e instanceof Error ? e.message : String(e); }
    finally { correctionsLoading = false; }
  }

  async function handleKBSearch() {
    if (!kbSearchQuery.trim()) return;
    kbSearchLoading = true;
    kbSearchError = null;
    kbSearchResults = [];
    try { kbSearchResults = await searchKB(kbSearchQuery.trim()); }
    catch (e) { kbSearchError = e instanceof Error ? e.message : String(e); }
    finally { kbSearchLoading = false; }
  }

  async function handleCorrect(chunkId: string) {
    if (!correctReason.trim() || !correctContent.trim()) return;
    correctLoading = true;
    correctError = null;
    try {
      await correctChunk(chunkId, correctContent.trim(), correctReason.trim());
      if (kbSearchQuery.trim()) kbSearchResults = await searchKB(kbSearchQuery.trim());
      await loadKBStats();
      correctingChunkId = null;
      correctReason = '';
      correctContent = '';
    } catch (e) { correctError = e instanceof Error ? e.message : String(e); }
    finally { correctLoading = false; }
  }

  // --- Wiki Handlers ---
  async function handleWikiIngest() {
    if (!wikiDocId.trim()) return;
    wikiLoading = true; wikiMsg = null; wikiError = null;
    try {
      const r = await wikiIngest(wikiDocId.trim());
      wikiMsg = `✓ Created wiki page: ${r.slug}`;
    } catch (e) { wikiError = e instanceof Error ? e.message : String(e); }
    finally { wikiLoading = false; }
  }

  async function handleWikiQueryToPage() {
    wikiLoading = true; wikiMsg = null; wikiError = null;
    try {
      const r = await wikiQueryToPage(wikiSessionId.trim() || undefined);
      wikiMsg = `✓ ${r.pages_created} page(s) created`;
    } catch (e) { wikiError = e instanceof Error ? e.message : String(e); }
    finally { wikiLoading = false; }
  }

  async function handleWikiLint() {
    wikiLintLoading = true;
    try { wikiLintIssues = await wikiLint(); }
    catch { wikiLintIssues = []; }
    finally { wikiLintLoading = false; }
  }

  async function handleWikiPromote(slug: string) {
    wikiLoading = true; wikiMsg = null; wikiError = null;
    try {
      const r = await wikiPromote(slug);
      wikiMsg = r.skipped ? `Skipped: ${r.skip_reason}` : `✓ ${slug}: ${r.old_state} → ${r.new_state}`;
    } catch (e) { wikiError = e instanceof Error ? e.message : String(e); }
    finally { wikiLoading = false; }
  }

  async function loadWikiPages() {
    wikiPagesLoading = true;
    try { wikiPages = await listWikiPages(); }
    catch { wikiPages = []; }
    finally { wikiPagesLoading = false; }
  }

  async function openWikiPage(slug: string) {
    if (wikiPageDetailSlug === slug) { wikiPageDetail = null; wikiPageDetailSlug = null; return; }
    wikiPageDetailLoading = true;
    wikiPageDetailSlug = slug;
    try { wikiPageDetail = await getWikiPage(slug); }
    catch { wikiPageDetail = null; }
    finally { wikiPageDetailLoading = false; }
  }

  // --- Vendor Doc Handlers ---
  async function loadVendorDocList() {
    vendorDocListLoading = true;
    try { vendorDocList = await listVendorDocs(); }
    catch { vendorDocList = []; }
    finally { vendorDocListLoading = false; }
  }

  async function openVendorDoc(filename: string) {
    if (vendorDocDetailFilename === filename) { vendorDocDetail = null; vendorDocDetailFilename = null; return; }
    vendorDocDetailLoading = true;
    vendorDocDetailFilename = filename;
    try { vendorDocDetail = await getVendorDoc(filename); }
    catch { vendorDocDetail = null; }
    finally { vendorDocDetailLoading = false; }
  }

  function downloadVendorDocJson() {
    if (!vendorDocDetail) return;
    const blob = new Blob([JSON.stringify(vendorDocDetail, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${vendorDocDetail.doc_ref}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function vendorDocToMarkdown(doc: VendorDoc): string {
    const lines: string[] = [`# ${doc.title}`, ''];
    if (doc.scope_note) lines.push(`> ${doc.scope_note}`, '');
    for (const s of doc.sections) lines.push(`## ${s.heading}`, '', s.content, '');
    if (doc.citations.length > 0) {
      lines.push('## Sources', '');
      for (const c of doc.citations)
        lines.push(`- **${c.id}** — ${c.source_path || c.document_id}${c.line_start ? ` L${c.line_start}–${c.line_end}` : ''}`);
    }
    return lines.join('\n');
  }

  function downloadVendorDocMarkdown() {
    if (!vendorDocDetail) return;
    const blob = new Blob([vendorDocToMarkdown(vendorDocDetail)], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${vendorDocDetail.doc_ref}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function handleGenerateVendorDoc() {
    if (!vendorDocTopic.trim()) return;
    vendorDocLoading = true;
    vendorDocStatusLines = [];
    vendorDocError = null;
    vendorDocResult = null;
    vendorDocUsage = null;
    try {
      for await (const event of generateVendorDocStream({
        topic: vendorDocTopic.trim(),
        template_id: vendorDocTemplateId,
        vendor_name: vendorDocVendorName.trim(),
        language: 'en',
      })) {
        if (event.type === 'status') vendorDocStatusLines = [...vendorDocStatusLines, event.message];
        else if (event.type === 'result') {
          vendorDocResult = event.data.result as unknown as VendorDoc;
          vendorDocUsage = event.data.usage;
          if (event.data.error) vendorDocError = event.data.error;
        } else if (event.type === 'error') {
          vendorDocError = event.message;
        }
      }
    } catch (e) { vendorDocError = e instanceof Error ? e.message : String(e); }
    finally { vendorDocLoading = false; }
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

  // --- Conflict Handlers ---
  async function loadConflicts() {
    conflictsLoading = true; conflictsError = null;
    try { kbConflicts = await listConflicts(conflictStatusFilter); }
    catch (e) { conflictsError = e instanceof Error ? e.message : String(e); kbConflicts = []; }
    finally { conflictsLoading = false; }
  }

  async function handleResolve(conflictId: string, resolution: string) {
    resolving = { ...resolving, [conflictId]: true };
    try { await resolveConflict(conflictId, resolution); await loadConflicts(); }
    catch (e) { conflictsError = e instanceof Error ? e.message : String(e); }
    finally { resolving = { ...resolving, [conflictId]: false }; }
  }

  // --- Chat Handlers ---
  async function handleChat() {
    if (!chatInput.trim() || chatLoading) return;
    const userMsg = chatInput.trim();
    chatInput = '';
    chatMessages = [...chatMessages, { role: 'user', content: userMsg }];
    chatLoading = true;
    chatStatusLines = [];
    chatError = null;
    try {
      for await (const event of chatStream([...chatMessages], selectedModelId || undefined)) {
        if (event.type === 'status') {
          chatStatusLines = [...chatStatusLines, event.message];
        } else if (event.type === 'result') {
          chatMessages = [...chatMessages, { role: 'assistant', content: event.data.content }];
          chatUsage = event.data.usage;
        } else if (event.type === 'error') {
          chatError = event.message;
        }
      }
    } catch (e) {
      chatError = e instanceof Error ? e.message : String(e);
    } finally {
      chatLoading = false;
      chatStatusLines = [];
    }
  }

  function handleChatKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleChat();
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

  <!-- Tab Navigation -->
  <nav class="tab-nav">
    {#each ([
      { id: 'run', label: 'Run' },
      { id: 'chat', label: 'Chat' },
      { id: 'kb', label: 'Knowledge Base' },
      { id: 'wiki', label: 'Wiki' },
      { id: 'vendordoc', label: 'Vendor Docs' },
      { id: 'mcp', label: 'MCP' },
      { id: 'iteration', label: 'Iteration' },
      { id: 'guide', label: 'Guide' },
    ] as const) as tab}
      <button
        class="nav-tab {activeTab === tab.id ? 'active' : ''}"
        onclick={() => activeTab = tab.id}
      >{tab.label}</button>
    {/each}
  </nav>

  <main>

    <!-- ══════════════════════════════ RUN TAB ══════════════════════════════ -->
    {#if activeTab === 'run'}
      <section class="input-section">
        <div class="input-section-header">
          <h2>Ticket Input</h2>
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
            placeholder="Paste ticket JSON here..."
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
    {/if}

    <!-- ══════════════════════════════ CHAT TAB ══════════════════════════════ -->
    {#if activeTab === 'chat'}
      <section class="chat-section">
        <div class="chat-messages" id="chat-messages">
          {#if chatMessages.length === 0}
            <div class="chat-empty">
              <p>Ask anything about your IT operations. OpsPilot will search the knowledge base and answer.</p>
              <div class="chat-suggestions">
                <button class="suggestion-btn" onclick={() => { chatInput = 'How do I troubleshoot VPN authentication failures?'; handleChat(); }}>
                  VPN authentication failures
                </button>
                <button class="suggestion-btn" onclick={() => { chatInput = 'What are common causes of network connectivity issues?'; handleChat(); }}>
                  Network connectivity issues
                </button>
                <button class="suggestion-btn" onclick={() => { chatInput = 'How do I reset a user password?'; handleChat(); }}>
                  Reset user password
                </button>
              </div>
            </div>
          {:else}
            {#each chatMessages as msg}
              <div class="chat-bubble {msg.role}">
                <div class="bubble-content">{msg.content}</div>
              </div>
            {/each}
            {#if chatLoading && chatStatusLines.length > 0}
              <div class="chat-bubble assistant">
                <div class="bubble-content chat-thinking">
                  {chatStatusLines[chatStatusLines.length - 1]}…
                </div>
              </div>
            {/if}
          {/if}
        </div>

        {#if chatError}
          <div class="error-banner" style="margin: 0.5rem 0"><strong>Error:</strong> {chatError}</div>
        {/if}

        <div class="chat-input-row">
          <textarea
            class="chat-input"
            rows={2}
            bind:value={chatInput}
            placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
            disabled={chatLoading}
            onkeydown={handleChatKeydown}
          ></textarea>
          <button class="btn-chat-send" onclick={handleChat} disabled={chatLoading || !chatInput.trim()}>
            {#if chatLoading}
              <span class="spinner"></span>
            {:else}
              ↑
            {/if}
          </button>
        </div>

        <div class="chat-footer">
          {#if chatUsage}
            <span class="usage-badge">
              ↑ {chatUsage.input_tokens.toLocaleString()} / ↓ {chatUsage.output_tokens.toLocaleString()} tokens
              {#if chatUsage.cost_usd > 0}· ${chatUsage.cost_usd.toFixed(4)}{/if}
            </span>
          {/if}
          {#if chatMessages.length > 0}
            <button class="btn-sm" onclick={() => { chatMessages = []; chatUsage = null; chatError = null; }}>
              Clear chat
            </button>
          {/if}
        </div>
      </section>
    {/if}

    <!-- ══════════════════════════════ KB TAB ══════════════════════════════ -->
    {#if activeTab === 'kb'}
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
            <input class="search-input" bind:value={kbSearchQuery} placeholder="Search KB…"
              onkeydown={(e) => e.key === 'Enter' && handleKBSearch()} />
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
                <tr><th>Type</th><th>Sim</th><th>Doc A</th><th>Doc B</th><th>Status</th><th>Actions</th></tr>
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
                <tr><th>ID</th><th>Chunk</th><th>By</th><th>Reason</th><th>Old content</th><th>New content</th><th>Created</th></tr>
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
    {/if}

    <!-- ══════════════════════════════ WIKI TAB ══════════════════════════════ -->
    {#if activeTab === 'wiki'}
      <section class="wiki-section">
        <div class="section-header"><h2>Wiki</h2></div>
        <div class="action-row">
          <input class="short-input" bind:value={wikiDocId} placeholder="KB doc_id for ingest…" />
          <button class="btn-action" onclick={handleWikiIngest} disabled={wikiLoading || !wikiDocId.trim()}>Ingest KB Doc</button>
          <input class="short-input" bind:value={wikiSessionId} placeholder="Session ID (blank=scan all)" />
          <button class="btn-action" onclick={handleWikiQueryToPage} disabled={wikiLoading}>Query→Page</button>
          <button class="btn-action btn-secondary" onclick={handleWikiLint} disabled={wikiLintLoading}>
            {wikiLintLoading ? '…' : 'Lint'}
          </button>
        </div>
        {#if wikiMsg}<p class="section-ok">{wikiMsg}</p>{/if}
        {#if wikiError}<p class="section-error">{wikiError}</p>{/if}
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
        {:else if !wikiLintLoading}
          <p class="section-empty">Run lint to check wiki pages.</p>
        {/if}
        <div class="action-row" style="margin-top:1rem">
          <button class="btn-action btn-secondary" onclick={loadWikiPages} disabled={wikiPagesLoading}>
            {wikiPagesLoading ? '…' : 'List Pages'}
          </button>
        </div>
        {#if wikiPages.length > 0}
          <table class="data-table" style="margin-top:0.5rem">
            <thead><tr><th>Slug</th><th>Kind</th><th>Title</th><th>State</th><th>Lang</th></tr></thead>
            <tbody>
              {#each wikiPages as p}
                <tr class="clickable-row" onclick={() => openWikiPage(p.slug)}
                    class:expanded-row={wikiPageDetailSlug === p.slug}>
                  <td class="mono">{p.slug}</td>
                  <td><span class="sev-badge sev-info">{p.kind}</span></td>
                  <td>{p.title}</td>
                  <td><span class="sev-badge sev-{p.lifecycle_state === 'live' ? 'ok' : 'warn'}">{p.lifecycle_state}</span></td>
                  <td class="mono dim">{p.language}</td>
                </tr>
                {#if wikiPageDetailSlug === p.slug}
                  <tr class="detail-row">
                    <td colspan="5">
                      {#if wikiPageDetailLoading}
                        <p class="dim" style="padding:0.5rem">Loading…</p>
                      {:else if wikiPageDetail}
                        <div class="wiki-detail">
                          <p class="wiki-detail-summary dim">{wikiPageDetail.summary}</p>
                          {#if wikiPageDetail.tags.length > 0}
                            <div class="wiki-detail-tags">
                              {#each wikiPageDetail.tags as tag}<span class="sev-badge sev-info">{tag}</span>{/each}
                            </div>
                          {/if}
                          <pre class="wiki-detail-body">{wikiPageDetail.body}</pre>
                        </div>
                      {/if}
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        {:else if !wikiPagesLoading}
          <p class="section-empty" style="margin-top:0.5rem">No pages yet — click List Pages.</p>
        {/if}
      </section>
    {/if}

    <!-- ══════════════════════════ VENDOR DOCS TAB ══════════════════════════ -->
    {#if activeTab === 'vendordoc'}
      <section class="vendordoc-section">
        <div class="section-header">
          <h2>Vendor Document</h2>
          {#if vendorDocResult}
            <button class="btn-action btn-secondary" onclick={copyVendorDoc}>Copy as Markdown</button>
          {/if}
        </div>
        <div class="vd-form">
          <div class="vd-row">
            <label class="vd-label">Topic
              <input class="vd-input" bind:value={vendorDocTopic}
                placeholder="e.g. VPN authentication failure troubleshooting"
                disabled={vendorDocLoading} />
            </label>
            <label class="vd-label">Template
              <select class="vd-select" bind:value={vendorDocTemplateId} disabled={vendorDocLoading}>
                <option value="sop_summary">SOP Summary</option>
                <option value="maintenance_window">Maintenance Window</option>
                <option value="incident_report">Incident Report</option>
                <option value="handover">Handover Checklist</option>
              </select>
            </label>
            <label class="vd-label">Vendor (optional)
              <input class="vd-input vd-input-sm" bind:value={vendorDocVendorName}
                placeholder="e.g. SecureNet Ltd" disabled={vendorDocLoading} />
            </label>
          </div>
          <div class="vd-actions">
            <button class="btn-run" onclick={handleGenerateVendorDoc}
              disabled={vendorDocLoading || !vendorDocTopic.trim()}>
              {#if vendorDocLoading}<span class="spinner"></span> Generating…{:else}Generate{/if}
            </button>
            {#if vendorDocUsage}
              <span class="usage-badge">
                ↑ {vendorDocUsage.input_tokens.toLocaleString()} / ↓ {vendorDocUsage.output_tokens.toLocaleString()} tokens
                {#if vendorDocUsage.cost_usd > 0}· ${vendorDocUsage.cost_usd.toFixed(4)}{/if}
              </span>
            {/if}
          </div>
        </div>
        {#if vendorDocStatusLines.length > 0}
          <div class="status-log" style="margin-top:0.75rem">
            {#each vendorDocStatusLines as line}<div class="status-line">› {line}</div>{/each}
            {#if vendorDocLoading}<div class="status-line status-line--active">…</div>{/if}
          </div>
        {/if}
        {#if vendorDocError}<p class="section-error" style="margin-top:0.5rem">{vendorDocError}</p>{/if}
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
            {#if vendorDocResult.scope_note}<p class="vd-scope-note">{vendorDocResult.scope_note}</p>{/if}
            {#each vendorDocResult.sections as section}
              <div class="vd-section">
                <h4 class="vd-section-heading">{section.heading}</h4>
                <p class="vd-section-content">{section.content}</p>
                {#if section.citations.length > 0}
                  <div class="vd-section-cits">
                    {#each section.citations as cit}<span class="vd-cit-tag">{cit}</span>{/each}
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
        <div class="action-row" style="margin-top:1rem">
          <button class="btn-action btn-secondary" onclick={loadVendorDocList} disabled={vendorDocListLoading}>
            {vendorDocListLoading ? '…' : 'List Saved Docs'}
          </button>
        </div>
        {#if vendorDocList.length > 0}
          <table class="data-table" style="margin-top:0.5rem">
            <thead><tr><th>Doc Ref</th><th>Template</th><th>Title</th><th>§</th><th>Cit.</th></tr></thead>
            <tbody>
              {#each vendorDocList as d}
                <tr class="clickable-row" onclick={() => openVendorDoc(d.filename)}
                    class:expanded-row={vendorDocDetailFilename === d.filename}>
                  <td class="mono">{d.doc_ref}</td>
                  <td><span class="sev-badge sev-info">{d.template_id.replace(/_/g, ' ')}</span></td>
                  <td>{d.title.slice(0, 55)}{d.title.length > 55 ? '…' : ''}</td>
                  <td class="mono">{d.sections_count}</td>
                  <td class="mono">{d.citations_count}</td>
                </tr>
                {#if vendorDocDetailFilename === d.filename}
                  <tr class="detail-row">
                    <td colspan="5">
                      {#if vendorDocDetailLoading}
                        <p class="dim" style="padding:0.5rem">Loading…</p>
                      {:else if vendorDocDetail}
                        <div class="vd-output" style="margin:0;border-radius:0">
                          <div class="vd-doc-header">
                            <div>
                              <div class="vd-title">{vendorDocDetail.title}</div>
                              <div class="vd-meta">
                                <span class="vd-ref mono dim">{vendorDocDetail.doc_ref}</span>
                                <span class="vd-template-badge">{vendorDocDetail.template_id.replace(/_/g, ' ')}</span>
                              </div>
                            </div>
                            <div style="display:flex;gap:0.5rem;align-items:center">
                              <button class="btn-sm" onclick={downloadVendorDocJson}>↓ JSON</button>
                              <button class="btn-sm" onclick={downloadVendorDocMarkdown}>↓ Markdown</button>
                            </div>
                          </div>
                          {#if vendorDocDetail.scope_note}<p class="vd-scope-note">{vendorDocDetail.scope_note}</p>{/if}
                          {#each vendorDocDetail.sections as section}
                            <div class="vd-section">
                              <h4 class="vd-section-heading">{section.heading}</h4>
                              <p class="vd-section-content">{section.content}</p>
                            </div>
                          {/each}
                          {#if vendorDocDetail.citations.length > 0}
                            <details class="vd-citations">
                              <summary class="vd-cit-summary">Sources ({vendorDocDetail.citations.length})</summary>
                              <ul class="vd-cit-list">
                                {#each vendorDocDetail.citations as c}
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
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        {:else if !vendorDocListLoading}
          <p class="section-empty" style="margin-top:0.5rem">No saved docs — click List Saved Docs.</p>
        {/if}
      </section>
    {/if}

    <!-- ══════════════════════════════ MCP TAB ══════════════════════════════ -->
    {#if activeTab === 'mcp'}
      <MCPTab />
    {/if}

    <!-- ══════════════════════════ ITERATION TAB ══════════════════════════ -->
    {#if activeTab === 'iteration' && modules.iteration !== false}
      <IterationTab />
    {/if}

    {#if activeTab === 'guide'}
      <GuideTab />
    {/if}

  </main>
</div>

<style>
  .app {
    max-width: 960px;
    margin: 0 auto;
    padding: 1.5rem;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
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

  .model-select:disabled { opacity: 0.6; cursor: not-allowed; }

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

  .theme-toggle:hover { background: var(--bg-muted); color: var(--text); }

  /* ── Tab Navigation ── */
  .tab-nav {
    display: flex;
    gap: 0.25rem;
    border-bottom: 2px solid var(--border);
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
  }

  .nav-tab {
    padding: 0.5rem 1rem;
    font-size: 0.9rem;
    font-weight: 500;
    color: var(--text-muted);
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }

  .nav-tab:hover { color: var(--text); }

  .nav-tab.active {
    color: var(--primary);
    border-bottom-color: var(--primary);
    font-weight: 600;
  }

  /* ── Input Section ── */
  .input-section { margin-bottom: 1.5rem; }

  .input-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
  }

  .input-section-header h2 {
    font-size: 1.1rem;
    color: var(--text);
    margin: 0;
  }

  .mode-toggle {
    display: flex;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    overflow: hidden;
  }

  .mode-btn {
    padding: 0.25rem 0.75rem;
    font-size: 0.8rem;
    background: var(--bg-subtle);
    color: var(--text-muted);
    border: none;
    cursor: pointer;
  }

  .mode-btn.active {
    background: var(--primary);
    color: #fff;
    font-weight: 600;
  }

  .mode-btn:not(.active):hover { background: var(--bg-muted); }

  textarea {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--bg-surface);
    margin-bottom: 0.75rem;
    font-size: 0.9rem;
    color: var(--text);
    resize: vertical;
  }

  .nl-textarea { font-size: 1rem; line-height: 1.6; }

  .run-row { display: flex; align-items: center; gap: 1rem; }

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
    cursor: pointer;
  }

  .btn-run:disabled { opacity: 0.6; cursor: not-allowed; }

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

  @keyframes spin { to { transform: rotate(360deg); } }

  .status-log {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 12px;
    font-family: monospace;
    font-size: 0.82rem;
  }

  .status-line { color: var(--text-muted, #888); line-height: 1.6; }
  .status-line--active { animation: blink 1s step-start infinite; }
  @keyframes blink { 50% { opacity: 0; } }

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
    margin-bottom: 1.5rem;
  }

  @media (max-width: 640px) { .cards { grid-template-columns: 1fr; } }

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
    cursor: pointer;
  }

  .btn-copy:hover { background: var(--bg-hover); }

  .card ul, .card ol { margin: 0; padding-left: 1.25rem; }
  .card li { margin-bottom: 0.4rem; font-size: 0.95rem; }
  .rationale { margin: 0.2rem 0 0.6rem; color: var(--text-muted); font-size: 0.88rem; }

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

  .tier-badge {
    display: inline-block;
    margin-right: 0.4rem;
    padding: 0.05rem 0.45rem;
    border-radius: 9999px;
    font-weight: 700;
    font-size: 0.75rem;
    vertical-align: middle;
    border: 1px solid var(--border);
    color: var(--text-muted);
  }
  .tier-badge.tier-L1 { background: #e6f4ea; color: #1e7e34; border-color: #b7dfc2; }
  .tier-badge.tier-L2 { background: #fff4e5; color: #b26a00; border-color: #f0d2a0; }
  .tier-badge.tier-L3 { background: #fde8e8; color: #b02a37; border-color: #f2c0c4; }

  .wi-badge {
    display: inline-block;
    padding: 0.05rem 0.45rem;
    border-radius: 9999px;
    font-weight: 700;
    font-size: 0.8rem;
    background: var(--accent-bg, #e8f0fe);
    color: var(--accent-text, #1a56db);
    border: 1px solid var(--border);
  }
  .confirm-banner {
    margin: 0.75rem 0;
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    background: var(--warn-bg);
    border: 1px solid var(--warn-border);
  }
  .confirm-banner p { margin: 0 0 0.6rem; }
  .confirm-actions { display: flex; gap: 0.5rem; }
  .btn-confirm {
    padding: 0.4rem 0.9rem;
    border-radius: 0.4rem;
    border: 1px solid var(--border);
    background: var(--surface, #fff);
    cursor: pointer;
    font-weight: 600;
  }
  .btn-confirm:hover { background: var(--accent-bg, #e8f0fe); }
  .classified-note { margin: 0.5rem 0; color: var(--text-muted); font-size: 0.9rem; }

  .wi-type-label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  .wi-type-select {
    padding: 0.4rem 0.6rem;
    border-radius: 0.4rem;
    border: 1px solid var(--border);
    background: var(--surface, #fff);
    font-size: 0.9rem;
  }

  .escalation { margin-top: 0.5rem; font-size: 0.9rem; color: var(--warn-text2); }

  /* ── History ── */
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

  .history-header h2 { font-size: 1.1rem; color: var(--text); margin: 0; }


  .history-empty { color: var(--text-faint); font-size: 0.9rem; }

  .history-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }

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

  .col-time { color: var(--text-sub); white-space: nowrap; }

  .status-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .status-archived { background: var(--success-bg); color: var(--success-text); }
  .status-aborted { background: var(--error-bg); color: var(--error-text); }
  .status-active { background: var(--sev-medium-bg); color: var(--warn-text); }

  .btn-view {
    font-size: 0.8rem;
    padding: 0.2rem 0.6rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--primary);
    cursor: pointer;
  }

  .btn-view:hover { background: var(--bg-hover); }

  .expanded-row td { padding: 0.75rem; background: var(--bg-subtle); border-bottom: 2px solid var(--border); }
  .clickable-row { cursor: pointer; }
  .clickable-row:hover td { background: var(--bg-hover); }
  .detail-row td { padding: 0; background: var(--bg-subtle); border-bottom: 2px solid var(--border-strong); }

  .col-sid { font-family: 'Courier New', monospace; font-size: 0.78rem; color: var(--text-muted); white-space: nowrap; }

  .session-detail { padding: 0.75rem 1.25rem 1rem; }
  .session-detail-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; font-size: 0.82rem; }

  /* ── Chat ── */
  .chat-section {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 200px);
    min-height: 400px;
  }

  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 1rem 0;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .chat-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
    text-align: center;
    gap: 1rem;
  }

  .chat-suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    justify-content: center;
    margin-top: 0.5rem;
  }

  .suggestion-btn {
    padding: 0.4rem 0.9rem;
    font-size: 0.85rem;
    background: var(--bg-subtle);
    border: 1px solid var(--border-strong);
    border-radius: 9999px;
    color: var(--primary);
    cursor: pointer;
  }

  .suggestion-btn:hover { background: var(--bg-muted); }

  .chat-bubble {
    display: flex;
    max-width: 80%;
  }

  .chat-bubble.user {
    align-self: flex-end;
    flex-direction: row-reverse;
  }

  .chat-bubble.assistant { align-self: flex-start; }

  .bubble-content {
    padding: 0.65rem 0.9rem;
    border-radius: 12px;
    font-size: 0.95rem;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .chat-bubble.user .bubble-content {
    background: var(--primary);
    color: #fff;
    border-bottom-right-radius: 3px;
  }

  .chat-bubble.assistant .bubble-content {
    background: var(--bg-subtle);
    color: var(--text);
    border: 1px solid var(--border);
    border-bottom-left-radius: 3px;
  }

  .chat-thinking { color: var(--text-muted); font-style: italic; }

  .chat-input-row {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
    margin-top: 1rem;
    border-top: 1px solid var(--border);
    padding-top: 1rem;
  }

  .chat-input {
    flex: 1;
    margin: 0;
    resize: none;
    border-radius: 8px;
  }

  .btn-chat-send {
    width: 42px;
    height: 42px;
    background: var(--primary);
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 1.1rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
  }

  .btn-chat-send:disabled { opacity: 0.5; cursor: not-allowed; }

  .chat-footer {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0 0;
    min-height: 1.5rem;
  }

  /* ── KB, Wiki, Sections ── */
  .kb-section, .wiki-section, .vendordoc-section {
    padding-top: 0.5rem;
  }

  .section-tabs { display: flex; gap: 0.25rem; }

  .tab-btn {
    font-size: 0.8rem;
    padding: 0.2rem 0.7rem;
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    background: var(--bg-subtle);
    color: var(--text-sub);
    cursor: pointer;
  }

  .tab-btn.active { background: var(--primary); color: #fff; border-color: var(--primary); }

  .dim { color: var(--text-faint); }

  .snippet { color: var(--text-sub); font-size: 0.82rem; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .search-row { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
  .search-input { flex: 1; padding: 0.45rem 0.75rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.9rem; }

  .action-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; align-items: center; }
  .short-input { padding: 0.4rem 0.7rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.85rem; width: 200px; }

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

  .btn-action:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-action.btn-secondary { background: var(--bg-muted); color: var(--primary); border: 1px solid var(--border-strong); }

  .btn-sm {
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--primary);
    cursor: pointer;
  }

  .sev-badge { font-size: 0.72rem; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 3px; }
  .sev-critical { background: var(--error-bg); color: var(--error-text); }
  .sev-high { background: var(--sev-high-bg); color: var(--sev-high-text); }
  .sev-medium { background: var(--sev-medium-bg); color: var(--warn-text); }
  .sev-low { background: var(--success-bg); color: var(--success-text); }
  .sev-ok { background: var(--success-bg); color: var(--success-text); }
  .sev-warn { background: var(--warn-bg); color: var(--warn-text); }
  .sev-info { background: var(--info-bg); color: var(--info-text); }

  /* ── Conflicts ── */
  .conflict-badge {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 16px; height: 16px; padding: 0 4px;
    background: var(--error-badge); color: #fff; border-radius: 9999px;
    font-size: 0.65rem; font-weight: 700; margin-left: 4px; vertical-align: middle;
  }

  .conflict-toolbar { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .filter-label { font-size: 0.85rem; color: var(--text-sub); display: flex; align-items: center; gap: 0.4rem; }
  .filter-label select { font-size: 0.85rem; padding: 0.2rem 0.5rem; border: 1px solid var(--border-strong); border-radius: 4px; }
  .conflict-table td { vertical-align: top; padding: 0.5rem 0.65rem; }
  .conflict-doc { font-size: 0.85rem; font-weight: 500; color: var(--text); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chunk-preview { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.2rem; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .conflict-type-badge { font-size: 0.72rem; font-weight: 600; padding: 0.1rem 0.45rem; border-radius: 3px; white-space: nowrap; }
  .ctype-temporal_supersede { background: var(--info-bg); color: var(--info-text); }
  .ctype-direct_contradiction { background: var(--error-bg); color: var(--error-text); }
  .ctype-scope_overlap { background: var(--sev-medium-bg); color: var(--warn-text); }
  .resolve-btns { display: flex; flex-direction: column; gap: 0.3rem; }
  .btn-a-wins { background: var(--success-bg); color: var(--success-text); border-color: var(--success-border); }
  .btn-b-wins { background: var(--info-bg); color: var(--info-text); border-color: var(--info-border); }
  .row-conflict { background: var(--row-conflict-bg); }
  .warn-badge { display: inline-block; margin-left: 4px; color: var(--warn-text2); font-size: 0.85rem; cursor: help; }

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

  /* ── Wiki ── */
  .wiki-detail { padding: 1rem 1.25rem; }
  .wiki-detail-summary { margin: 0 0 0.5rem; font-style: italic; }
  .wiki-detail-tags { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.75rem; }
  .wiki-detail-body {
    margin: 0; padding: 0.75rem 1rem; background: var(--bg-surface);
    border: 1px solid var(--border); border-radius: 6px; font-size: 0.82rem;
    line-height: 1.6; white-space: pre-wrap; word-break: break-word;
    max-height: 480px; overflow-y: auto; font-family: 'Courier New', monospace; color: var(--text);
  }

  /* ── Vendor Doc ── */
  .vd-form { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1rem; }
  .vd-row { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end; }
  .vd-label { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; color: var(--text-muted); flex: 1; min-width: 180px; }
  .vd-input { padding: 0.4rem 0.7rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.9rem; background: var(--bg-surface); color: var(--text); }
  .vd-input-sm { min-width: 140px; max-width: 200px; }
  .vd-select { padding: 0.4rem 0.7rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.9rem; background: var(--bg-surface); color: var(--text); }
  .vd-actions { display: flex; align-items: center; gap: 1rem; }
  .vd-output { margin-top: 1rem; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .vd-doc-header { padding: 1rem 1.25rem 0.75rem; background: var(--bg-subtle); border-bottom: 1px solid var(--border); display: flex; align-items: flex-start; justify-content: space-between; }
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
  .vd-ref { font-size: 0.78rem; }


</style>
