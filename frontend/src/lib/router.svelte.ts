// Minimal history-API router. The backend serves index.html for every non-API
// path, so deep links and refreshes work.

class Router {
  path = $state(location.pathname);
  search = $state(location.search);
}

export const router = new Router();

function sync(): void {
  router.path = location.pathname;
  router.search = location.search;
}

// How deep we are in in-app history, so "back" never leaves the app.
let depth = 0;

export function navigate(to: string, opts: { replace?: boolean } = {}): void {
  const url = new URL(to, location.origin);
  const next = url.pathname + url.search + url.hash;
  if (next === location.pathname + location.search + location.hash) return;
  if (opts.replace) history.replaceState({ depth }, '', next);
  else history.pushState({ depth: ++depth }, '', next);
  sync();
  if (!url.hash) window.scrollTo({ top: 0 });
}

/** Go back within the app, or to `fallback` when this page was opened directly. */
export function back(fallback: string): void {
  if (depth > 0) history.back();
  else navigate(fallback, { replace: true });
}

export function installRouter(): () => void {
  const onPop = (e: PopStateEvent) => {
    depth = (e.state as { depth?: number } | null)?.depth ?? 0;
    sync();
  };
  const onClick = (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = (e.target as Element | null)?.closest('a');
    if (!a || a.target || a.hasAttribute('download') || a.getAttribute('rel') === 'external') return;
    const href = a.getAttribute('href');
    if (!href || href.startsWith('#')) return;
    const url = new URL(href, location.href);
    if (url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
    e.preventDefault();
    navigate(url.pathname + url.search + url.hash);
  };
  window.addEventListener('popstate', onPop);
  document.addEventListener('click', onClick);
  return () => {
    window.removeEventListener('popstate', onPop);
    document.removeEventListener('click', onClick);
  };
}

export type Route =
  | { name: 'home' }
  | { name: 'login' }
  | { name: 'settings' }
  | { name: 'consume' }
  | { name: 'trip'; id: number; step: TripStep }
  | { name: 'notfound' };

export type TripStep = 'scan' | 'receipts' | 'review' | null;

export function match(path: string): Route {
  const p = path.replace(/\/+$/, '') || '/';
  if (p === '/') return { name: 'home' };
  if (p === '/login') return { name: 'login' };
  if (p === '/settings') return { name: 'settings' };
  if (p === '/consume') return { name: 'consume' };
  const m = /^\/trips\/(\d+)(?:\/(scan|receipts|review))?$/.exec(p);
  if (m) return { name: 'trip', id: Number(m[1]), step: (m[2] as TripStep) ?? null };
  return { name: 'notfound' };
}
