<script lang="ts">
  // One form for both levels of AI settings: a person's own ("personal") and
  // the household default that an admin sets ("instance").
  import { api, errorMessage } from '../lib/api';
  import { toasts } from '../lib/ui.svelte';
  import type { AIMode, AIProviderName, AIScope, AISettingsIn, AISettingsOut, SettingsOut, TestResult } from '../lib/types';
  import Icon from '../components/Icon.svelte';

  let { scope, ai, onsaved }: { scope: AIScope; ai: AISettingsOut; onsaved: (s: SettingsOut) => void } = $props();

  const uid = $props.id();
  // svelte-ignore state_referenced_locally -- form starts from the saved values
  let provider = $state<AIProviderName>(ai.provider);
  // svelte-ignore state_referenced_locally
  let model = $state(ai.model ?? '');
  // svelte-ignore state_referenced_locally
  let baseUrl = $state(ai.base_url ?? '');
  // svelte-ignore state_referenced_locally
  let mode = $state<AIMode>(ai.mode);
  let apiKey = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let testing = $state(false);
  let result = $state<TestResult | null>(null);

  const personal = $derived(scope === 'personal');
  // "none" means something different at each level: a person falls back to the
  // household default, the household falls back to no AI at all.
  const providers = $derived<{ value: AIProviderName; label: string; hint: string }[]>([
    personal
      ? { value: 'none', label: 'Use the household default', hint: "Whatever an admin has set up for everyone. If that's nothing, receipts are read by the built-in text recognition only." }
      : { value: 'none', label: 'Off', hint: "Receipts are read by the built-in text recognition only, unless someone has set up their own." },
    { value: 'anthropic', label: 'Anthropic (Claude)', hint: 'Needs an API key from console.anthropic.com.' },
    { value: 'openai', label: 'OpenAI-compatible', hint: 'OpenAI, or a local server such as Ollama or LM Studio.' },
  ]);

  async function save(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    result = null;
    const body: AISettingsIn = { provider, mode, model: model.trim() || null };
    if (provider === 'openai') body.base_url = baseUrl.trim() || null;
    if (apiKey.trim()) body.api_key = apiKey.trim();
    try {
      const s = await api.saveAI(scope, body);
      apiKey = '';
      onsaved(s);
      toasts.success(personal ? 'Your AI settings saved' : 'Household AI settings saved');
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function clearKey() {
    try {
      onsaved(await api.saveAI(scope, { api_key: '' }));
      toasts.success('Saved API key removed');
    } catch (err) {
      toasts.error(errorMessage(err));
    }
  }

  async function test() {
    testing = true;
    result = null;
    try {
      result = await api.testAI(scope);
    } catch (err) {
      result = { ok: false, message: errorMessage(err) };
    } finally {
      testing = false;
    }
  }
</script>

<form class="form" onsubmit={save}>
  <fieldset>
    <legend>Provider</legend>
    {#each providers as p (p.value)}
      <label class="radio">
        <input type="radio" name="{uid}-provider" value={p.value} bind:group={provider} />
        <span><strong>{p.label}</strong><span class="small muted">{p.hint}</span></span>
      </label>
    {/each}
  </fieldset>

  {#if provider !== 'none'}
    <label class="field">
      <span>API key</span>
      <input
        bind:value={apiKey}
        type="password"
        autocomplete="off"
        placeholder={ai.api_key_set ? 'Saved. Type a new one to replace it' : provider === 'openai' ? 'Not needed for most local servers' : 'Paste the key'}
      />
      <small class="hint">
        {ai.api_key_set ? 'A key is saved. It is never shown again.' : 'No key saved.'}
        {#if ai.api_key_set}<button type="button" class="linklike" onclick={clearKey}>Remove saved key</button>{/if}
      </small>
    </label>
    <label class="field">
      <span>Model <span class="opt">(optional)</span></span>
      <input bind:value={model} autocapitalize="none" spellcheck="false" placeholder="Leave blank for the default" />
    </label>
    {#if provider === 'openai'}
      <label class="field">
        <span>Server address</span>
        <input bind:value={baseUrl} type="url" inputmode="url" autocapitalize="none" spellcheck="false" placeholder="https://api.openai.com/v1" />
        <small class="hint">For a local model, e.g. http://localhost:11434/v1</small>
      </label>
    {/if}

    <fieldset>
      <legend>When to use it</legend>
      <label class="radio">
        <input type="radio" name="{uid}-mode" value="fallback" bind:group={mode} />
        <span><strong>Only when unsure</strong><span class="small muted">Built-in recognition first; AI steps in when the result looks doubtful.</span></span>
      </label>
      <label class="radio">
        <input type="radio" name="{uid}-mode" value="always" bind:group={mode} />
        <span><strong>Every receipt</strong><span class="small muted">Most accurate, slower, and costs more if the provider charges.</span></span>
      </label>
    </fieldset>
  {/if}

  {#if error}<p class="form-error" role="alert">{error}</p>{/if}
  <div class="row">
    <button class="btn primary" disabled={busy}>
      {#if busy}<span class="spinner"></span>{/if} Save
    </button>
    {#if ai.provider !== 'none'}
      <button type="button" class="btn" onclick={test} disabled={testing}>
        {#if testing}<span class="spinner"></span>{:else}<Icon name="refresh" size={20} />{/if} Test saved settings
      </button>
    {/if}
  </div>
  {#if result}
    <p class="note {result.ok ? 'good' : 'bad'}" role="status">
      <Icon name={result.ok ? 'check' : 'alert'} size={18} /><span>{result.message}</span>
    </p>
  {/if}
</form>

<style>
  .form {
    display: grid;
    gap: 16px;
  }
  fieldset {
    border: 0;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 4px;
  }
  legend {
    padding: 0;
    margin-bottom: 6px;
    font-weight: 650;
    font-size: var(--fs-sm);
    color: var(--ink-2);
  }
  .radio {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    padding: 10px 12px;
    border-radius: var(--r-md);
    border: 2px solid var(--line);
    cursor: pointer;
  }
  .radio:has(input:checked) {
    border-color: var(--cobalt);
    background: var(--cobalt-soft);
  }
  .radio input {
    width: 20px;
    height: 20px;
    margin-top: 2px;
    accent-color: var(--cobalt);
    flex: none;
  }
  .radio > span {
    display: grid;
    gap: 2px;
  }
  .opt {
    font-weight: 400;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
</style>
