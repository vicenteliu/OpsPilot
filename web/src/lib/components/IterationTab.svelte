<script lang="ts">
  // Iteration tab — skill lineage / version history. Loads once on mount.
  import { getLineage, type SkillLineage } from '$lib/api';

  let lineages = $state<SkillLineage[]>([]);
  let lineageLoading = $state<boolean>(false);
  let lineageError = $state<string | null>(null);
  let expandedSkill = $state<Record<string, boolean>>({});

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

  let _loaded = false;
  $effect(() => {
    if (_loaded) return;
    _loaded = true;
    refreshLineage();
  });
</script>

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

<style>
  .iteration-section { padding-top: 0.5rem; }
  .iteration-header { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .iteration-header h2 { font-size: 1.1rem; color: var(--text); margin: 0; }
  .iteration-empty, .iteration-error { color: var(--text-faint); font-size: 0.9rem; }
  .iteration-error { color: var(--error-text); }

  .skill-block { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 0.75rem; overflow: hidden; }
  .skill-toggle { width: 100%; display: flex; align-items: center; gap: 0.75rem; padding: 0.65rem 1rem; background: var(--bg-subtle); border: none; cursor: pointer; text-align: left; font-size: 0.95rem; }
  .skill-toggle:hover { background: var(--bg-muted); }
  .skill-name { font-family: 'Courier New', monospace; font-weight: 600; color: var(--primary); flex: 1; }
  .skill-count { font-size: 0.8rem; color: var(--text-muted); }
  .toggle-arrow { color: var(--text-faint); font-size: 0.8rem; }

  .lineage-tree { padding: 0.75rem 1rem; background: var(--bg-surface); }
  .lineage-row { padding: 0.5rem 0; border-left: 2px solid var(--border-strong); padding-left: 1rem; margin-left: 0.5rem; }
  .lineage-row.rolled-back { opacity: 0.55; }
  .lineage-version { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.2rem; }
  .version-badge { font-family: 'Courier New', monospace; font-size: 0.82rem; font-weight: 700; background: var(--info-bg); color: var(--info-text); padding: 0.1rem 0.5rem; border-radius: 4px; }
  .version-badge.rolled-back-badge { background: var(--error-bg); color: var(--error-text); }
  .rollback-flag { font-size: 0.72rem; color: var(--error-text); background: var(--error-bg); padding: 0.1rem 0.4rem; border-radius: 3px; }
  .lineage-meta { display: flex; align-items: center; gap: 0.6rem; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.2rem; }
  .lineage-date { font-family: 'Courier New', monospace; }
  .itr-id { font-family: 'Courier New', monospace; background: var(--bg-muted); padding: 0.05rem 0.35rem; border-radius: 3px; }
  .itr-id.dim { color: var(--text-faint); }
  .variant-id { font-family: 'Courier New', monospace; color: var(--success-text); font-size: 0.75rem; }
  .lineage-summary { font-size: 0.88rem; color: var(--text); line-height: 1.4; }
  .lineage-connector { color: var(--border-strong); padding-left: 1rem; margin-left: 0.5rem; font-size: 0.9rem; }
</style>
