<script lang="ts">
  // The app mark (same artwork as icons/icon.svg).
  let { size = 32 }: { size?: number } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true" focusable="false">
  <rect width="512" height="512" rx="112" fill="#2445C7" />
  <path
    d="M148 96h216a20 20 0 0 1 20 20v300l-31-22-31 22-31-22-31 22-31-22-31 22-31-22-31 22V116a20 20 0 0 1 20-20z"
    fill="#fff"
  />
  <g fill="#121C3A">
    <rect x="170" y="140" width="16" height="132" rx="3" />
    <rect x="198" y="140" width="8" height="132" rx="3" />
    <rect x="218" y="140" width="22" height="132" rx="3" />
    <rect x="252" y="140" width="8" height="132" rx="3" />
    <rect x="272" y="140" width="14" height="132" rx="3" />
    <rect x="298" y="140" width="8" height="132" rx="3" />
    <rect x="318" y="140" width="24" height="132" rx="3" />
  </g>
  <circle cx="338" cy="330" r="62" fill="#F0B429" />
  <path d="M308 330l21 21 39-42" fill="none" stroke="#121C3A" stroke-width="18" stroke-linecap="round" stroke-linejoin="round" />
</svg>

<style>
  svg {
    flex: none;
    border-radius: 22%;
    box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.35);
  }
</style>
