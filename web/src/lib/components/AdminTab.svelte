<script lang="ts">
  // Admin module (ADR-0020) — users, role overrides, group→role mappings,
  // auth-source status, login audit. Admin role only (backend also enforces).
  import {
    adminListUsers, adminCreateUser, adminSetRole, adminSetEnabled,
    adminListGroupRoles, adminSetGroupRole, adminDeleteGroupRole,
    adminAuthStatus, adminTestConnection, adminLoginAudit,
    adminListProviders, adminTestProvider, adminGetDefaultModel, adminSetDefaultModel,
    adminSystemLogs, getModels,
    type AdminUser, type GroupRoleMapping, type AuthSourceStatus, type LoginEvent,
    type ProviderStatus, type ModelOption, type LogRecord,
  } from '$lib/api';

  const ROLES = ['viewer', 'operator', 'admin'] as const;
  const LOG_LEVELS = ['', 'INFO', 'WARNING', 'ERROR'] as const;
  let section = $state<'users' | 'mappings' | 'sources' | 'providers' | 'model' | 'audit' | 'logs'>('users');
  let error = $state<string | null>(null);

  let logs = $state<LogRecord[]>([]);
  let logsAvailable = $state<boolean>(true);
  let logLevel = $state<string>('');

  const loadLogs = () => guard(async () => {
    const r = await adminSystemLogs(logLevel, 300);
    logs = r.records;
    logsAvailable = r.available;
  });

  let providers = $state<ProviderStatus[]>([]);
  let providerTest = $state<Record<string, string>>({});
  let availableModels = $state<ModelOption[]>([]);
  let defaultModel = $state<string>('');

  const loadProviders = () => guard(async () => { providers = await adminListProviders(); });

  async function loadModelSettings() {
    await guard(async () => {
      const [models, current] = await Promise.all([getModels(), adminGetDefaultModel()]);
      availableModels = models.models;
      defaultModel = current ?? models.default_id;
    });
  }

  async function testProvider(id: string) {
    await guard(async () => {
      const r = await adminTestProvider(id);
      providerTest = { ...providerTest, [id]: `${r.ok ? '✓' : '✗'} ${r.detail}` };
    });
  }

  async function saveDefaultModel() {
    await guard(async () => { await adminSetDefaultModel(defaultModel || null); });
  }

  let users = $state<AdminUser[]>([]);
  let newUser = $state({ username: '', password: '', role: 'viewer' });

  let mappings = $state<GroupRoleMapping[]>([]);
  let newMap = $state<GroupRoleMapping>({ source: 'ldap', group_name: '', role: 'viewer' });

  let sources = $state<AuthSourceStatus[]>([]);
  let testResult = $state<Record<string, string>>({});
  let audit = $state<LoginEvent[]>([]);

  async function guard(fn: () => Promise<void>) {
    error = null;
    try { await fn(); } catch (e) { error = e instanceof Error ? e.message : String(e); }
  }

  const loadUsers = () => guard(async () => { users = await adminListUsers(); });
  const loadMappings = () => guard(async () => { mappings = await adminListGroupRoles(); });
  const loadSources = () => guard(async () => { sources = await adminAuthStatus(); });
  const loadAudit = () => guard(async () => { audit = await adminLoginAudit(); });

  async function createUser() {
    await guard(async () => {
      await adminCreateUser(newUser.username, newUser.password, newUser.role);
      newUser = { username: '', password: '', role: 'viewer' };
      await loadUsers();
    });
  }

  async function changeRole(u: AdminUser, role: string) {
    await guard(async () => { await adminSetRole(u.username, role); await loadUsers(); });
  }

  async function toggleEnabled(u: AdminUser) {
    await guard(async () => { await adminSetEnabled(u.username, !u.enabled); await loadUsers(); });
  }

  async function addMapping() {
    await guard(async () => {
      await adminSetGroupRole(newMap);
      newMap = { source: 'ldap', group_name: '', role: 'viewer' };
      await loadMappings();
    });
  }

  async function removeMapping(m: GroupRoleMapping) {
    await guard(async () => { await adminDeleteGroupRole(m.source, m.group_name); await loadMappings(); });
  }

  async function testConn(source: string) {
    await guard(async () => {
      const r = await adminTestConnection(source);
      testResult = { ...testResult, [source]: `${r.ok ? '✓' : '✗'} ${r.detail}` };
    });
  }

  let _loaded = false;
  $effect(() => { if (_loaded) return; _loaded = true; loadUsers(); });
</script>

<section>
  <div class="section-header">
    <h2>Administration</h2>
    <div class="section-tabs">
      <button class="tab-btn {section === 'users' ? 'active' : ''}" onclick={() => { section = 'users'; loadUsers(); }}>Users</button>
      <button class="tab-btn {section === 'mappings' ? 'active' : ''}" onclick={() => { section = 'mappings'; loadMappings(); }}>Group → role</button>
      <button class="tab-btn {section === 'sources' ? 'active' : ''}" onclick={() => { section = 'sources'; loadSources(); }}>Auth sources</button>
      <button class="tab-btn {section === 'providers' ? 'active' : ''}" onclick={() => { section = 'providers'; loadProviders(); }}>LLM providers</button>
      <button class="tab-btn {section === 'model' ? 'active' : ''}" onclick={() => { section = 'model'; loadModelSettings(); }}>Default model</button>
      <button class="tab-btn {section === 'audit' ? 'active' : ''}" onclick={() => { section = 'audit'; loadAudit(); }}>Login audit</button>
      <button class="tab-btn {section === 'logs' ? 'active' : ''}" onclick={() => { section = 'logs'; loadLogs(); }}>System logs</button>
    </div>
  </div>

  {#if error}<p class="section-error">{error}</p>{/if}

  {#if section === 'users'}
    <div class="admin-newrow">
      <input class="admin-input" placeholder="username" bind:value={newUser.username} />
      <input class="admin-input" type="password" placeholder="password" bind:value={newUser.password} />
      <select class="admin-input" bind:value={newUser.role}>
        {#each ROLES as r}<option value={r}>{r}</option>{/each}
      </select>
      <button class="btn-action" onclick={createUser} disabled={!newUser.username || !newUser.password}>Create</button>
    </div>
    <table class="data-table">
      <thead><tr><th>Username</th><th>Source</th><th>Role</th><th>Enabled</th></tr></thead>
      <tbody>
        {#each users as u}
          <tr>
            <td class="mono">{u.username}</td>
            <td class="dim">{u.auth_source}</td>
            <td>
              <select class="admin-input" value={u.role} onchange={(e) => changeRole(u, (e.target as HTMLSelectElement).value)}>
                {#each ROLES as r}<option value={r}>{r}</option>{/each}
              </select>
            </td>
            <td><button class="btn-secondary" onclick={() => toggleEnabled(u)}>{u.enabled ? 'disable' : 'enable'}</button></td>
          </tr>
        {/each}
      </tbody>
    </table>

  {:else if section === 'mappings'}
    <p class="admin-hint">Directory group / OIDC claim value → role. Used by LDAP and SSO logins; a per-user role override wins.</p>
    <div class="admin-newrow">
      <select class="admin-input" bind:value={newMap.source}>
        <option value="ldap">ldap</option><option value="oidc">oidc</option>
      </select>
      <input class="admin-input" placeholder="group / claim value" bind:value={newMap.group_name} />
      <select class="admin-input" bind:value={newMap.role}>
        {#each ROLES as r}<option value={r}>{r}</option>{/each}
      </select>
      <button class="btn-action" onclick={addMapping} disabled={!newMap.group_name}>Add</button>
    </div>
    <table class="data-table">
      <thead><tr><th>Source</th><th>Group / claim</th><th>Role</th><th></th></tr></thead>
      <tbody>
        {#each mappings as m}
          <tr>
            <td class="dim">{m.source}</td><td class="mono">{m.group_name}</td><td>{m.role}</td>
            <td><button class="btn-secondary" onclick={() => removeMapping(m)}>remove</button></td>
          </tr>
        {/each}
      </tbody>
    </table>

  {:else if section === 'sources'}
    <p class="admin-hint">Connection secrets live in environment variables and are never shown or stored here.</p>
    <table class="data-table">
      <thead><tr><th>Source</th><th>Configured</th><th></th><th>Result</th></tr></thead>
      <tbody>
        {#each sources as s}
          <tr>
            <td class="mono">{s.source}</td>
            <td>{s.configured ? '✓' : '—'}</td>
            <td>{#if s.source !== 'local'}<button class="btn-secondary" onclick={() => testConn(s.source)}>test connection</button>{/if}</td>
            <td class="dim">{testResult[s.source] ?? ''}</td>
          </tr>
        {/each}
      </tbody>
    </table>

  {:else if section === 'providers'}
    <p class="admin-hint">API keys are read from environment variables and are never shown or stored here (ADR-0020). Set them in <code>.env</code> / your deployment env.</p>
    <table class="data-table">
      <thead><tr><th>Provider</th><th>Env var</th><th>Configured</th><th></th><th>Result</th></tr></thead>
      <tbody>
        {#each providers as p}
          <tr>
            <td>{p.label}</td>
            <td class="mono dim">{p.env_var || '—'}</td>
            <td>{p.configured ? '✓' : '—'}</td>
            <td>{#if p.env_var}<button class="btn-secondary" onclick={() => testProvider(p.id)}>test</button>{/if}</td>
            <td class="dim">{providerTest[p.id] ?? ''}</td>
          </tr>
        {/each}
      </tbody>
    </table>

  {:else if section === 'model'}
    <p class="admin-hint">The team-default model, chosen from what the active playbook offers. Each run can still override it on the Run page.</p>
    <div class="admin-newrow">
      <select class="admin-input" bind:value={defaultModel}>
        {#each availableModels as m}<option value={m.id}>{m.label}</option>{/each}
      </select>
      <button class="btn-action" onclick={saveDefaultModel} disabled={!defaultModel}>Set default</button>
    </div>

  {:else if section === 'audit'}
    <table class="data-table">
      <thead><tr><th>When</th><th>Username</th><th>Source</th><th>Outcome</th></tr></thead>
      <tbody>
        {#each audit as e}
          <tr>
            <td class="dim mono">{e.ts.slice(0, 19)}</td><td class="mono">{e.username}</td>
            <td class="dim">{e.source}</td>
            <td class={e.outcome === 'success' ? '' : 'admin-fail'}>{e.outcome}</td>
          </tr>
        {/each}
      </tbody>
    </table>

  {:else}
    <p class="admin-hint">Recent in-process logs (newest last). Ephemeral and per-worker — for real log aggregation, ship the JSON stdout logs.</p>
    <div class="admin-newrow">
      <select class="admin-input" bind:value={logLevel} onchange={loadLogs}>
        {#each LOG_LEVELS as lv}<option value={lv}>{lv || 'all levels'}</option>{/each}
      </select>
      <button class="btn-action" onclick={loadLogs}>Refresh</button>
    </div>
    {#if !logsAvailable}
      <p class="section-empty">Log buffer not available.</p>
    {:else if logs.length === 0}
      <p class="section-empty">No log records captured yet.</p>
    {:else}
      <table class="data-table">
        <thead><tr><th>When</th><th>Level</th><th>Logger</th><th>Message</th></tr></thead>
        <tbody>
          {#each logs as r}
            <tr>
              <td class="dim mono">{r.ts.slice(0, 23)}</td>
              <td class="mono {r.level === 'ERROR' || r.level === 'CRITICAL' ? 'admin-fail' : r.level === 'WARNING' ? 'admin-warn' : 'dim'}">{r.level}</td>
              <td class="mono dim">{r.logger}</td>
              <td>{r.msg}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}
</section>

<style>
  .admin-newrow { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .admin-input {
    font-size: 0.85rem; padding: 0.35rem 0.5rem; border-radius: 4px;
    border: 1px solid var(--border-strong); background: var(--bg-subtle); color: var(--text);
  }
  .admin-hint { font-size: 0.82rem; color: var(--text-muted); margin: 0 0 0.8rem; }
  .admin-fail { color: #ef4444; }
  .admin-warn { color: #d97706; }
</style>
