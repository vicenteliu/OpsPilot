<script lang="ts">
  // MCP tab — read-only list of registered MCP servers. Loads on demand (↻).
  import { listMCPServers, type MCPServer } from '$lib/api';

  let mcpServers = $state<MCPServer[]>([]);
  let mcpLoading = $state<boolean>(false);
  let mcpError = $state<string | null>(null);

  async function loadMCPServers() {
    mcpLoading = true;
    mcpError = null;
    try {
      mcpServers = await listMCPServers();
    } catch (e) {
      mcpError = e instanceof Error ? e.message : String(e);
      mcpServers = [];
    } finally {
      mcpLoading = false;
    }
  }
</script>

<section class="mcp-section">
  <div class="section-header">
    <h2>MCP Servers</h2>
    <button class="btn-refresh" onclick={loadMCPServers} disabled={mcpLoading}>↻</button>
  </div>
  {#if mcpError}
    <p class="section-error">{mcpError}</p>
  {:else if mcpLoading}
    <p class="section-empty">Loading…</p>
  {:else if mcpServers.length === 0}
    <p class="section-empty">Click ↻ to load MCP servers from mcp-config.yaml.</p>
  {:else}
    <table class="data-table">
      <thead><tr><th>ID</th><th>Transport</th><th>Enabled</th><th>Trust</th><th>Tools</th></tr></thead>
      <tbody>
        {#each mcpServers as s}
          <tr>
            <td class="mono">{s.id}</td>
            <td>{s.transport}</td>
            <td>{s.enabled ? '✓' : '—'}</td>
            <td>{s.trust}</td>
            <td class="num">{s.tools.length}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .mcp-section { padding-top: 0.5rem; }
</style>
