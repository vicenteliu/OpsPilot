<script lang="ts">
  // Inventory tab — Asset list / detail with event timeline / create & edit
  // forms (ADR-0017). The row is a projection; the event log is the history.
  import {
    ASSET_STATUSES, listAssets, getAsset, createAsset, updateAsset, deleteAsset,
    createProcurement, getProcurement, updateProcurement, deleteProcurement,
    type Asset, type AssetDetail, type AssetFields, type ProcurementDetail, type ProcurementFields,
  } from '$lib/api';

  const EMPTY_FORM: AssetFields = {
    asset_tag: '', category: '', brand_model: '', serial_number: '', specs: '', notes: '',
    work_item_ref: '', pr_number: '', order_number: '', tracking_number: '', vendor: '', cost: '',
    status: 'requested', handler: '', assignee: '', location: '', warranty_until: '',
  };

  let view = $state<'list' | 'new' | 'detail'>('list');
  let assets = $state<Asset[]>([]);
  let listLoading = $state<boolean>(false);
  let listError = $state<string | null>(null);
  let statusFilter = $state<string>('');
  let warrantyFilter = $state<string>('');
  let query = $state<string>('');

  // Warranty ending within 30 days (or already ended) gets the warn style.
  const WARN_CUTOFF = new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 10);
  function warrantyWarn(until: string): boolean {
    return !!until && until.slice(0, 10) <= WARN_CUTOFF;
  }

  let detail = $state<AssetDetail | null>(null);
  let detailError = $state<string | null>(null);

  // Batch selection → procurement grouping (#87)
  let selected = $state<Record<string, boolean>>({});
  let proc = $state<ProcurementDetail | null>(null);
  let procForm = $state<ProcurementFields>({
    pr_number: '', order_number: '', tracking_number: '', vendor: '', cost: '',
  });
  let procSaving = $state<boolean>(false);
  let procError = $state<string | null>(null);
  const selectedIds = $derived(Object.keys(selected).filter((k) => selected[k]));

  async function groupSelected() {
    procError = null;
    try {
      await createProcurement(selectedIds);
      selected = {};
      await loadList();
    } catch (e) { listError = e instanceof Error ? e.message : String(e); }
  }

  async function loadProcurement(procurementId: string) {
    try {
      proc = await getProcurement(procurementId);
      procForm = {
        pr_number: proc.pr_number, order_number: proc.order_number,
        tracking_number: proc.tracking_number, vendor: proc.vendor, cost: proc.cost,
      };
    } catch { proc = null; }
  }

  async function saveProcurement() {
    if (!proc || !detail) return;
    procSaving = true;
    procError = null;
    try {
      await updateProcurement(proc.procurement_id, procForm);
      await openDetail(detail.asset_id);  // re-reads asset + refreshed events
    } catch (e) { procError = e instanceof Error ? e.message : String(e); }
    finally { procSaving = false; }
  }

  async function ungroupProcurement() {
    if (!proc || !detail) return;
    if (!confirm(`Ungroup ${proc.member_count} asset(s)? Their fields are kept.`)) return;
    try {
      await deleteProcurement(proc.procurement_id);
      await openDetail(detail.asset_id);
    } catch (e) { procError = e instanceof Error ? e.message : String(e); }
  }

  let editing = $state<boolean>(false);
  let form = $state<AssetFields>({ ...EMPTY_FORM });
  let formError = $state<string | null>(null);
  let formSaving = $state<boolean>(false);

  async function loadList() {
    listLoading = true;
    listError = null;
    try { assets = await listAssets(statusFilter, '', query.trim(), warrantyFilter); }
    catch (e) { listError = e instanceof Error ? e.message : String(e); assets = []; }
    finally { listLoading = false; }
  }

  async function openDetail(assetId: string) {
    detailError = null;
    editing = false;
    proc = null;
    try {
      detail = await getAsset(assetId);
      view = 'detail';
      if (detail.procurement_id) await loadProcurement(detail.procurement_id);
    } catch (e) { detailError = e instanceof Error ? e.message : String(e); }
  }

  function startNew() {
    form = { ...EMPTY_FORM };
    formError = null;
    view = 'new';
  }

  function startEdit() {
    if (!detail) return;
    const { asset_id: _id, procurement_id: _p, created_at: _c, updated_at: _u, events: _e, ...fields } = detail;
    form = { ...fields };
    formError = null;
    editing = true;
  }

  async function saveNew() {
    formSaving = true;
    formError = null;
    try {
      const created = await createAsset(form);
      await loadList();
      await openDetail(created.asset_id);
    } catch (e) { formError = e instanceof Error ? e.message : String(e); }
    finally { formSaving = false; }
  }

  async function saveEdit() {
    if (!detail) return;
    formSaving = true;
    formError = null;
    try {
      await updateAsset(detail.asset_id, form);
      await openDetail(detail.asset_id);
      await loadList();
    } catch (e) { formError = e instanceof Error ? e.message : String(e); }
    finally { formSaving = false; }
  }

  async function removeAsset() {
    if (!detail) return;
    if (!confirm(`Delete ${detail.asset_tag || detail.asset_id}? Retirement is a status — delete is for data-entry mistakes.`)) return;
    try {
      await deleteAsset(detail.asset_id);
      detail = null;
      view = 'list';
      await loadList();
    } catch (e) { detailError = e instanceof Error ? e.message : String(e); }
  }

  let _loaded = false;
  $effect(() => {
    if (_loaded) return;
    _loaded = true;
    loadList();
  });
</script>

{#snippet fieldInput(label: string, key: keyof AssetFields)}
  <label class="inv-field">
    <span class="inv-field-label">{label}</span>
    <input class="inv-input" bind:value={form[key]} />
  </label>
{/snippet}

{#snippet assetForm(onSave: () => void, saveLabel: string)}
  <div class="inv-form">
    <div class="inv-form-group">
      <div class="inv-group-title">Identity</div>
      <div class="inv-grid">
        {@render fieldInput('Asset tag', 'asset_tag')}
        {@render fieldInput('Category', 'category')}
        {@render fieldInput('Brand / model', 'brand_model')}
        {@render fieldInput('Serial number', 'serial_number')}
        {@render fieldInput('Specs', 'specs')}
        {@render fieldInput('Notes', 'notes')}
      </div>
    </div>
    <div class="inv-form-group">
      <div class="inv-group-title">Procurement</div>
      <div class="inv-grid">
        {@render fieldInput('Work item ref', 'work_item_ref')}
        {@render fieldInput('PR number', 'pr_number')}
        {@render fieldInput('Order number', 'order_number')}
        {@render fieldInput('Tracking number', 'tracking_number')}
        {@render fieldInput('Vendor', 'vendor')}
        {@render fieldInput('Cost', 'cost')}
      </div>
    </div>
    <div class="inv-form-group">
      <div class="inv-group-title">Lifecycle</div>
      <div class="inv-grid">
        <label class="inv-field">
          <span class="inv-field-label">Status</span>
          <select class="inv-input" bind:value={form.status}>
            {#each ASSET_STATUSES as s}<option value={s}>{s}</option>{/each}
          </select>
        </label>
        {@render fieldInput('Handler', 'handler')}
        {@render fieldInput('Assignee', 'assignee')}
        {@render fieldInput('Location', 'location')}
        {@render fieldInput('Warranty until', 'warranty_until')}
      </div>
    </div>
    {#if formError}<p class="section-error">{formError}</p>{/if}
    <div class="inv-form-actions">
      <button class="btn-action" onclick={onSave} disabled={formSaving}>
        {formSaving ? '…' : saveLabel}
      </button>
      <button class="btn-secondary" onclick={() => { view === 'new' ? view = 'list' : editing = false; }}>
        Cancel
      </button>
    </div>
  </div>
{/snippet}

<section class="inv-section">
  <div class="section-header">
    <h2>Inventory</h2>
    {#if view !== 'list'}
      <button class="btn-secondary" onclick={() => { view = 'list'; editing = false; loadList(); }}>
        ← All assets
      </button>
    {:else}
      <button class="btn-action" onclick={startNew}>+ New asset</button>
    {/if}
  </div>

  {#if view === 'list'}
    <div class="search-row">
      <select class="inv-input inv-status-filter" bind:value={statusFilter} onchange={loadList}>
        <option value="">all statuses</option>
        {#each ASSET_STATUSES as s}<option value={s}>{s}</option>{/each}
      </select>
      <select class="inv-input inv-status-filter" bind:value={warrantyFilter} onchange={loadList}>
        <option value="">warranty: all</option>
        <option value="30">ending ≤ 30d</option>
        <option value="7">ending ≤ 7d</option>
      </select>
      <input class="search-input" bind:value={query} placeholder="Search tag / model / serial / people / vendor…"
        onkeydown={(e) => e.key === 'Enter' && loadList()} />
      <button class="btn-action" onclick={loadList} disabled={listLoading}>
        {listLoading ? '…' : 'Search'}
      </button>
      {#if selectedIds.length >= 2}
        <button class="btn-action" onclick={groupSelected}>
          Group {selectedIds.length} as procurement
        </button>
      {/if}
    </div>
    {#if listError}
      <p class="section-error">{listError}</p>
    {:else if listLoading}
      <p class="section-empty">Loading…</p>
    {:else if assets.length === 0}
      <p class="section-empty">No assets yet. Create one, or import a spreadsheet with <code>opspilot inventory import</code>.</p>
    {:else}
      <table class="data-table">
        <thead>
          <tr><th></th><th>Tag</th><th>Category</th><th>Brand / model</th><th>Serial</th><th>Status</th><th>Assignee</th><th>Warranty</th><th>Updated</th></tr>
        </thead>
        <tbody>
          {#each assets as a}
            <tr class="inv-row" onclick={() => openDetail(a.asset_id)}>
              <td onclick={(e) => e.stopPropagation()}>
                <input type="checkbox" bind:checked={selected[a.asset_id]} />
              </td>
              <td class="mono">{a.asset_tag || '—'}</td>
              <td>{a.category || '—'}</td>
              <td>{a.brand_model || '—'}</td>
              <td class="mono">{a.serial_number || '—'}</td>
              <td><span class="inv-status inv-status-{a.status}">{a.status}</span></td>
              <td>{a.assignee || '—'}</td>
              <td class="dim {warrantyWarn(a.warranty_until) ? 'inv-warranty-warn' : ''}">
                {a.warranty_until ? a.warranty_until.slice(0, 10) : '—'}
              </td>
              <td class="dim">{a.updated_at.slice(0, 10)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

  {:else if view === 'new'}
    <h3 class="inv-subtitle">New asset</h3>
    {@render assetForm(saveNew, 'Create asset')}

  {:else if detail}
    {#if detailError}<p class="section-error">{detailError}</p>{/if}
    <div class="inv-detail-head">
      <h3 class="inv-subtitle">
        {detail.asset_tag || detail.asset_id}
        <span class="inv-status inv-status-{detail.status}">{detail.status}</span>
      </h3>
      {#if !editing}
        <div class="inv-detail-actions">
          <button class="btn-action" onclick={startEdit}>✎ Edit</button>
          <button class="btn-secondary" onclick={removeAsset}>Delete</button>
        </div>
      {/if}
    </div>

    {#if editing}
      {@render assetForm(saveEdit, 'Save changes')}
    {:else}
      <div class="inv-grid inv-detail-grid">
        {#each [
          ['Asset id', detail.asset_id], ['Asset tag', detail.asset_tag], ['Category', detail.category],
          ['Brand / model', detail.brand_model], ['Serial number', detail.serial_number], ['Specs', detail.specs],
          ['Notes', detail.notes], ['Work item ref', detail.work_item_ref], ['PR number', detail.pr_number],
          ['Order number', detail.order_number], ['Tracking number', detail.tracking_number], ['Vendor', detail.vendor],
          ['Cost', detail.cost], ['Handler', detail.handler], ['Assignee', detail.assignee],
          ['Location', detail.location], ['Warranty until', detail.warranty_until],
          ['Created', detail.created_at.slice(0, 19)], ['Updated', detail.updated_at.slice(0, 19)],
        ] as [label, value]}
          <div class="inv-field">
            <span class="inv-field-label">{label}</span>
            <span class="inv-value {value ? '' : 'dim'}">{value || '—'}</span>
          </div>
        {/each}
      </div>

      {#if proc}
        <div class="inv-form-group inv-proc-panel">
          <div class="inv-group-title">
            Procurement {proc.procurement_id} · {proc.member_count} asset(s) — edits sync to all members
          </div>
          <div class="inv-grid">
            <label class="inv-field"><span class="inv-field-label">PR number</span>
              <input class="inv-input" bind:value={procForm.pr_number} /></label>
            <label class="inv-field"><span class="inv-field-label">Order number</span>
              <input class="inv-input" bind:value={procForm.order_number} /></label>
            <label class="inv-field"><span class="inv-field-label">Tracking number</span>
              <input class="inv-input" bind:value={procForm.tracking_number} /></label>
            <label class="inv-field"><span class="inv-field-label">Vendor</span>
              <input class="inv-input" bind:value={procForm.vendor} /></label>
            <label class="inv-field"><span class="inv-field-label">Cost</span>
              <input class="inv-input" bind:value={procForm.cost} /></label>
          </div>
          {#if procError}<p class="section-error">{procError}</p>{/if}
          <div class="inv-form-actions">
            <button class="btn-action" onclick={saveProcurement} disabled={procSaving}>
              {procSaving ? '…' : `Save & sync ${proc.member_count} asset(s)`}
            </button>
            <button class="btn-secondary" onclick={ungroupProcurement}>Ungroup</button>
          </div>
        </div>
      {/if}

      <h4 class="inv-events-title">Events</h4>
      <table class="data-table">
        <thead><tr><th>When</th><th>Actor</th><th>Change</th><th>Note</th></tr></thead>
        <tbody>
          {#each detail.events as e}
            <tr>
              <td class="dim mono">{e.ts.slice(0, 19)}</td>
              <td>{e.actor || '—'}</td>
              <td>{e.change}</td>
              <td class="dim">{e.note || '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}
</section>

<style>
  .inv-subtitle {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-size: 1.05rem;
    margin: 0.5rem 0 0.9rem;
  }

  .inv-detail-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .inv-detail-actions { display: flex; gap: 0.5rem; }

  .inv-status {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    padding: 0.15rem 0.45rem;
    border-radius: 4px;
    background: var(--bg-muted);
    color: var(--text-muted);
    border: 1px solid var(--border);
  }

  .inv-status-deployed { color: var(--primary); border-color: var(--primary-border); background: var(--primary-bg); }
  .inv-warranty-warn { color: #d97706; font-weight: 600; }

  .inv-proc-panel {
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.8rem;
    margin-bottom: 1.2rem;
  }
  .inv-status-in_repair { color: #d97706; }
  .inv-status-retired { opacity: 0.6; }

  .inv-row { cursor: pointer; }

  .inv-status-filter { max-width: 160px; }

  .inv-form { display: flex; flex-direction: column; gap: 1rem; }

  .inv-group-title {
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 0.4rem;
  }

  .inv-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 0.6rem 1rem;
  }

  .inv-detail-grid { margin-bottom: 1.2rem; }

  .inv-field { display: flex; flex-direction: column; gap: 0.2rem; }

  .inv-field-label {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .inv-input {
    font-size: 0.85rem;
    padding: 0.35rem 0.5rem;
    border-radius: 4px;
    border: 1px solid var(--border-strong);
    background: var(--bg-subtle);
    color: var(--text);
  }

  .inv-value { font-size: 0.88rem; word-break: break-word; }

  .inv-form-actions { display: flex; gap: 0.5rem; }

  .inv-events-title {
    font-size: 0.9rem;
    margin: 0.4rem 0 0.5rem;
  }
</style>
