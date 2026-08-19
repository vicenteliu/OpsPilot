<script lang="ts">
  // Memory tab — the second owned domain (ADR-0031, revised by ADR-0035).
  //
  // Standing facts about the environment that have no table of their own. An
  // entry is *admitted*: a human writes the sentence and the reason, and the
  // actor comes from the session — never from anything this form sends.
  //
  // The reason field is required here for the same purpose it exists at all:
  // six months on it is the only way to tell a real finding from a misdiagnosis
  // someone enshrined, which is exactly what the review date asks a reader to
  // judge.
  import {
    listMemory, listMemoryScopes, admitMemory, supersedeMemory, archiveMemory,
    listMemoryConflicts, resolveMemoryConflict, CONFLICT_RESOLUTIONS,
    type MemoryEntry, type MemoryConflict,
  } from '$lib/api';

  let entries = $state<MemoryEntry[]>([]);
  let scopes = $state<string[]>([]);
  let loading = $state<boolean>(false);
  let error = $state<string | null>(null);
  let scopeFilter = $state<string>('');
  let includeRetired = $state<boolean>(false);
  let retiredIgnored = $state<boolean>(false);

  // New entry. `scope` is pick-or-create: free text alone drifts into
  // "HQ" / "hq" / "head office", and anchor-filtered retrieval then silently
  // misses — the failure anchors exist to prevent.
  let statement = $state<string>('');
  let reason = $state<string>('');
  let scope = $state<string>('');
  let reviewAfter = $state<string>('');
  let saving = $state<boolean>(false);

  // Conflicts between a recorded constraint and an ingested document. Detecting
  // was automatic; deciding which side loses is not, and the reason is stored
  // because six months on it is the only way to tell a real finding from a
  // misdiagnosis someone enshrined (ADR-0029).
  let conflicts = $state<MemoryConflict[]>([]);
  let resolvingId = $state<string | null>(null);
  let resolution = $state<string>('chunk_superseded');
  let resolveNote = $state<string>('');

  let supersedingId = $state<string | null>(null);
  let newStatement = $state<string>('');
  let newReason = $state<string>('');

  const today = new Date().toISOString().slice(0, 10);
  const overdue = (e: MemoryEntry) => !!e.review_after && e.review_after.slice(0, 10) < today;

  async function load() {
    loading = true; error = null;
    try {
      const listed = await listMemory({ scope: scopeFilter || undefined, includeRetired });
      entries = listed.entries;
      retiredIgnored = listed.includeRetiredIgnored;
      scopes = await listMemoryScopes();
      conflicts = await listMemoryConflicts('open');
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
    finally { loading = false; }
  }

  async function admit() {
    saving = true; error = null;
    try {
      await admitMemory({
        statement, reason,
        scope: scope || null,
        review_after: reviewAfter ? `${reviewAfter}T00:00:00Z` : null,
      });
      statement = ''; reason = ''; reviewAfter = '';
      await load();
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
    finally { saving = false; }
  }

  async function supersede(id: string) {
    error = null;
    try {
      await supersedeMemory(id, { statement: newStatement, reason: newReason });
      supersedingId = null; newStatement = ''; newReason = '';
      await load();
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
  }

  async function archive(id: string) {
    error = null;
    try { await archiveMemory(id); await load(); }
    catch (e) { error = e instanceof Error ? e.message : String(e); }
  }

  async function settle(id: string) {
    error = null;
    try {
      await resolveMemoryConflict(id, { resolution, note: resolveNote });
      resolvingId = null; resolveNote = ''; resolution = 'chunk_superseded';
      await load();
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
  }

  let _init = false;
  $effect(() => { if (!_init) { _init = true; load(); } });
</script>

<h2 class="mem-title">Memory</h2>
<p class="mem-lede">
  Standing facts about this environment — constraints, gotchas, and relationships
  that no other table wants. They are injected into a chat turn when they apply
  at what you are working on.
</p>

{#if error}<div class="mem-error">{error}</div>{/if}

{#if conflicts.length > 0}
  <section class="mem-conflicts">
    <h3>{conflicts.length} disagreement{conflicts.length === 1 ? '' : 's'} to settle</h3>
    <p class="mem-hint">
      A recorded constraint and a knowledge-base document contradict each other.
      The assistant noticed while composing an answer; which side loses is yours.
    </p>
    {#each conflicts as c (c.id)}
      <article class="mem-card mem-conflict">
        <div class="mem-meta"><span class="mem-where">{c.memory_id}</span> vs <span class="mem-where">{c.chunk_id}</span></div>
        <div class="mem-statement">{c.note}</div>
        <div class="mem-meta mem-muted">
          noticed {c.detected_at.slice(0, 10)}{#if c.detected_in}· in {c.detected_in}{/if}
        </div>
        {#if resolvingId === c.id}
          <div class="mem-supersede">
            {#each CONFLICT_RESOLUTIONS as r}
              <label class="mem-radio">
                <input type="radio" bind:group={resolution} value={r.id} />
                <span><strong>{r.label}</strong>{#if r.hint} — {r.hint}{/if}</span>
              </label>
            {/each}
            <input class="mem-input" bind:value={resolveNote} placeholder="Why (recorded with the decision)" />
            <div class="mem-row">
              <button class="btn-action" onclick={() => settle(c.id)}>Settle</button>
              <button class="btn-secondary" onclick={() => (resolvingId = null)}>Cancel</button>
            </div>
            <p class="mem-hint">
              There is no “merge”: merging would mean editing the constraint in
              place, and a constraint is superseded by appending a new one.
            </p>
          </div>
        {:else}
          <div class="mem-row mem-actions">
            <button class="btn-action" onclick={() => { resolvingId = c.id; resolveNote = ''; }}>Settle this</button>
          </div>
        {/if}
      </article>
    {/each}
  </section>
{/if}

<section class="mem-new">
  <h3>Admit an entry</h3>
  <input class="mem-input" bind:value={statement} placeholder="The fact, as one sentence" />
  <input class="mem-input" bind:value={reason} placeholder="Why it is worth recording (required)" />
  <div class="mem-row">
    <input class="mem-input mem-narrow" bind:value={scope} list="mem-scopes"
           placeholder="Where it applies — blank means everywhere" />
    <datalist id="mem-scopes">
      {#each scopes as s}<option value={s}></option>{/each}
    </datalist>
    <input class="mem-input mem-narrow" type="date" bind:value={reviewAfter} title="Re-check it after" />
    <button class="btn-action" onclick={admit} disabled={saving || !statement.trim() || !reason.trim()}>
      {saving ? 'Admitting…' : 'Admit'}
    </button>
  </div>
  <p class="mem-hint">
    An entry with no anchor applies everywhere and is capped, because those are
    the minority. Leaving the reason blank is refused: it is what the review date
    asks a reader to judge.
  </p>
</section>

<section class="mem-list">
  <div class="mem-row">
    <select class="mem-input mem-narrow" bind:value={scopeFilter} onchange={load}>
      <option value="">All entries</option>
      {#each scopes as s}<option value={s}>applies at {s}</option>{/each}
    </select>
    <label class="mem-check">
      <input type="checkbox" bind:checked={includeRetired} onchange={load} /> include retired
    </label>
    {#if retiredIgnored}
      <span class="mem-muted">— ignored: an anchored view shows what applies here</span>
    {/if}
    <button class="btn-secondary" onclick={load} disabled={loading}>Refresh</button>
  </div>

  {#if loading}
    <p class="mem-muted">Loading…</p>
  {:else if entries.length === 0}
    <p class="mem-muted">Nothing recorded yet.</p>
  {:else}
    {#each entries as e (e.id)}
      <article class="mem-card" class:mem-retired={!e.is_live}>
        <div class="mem-card-head">
          <span class="mem-statement">{e.statement}</span>
          <span class="mem-id">{e.id}</span>
        </div>
        <div class="mem-meta">
          <span class="mem-where">{e.scope ?? e.asset_id ?? 'everywhere'}</span>
          <span>· {e.reason}</span>
        </div>
        <div class="mem-meta mem-muted">
          by {e.actor} · {e.created_at.slice(0, 10)}
          {#if e.source_ref}· from {e.source_ref}{/if}
          {#if overdue(e) && e.is_live}
            <span class="mem-overdue">⚠ due for review since {e.review_after?.slice(0, 10)}</span>
          {/if}
          {#if e.superseded_by}<span>· superseded by {e.superseded_by}</span>{/if}
          {#if e.archived_at}<span>· archived</span>{/if}
        </div>

        {#if e.is_live}
          {#if supersedingId === e.id}
            <div class="mem-supersede">
              <input class="mem-input" bind:value={newStatement} placeholder="What is true now" />
              <input class="mem-input" bind:value={newReason} placeholder="Why it changed" />
              <div class="mem-row">
                <button class="btn-action" onclick={() => supersede(e.id)}
                        disabled={!newStatement.trim() || !newReason.trim()}>Supersede</button>
                <button class="btn-secondary" onclick={() => (supersedingId = null)}>Cancel</button>
              </div>
              <p class="mem-hint">
                The old entry is kept, not edited — "we recorded it wrong" and
                "the world changed" have to stay distinguishable.
              </p>
            </div>
          {:else}
            <div class="mem-row mem-actions">
              <button class="btn-secondary" onclick={() => { supersedingId = e.id; newStatement = ''; newReason = ''; }}>
                Supersede
              </button>
              <button class="btn-secondary" onclick={() => archive(e.id)}>Archive</button>
            </div>
          {/if}
        {/if}
      </article>
    {/each}
  {/if}
</section>

<style>
  .mem-title { margin: 0.4rem 0 0.2rem; }
  .mem-lede { color: var(--text-muted); margin: 0 0 1rem; max-width: 62ch; }
  .mem-error {
    border: 1px solid var(--danger, #dc2626); color: var(--danger, #dc2626);
    padding: 0.5rem 0.7rem; border-radius: 6px; margin-bottom: 0.8rem;
  }
  .mem-new, .mem-list { margin-bottom: 1.4rem; }
  .mem-new h3 { margin: 0 0 0.5rem; font-size: 0.95rem; }
  .mem-row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .mem-actions { margin-top: 0.5rem; }
  .mem-input {
    padding: 0.4rem 0.6rem; border: 1px solid var(--border); border-radius: 6px;
    background: var(--bg-input, var(--bg-muted)); color: var(--text); width: 100%;
    margin-bottom: 0.5rem; font-size: 0.9rem;
  }
  .mem-narrow { width: auto; min-width: 12rem; margin-bottom: 0; }
  .mem-check { display: flex; gap: 0.35rem; align-items: center; font-size: 0.85rem; color: var(--text-muted); }
  .mem-hint { color: var(--text-muted); font-size: 0.8rem; margin: 0.3rem 0 0; max-width: 62ch; }
  .mem-muted { color: var(--text-muted); font-size: 0.85rem; }
  .mem-card {
    border: 1px solid var(--border); border-radius: 8px;
    padding: 0.7rem 0.9rem; margin-top: 0.6rem;
  }
  .mem-retired { opacity: 0.55; }
  .mem-card-head { display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
  .mem-statement { font-weight: 600; }
  .mem-id { font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-muted); }
  .mem-meta { font-size: 0.83rem; color: var(--text-muted); margin-top: 0.25rem; }
  .mem-where {
    font-family: var(--font-mono); font-size: 0.72rem; padding: 0.1rem 0.4rem;
    border-radius: 4px; background: var(--bg-muted); border: 1px solid var(--border);
  }
  .mem-overdue { color: #d97706; font-weight: 600; margin-left: 0.4rem; }
  .mem-supersede { margin-top: 0.6rem; }
  .mem-conflicts { margin-bottom: 1.4rem; }
  .mem-conflicts h3 { margin: 0 0 0.3rem; font-size: 0.95rem; color: #d97706; }
  .mem-conflict { border-color: #d97706; }
  .mem-radio { display: flex; gap: 0.45rem; align-items: flex-start; font-size: 0.85rem; margin-bottom: 0.35rem; }
  .mem-radio span { color: var(--text-muted); }
  .mem-radio strong { color: var(--text); }
</style>
