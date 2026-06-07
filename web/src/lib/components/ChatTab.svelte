<script lang="ts">
  // Chat tab — KB-augmented conversation over SSE. Reads the header-selected model.
  import { chatStream, type ChatMessage } from '$lib/api';

  let { selectedModelId }: { selectedModelId: string } = $props();

  let chatMessages = $state<ChatMessage[]>([]);
  let chatInput = $state<string>('');
  let chatLoading = $state<boolean>(false);
  let chatStatusLines = $state<string[]>([]);
  let chatError = $state<string | null>(null);
  let chatUsage = $state<{ input_tokens: number; output_tokens: number; cost_usd: number } | null>(null);

  async function handleChat() {
    if (!chatInput.trim() || chatLoading) return;
    const userMsg = chatInput.trim();
    chatInput = '';
    chatMessages = [...chatMessages, { role: 'user', content: userMsg }];
    chatLoading = true;
    chatStatusLines = [];
    chatError = null;
    try {
      for await (const event of chatStream([...chatMessages], selectedModelId || undefined)) {
        if (event.type === 'status') {
          chatStatusLines = [...chatStatusLines, event.message];
        } else if (event.type === 'result') {
          chatMessages = [...chatMessages, { role: 'assistant', content: event.data.content }];
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
        </div>
      {/each}
      {#if chatLoading && chatStatusLines.length > 0}
        <div class="chat-bubble assistant">
          <div class="bubble-content chat-thinking">
            {chatStatusLines[chatStatusLines.length - 1]}…
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
