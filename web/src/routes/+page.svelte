<script lang="ts">
  import '../app.css';
  import { getApiToken, getConfig, getModels, setApiToken, type ModelOption } from '$lib/api';
  import GuideTab from '$lib/components/GuideTab.svelte';
  import MCPTab from '$lib/components/MCPTab.svelte';
  import IterationTab from '$lib/components/IterationTab.svelte';
  import WikiTab from '$lib/components/WikiTab.svelte';
  import VendorDocTab from '$lib/components/VendorDocTab.svelte';
  import ChatTab from '$lib/components/ChatTab.svelte';
  import KBTab from '$lib/components/KBTab.svelte';
  import RunTab from '$lib/components/RunTab.svelte';

  // --- Theme (dark is the default) ---
  let theme = $state<'light' | 'dark'>(
    typeof localStorage !== 'undefined'
      ? (localStorage.getItem('theme') as 'light' | 'dark') ?? 'dark'
      : 'dark'
  );

  $effect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  });

  function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
  }

  // --- API token (only needed when the backend sets OPSPILOT_API_TOKEN) ---
  let apiToken = $state<string>(typeof localStorage !== 'undefined' ? getApiToken() : '');
  $effect(() => setApiToken(apiToken));

  // --- Active Tab ---
  type Tab = 'run' | 'kb' | 'wiki' | 'vendordoc' | 'mcp' | 'iteration' | 'chat' | 'guide';
  let activeTab = $state<Tab>('run');

  // Nav indices mirror the TUI's 1-8 module keys.
  const NAV_ITEMS = [
    { id: 'run', label: 'Run' },
    { id: 'chat', label: 'Chat' },
    { id: 'kb', label: 'Knowledge Base' },
    { id: 'wiki', label: 'Wiki' },
    { id: 'vendordoc', label: 'Vendor Docs' },
    { id: 'mcp', label: 'MCP' },
    { id: 'iteration', label: 'Iteration' },
    { id: 'guide', label: 'Guide' },
  ] as const;

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
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-dot"></span>
      <span class="brand-name">OpsPilot</span>
    </div>
    <div class="brand-sub">AI ops workbench</div>

    <nav class="side-nav">
      {#each NAV_ITEMS as tab, i}
        <button
          class="nav-item {activeTab === tab.id ? 'active' : ''}"
          onclick={() => activeTab = tab.id}
        >
          <span class="nav-index">{String(i + 1).padStart(2, '0')}</span>
          <span class="nav-label">{tab.label}</span>
        </button>
      {/each}
    </nav>

    <div class="sidebar-foot">
      <div class="foot-label">Model</div>
      {#if !modelsLoaded}
        <span class="model-ref">loading…</span>
      {:else if availableModels.length > 1}
        <select class="model-select" bind:value={selectedModelId}>
          {#each availableModels as m}
            <option value={m.id}>{m.label}</option>
          {/each}
        </select>
      {:else}
        <span class="model-ref" title="Active model">{selectedModelId || modelRef || '—'}</span>
      {/if}
      <div class="foot-label">API token</div>
      <input
        class="token-input"
        type="password"
        placeholder="unset (local mode)"
        bind:value={apiToken}
        autocomplete="off"
      />
      <button class="theme-toggle" onclick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
        {theme === 'dark' ? '☀ light' : '☾ dark'}
      </button>
    </div>
  </aside>

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
    display: flex;
    min-height: 100vh;
  }

  /* ── Sidebar ── */
  .sidebar {
    display: flex;
    flex-direction: column;
    width: 220px;
    flex-shrink: 0;
    padding: 1.25rem 0.85rem 1rem;
    background: var(--bg-surface);
    border-right: 1px solid var(--border);
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0 0.4rem;
  }

  .brand-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--primary);
    box-shadow: 0 0 8px var(--primary);
    flex-shrink: 0;
  }

  .brand-name {
    font-size: 1.15rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--text);
  }

  .brand-sub {
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.12em;
    padding: 0.15rem 0.4rem 0;
    margin-bottom: 1.5rem;
  }

  .side-nav {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    width: 100%;
    padding: 0.45rem 0.65rem;
    font-size: 0.88rem;
    font-weight: 500;
    text-align: left;
    color: var(--text-muted);
    background: none;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: color 0.12s, background 0.12s;
  }

  .nav-item:hover {
    color: var(--text);
    background: var(--bg-muted);
  }

  .nav-item.active {
    color: var(--primary);
    background: var(--primary-bg);
  }

  .nav-index {
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--text-faint);
    width: 1.4em;
    flex-shrink: 0;
  }

  .nav-item.active .nav-index { color: var(--primary); opacity: 0.7; }

  /* ── Sidebar footer ── */
  .sidebar-foot {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    padding: 0.85rem 0.4rem 0;
    border-top: 1px solid var(--border);
  }

  .foot-label {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }

  .model-ref,
  .model-select {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    background: var(--primary-bg);
    color: var(--primary);
    padding: 0.3rem 0.5rem;
    border-radius: 4px;
    border: 1px solid var(--primary-border);
    width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .model-select { cursor: pointer; }
  .model-select:disabled { opacity: 0.6; cursor: not-allowed; }

  .token-input {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    padding: 0.3rem 0.5rem;
    border-radius: 4px;
    border: 1px solid var(--border-strong);
    background: var(--bg-subtle);
    color: var(--text);
    width: 100%;
  }

  .theme-toggle {
    background: none;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.3rem 0.55rem;
    font-size: 0.75rem;
    font-family: var(--font-mono);
    color: var(--text-muted);
    line-height: 1;
    cursor: pointer;
    text-align: center;
  }

  .theme-toggle:hover { background: var(--bg-muted); color: var(--text); }

  /* ── Main content ── */
  main {
    flex: 1;
    min-width: 0;
    max-width: 1080px;
    padding: 1.75rem 2rem 2.5rem;
  }

  /* ── Narrow screens: sidebar becomes a top bar ── */
  @media (max-width: 768px) {
    .app { flex-direction: column; }

    .sidebar {
      width: 100%;
      height: auto;
      position: static;
      border-right: none;
      border-bottom: 1px solid var(--border);
      padding: 0.85rem 1rem;
    }

    .brand-sub { display: none; }

    .side-nav {
      flex-direction: row;
      overflow-x: auto;
      gap: 0.25rem;
      margin-top: 0.6rem;
    }

    .nav-item { width: auto; white-space: nowrap; padding: 0.35rem 0.6rem; }
    .nav-index { display: none; }

    .sidebar-foot {
      flex-direction: row;
      align-items: center;
      border-top: none;
      padding: 0.6rem 0 0;
    }

    .foot-label { display: none; }
    .model-ref, .model-select { width: auto; }

    main { padding: 1.25rem 1rem 2rem; }
  }
</style>
