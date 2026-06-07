<script lang="ts">
  // KB tab — docs / search / conflicts / corrections. Loads docs+stats on mount.
  import {
    getKBStats, listKBDocs, searchKB, listConflicts, resolveConflict, correctChunk, listCorrections,
    type KBDoc, type KBHit, type KBConflict, type KBStats, type KBCorrection,
  } from '$lib/api';

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

  let _loaded = false;
  $effect(() => {
    if (_loaded) return;
    _loaded = true;
    loadKBDocs();
  });
</script>

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
