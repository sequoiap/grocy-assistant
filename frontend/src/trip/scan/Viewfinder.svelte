<script lang="ts">
  // Live camera with continuous barcode detection. Pauses when the tab is hidden
  // and stops entirely when unmounted (leaving the Scan step).
  import { onDestroy, onMount } from 'svelte';
  import Icon from '../../components/Icon.svelte';
  import { unlockAudio } from '../../lib/feedback';
  import {
    CameraError,
    getDetector,
    listCameras,
    openCamera,
    setTorch,
    stopStream,
    torchSupported,
    type CameraProblem,
    type Detector,
  } from '../../lib/scanner';
  import type { Snippet } from 'svelte';

  let {
    ondetect,
    flashKey = 0,
    overlay,
    hint = 'Point the camera at a barcode. It scans continuously, so just move from item to item.',
    target = 'barcode',
  }: {
    /** What the person is aiming at; sets the shape of the aiming frame. */
    target?: 'barcode' | 'qr';
    ondetect: (code: string) => void;
    /** Shown under the start button, before the camera is on. */
    hint?: string;
    /** Bump to flash the frame (a code was accepted). */
    flashKey?: number;
    overlay?: Snippet;
  } = $props();

  const DEVICE_KEY = 'ga.cameraId';

  type Phase = 'idle' | 'starting' | 'live' | 'paused' | 'problem';
  let phase = $state<Phase>('idle');
  let problem = $state<CameraProblem | null>(null);
  let problemDetail = $state('');
  let video: HTMLVideoElement | undefined = $state();
  let stream: MediaStream | null = null;
  let detector: Detector | null = null;
  let cameras = $state<MediaDeviceInfo[]>([]);
  let deviceId = $state<string | undefined>(readDevice());
  let torch = $state(false);
  let canTorch = $state(false);
  let flashing = $state(false);
  let loopTimer: ReturnType<typeof setTimeout> | undefined;
  let running = false;
  let destroyed = false;

  function readDevice(): string | undefined {
    try {
      return localStorage.getItem(DEVICE_KEY) ?? undefined;
    } catch {
      return undefined;
    }
  }

  async function start() {
    if (destroyed || phase === 'starting') return;
    unlockAudio();
    phase = 'starting';
    problem = null;
    try {
      const detectorReady = getDetector();
      try {
        stream = await openCamera(deviceId);
      } catch (err) {
        // A remembered camera may be gone; fall back to the default one.
        if (deviceId && err instanceof CameraError && err.kind === 'notfound') {
          deviceId = undefined;
          stream = await openCamera();
        } else throw err;
      }
      if (destroyed) return stopStream(stream);
      if (!video) return;
      video.srcObject = stream;
      await video.play().catch(() => undefined);
      detector = await detectorReady;
      canTorch = torchSupported(stream);
      torch = false;
      cameras = await listCameras();
      phase = 'live';
      running = true;
      loop();
    } catch (err) {
      stop();
      phase = 'problem';
      problem = err instanceof CameraError ? err.kind : 'other';
      problemDetail = err instanceof Error ? err.message : '';
    }
  }

  function stop() {
    running = false;
    clearTimeout(loopTimer);
    stopStream(stream);
    stream = null;
    if (video) video.srcObject = null;
  }

  async function loop() {
    if (!running || !video || !detector) return;
    if (video.readyState >= 2 && video.videoWidth > 0) {
      try {
        const found = await detector.detect(video);
        for (const code of found) if (code.rawValue) ondetect(code.rawValue);
      } catch {
        /* a dropped frame; keep going */
      }
    }
    if (running) loopTimer = setTimeout(loop, detector.native ? 100 : 150);
  }

  async function toggleTorch() {
    if (!stream) return;
    try {
      await setTorch(stream, !torch);
      torch = !torch;
    } catch {
      canTorch = false;
    }
  }

  async function switchCamera() {
    if (cameras.length < 2) return;
    const current = stream?.getVideoTracks()[0]?.getSettings().deviceId ?? deviceId;
    const idx = cameras.findIndex((c) => c.deviceId === current);
    deviceId = cameras[(idx + 1) % cameras.length].deviceId;
    try {
      localStorage.setItem(DEVICE_KEY, deviceId);
    } catch {
      /* not remembered */
    }
    stop();
    phase = 'idle';
    await start();
  }

  function onVisibility() {
    if (document.hidden) {
      if (phase === 'live') {
        stop();
        phase = 'paused';
      }
    } else if (phase === 'paused') {
      void start();
    }
  }

  // Flash when the parent accepts a code.
  let lastFlash = 0;
  $effect(() => {
    if (flashKey && flashKey !== lastFlash) {
      lastFlash = flashKey;
      flashing = false;
      requestAnimationFrame(() => (flashing = true));
      setTimeout(() => (flashing = false), 450);
    }
  });

  onMount(() => {
    document.addEventListener('visibilitychange', onVisibility);
    if (!window.isSecureContext) {
      phase = 'problem';
      problem = 'insecure';
      return;
    }
    // Start straight away when the camera was allowed before; otherwise wait for a tap,
    // so the permission prompt never comes out of nowhere.
    const perms = navigator.permissions;
    if (perms?.query) {
      perms
        .query({ name: 'camera' as PermissionName })
        .then((s) => {
          if (s.state === 'granted') void start();
          else if (s.state === 'denied') {
            phase = 'problem';
            problem = 'denied';
          }
        })
        .catch(() => undefined);
    }
  });

  onDestroy(() => {
    destroyed = true;
    document.removeEventListener('visibilitychange', onVisibility);
    stop();
  });

  const messages: Record<CameraProblem, { title: string; body: string }> = {
    insecure: {
      title: 'The camera needs a secure connection',
      body: 'Browsers only allow the camera on HTTPS addresses (or on this computer itself). This page was opened over plain HTTP. Type barcodes below, or ask whoever runs the server to set up HTTPS.',
    },
    unsupported: {
      title: "This browser can't use the camera",
      body: 'Type barcodes below instead, or open this page in a current version of Chrome, Safari or Firefox.',
    },
    denied: {
      title: 'Camera access is blocked',
      body: "Allow the camera for this site in your browser's settings (usually the icon next to the address), then try again. You can type barcodes below meanwhile.",
    },
    notfound: {
      title: 'No camera found',
      body: 'Type barcodes below, or plug in a USB barcode scanner: it types into the box for you.',
    },
    busy: {
      title: 'The camera is busy',
      body: 'Another app or tab is using it. Close that, then try again.',
    },
    other: {
      title: "The camera didn't start",
      body: 'Try again, or type barcodes below.',
    },
  };
</script>

<div class="stage" class:live={phase === 'live'} class:flashing>
  <!-- svelte-ignore a11y_media_has_caption -->
  <video bind:this={video} playsinline muted autoplay aria-label="Camera preview"></video>

  {#if phase === 'live'}
    <div class="frame" class:qr={target === 'qr'} aria-hidden="true">
      {#if target === 'barcode'}<span></span>{/if}
    </div>
    <div class="controls">
      {#if canTorch}
        <button type="button" class="ctl" class:on={torch} aria-pressed={torch} onclick={toggleTorch} aria-label="Torch">
          <Icon name="torch" />
        </button>
      {/if}
      {#if cameras.length > 1}
        <button type="button" class="ctl" onclick={switchCamera} aria-label="Switch camera">
          <Icon name="flip" />
        </button>
      {/if}
    </div>
    {#if overlay}<div class="overlay">{@render overlay()}</div>{/if}
  {:else}
    <div class="cover">
      {#if phase === 'problem' && problem}
        <Icon name={problem === 'insecure' ? 'shield' : 'camera'} size={30} />
        <p class="c-title">{messages[problem].title}</p>
        <p class="c-body">{messages[problem].body}</p>
        {#if problem === 'other' && problemDetail}<p class="c-body small">({problemDetail})</p>{/if}
        {#if problem !== 'insecure' && problem !== 'unsupported'}
          <button type="button" class="btn" onclick={start}>Try again</button>
        {/if}
      {:else if phase === 'starting'}
        <span class="spinner big"></span>
        <p class="c-title">Starting the camera…</p>
      {:else}
        <button type="button" class="btn primary big start" onclick={start}>
          <Icon name="camera" size={26} /> Start scanning
        </button>
        <p class="c-body">{hint}</p>
      {/if}
    </div>
  {/if}
</div>

<style>
  .stage {
    position: relative;
    overflow: hidden;
    aspect-ratio: 4 / 3;
    max-height: 46dvh;
    width: 100%;
    background: var(--scan-stage);
    color: #eaf0fb;
    isolation: isolate;
  }
  @media (min-width: 960px) {
    .stage {
      border-radius: var(--r-lg);
      max-height: none;
    }
  }
  video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0;
  }
  .live video {
    opacity: 1;
  }
  .frame {
    position: absolute;
    inset: 22% 10%;
    border-radius: 18px;
    box-shadow: 0 0 0 100vmax rgba(7, 12, 29, 0.38);
    border: 4px solid rgba(255, 255, 255, 0.92);
    transition: border-color 120ms ease;
  }
  /* A QR code is square and has no "line" to lay across it. */
  .frame.qr {
    inset: 12% auto 12% 50%;
    aspect-ratio: 1;
    translate: -50% 0;
  }
  .frame span {
    position: absolute;
    left: 8%;
    right: 8%;
    top: 50%;
    height: 2px;
    background: rgba(240, 180, 41, 0.85);
    box-shadow: 0 0 12px rgba(240, 180, 41, 0.9);
  }
  .flashing .frame {
    border-color: var(--saffron);
    animation: thump 420ms ease-out;
  }
  .flashing::after {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(240, 180, 41, 0.35);
    animation: fade 420ms ease-out forwards;
    pointer-events: none;
  }
  @keyframes thump {
    30% {
      transform: scale(1.04);
    }
  }
  @keyframes fade {
    to {
      opacity: 0;
    }
  }
  .controls {
    position: absolute;
    top: 12px;
    right: 12px;
    display: flex;
    gap: 8px;
  }
  .ctl {
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    border: 0;
    background: rgba(7, 12, 29, 0.6);
    color: #fff;
    cursor: pointer;
  }
  .ctl.on {
    background: var(--saffron);
    color: var(--on-saffron);
  }
  .overlay {
    position: absolute;
    left: 12px;
    right: 12px;
    bottom: 12px;
  }
  .cover {
    position: absolute;
    inset: 0;
    display: grid;
    place-content: center;
    justify-items: center;
    gap: 10px;
    padding: 20px;
    text-align: center;
  }
  .c-title {
    font-weight: 750;
    font-size: var(--fs-lg);
  }
  .c-body {
    max-width: 44ch;
    color: #b8c3e0;
    font-size: var(--fs-sm);
  }
  .start {
    margin-bottom: 4px;
  }
  .spinner.big {
    width: 32px;
    height: 32px;
  }
</style>
