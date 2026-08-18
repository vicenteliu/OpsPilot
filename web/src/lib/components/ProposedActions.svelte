<script lang="ts">
  // Proposed actions on a Session (ADR-0028).
  //
  // A Session *proposes*; a human executes. Automatic execution is not here,
  // including for actions the approval gate does not flag — the gate is a
  // heuristic denylist, a defence-in-depth signal rather than a security
  // boundary, and it is not the thing that should decide whether something runs
  // unattended.
  //
  // The first batch is read-only diagnostics, and that lives in the artifact
  // schema: `intent` is a const, so a mutating action cannot be expressed. This
  // component never has to check for one.
  import {
    listProposedActions, previewAction, executeAction,
    type ProposedAction, type ActionPreview, type ActionOutcome,
  } from '$lib/api';

  let { sessionId }: { sessionId: string } = $props();

  let actions = $state<ProposedAction[]>([]);
  let previews = $state<Record<string, ActionPreview>>({});
  let outcomes = $state<Record<string, ActionOutcome>>({});
  let busy = $state<string | null>(null);
  let error = $state<string | null>(null);

  async function load() {
    try { actions = await listProposedActions(sessionId); }
    catch (e) { error = e instanceof Error ? e.message : String(e); }
  }

  async function doPreview(ref: string) {
    busy = ref; error = null;
    try { previews = { ...previews, [ref]: await previewAction(sessionId, ref) }; }
    catch (e) { error = e instanceof Error ? e.message : String(e); }
    finally { busy = null; }
  }

  async function doExecute(ref: string) {
    busy = ref; error = null;
    try { outcomes = { ...outcomes, [ref]: await executeAction(sessionId, ref) }; }
    catch (e) { error = e instanceof Error ? e.message : String(e); }
    finally { busy = null; }
  }

  let _init = false;
  $effect(() => { if (!_init && sessionId) { _init = true; load(); } });
</script>

{#if actions.length > 0}
  <section class="pa">
    <h3>{actions.length} proposed diagnostic{actions.length === 1 ? '' : 's'}</h3>
    <p class="pa-lede">
      Read-only. Nothing here runs until you press execute, and what runs is
      recorded against this session with your name on it.
    </p>
    {#if error}<div class="pa-error">{error}</div>{/if}

    {#each actions as a (a.ref)}
      <article class="pa-card">
        <div class="pa-head">
          <code class="pa-cmd">{a.command}</code>
          <span class="pa-target">{a.target}</span>
        </div>
        <p class="pa-why">{a.why}</p>

        {#if outcomes[a.ref]}
          <div class="pa-outcome">
            <div class="pa-meta">
              ran by {outcomes[a.ref].executed_by} · {outcomes[a.ref].status}
              {#if outcomes[a.ref].exit_code !== null}· exit {outcomes[a.ref].exit_code}{/if}
            </div>
            {#if outcomes[a.ref].stdout}<pre class="pa-pre">{outcomes[a.ref].stdout}</pre>{/if}
            {#if outcomes[a.ref].stderr}<pre class="pa-pre pa-err">{outcomes[a.ref].stderr}</pre>{/if}
          </div>
        {:else if previews[a.ref]}
          <div class="pa-preview">
            {#if previews[a.ref].approval_required}
              <div class="pa-flag">
                The approval gate flagged this. It is a heuristic denylist and a
                defence-in-depth signal — the sandbox is what actually contains
                the blast radius. Read the command before you run it.
              </div>
            {/if}
            <div class="pa-meta">dry run: {previews[a.ref].dry_run_status}</div>
            {#if previews[a.ref].dry_run_stdout}
              <pre class="pa-pre">{previews[a.ref].dry_run_stdout}</pre>
            {/if}
            <button class="btn-action" onclick={() => doExecute(a.ref)} disabled={busy === a.ref}>
              {busy === a.ref ? 'Running…' : 'Execute'}
            </button>
          </div>
        {:else}
          <button class="btn-secondary" onclick={() => doPreview(a.ref)} disabled={busy === a.ref}>
            {busy === a.ref ? 'Checking…' : 'Preview'}
          </button>
        {/if}
      </article>
    {/each}
  </section>
{/if}

<style>
  .pa { margin-top: 1.2rem; }
  .pa h3 { margin: 0 0 0.2rem; font-size: 0.95rem; }
  .pa-lede { color: var(--text-muted); font-size: 0.85rem; margin: 0 0 0.7rem; max-width: 62ch; }
  .pa-error { color: var(--danger, #dc2626); font-size: 0.85rem; margin-bottom: 0.5rem; }
  .pa-card { border: 1px solid var(--border); border-radius: 8px; padding: 0.7rem 0.9rem; margin-bottom: 0.6rem; }
  .pa-head { display: flex; gap: 0.6rem; align-items: baseline; flex-wrap: wrap; }
  .pa-cmd { font-family: var(--font-mono); font-size: 0.82rem; }
  .pa-target {
    font-family: var(--font-mono); font-size: 0.7rem; padding: 0.1rem 0.4rem;
    border-radius: 4px; background: var(--bg-muted); border: 1px solid var(--border);
  }
  .pa-why { color: var(--text-muted); font-size: 0.85rem; margin: 0.35rem 0 0.55rem; }
  .pa-meta { color: var(--text-muted); font-size: 0.78rem; margin-bottom: 0.35rem; }
  .pa-flag {
    border: 1px solid #d97706; color: #d97706; background: rgba(217, 119, 6, 0.08);
    padding: 0.45rem 0.6rem; border-radius: 6px; font-size: 0.8rem;
    margin-bottom: 0.5rem; max-width: 62ch;
  }
  .pa-pre {
    font-family: var(--font-mono); font-size: 0.75rem; white-space: pre-wrap;
    background: var(--bg-muted); border: 1px solid var(--border); border-radius: 6px;
    padding: 0.5rem; max-height: 16rem; overflow: auto; margin: 0 0 0.5rem;
  }
  .pa-err { color: var(--danger, #dc2626); }
  .pa-outcome { margin-top: 0.4rem; }
</style>
