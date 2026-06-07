<script lang="ts">
  import '../app.css';
  import { getConfig, getModels, type ModelOption } from '$lib/api';
  import GuideTab from '$lib/components/GuideTab.svelte';
  import MCPTab from '$lib/components/MCPTab.svelte';
  import IterationTab from '$lib/components/IterationTab.svelte';
  import WikiTab from '$lib/components/WikiTab.svelte';
  import VendorDocTab from '$lib/components/VendorDocTab.svelte';
  import ChatTab from '$lib/components/ChatTab.svelte';
  import KBTab from '$lib/components/KBTab.svelte';
  import RunTab from '$lib/components/RunTab.svelte';

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
    })();
  });

</script>

<div class="app">
  <!-- Header -->
  <header>
    <h1>OpsPilot</h1>
    {#if !modelsLoaded}
      <span class="model-ref">Loading...</span>
    {:else if availableModels.length > 1}
      <select class="model-select" bind:value={selectedModelId}>
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
      <RunTab {selectedModelId} {modules} />
    {/if}

    <!-- ══════════════════════════════ CHAT TAB ══════════════════════════════ -->
    {#if activeTab === 'chat'}
      <ChatTab {selectedModelId} />
    {/if}

    <!-- ══════════════════════════════ KB TAB ══════════════════════════════ -->
    {#if activeTab === 'kb'}
      <KBTab />
    {/if}

    <!-- ══════════════════════════════ WIKI TAB ══════════════════════════════ -->
    {#if activeTab === 'wiki'}
      <WikiTab />
    {/if}

    <!-- ══════════════════════════ VENDOR DOCS TAB ══════════════════════════ -->
    {#if activeTab === 'vendordoc'}
      <VendorDocTab />
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



</style>
