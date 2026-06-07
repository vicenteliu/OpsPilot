<script lang="ts">
  // Wiki tab — ingest / query-to-page / lint / promote + page browser.
  import {
    wikiIngest, wikiQueryToPage, wikiLint, wikiPromote, listWikiPages, getWikiPage,
    type WikiLintIssue, type WikiPageSummary, type WikiPageDetail,
  } from '$lib/api';

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
</script>

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
