<script lang="ts">
  // Chat tab — agentic KB troubleshooting over SSE. Reads the header-selected model.
  import { chatStream, type ChatMessage, type ChatCitation } from '$lib/api';

  let { selectedModelId }: { selectedModelId: string } = $props();

  // An assistant turn carries its answer plus the KB citations it grounded on.
  type ChatTurn = ChatMessage & { citations?: ChatCitation[] };

  let chatMessages = $state<ChatTurn[]>([]);
  let chatInput = $state<string>('');
  let deepThinking = $state<boolean>(false);
  let chatLoading = $state<boolean>(false);
  let chatStatusLines = $state<string[]>([]);
  let chatSteps = $state<string[]>([]);
  let chatError = $state<string | null>(null);
  let chatUsage = $state<{ input_tokens: number; output_tokens: number; cost_usd: number } | null>(null);

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
      for await (const event of chatStream([...chatMessages], selectedModelId || undefined, deepThinking)) {
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
      {#each chatMessages as msg}
        <div class="chat-bubble {msg.role}">
          <div class="bubble-content">{msg.content}</div>
          {#if msg.role === 'assistant' && msg.citations && msg.citations.length > 0}
            <div class="chat-citations">
              <span class="cite-label">Sources</span>
              {#each msg.citations as c}
                <span class="cite-chip" title={c.snippet}>
                  {c.source_path ?? c.document_id ?? c.chunk_id}
                </span>
              {/each}
            </div>
          {/if}
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
