<script lang="ts">
  // Vendor Doc tab — SSE generate + saved-doc browser with JSON/Markdown export.
  import {
    generateVendorDocStream, listVendorDocs, getVendorDoc,
    type RunResponse, type VendorDoc, type VendorDocSummary,
  } from '$lib/api';

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
</script>

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
