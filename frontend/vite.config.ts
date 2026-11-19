import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { VitePWA } from 'vite-plugin-pwa';

const backend = process.env.GA_BACKEND ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [
    svelte(),
    VitePWA({
      registerType: 'prompt',
      injectRegister: false,
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'Grocy Assistant',
        short_name: 'Groceries',
        description: 'Scan your shopping, snap the receipt, add it all to Grocy in one go.',
        lang: 'en',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        theme_color: '#2445C7',
        background_color: '#F4F6FA',
        // Long-press the home-screen icon to go straight to these.
        shortcuts: [{ name: 'Consume or open', short_name: 'Consume', url: '/consume' }],
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          { src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
        ],
      },
      workbox: {
        // The barcode reader's wasm is ~1 MB; precache it so the scanner starts fast.
        globPatterns: ['**/*.{js,css,html,svg,png,woff2,wasm}'],
        maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
        navigateFallback: '/index.html',
        // Only the app's own pages (see match() in src/lib/router.svelte.ts) are
        // answered from the cache. Anything else is left to the network: /api, and
        // the addresses a single-sign-on proxy uses on this same site for its
        // sign-in round trip (/outpost.goauthentik.io/..., /oauth2/...), which
        // would otherwise get the app instead of the proxy and never complete.
        navigateFallbackAllowlist: [/^\/(\?|$)/, /^\/(login|settings|consume)(\/|\?|$)/, /^\/trips\//],
        // No runtime caching at all: /api/* always goes straight to the network.
        runtimeCaching: [],
        cleanupOutdatedCaches: true,
      },
      devOptions: { enabled: false },
    }),
  ],
  build: {
    outDir: 'dist',
    target: 'es2022',
    sourcemap: false,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: false },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy: {
      '/api': { target: backend, changeOrigin: false },
    },
  },
});
