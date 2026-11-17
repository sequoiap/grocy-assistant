// App-wide UI state: transient notices and network status.
import { errorMessage, isAccountInvalid, isGrocyUnreachable, isProxySignIn } from './api';

export type ToastKind = 'info' | 'success' | 'error';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  action?: { label: string; run: () => void };
}

class Toasts {
  list = $state<Toast[]>([]);
  #next = 1;

  show(message: string, kind: ToastKind = 'info', action?: Toast['action'], ms?: number): number {
    const id = this.#next++;
    this.list = [...this.list.slice(-2), { id, kind, message, action }];
    const timeout = ms ?? (kind === 'error' ? 7000 : action ? 6000 : 3500);
    setTimeout(() => this.dismiss(id), timeout);
    return id;
  }

  error(message: string): number {
    return this.show(message, 'error');
  }

  success(message: string, action?: Toast['action']): number {
    return this.show(message, 'success', action);
  }

  dismiss(id: number): void {
    this.list = this.list.filter((t) => t.id !== id);
  }
}

export const toasts = new Toasts();

/** Tells the person an action didn't go through, in the tone the reason deserves. */
export function reportError(err: unknown): void {
  // The sign-in screen they are about to land on says why they were signed out.
  if (isAccountInvalid(err)) return;
  // Likewise the screen that sends them to their single sign-on.
  if (isProxySignIn(err)) return;
  // Grocy being down is not their mistake and nothing was lost: say so plainly, without the alarm.
  if (isGrocyUnreachable(err)) toasts.show(errorMessage(err), 'info', undefined, 7000);
  else toasts.error(errorMessage(err));
}

class Network {
  online = $state(typeof navigator === 'undefined' ? true : navigator.onLine);

  install(): () => void {
    const up = () => (this.online = true);
    const down = () => (this.online = false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }
}

export const network = new Network();

/** Wide layout breakpoint, tracked reactively. */
class Viewport {
  wide = $state(false);
  coarse = $state(false);

  install(): () => void {
    const wide = matchMedia('(min-width: 960px)');
    const coarse = matchMedia('(pointer: coarse)');
    const update = () => {
      this.wide = wide.matches;
      this.coarse = coarse.matches;
    };
    update();
    wide.addEventListener('change', update);
    coarse.addEventListener('change', update);
    return () => {
      wide.removeEventListener('change', update);
      coarse.removeEventListener('change', update);
    };
  }
}

export const viewport = new Viewport();
