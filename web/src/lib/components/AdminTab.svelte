<script lang="ts">
  // Admin module (ADR-0020) — users, role overrides, group→role mappings,
  // auth-source status, login audit. Admin role only (backend also enforces).
  import {
    adminListUsers, adminCreateUser, adminSetRole, adminSetEnabled,
    adminListGroupRoles, adminSetGroupRole, adminDeleteGroupRole,
    adminAuthStatus, adminTestConnection, adminLoginAudit,
    type AdminUser, type GroupRoleMapping, type AuthSourceStatus, type LoginEvent,
  } from '$lib/api';

  const ROLES = ['viewer', 'operator', 'admin'] as const;
  let section = $state<'users' | 'mappings' | 'sources' | 'audit'>('users');
  let error = $state<string | null>(null);

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
      <button class="tab-btn {section === 'audit' ? 'active' : ''}" onclick={() => { section = 'audit'; loadAudit(); }}>Login audit</button>
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

  {:else}
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
</style>
