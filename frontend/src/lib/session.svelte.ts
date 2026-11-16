import { api, ApiError, errorMessage, isProxySignIn } from './api';
import type { GrocyMeta, StatusOut, UserOut } from './types';

// The reason Grocy signed someone out has to outlive the trip page it happened
// on, and a phone reloading the app while they look up their password.
const NOTICE_KEY = 'grocy-assistant.signin-notice';
/** How often an open, visible app asks whether it is still signed in. */
const HEARTBEAT_MS = 20000;

// When this browser was last sent off to the single-sign-on proxy by itself.
const SENT_KEY = 'grocy-assistant.sent-through-proxy';
/** Not twice within this long: if the first trip didn't help, a second won't, and the person should see why. */
const SEND_AGAIN_AFTER_MS = 60000;

function sentRecently(): boolean {
  try {
    return Date.now() - Number(sessionStorage.getItem(SENT_KEY) ?? 0) < SEND_AGAIN_AFTER_MS;
  } catch {
    return true; // can't remember having been: don't risk going round in circles
  }
}

function savedNotice(): string | null {
  try {
    return sessionStorage.getItem(NOTICE_KEY);
  } catch {
    return null;
  }
}

class Session {
  status = $state<StatusOut | null>(null);
  /** Who is signed in, with their Grocy account. Null means the sign-in screen. */
  user = $state<UserOut | null>(null);
  /** Set once the boot probe has finished (successfully or not). */
  ready = $state(false);
  bootError = $state<string | null>(null);
  /** Why the server signed the person out, to show on the sign-in screen. */
  notice = $state<string | null>(savedNotice());
  /**
   * A single-sign-on proxy in front of the app wants the person to sign in there
   * before it lets anything through. Nothing works until they have.
   */
  proxyWantsSignIn = $state(false);
  #goWhenVisible = false;

  async boot(): Promise<void> {
    this.bootError = null;
    try {
      this.status = await api.status();
      try {
        this.signedIn(await api.me());
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 401)) throw err;
        this.user = null;
      }
    } catch (err) {
      // That one has a screen of its own (stoppedByProxy).
      if (!isProxySignIn(err)) this.bootError = errorMessage(err);
    } finally {
      this.ready = true;
    }
  }

  /**
   * A request was answered by the proxy's sign-in page, not by the server. The
   * person has to be taken there, which only a real page load can do.
   */
  stoppedByProxy(): void {
    if (this.proxyWantsSignIn) return;
    this.proxyWantsSignIn = true;
    if (sentRecently()) return; // just been, and it didn't help: leave it to the button
    if (document.visibilityState === 'visible') this.goThroughProxy();
    else this.#goWhenVisible = true;
  }

  /**
   * Load a page the phone doesn't have cached, so the proxy gets to see the
   * browser: it shows its sign-in if it wants one, and the server then sends the
   * browser back to where it was.
   */
  goThroughProxy(): void {
    try {
      sessionStorage.setItem(SENT_KEY, String(Date.now()));
    } catch {
      /* private mode: stoppedByProxy then leaves it to the button */
    }
    const here = location.pathname + location.search;
    location.assign(`/api/auth/through-proxy?next=${encodeURIComponent(here)}`);
  }

  signedIn(user: UserOut): void {
    this.user = user;
    this.setNotice(null);
  }

  /**
   * The server no longer knows this session. `reason` is given when Grocy
   * rejected the account; a session that simply expired ends quietly.
   */
  ended(reason: string | null = null): void {
    if (reason) this.setNotice(reason);
    if (this.user) this.user = null;
    meta.clear();
  }

  /**
   * Grocy rejected the person's key and the server signed them out. Behind a
   * single-sign-on proxy the server signs them straight back in when asked, with
   * a new key, so nobody needs to hear about it. Resolves true if that worked.
   */
  async signInAgain(): Promise<boolean> {
    if (!this.status?.single_sign_on || !this.user) return false;
    try {
      this.user = await api.me();
      return true;
    } catch {
      return false;
    }
  }

  setNotice(message: string | null): void {
    this.notice = message;
    try {
      if (message) sessionStorage.setItem(NOTICE_KEY, message);
      else sessionStorage.removeItem(NOTICE_KEY);
    } catch {
      /* private mode: it just won't survive a reload */
    }
  }

  /**
   * While the app is open, ask the server now and then whether this sign-in still
   * stands. The server re-checks people's Grocy accounts in the background, so this
   * is how a page nobody is touching finds out it has been signed out. (A trip page
   * also learns it from its own, faster polling.) Returns a function that stops it.
   */
  watch(): () => void {
    const check = async () => {
      if (document.visibilityState !== 'visible') return;
      if (this.proxyWantsSignIn) {
        // Found out while the app was in the background; go now that someone is looking.
        if (this.#goWhenVisible) this.goThroughProxy();
        this.#goWhenVisible = false;
        return;
      }
      if (!this.user) return;
      try {
        const me = await api.me();
        const now = this.user;
        const changed =
          now &&
          (me.is_admin !== now.is_admin || me.display_name !== now.display_name || me.via_proxy !== now.via_proxy);
        if (changed) this.user = me;
      } catch (err) {
        // A reason from Grocy has already reached ended() through the app-wide
        // handler; this covers a session that simply expired. Anything else
        // (offline, server restarting) says nothing about the sign-in.
        if (err instanceof ApiError && err.status === 401) this.ended();
      }
    };
    const timer = setInterval(check, HEARTBEAT_MS);
    const onVisible = () => void check();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }

  async signOut(): Promise<void> {
    try {
      await api.logout();
    } finally {
      this.user = null;
      this.setNotice(null);
      meta.clear();
    }
  }
}

export const session = new Session();

/** Grocy locations, stores and units for the pickers; loaded on demand, shared. */
class MetaStore {
  value = $state<GrocyMeta | null>(null);
  error = $state<string | null>(null);
  #pending: Promise<GrocyMeta | null> | null = null;

  load(force = false): Promise<GrocyMeta | null> {
    if (this.value && !force) {
      // A copy served while Grocy was unreachable is good enough to work with;
      // ask again in the background so it heals by itself once Grocy is back.
      if (this.value.grocy_reachable === false) void this.#fetch();
      return Promise.resolve(this.value);
    }
    return this.#fetch(force);
  }

  #fetch(force = false): Promise<GrocyMeta | null> {
    if (this.#pending && !force) return this.#pending;
    this.#pending = api
      .meta()
      .then((m) => {
        this.value = m;
        this.error = null;
        return m;
      })
      .catch((err) => {
        this.error = errorMessage(err);
        return null;
      })
      .finally(() => {
        this.#pending = null;
      });
    return this.#pending;
  }

  clear(): void {
    this.value = null;
    this.error = null;
  }

  locationName(id: number | null | undefined): string | null {
    if (id == null) return null;
    return this.value?.locations.find((l) => l.id === id)?.name ?? null;
  }

  storeName(id: number | null | undefined): string | null {
    if (id == null) return null;
    return this.value?.stores.find((s) => s.id === id)?.name ?? null;
  }
}

export const meta = new MetaStore();
