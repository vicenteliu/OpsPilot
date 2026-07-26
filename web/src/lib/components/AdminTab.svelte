<script lang="ts">
  // Admin module (ADR-0020) — users, role overrides, group→role mappings,
  // auth-source status, login audit. Admin role only (backend also enforces).
  import {
    adminListUsers, adminCreateUser, adminSetRole, adminSetEnabled,
    adminListGroupRoles, adminSetGroupRole, adminDeleteGroupRole,
    adminAuthStatus, adminTestConnection, adminLoginAudit,
    adminListProviders, adminTestProvider, adminGetDefaultModel, adminSetDefaultModel,
    adminGetModelTiers, adminSetModelTiers,
    adminGetPlaybookModels, adminSetPlaybookModels,
    adminListSkills, adminGetSkill, adminSaveSkill, adminDraftSkill,
    adminListMcpServers, adminSaveMcpServer, adminDeleteMcpServer,
    adminSystemLogs, getModels,
    type AdminUser, type GroupRoleMapping, type AuthSourceStatus, type LoginEvent,
    type ProviderStatus, type ModelOption, type LogRecord, type PlaybookModelEntry,
    type SkillSummary, type AdminMcpServer, type RemoteMcpUpsert,
  } from '$lib/api';

  const ROLES = ['viewer', 'operator', 'admin'] as const;
  const LOG_LEVELS = ['', 'INFO', 'WARNING', 'ERROR'] as const;
  const PROVIDER_IDS = ['anthropic', 'openai', 'openrouter', 'gemini', 'grok', 'ollama-local'] as const;
  const MODEL_KINDS = ['anthropic', 'openai', 'ollama'] as const;
  const SKILL_TRUST = ['internal', 'community', 'unknown'] as const;
  const SKILL_TOOLS = ['kb_search'] as const;
  let section = $state<'users' | 'mappings' | 'sources' | 'providers' | 'modellist' | 'model' | 'skills' | 'mcp' | 'audit' | 'logs'>('users');
  let error = $state<string | null>(null);

  const MCP_TRANSPORTS = ['http', 'sse'] as const;
  const MCP_TRUST = ['unknown', 'community', 'trusted'] as const;
  const MCP_AUTH = ['none', 'api_key_header', 'bearer_env', 'oauth2'] as const;
  type McpForm = RemoteMcpUpsert & { id: string };
  let mcpServers = $state<AdminMcpServer[]>([]);
  let mcpForm = $state<McpForm | null>(null);
  let mcpMsg = $state<string>('');

  const loadMcpServers = () => guard(async () => {
    mcpServers = await adminListMcpServers();
    mcpForm = null;
    mcpMsg = '';
  });

  function newMcpServer() {
    mcpForm = {
      id: '', name: '', transport: 'http', url: '', tools_prefix: 'mcp__',
      trust: 'unknown', enabled: true, description: '',
      auth_type: 'none', auth_env: '', auth_header: ''
    };
    mcpMsg = '';
  }

  function editMcpServer(s: AdminMcpServer) {
    mcpForm = {
      id: s.id, name: s.name, transport: (s.transport === 'sse' ? 'sse' : 'http'),
      url: s.url ?? '', tools_prefix: s.tools_prefix, trust: s.trust, enabled: s.enabled,
      description: '', auth_type: 'none', auth_env: '', auth_header: ''
    };
    mcpMsg = '';
  }

  const saveMcpServer = () => guard(async () => {
    if (!mcpForm) return;
    const f = mcpForm;
    if (!f.id.trim() || !f.name.trim() || !f.url.trim()) {
      throw new Error('id, name and url are required.');
    }
    const { id, ...payload } = f;
    mcpServers = await adminSaveMcpServer(id, payload);
    mcpForm = null;
    mcpMsg = 'Saved — mcp-config.yaml updated and reloaded.';
  });

  const removeMcpServer = (s: AdminMcpServer) => guard(async () => {
    await adminDeleteMcpServer(s.id);
    mcpServers = await adminListMcpServers();
  });

  type SkillForm = { id: string; name: string; trigger: string; body: string; allowed_tools: string[]; trust: string };
  let skills = $state<SkillSummary[]>([]);
  let skillForm = $state<SkillForm | null>(null);
  let skillIsNew = $state<boolean>(false);
  let skillMsg = $state<string>('');
  let draftPrompt = $state<string>('');
  let drafting = $state<boolean>(false);

  const loadSkills = () => guard(async () => {
    skills = await adminListSkills();
    skillForm = null;
    skillMsg = '';
  });

  function newSkill() {
    skillForm = { id: '', name: '', trigger: '', body: '', allowed_tools: ['kb_search'], trust: 'internal' };
    skillIsNew = true;
    skillMsg = '';
    draftPrompt = '';
  }

  const draftSkill = () => guard(async () => {
    if (!draftPrompt.trim()) throw new Error('Describe the problem to draft from.');
    drafting = true;
    try {
      const d = await adminDraftSkill(draftPrompt);
      skillForm = { id: d.id, name: d.name, trigger: d.trigger, body: d.body, allowed_tools: d.allowed_tools, trust: d.trust };
    } finally {
      drafting = false;
    }
  });

  const editSkill = (id: string) => guard(async () => {
    const d = await adminGetSkill(id);
    skillForm = { id: d.id, name: d.name, trigger: d.trigger, body: d.body, allowed_tools: d.allowed_tools, trust: d.trust };
    skillIsNew = false;
    skillMsg = '';
  });

  const saveSkill = () => guard(async () => {
    if (!skillForm) return;
    const f = skillForm;
    if (!f.id.trim() || !f.name.trim() || !f.trigger.trim() || !f.body.trim()) {
      throw new Error('id, name, trigger and body are all required.');
    }
    await adminSaveSkill(f.id, { name: f.name, trigger: f.trigger, body: f.body, allowed_tools: f.allowed_tools, trust: f.trust });
    skills = await adminListSkills();
    skillForm = null;
    skillMsg = 'Saved — SKILL.md written and reloaded.';
  });

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

  let playbookModels = $state<PlaybookModelEntry[]>([]);
  let playbookId = $state<string>('');
  let modelListMsg = $state<string>('');

  const loadPlaybookModels = () => guard(async () => {
    modelListMsg = '';
    const r = await adminGetPlaybookModels();
    playbookId = r.playbook_id;
    playbookModels = r.models;
  });

  function addModelRow() {
    playbookModels = [
      ...playbookModels,
      { provider_id: 'anthropic', kind: 'anthropic', name: '', version: '',
        params: { temperature: 0.2, top_p: 0.9, max_tokens: 4096 }, primary: false },
    ];
  }

  function removeModelRow(i: number) {
    playbookModels = playbookModels.filter((_, idx) => idx !== i);
  }

  const savePlaybookModels = () => guard(async () => {
    modelListMsg = '';
    if (playbookModels.some((m) => !m.name.trim() || !m.version.trim())) {
      throw new Error('Every model needs a name and version.');
    }
    const r = await adminSetPlaybookModels(playbookModels);
    playbookModels = r.models;
    modelListMsg = 'Saved — playbook.yaml updated and reloaded.';
  });

  const loadProviders = () => guard(async () => { providers = await adminListProviders(); });

  let cheapModel = $state<string>('');
  let thinkingModel = $state<string>('');
  let tiersMsg = $state<string>('');

  async function loadModelSettings() {
    await guard(async () => {
      const [models, current, tiers] = await Promise.all([
        getModels(), adminGetDefaultModel(), adminGetModelTiers()
      ]);
      availableModels = models.models;
      defaultModel = current ?? models.default_id;
      cheapModel = tiers.cheap_model_id ?? '';
      thinkingModel = tiers.thinking_model_id ?? '';
      tiersMsg = '';
    });
  }

  async function saveModelTiers() {
    await guard(async () => {
      await adminSetModelTiers({ cheap_model_id: cheapModel || null, thinking_model_id: thinkingModel || null });
      tiersMsg = 'Saved.';
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
      <button class="tab-btn {section === 'modellist' ? 'active' : ''}" onclick={() => { section = 'modellist'; loadPlaybookModels(); }}>Model list</button>
      <button class="tab-btn {section === 'model' ? 'active' : ''}" onclick={() => { section = 'model'; loadModelSettings(); }}>Default model</button>
      <button class="tab-btn {section === 'skills' ? 'active' : ''}" onclick={() => { section = 'skills'; loadSkills(); }}>Skills</button>
      <button class="tab-btn {section === 'mcp' ? 'active' : ''}" onclick={() => { section = 'mcp'; loadMcpServers(); }}>MCP servers</button>
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

  {:else if section === 'modellist'}
    <p class="admin-hint">
      Selectable models for the active playbook <code>{playbookId}</code> — the first row is the primary,
      the rest appear in the Run-page and Default-model dropdowns. Saving rewrites the version-controlled
      <code>playbook.yaml</code> in place and reloads it live.
    </p>
    <p class="admin-warn admin-hint">
      ⚠ This bypasses the regression harness that normally gates model upgrades. Enter models your
      providers can actually serve; the primary cannot be removed. <code>kind</code> is the provider
      protocol (anthropic / openai / ollama).
    </p>
    <table class="data-table">
      <thead><tr><th></th><th>Provider</th><th>Kind</th><th>Name</th><th>Version</th><th></th></tr></thead>
      <tbody>
        {#each playbookModels as m, i}
          <tr>
            <td class="dim">{i === 0 ? 'primary' : ''}</td>
            <td>
              <select class="admin-input" bind:value={m.provider_id}>
                {#each PROVIDER_IDS as p}<option value={p}>{p}</option>{/each}
              </select>
            </td>
            <td>
              <select class="admin-input" bind:value={m.kind}>
                {#each MODEL_KINDS as k}<option value={k}>{k}</option>{/each}
              </select>
            </td>
            <td><input class="admin-input" placeholder="model name" bind:value={m.name} /></td>
            <td><input class="admin-input admin-input-sm" placeholder="version" bind:value={m.version} /></td>
            <td>{#if i > 0}<button class="btn-secondary" onclick={() => removeModelRow(i)}>remove</button>{/if}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="admin-newrow">
      <button class="btn-secondary" onclick={addModelRow}>+ Add model</button>
      <button class="btn-action" onclick={savePlaybookModels} disabled={playbookModels.length === 0}>Save changes</button>
      {#if modelListMsg}<span class="admin-ok">{modelListMsg}</span>{/if}
    </div>

  {:else if section === 'model'}
    <p class="admin-hint">The team-default model, chosen from what the active playbook offers. Each run can still override it on the Run page.</p>
    <div class="admin-newrow">
      <select class="admin-input" bind:value={defaultModel}>
        {#each availableModels as m}<option value={m.id}>{m.label}</option>{/each}
      </select>
      <button class="btn-action" onclick={saveDefaultModel} disabled={!defaultModel}>Set default</button>
    </div>

    <p class="admin-hint">
      <strong>Complexity tiers (ADR-0023)</strong> — the Chat "deep thinking" toggle routes to the
      thinking tier; other turns use the cheap tier. A model reasons deeply only when its own params
      enable extended thinking. Leave blank to disable a tier.
    </p>
    <div class="admin-newrow">
      <select class="admin-input" bind:value={cheapModel}>
        <option value="">cheap tier — (none)</option>
        {#each availableModels as m}<option value={m.id}>{m.label}</option>{/each}
      </select>
      <select class="admin-input" bind:value={thinkingModel}>
        <option value="">thinking tier — (none)</option>
        {#each availableModels as m}<option value={m.id}>{m.label}</option>{/each}
      </select>
      <button class="btn-action" onclick={saveModelTiers}>Save tiers</button>
      {#if tiersMsg}<span class="admin-ok">{tiersMsg}</span>{/if}
    </div>

  {:else if section === 'skills'}
    <p class="admin-hint">
      Troubleshooting skills the assistant loads on demand in Chat (ADR-0022). Saving writes
      <code>agent_skills/&lt;id&gt;/SKILL.md</code> in place (a git diff) and reloads it live.
      Skills guide the assistant — they don't override human judgement — and aren't harness-gated.
    </p>
    {#if !skillForm}
      <div class="admin-newrow">
        <button class="btn-action" onclick={newSkill}>+ New skill</button>
        {#if skillMsg}<span class="admin-ok">{skillMsg}</span>{/if}
      </div>
      <table class="data-table">
        <thead><tr><th>ID</th><th>Name</th><th>When to use</th><th>Trust</th><th></th></tr></thead>
        <tbody>
          {#each skills as s}
            <tr>
              <td class="mono">{s.id}</td>
              <td>{s.name}</td>
              <td class="dim">{s.trigger}</td>
              <td class="dim">{s.trust}</td>
              <td><button class="btn-secondary" onclick={() => editSkill(s.id)}>edit</button></td>
            </tr>
          {/each}
          {#if skills.length === 0}
            <tr><td colspan="5" class="section-empty">No skills yet — create one.</td></tr>
          {/if}
        </tbody>
      </table>
    {:else}
      <div class="skill-editor">
        {#if skillIsNew}
          <div class="skill-draft">
            <span class="skill-draft-label">✨ Draft with AI</span>
            <textarea
              class="admin-input"
              rows={2}
              bind:value={draftPrompt}
              placeholder="Describe a common problem — the assistant drafts a skill you can review and edit below."
              disabled={drafting}
            ></textarea>
            <button class="btn-secondary" onclick={draftSkill} disabled={drafting || !draftPrompt.trim()}>
              {drafting ? 'Drafting…' : 'Draft'}
            </button>
          </div>
        {/if}
        <label class="skill-field">
          <span>ID (kebab-case)</span>
          <input class="admin-input" bind:value={skillForm.id} disabled={!skillIsNew} placeholder="vpn-auth-failures" />
        </label>
        <label class="skill-field">
          <span>Name</span>
          <input class="admin-input" bind:value={skillForm.name} placeholder="VPN authentication failures" />
        </label>
        <label class="skill-field">
          <span>When to use (trigger)</span>
          <input class="admin-input" bind:value={skillForm.trigger} placeholder="A user cannot authenticate to the VPN…" />
        </label>
        <div class="skill-field">
          <span>Allowed tools</span>
          <div class="skill-tools">
            {#each SKILL_TOOLS as t}
              <label class="skill-tool"><input type="checkbox" bind:group={skillForm.allowed_tools} value={t} /> {t}</label>
            {/each}
          </div>
        </div>
        <label class="skill-field">
          <span>Trust</span>
          <select class="admin-input" bind:value={skillForm.trust}>
            {#each SKILL_TRUST as t}<option value={t}>{t}</option>{/each}
          </select>
        </label>
        <label class="skill-field">
          <span>Procedure (markdown)</span>
          <textarea class="admin-input skill-body" rows={14} bind:value={skillForm.body} placeholder="# Steps…"></textarea>
        </label>
        <div class="admin-newrow">
          <button class="btn-action" onclick={saveSkill}>Save skill</button>
          <button class="btn-secondary" onclick={() => { skillForm = null; }}>Cancel</button>
        </div>
      </div>
    {/if}

  {:else if section === 'mcp'}
    <p class="admin-hint">
      MCP tool servers the chat agent can call. Add/edit <strong>remote</strong> (http/sse) servers here —
      URL + auth via an environment variable (the secret is never stored). <strong>stdio</strong> servers run
      a local command (= code execution), so they're file-managed only: edit <code>mcp-config.yaml</code> and
      git-review them (ADR-0024). Saving writes the config and reloads live.
    </p>
    {#if !mcpForm}
      <div class="admin-newrow">
        <button class="btn-action" onclick={newMcpServer}>+ Add remote server</button>
        {#if mcpMsg}<span class="admin-ok">{mcpMsg}</span>{/if}
      </div>
      <table class="data-table">
        <thead><tr><th>ID</th><th>Name</th><th>Transport</th><th>URL</th><th>Enabled</th><th>Trust</th><th></th></tr></thead>
        <tbody>
          {#each mcpServers as s}
            <tr>
              <td class="mono">{s.id}</td>
              <td>{s.name}</td>
              <td class="dim">{s.transport}</td>
              <td class="dim mono">{s.url ?? '—'}</td>
              <td>{s.enabled ? '✓' : '—'}</td>
              <td class="dim">{s.trust}</td>
              <td>
                {#if s.read_only}
                  <span class="dim" title="stdio — file-managed in mcp-config.yaml">file-managed</span>
                {:else}
                  <button class="btn-secondary" onclick={() => editMcpServer(s)}>edit</button>
                  <button class="btn-secondary" onclick={() => removeMcpServer(s)}>remove</button>
                {/if}
              </td>
            </tr>
          {/each}
          {#if mcpServers.length === 0}
            <tr><td colspan="7" class="section-empty">No MCP servers configured.</td></tr>
          {/if}
        </tbody>
      </table>
    {:else}
      <div class="skill-editor">
        <label class="skill-field"><span>ID (kebab-case)</span>
          <input class="admin-input" bind:value={mcpForm.id} placeholder="search" /></label>
        <label class="skill-field"><span>Name</span>
          <input class="admin-input" bind:value={mcpForm.name} placeholder="Web Search" /></label>
        <label class="skill-field"><span>Transport</span>
          <select class="admin-input" bind:value={mcpForm.transport}>
            {#each MCP_TRANSPORTS as t}<option value={t}>{t}</option>{/each}
          </select></label>
        <label class="skill-field"><span>URL</span>
          <input class="admin-input" bind:value={mcpForm.url} placeholder="https://host/mcp" /></label>
        <label class="skill-field"><span>Tools prefix</span>
          <input class="admin-input" bind:value={mcpForm.tools_prefix} placeholder="mcp__search__" /></label>
        <label class="skill-field"><span>Trust</span>
          <select class="admin-input" bind:value={mcpForm.trust}>
            {#each MCP_TRUST as t}<option value={t}>{t}</option>{/each}
          </select></label>
        <label class="skill-field"><span>Auth</span>
          <select class="admin-input" bind:value={mcpForm.auth_type}>
            {#each MCP_AUTH as a}<option value={a}>{a}</option>{/each}
          </select></label>
        {#if mcpForm.auth_type !== 'none'}
          <label class="skill-field"><span>Auth env var (holds the secret)</span>
            <input class="admin-input" bind:value={mcpForm.auth_env} placeholder="SEARCH_TOKEN" /></label>
          {#if mcpForm.auth_type === 'api_key_header'}
            <label class="skill-field"><span>Header name</span>
              <input class="admin-input" bind:value={mcpForm.auth_header} placeholder="X-API-Key" /></label>
          {/if}
        {/if}
        <label class="skill-tool"><input type="checkbox" bind:checked={mcpForm.enabled} /> Enabled</label>
        <div class="admin-newrow">
          <button class="btn-action" onclick={saveMcpServer}>Save server</button>
          <button class="btn-secondary" onclick={() => { mcpForm = null; }}>Cancel</button>
        </div>
      </div>
    {/if}

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
  .admin-input-sm { width: 7rem; }
  .admin-hint { font-size: 0.82rem; color: var(--text-muted); margin: 0 0 0.8rem; }
  .admin-fail { color: #ef4444; }
  .admin-warn { color: #d97706; }
  .admin-ok { font-size: 0.82rem; color: #16a34a; align-self: center; }
  .skill-editor { display: flex; flex-direction: column; gap: 0.75rem; max-width: 46rem; }
  .skill-field { display: flex; flex-direction: column; gap: 0.25rem; }
  .skill-field > span { font-size: 0.78rem; color: var(--text-muted); }
  .skill-body { font-family: var(--font-mono, monospace); resize: vertical; }
  .skill-tools { display: flex; gap: 1rem; }
  .skill-tool { display: flex; align-items: center; gap: 0.3rem; font-size: 0.85rem; }
  .skill-draft {
    display: flex; flex-direction: column; gap: 0.4rem; padding: 0.6rem;
    border: 1px dashed var(--border-strong, rgba(127, 127, 127, 0.4)); border-radius: 6px;
  }
  .skill-draft-label { font-size: 0.82rem; color: var(--text-muted); }
  .skill-draft button { align-self: flex-start; }
</style>
