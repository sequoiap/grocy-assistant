<script lang="ts">
  // Collects one receipt's photo(s), shrinks them, and uploads them together.
  import { onDestroy } from 'svelte';
  import { api, errorMessage } from '../../lib/api';
  import { downscale } from '../../lib/image';
  import Icon from '../../components/Icon.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store, hasReceipts }: { store: TripStore; hasReceipts: boolean } = $props();

  interface Section {
    key: number;
    file: File;
    url: string;
  }

  let sections = $state<Section[]>([]);
  let phase = $state<'idle' | 'preparing' | 'uploading'>('idle');
  let progress = $state(0);
  let error = $state<string | null>(null);
  let cameraInput: HTMLInputElement | undefined = $state();
  let libraryInput: HTMLInputElement | undefined = $state();
  let nextKey = 1;

  function addFiles(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const files = Array.from(input.files ?? []).filter((f) => f.type.startsWith('image/') || f.type === '');
    sections = [...sections, ...files.map((file) => ({ key: nextKey++, file, url: URL.createObjectURL(file) }))];
    input.value = '';
    error = null;
  }

  function removeSection(key: number) {
    const s = sections.find((x) => x.key === key);
    if (s) URL.revokeObjectURL(s.url);
    sections = sections.filter((x) => x.key !== key);
  }

  function move(key: number, dir: -1 | 1) {
    const i = sections.findIndex((x) => x.key === key);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= sections.length) return;
    const next = [...sections];
    [next[i], next[j]] = [next[j], next[i]];
    sections = next;
  }

  function clear() {
    sections.forEach((s) => URL.revokeObjectURL(s.url));
    sections = [];
  }

  async function upload() {
    if (!sections.length) return;
    error = null;
    phase = 'preparing';
    try {
      const blobs = await Promise.all(sections.map((s) => downscale(s.file)));
      phase = 'uploading';
      progress = 0;
      const ok = await store.run(
        () => api.uploadReceipt(store.id, blobs, (f) => (progress = f)),
        { rethrow: true },
      );
      if (ok) clear();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      phase = 'idle';
    }
  }

  onDestroy(clear);
</script>

<section class="composer" aria-labelledby="composer-h">
  <input bind:this={cameraInput} type="file" accept="image/*" capture="environment" onchange={addFiles} hidden />
  <input bind:this={libraryInput} type="file" accept="image/*" multiple onchange={addFiles} hidden />

  {#if sections.length === 0}
    <h2 id="composer-h">{hasReceipts ? 'Add another receipt' : 'Add the receipt'}</h2>
    <p class="muted">Lay it flat in good light. A long receipt can go in as several photos, top to bottom.</p>
    <div class="pick">
      <button type="button" class="btn primary big" onclick={() => cameraInput?.click()}>
        <Icon name="camera" size={26} /> Take a photo
      </button>
      <button type="button" class="btn big" onclick={() => libraryInput?.click()}>
        <Icon name="image" size={24} /> Choose from photos
      </button>
    </div>
  {:else}
    <h2 id="composer-h">New receipt</h2>
    <p class="muted small">
      {sections.length === 1
        ? 'If the receipt is longer than this photo, add the next section.'
        : `${sections.length} photos, read top to bottom as one receipt.`}
    </p>
    <ol class="sections">
      {#each sections as s, i (s.key)}
        <li>
          <img src={s.url} alt="Section {i + 1}" />
          <span class="sn">{i + 1}</span>
          <div class="s-actions">
            {#if sections.length > 1}
              <button type="button" aria-label="Move section {i + 1} up" disabled={i === 0} onclick={() => move(s.key, -1)}><Icon name="back" size={18} /></button>
              <button type="button" aria-label="Move section {i + 1} down" disabled={i === sections.length - 1} onclick={() => move(s.key, 1)}><Icon name="forward" size={18} /></button>
            {/if}
            <button type="button" aria-label="Remove section {i + 1}" onclick={() => removeSection(s.key)}><Icon name="x" size={18} /></button>
          </div>
        </li>
      {/each}
      <li class="more">
        <button type="button" onclick={() => cameraInput?.click()} disabled={phase !== 'idle'}>
          <Icon name="plus" size={26} />
          <span>Next section</span>
        </button>
      </li>
    </ol>
    {#if error}<p class="form-error" role="alert">{error}</p>{/if}
    <div class="go">
      <button type="button" class="btn" onclick={clear} disabled={phase !== 'idle'}>Cancel</button>
      <button type="button" class="btn primary big grow" onclick={upload} disabled={phase !== 'idle'}>
        {#if phase === 'preparing'}
          <span class="spinner"></span> Preparing photos…
        {:else if phase === 'uploading'}
          <span class="spinner"></span> Uploading {Math.round(progress * 100)}%
        {:else}
          Read this receipt
        {/if}
      </button>
    </div>
    {#if phase === 'uploading'}
      <progress max="1" value={progress} aria-label="Upload progress"></progress>
    {/if}
    <button type="button" class="linklike small lib" onclick={() => libraryInput?.click()} disabled={phase !== 'idle'}>
      Add a section from your photos instead
    </button>
  {/if}
</section>

<style>
  .composer {
    display: grid;
    gap: 12px;
    padding: 20px var(--gutter);
    background: var(--surface);
    border-bottom: 1px solid var(--line);
  }
  @media (min-width: 960px) {
    .composer {
      border: 2px solid var(--line);
      border-radius: var(--r-lg);
    }
  }
  .pick {
    display: grid;
    gap: 10px;
  }
  @media (min-width: 560px) {
    .pick {
      grid-template-columns: 1fr 1fr;
    }
  }
  .sections {
    display: flex;
    gap: 10px;
    margin: 0;
    padding: 4px 0 8px;
    list-style: none;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
  }
  .sections li {
    position: relative;
    flex: none;
    width: 112px;
    height: 150px;
    border-radius: 12px;
    overflow: hidden;
    background: var(--surface-2);
    scroll-snap-align: start;
  }
  .sections img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .sn {
    position: absolute;
    top: 6px;
    left: 6px;
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: var(--cobalt);
    color: var(--on-cobalt);
    font-weight: 750;
    font-size: var(--fs-sm);
  }
  .s-actions {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    justify-content: flex-end;
    gap: 2px;
    padding: 4px;
    background: linear-gradient(transparent, rgba(7, 12, 29, 0.7));
  }
  .s-actions button {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border: 0;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.92);
    color: #121c3a;
    cursor: pointer;
  }
  .s-actions button:disabled {
    opacity: 0.4;
  }
  .more button {
    width: 100%;
    height: 100%;
    display: grid;
    place-content: center;
    justify-items: center;
    gap: 6px;
    border: 2px dashed var(--line-strong);
    border-radius: 12px;
    background: transparent;
    color: var(--cobalt);
    font: inherit;
    font-weight: 700;
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .go {
    display: flex;
    gap: 10px;
  }
  .grow {
    flex: 1;
  }
  progress {
    width: 100%;
    height: 8px;
    accent-color: var(--cobalt);
  }
  .lib {
    justify-self: start;
  }
</style>
