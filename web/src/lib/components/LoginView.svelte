<script lang="ts">
  // Login screen (ADR-0020). Shown until GET /api/auth/me resolves a user.
  import { login, type Me } from '$lib/api';

  let { onLogin }: { onLogin: (me: Me) => void } = $props();

  let username = $state('');
  let password = $state('');
  let error = $state<string | null>(null);
  let busy = $state(false);

  async function submit(e: Event) {
    e.preventDefault();
    busy = true;
    error = null;
    try {
      onLogin(await login(username, password));
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }
</script>

<div class="login-wrap">
  <form class="login-card" onsubmit={submit}>
    <div class="login-brand">
      <span class="brand-dot"></span>
      <span class="brand-name">OpsPilot</span>
    </div>
    <p class="login-sub">Sign in to the workbench</p>
    <label class="login-field">
      <span>Username</span>
      <input bind:value={username} autocomplete="username" required />
    </label>
    <label class="login-field">
      <span>Password</span>
      <input type="password" bind:value={password} autocomplete="current-password" required />
    </label>
    {#if error}<p class="login-error">{error}</p>{/if}
    <button class="login-btn" type="submit" disabled={busy || !username || !password}>
      {busy ? 'Signing in…' : 'Sign in'}
    </button>
  </form>
</div>

<style>
  .login-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 1rem;
  }

  .login-card {
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
    width: 100%;
    max-width: 340px;
    padding: 1.75rem;
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 10px;
  }

  .login-brand {
    display: flex;
    align-items: center;
    gap: 0.55rem;
  }

  .brand-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--primary);
    box-shadow: 0 0 8px var(--primary);
  }

  .brand-name {
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--text);
  }

  .login-sub {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin: -0.3rem 0 0.4rem;
  }

  .login-field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.8rem;
    color: var(--text-muted);
  }

  .login-field input {
    font-size: 0.9rem;
    padding: 0.5rem 0.6rem;
    border-radius: 6px;
    border: 1px solid var(--border-strong);
    background: var(--bg-subtle);
    color: var(--text);
  }

  .login-error {
    font-size: 0.82rem;
    color: #ef4444;
    margin: 0;
  }

  .login-btn {
    margin-top: 0.3rem;
    padding: 0.55rem;
    font-size: 0.9rem;
    font-weight: 600;
    color: #fff;
    background: var(--primary);
    border: none;
    border-radius: 6px;
    cursor: pointer;
  }

  .login-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
</style>
