<script lang="ts">
  // Chat tab — the **Consultation** surface (ADR-0032). Turns persist, the open
  // **Working set** decides which recorded **Memory** applies, and any sentence
  // the assistant says can be pinned into Memory with a reason.
  import {
    chatStream, getWorkingSet, openWorkingSet, closeWorkingSet, pinMessage,
    getConsultation, listMemoryScopes, escalateConsultation,
    type ChatMessage, type ChatCitation, type WorkingSet,
  } from '$lib/api';

  let { selectedModelId }: { selectedModelId: string } = $props();

  // An assistant turn carries its answer, the KB citations it grounded on, and —
  // once persisted — the message id that a pin cites as its source.
  type ChatTurn = ChatMessage & { citations?: ChatCitation[]; messageId?: string };

  let chatMessages = $state<ChatTurn[]>([]);
  let chatInput = $state<string>('');
  let deepThinking = $state<boolean>(false);
  let chatLoading = $state<boolean>(false);
  let chatStatusLines = $state<string[]>([]);
  let chatSteps = $state<string[]>([]);
  let chatError = $state<string | null>(null);
  let chatUsage = $state<{ input_tokens: number; output_tokens: number; cost_usd: number } | null>(null);

  // The Consultation this conversation is being written into.
  let consultationId = $state<string | null>(null);
  // A Working set closed by the inactivity fallback owes its owner one notice,
  // or they misread why the assistant lost the thread.
  let notice = $state<string | null>(null);

  let workingSet = $state<WorkingSet | null>(null);
  let wsTitle = $state<string>('');
  let wsScope = $state<string>('');
  let wsEditing = $state<boolean>(false);
  let scopes = $state<string[]>([]);

  // Pinning: a sentence becomes a Memory entry only with a reason typed here.
  let pinFor = $state<number | null>(null);
  let pinStatement = $state<string>('');
  let pinReason = $state<string>('');
  let pinScope = $state<string>('');
  let pinBusy = $state<boolean>(false);
  let pinError = $state<string | null>(null);
  let pinned = $state<Record<number, string>>({});

  async function loadWorkingSet() {
    try {
      const res = await getWorkingSet();
      workingSet = res.working_set;
      if (res.notice) notice = res.notice;
      scopes = await listMemoryScopes();
    } catch { /* the bar is an aid, not a gate */ }
  }

  async function startWorkingSet() {
    if (!wsTitle.trim()) return;
    workingSet = await openWorkingSet({ title: wsTitle.trim(), scope: wsScope.trim() || null });
    wsEditing = false; wsTitle = ''; wsScope = '';
  }

  async function endWorkingSet() {
    await closeWorkingSet();
    workingSet = null;
  }

  // The message ids come back only after the turn is persisted, so pinning
  // waits for the Consultation to be re-read.
  async function refreshMessageIds() {
    if (!consultationId) return;
    try {
      const con = await getConsultation(consultationId);
      const assistants = con.messages.filter((m) => m.role === 'assistant');
      let i = 0;
      chatMessages = chatMessages.map((m) =>
        m.role === 'assistant' ? { ...m, messageId: assistants[i++]?.id } : m
      );
    } catch { /* pinning stays unavailable; the answer is unaffected */ }
  }

  async function pin(index: number) {
    const msg = chatMessages[index];
    if (!consultationId || !msg?.messageId) return;
    pinBusy = true; pinError = null;
    try {
      const entry = await pinMessage(consultationId, msg.messageId, {
        reason: pinReason,
        statement: pinStatement.trim() || undefined,
        scope: pinScope.trim() || workingSet?.scope || null,
      });
      pinned = { ...pinned, [index]: entry.id };
      pinFor = null; pinReason = ''; pinStatement = ''; pinScope = '';
    } catch (e) { pinError = e instanceof Error ? e.message : String(e); }
    finally { pinBusy = false; }
  }

  // Escalation: a Consultation reads; a Session acts. Only the Work item
  // description travels — the transcript stays behind, because a Fixture has to
  // be freezable and an arbitrarily long conversation is not (ADR-0032).
  let escalating = $state<boolean>(false);
  let escalateText = $state<string>('');
  let escalateBusy = $state<boolean>(false);
  let escalatedTo = $state<string | null>(null);
  let escalateError = $state<string | null>(null);

  async function doEscalate() {
    if (!consultationId || !escalateText.trim()) return;
    escalateBusy = true; escalateError = null;
    try {
      const res = await escalateConsultation(consultationId, escalateText.trim());
      escalatedTo = res.session_id;
      escalating = false;
    } catch (e) { escalateError = e instanceof Error ? e.message : String(e); }
    finally { escalateBusy = false; }
  }

  let _wsInit = false;
  $effect(() => { if (!_wsInit) { _wsInit = true; loadWorkingSet(); } });

  async function handleChat() {
    if (!chatInput.trim() || chatLoading) return;
    const userMsg = chatInput.trim();
    chatInput = '';
    chatMessages = [...chatMessages, { role: 'user', content: userMsg }];
    chatLoading = true;
    chatStatusLines = [];
    chatSteps = [];
    chatError = null;
    try {
      for await (const event of chatStream(
        [...chatMessages], selectedModelId || undefined, deepThinking, consultationId
      )) {
        if (event.type === 'status') {
          chatStatusLines = [...chatStatusLines, event.message];
        } else if (event.type === 'tool_call') {
          const label =
            event.tool === 'kb_search' ? `🔍 Searching KB: "${event.query}"`
            : event.tool === 'web_search' ? `🌐 Web search: "${event.query}"`
            : `🔧 ${event.tool}`;
          chatSteps = [...chatSteps, label];
        } else if (event.type === 'tool_result') {
          const label =
            event.tool === 'kb_search' || event.tool === 'web_search'
              ? `↳ ${event.hits} result${event.hits === 1 ? '' : 's'}`
              : '↳ done';
          chatSteps = [...chatSteps, label];
        } else if (event.type === 'skill_loaded') {
          chatSteps = [...chatSteps, `📋 Using skill: ${event.skill}`];
        } else if (event.type === 'routing') {
          chatSteps = [...chatSteps, `🧭 Routed to ${event.tier} tier`];
        } else if (event.type === 'result') {
          chatMessages = [
            ...chatMessages,
            { role: 'assistant', content: event.data.content, citations: event.data.citations }
          ];
          chatUsage = event.data.usage;
          if (event.data.consultation_id) consultationId = event.data.consultation_id;
          refreshMessageIds();
        } else if (event.type === 'notice') {
          notice = event.message;
        } else if (event.type === 'error') {
          chatError = event.message;
        }
      }
    } catch (e) {
      chatError = e instanceof Error ? e.message : String(e);
    } finally {
      chatLoading = false;
      chatStatusLines = [];
      chatSteps = [];
    }
  }

  function handleChatKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleChat();
    }
  }
</script>

<section class="chat-section">
  {#if notice}
    <div class="ws-notice">
      {notice}
      <button class="ws-dismiss" onclick={() => (notice = null)} aria-label="Dismiss">×</button>
    </div>
  {/if}

  <div class="ws-bar">
    {#if wsEditing}
      <input class="ws-input" bind:value={wsTitle} placeholder="What are you chasing?" />
      <input class="ws-input ws-scope" bind:value={wsScope} list="ws-scopes"
             placeholder="Where — site / environment" />
      <datalist id="ws-scopes">{#each scopes as s}<option value={s}></option>{/each}</datalist>
      <button class="btn-action" onclick={startWorkingSet} disabled={!wsTitle.trim()}>Start</button>
      <button class="btn-secondary" onclick={() => (wsEditing = false)}>Cancel</button>
    {:else if workingSet}
      <span class="ws-label">Working on</span>
      <strong>{workingSet.title}</strong>
      <span class="ws-anchor">{workingSet.scope ?? workingSet.asset_id ?? 'no anchor'}</span>
      <button class="btn-secondary ws-end" onclick={endWorkingSet}>Done</button>
    {:else}
      <span class="ws-idle">
        No working set — this chat sees only environment facts that apply everywhere.
      </span>
      <button class="btn-secondary" onclick={() => (wsEditing = true)}>Set one</button>
    {/if}
  </div>

  <div class="chat-messages" id="chat-messages">
    {#if chatMessages.length === 0}
      <div class="chat-empty">
        <p>Ask anything about your IT operations. OpsPilot will search the knowledge base and answer.</p>
        <div class="chat-suggestions">
          <button class="suggestion-btn" onclick={() => { chatInput = 'How do I troubleshoot VPN authentication failures?'; handleChat(); }}>
            VPN authentication failures
          </button>
          <button class="suggestion-btn" onclick={() => { chatInput = 'What are common causes of network connectivity issues?'; handleChat(); }}>
            Network connectivity issues
          </button>
          <button class="suggestion-btn" onclick={() => { chatInput = 'How do I reset a user password?'; handleChat(); }}>
            Reset user password
          </button>
        </div>
      </div>
    {:else}
      {#each chatMessages as msg, i}
        <div class="chat-bubble {msg.role}">
          <div class="bubble-col">
            <div class="bubble-content">{msg.content}</div>

            {#if msg.role === 'assistant'}
              {#if pinned[i]}
                <div class="pin-done">Remembered as {pinned[i]}</div>
              {:else if pinFor === i}
                <div class="pin-form">
                  <input class="ws-input" bind:value={pinStatement}
                         placeholder="The standing fact, as one sentence (blank = the whole message)" />
                  <input class="ws-input" bind:value={pinReason}
                         placeholder="Why it is worth remembering (required)" />
                  <input class="ws-input ws-scope" bind:value={pinScope} list="ws-scopes"
                         placeholder={workingSet?.scope ?? 'Where it applies'} />
                  {#if pinError}<div class="pin-error">{pinError}</div>{/if}
                  <div class="pin-actions">
                    <button class="btn-action" onclick={() => pin(i)}
                            disabled={pinBusy || !pinReason.trim()}>
                      {pinBusy ? 'Remembering…' : 'Remember this'}
                    </button>
                    <button class="btn-secondary" onclick={() => { pinFor = null; pinError = null; }}>
                      Cancel
                    </button>
                  </div>
                  <p class="pin-hint">
                    The reason is what tells a real finding from a misdiagnosis when
                    this comes up again months from now.
                  </p>
                </div>
              {:else if msg.messageId}
                <button class="pin-btn" onclick={() => {
                  pinFor = i; pinStatement = ''; pinReason = ''; pinScope = ''; pinError = null;
                }}>Remember this</button>
              {/if}
            {/if}

            {#if msg.role === 'assistant' && msg.citations && msg.citations.length > 0}
              <div class="chat-citations">
                <span class="cite-label">Sources</span>
                {#each msg.citations as c}
                  <span class="cite-chip" title={c.snippet}>
                    {c.source_path ?? c.document_id ?? c.chunk_id}
                    {#if c.source_authority}
                      <span class="cite-authority"
                            title="How far this source is trusted. Recorded at ingest; it does not affect ranking.">
                        {c.source_authority}
                      </span>
                    {/if}
                  </span>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      {/each}
      {#if chatLoading}
        <div class="chat-bubble assistant">
          <div class="bubble-content chat-thinking">
            {#if chatSteps.length > 0}
              {#each chatSteps as step}<div class="chat-step">{step}</div>{/each}
            {/if}
            <div>{chatStatusLines[chatStatusLines.length - 1] ?? 'Thinking'}…</div>
          </div>
        </div>
      {/if}
    {/if}
  </div>

  {#if chatError}
    <div class="error-banner" style="margin: 0.5rem 0"><strong>Error:</strong> {chatError}</div>
  {/if}

  {#if consultationId && chatMessages.length > 0}
    <div class="esc-bar">
      {#if escalatedTo}
        <span class="esc-done">Escalated to {escalatedTo}</span>
      {:else if escalating}
        <div class="esc-form">
          <input class="ws-input" bind:value={escalateText}
                 placeholder="The work item, in a sentence — the conversation does not travel" />
          {#if escalateError}<div class="pin-error">{escalateError}</div>{/if}
          <div class="pin-actions">
            <button class="btn-action" onclick={doEscalate}
                    disabled={escalateBusy || !escalateText.trim()}>
              {escalateBusy ? 'Running…' : 'Run as a session'}
            </button>
            <button class="btn-secondary" onclick={() => (escalating = false)}>Cancel</button>
          </div>
          <p class="pin-hint">
            A session is replayable and scoreable, which is why its input has to
            have edges. Write what the problem is; the transcript stays here and
            the two stay linked.
          </p>
        </div>
      {:else}
        <button class="pin-btn" onclick={() => {
          escalating = true;
          escalateText = chatMessages.find((m) => m.role === 'user')?.content.slice(0, 200) ?? '';
        }}>Escalate to a session</button>
      {/if}
    </div>
  {/if}

  <div class="chat-input-row">
    <textarea
      class="chat-input"
      rows={2}
      bind:value={chatInput}
      placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
      disabled={chatLoading}
      onkeydown={handleChatKeydown}
    ></textarea>
    <button class="btn-chat-send" onclick={handleChat} disabled={chatLoading || !chatInput.trim()}>
      {#if chatLoading}
        <span class="spinner"></span>
      {:else}
        ↑
      {/if}
    </button>
  </div>

  <div class="chat-footer">
    <label class="deep-toggle" title="Route this question to the thinking-tier model (if configured)">
      <input type="checkbox" bind:checked={deepThinking} disabled={chatLoading} />
      Deep thinking
    </label>
    {#if chatUsage}
      <span class="usage-badge">
        ↑ {chatUsage.input_tokens.toLocaleString()} / ↓ {chatUsage.output_tokens.toLocaleString()} tokens
        {#if chatUsage.cost_usd > 0}· ${chatUsage.cost_usd.toFixed(4)}{/if}
      </span>
    {/if}
    {#if chatMessages.length > 0}
      <button class="btn-sm" onclick={() => { chatMessages = []; chatUsage = null; chatError = null; }}>
        Clear chat
      </button>
    {/if}
  </div>
</section>

<style>
  /* Stack the answer + its sources vertically; the bubble itself is a flex row. */
  .bubble-col { display: flex; flex-direction: column; min-width: 0; }
  .ws-bar {
    display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
    padding: 0.45rem 0.7rem; margin-bottom: 0.6rem;
    border: 1px solid var(--border); border-radius: 8px; font-size: 0.85rem;
  }
  .ws-label { color: var(--text-muted); }
  .ws-idle { color: var(--text-muted); }
  .ws-anchor {
    font-family: var(--font-mono); font-size: 0.72rem; padding: 0.1rem 0.4rem;
    border-radius: 4px; background: var(--bg-muted); border: 1px solid var(--border);
  }
  .ws-end { margin-left: auto; }
  .ws-input {
    padding: 0.35rem 0.55rem; border: 1px solid var(--border); border-radius: 6px;
    background: var(--bg-input, var(--bg-muted)); color: var(--text);
    font-size: 0.85rem; width: 100%; margin-bottom: 0.35rem;
  }
  .ws-scope { width: auto; min-width: 11rem; }
  .ws-notice {
    display: flex; align-items: flex-start; gap: 0.5rem;
    border: 1px solid #d97706; color: #d97706; background: rgba(217, 119, 6, 0.08);
    padding: 0.5rem 0.7rem; border-radius: 6px; margin-bottom: 0.6rem; font-size: 0.85rem;
  }
  .ws-dismiss { margin-left: auto; background: none; border: 0; color: inherit; cursor: pointer; font-size: 1rem; }
  .pin-btn {
    margin-top: 0.5rem; background: none; border: 1px dashed var(--border);
    color: var(--text-muted); border-radius: 6px; padding: 0.2rem 0.5rem;
    font-size: 0.75rem; cursor: pointer;
  }
  .pin-btn:hover { color: var(--text); border-style: solid; }
  .pin-form { margin-top: 0.6rem; }
  .pin-actions { display: flex; gap: 0.5rem; }
  .pin-hint { color: var(--text-muted); font-size: 0.78rem; margin: 0.35rem 0 0; max-width: 56ch; }
  .pin-error { color: var(--danger, #dc2626); font-size: 0.8rem; margin-bottom: 0.35rem; }
  .esc-bar { margin: 0.4rem 0; }
  .esc-form { max-width: 46rem; }
  .esc-done { font-size: 0.8rem; color: var(--text-muted); font-family: var(--font-mono); }
  .pin-done { margin-top: 0.5rem; font-size: 0.78rem; color: var(--text-muted); font-family: var(--font-mono); }
  .cite-authority {
    font-family: var(--font-mono);
    font-size: 0.62rem;
    opacity: 0.7;
    margin-left: 0.25rem;
    cursor: help;
  }
  .chat-citations { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; align-items: center; }
  .cite-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.6; }
  .cite-chip {
    font-size: 0.72rem; padding: 0.1rem 0.45rem; border-radius: 10px;
    background: var(--bg-subtle, rgba(127, 127, 127, 0.15));
    border: 1px solid var(--border-strong, rgba(127, 127, 127, 0.3));
    max-width: 22rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .chat-step { font-size: 0.8rem; opacity: 0.75; }
  .deep-toggle { display: flex; align-items: center; gap: 0.3rem; font-size: 0.8rem; opacity: 0.85; cursor: pointer; }
</style>
