<script lang="ts">
  import { onMount } from 'svelte';
  import '../app.css';
  import { getConfig, runTicket, type RunResponse, type NextAction } from '$lib/api';

  // --- State ---
  let modelRef = $state<string>('');
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
  let result = $state<RunResponse | null>(null);
  let fetchError = $state<string | null>(null);

  // --- Derived ---
  let summary = $derived(result?.result ?? null);
  let runError = $derived(result?.error ?? null);

  // --- Lifecycle ---
  onMount(async () => {
    try {
      const cfg = await getConfig();
      modelRef = cfg.active_model_ref;
    } catch (e) {
      modelRef = 'unknown';
    }
  });

  // --- Handlers ---
  async function handleRun() {
    fetchError = null;
    result = null;
    let input: Record<string, unknown>;
    try {
      input = JSON.parse(ticketInput);
    } catch {
      fetchError = 'Invalid JSON in ticket input.';
      return;
    }
    loading = true;
    try {
      result = await runTicket(input);
    } catch (e) {
      fetchError = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function copyText(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  function formatNextActions(actions: NextAction[]): string {
    return actions
      .map((a, i) => `${i + 1}. **${a.action}**\n   ${a.rationale}`)
      .join('\n\n');
  }
</script>

<div class="app">
  <!-- Header -->
  <header>
    <h1>OpsPilot</h1>
    <span class="model-ref" title="Active model (read-only)">{modelRef || 'Loading...'}</span>
  </header>

  <!-- Ticket input section -->
  <main>
    <section class="input-section">
      <h2>Ticket Input</h2>
      <textarea
        rows={12}
        bind:value={ticketInput}
        placeholder="Paste ticket JSON here..."
        disabled={loading}
      ></textarea>
      <button class="btn-run" onclick={handleRun} disabled={loading}>
        {#if loading}
          <span class="spinner"></span> Running...
        {:else}
          Run
        {/if}
      </button>
    </section>

    <!-- Error display -->
    {#if fetchError}
      <div class="error-banner">
        <strong>Error:</strong> {fetchError}
      </div>
    {/if}

    {#if runError}
      <div class="error-banner">
        <strong>Run error:</strong> {runError}
      </div>
    {/if}

    <!-- Output cards -->
    {#if summary}
      <section class="cards">

        <!-- Summary card -->
        <div class="card">
          <div class="card-header">
            <h3>Summary</h3>
            <button class="btn-copy" onclick={() => copyText(summary?.summary ?? '')}>
              Copy
            </button>
          </div>
          <p>{summary.summary}</p>
        </div>

        <!-- Symptoms card -->
        <div class="card">
          <div class="card-header">
            <h3>Symptoms</h3>
            <button
              class="btn-copy"
              onclick={() => copyText((summary?.symptoms ?? []).join('\n'))}
            >
              Copy
            </button>
          </div>
          <ul>
            {#each summary.symptoms as symptom}
              <li>{symptom}</li>
            {/each}
          </ul>
        </div>

        <!-- Next Actions card -->
        <div class="card">
          <div class="card-header">
            <h3>Next Actions</h3>
            <button
              class="btn-copy"
              onclick={() => copyText(formatNextActions(summary?.next_actions ?? []))}
            >
              Copy
            </button>
          </div>
          <ol>
            {#each summary.next_actions as action}
              <li>
                <strong>{action.action}</strong>
                <p class="rationale">{action.rationale}</p>
              </li>
            {/each}
          </ol>
        </div>

        <!-- Severity card -->
        <div class="card">
          <div class="card-header">
            <h3>Severity</h3>
            <button
              class="btn-copy"
              onclick={() => copyText(
                summary?.severity_suggested +
                (summary?.escalation_hint ? '\n' + summary.escalation_hint : '')
              )}
            >
              Copy
            </button>
          </div>
          <span class="severity-badge">{summary.severity_suggested}</span>
          {#if summary.escalation_hint}
            <p class="escalation">{summary.escalation_hint}</p>
          {/if}
        </div>

      </section>
    {/if}
  </main>
</div>

<style>
  .app {
    max-width: 900px;
    margin: 0 auto;
    padding: 1.5rem;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.5rem;
    border-bottom: 2px solid #ddd;
    padding-bottom: 0.75rem;
  }

  header h1 {
    font-size: 1.8rem;
    color: #1a56db;
  }

  .model-ref {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.8rem;
    background: #e8f4fd;
    color: #1a56db;
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    border: 1px solid #bee3f8;
  }

  .input-section {
    margin-bottom: 1.5rem;
  }

  .input-section h2 {
    margin-bottom: 0.5rem;
    font-size: 1.1rem;
    color: #444;
  }

  textarea {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid #ccc;
    border-radius: 6px;
    background: #fff;
    margin-bottom: 0.75rem;
  }

  .btn-run {
    padding: 0.6rem 1.5rem;
    background: #1a56db;
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 1rem;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }

  .btn-run:disabled {
    opacity: 0.6;
    cursor: not-allowed;
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

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .error-banner {
    background: #fee2e2;
    color: #991b1b;
    border: 1px solid #fca5a5;
    border-radius: 6px;
    padding: 0.75rem 1rem;
    margin-bottom: 1rem;
  }

  .cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }

  @media (max-width: 640px) {
    .cards {
      grid-template-columns: 1fr;
    }
  }

  .card {
    background: #fff;
    border: 1px solid #e2e8f0;
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
    color: #64748b;
  }

  .btn-copy {
    font-size: 0.75rem;
    padding: 0.2rem 0.6rem;
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    color: #475569;
  }

  .btn-copy:hover {
    background: #e2e8f0;
  }

  .card ul,
  .card ol {
    margin: 0;
    padding-left: 1.25rem;
  }

  .card li {
    margin-bottom: 0.4rem;
    font-size: 0.95rem;
  }

  .rationale {
    margin: 0.2rem 0 0.6rem;
    color: #64748b;
    font-size: 0.88rem;
  }

  .severity-badge {
    display: inline-block;
    padding: 0.3rem 0.8rem;
    border-radius: 9999px;
    font-weight: 700;
    font-size: 1.1rem;
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fcd34d;
  }

  .escalation {
    margin-top: 0.5rem;
    font-size: 0.9rem;
    color: #b45309;
  }
</style>
