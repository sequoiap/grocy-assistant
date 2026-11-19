// Thin typed client for the backend. Same-origin, cookie session.
import type {
  AIScope,
  AISettingsIn,
  BulkItemPatch,
  GrocyMeta,
  IdName,
  ItemCreate,
  ItemPatch,
  LineItemCreate,
  LinePatch,
  LoginIn,
  ProductHit,
  ReceiptPatch,
  ScanOut,
  SettingsOut,
  StatusOut,
  SubmitResult,
  TestResult,
  TripOut,
  TripKind,
  TripSummary,
  UserOut,
} from './types';

/**
 * Machine-readable reasons the server adds to some errors:
 * - `api_key_required`: sign-in details were right, but the server couldn't get an API key by itself.
 * - `grocy_unreachable`: Grocy is down; nothing was changed.
 * - `grocy_account_invalid`: Grocy rejected this person's key, and the server has ended the session.
 *
 * And one this file adds by itself:
 * - `proxy_sign_in`: the answer came from something in front of the server (see answeredByProxy).
 */
export type ApiErrorCode = 'api_key_required' | 'grocy_unreachable' | 'grocy_account_invalid' | 'proxy_sign_in';

export class ApiError extends Error {
  /** HTTP status, or 0 when the server couldn't be reached at all. */
  readonly status: number;
  /** The server's `code` for this error, when it sent one (see ApiErrorCode). */
  readonly code: string | null;
  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.name = 'ApiError';
  }
  get offline(): boolean {
    return this.status === 0 && this.code === null;
  }
}

function hasCode(err: unknown, code: ApiErrorCode): boolean {
  return err instanceof ApiError && err.code === code;
}

/** Grocy is down. Nothing was changed, so this is news to pass on calmly, not a failure. */
export const isGrocyUnreachable = (err: unknown) => hasCode(err, 'grocy_unreachable');
/** Grocy no longer accepts this person's account; the server has already signed them out. */
export const isAccountInvalid = (err: unknown) => hasCode(err, 'grocy_account_invalid');
/** Username and password were right, but the person has to paste an API key to finish signing in. */
export const isApiKeyRequired = (err: unknown) => hasCode(err, 'api_key_required');
/** A single-sign-on proxy in front of the server wants the person to sign in there first. */
export const isProxySignIn = (err: unknown) => hasCode(err, 'proxy_sign_in');

type ValidationDetail = { loc?: (string | number)[]; msg?: string };

function messageFrom(status: number, body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return (detail as ValidationDetail[])
        .map((d) => {
          const field = d.loc?.filter((p) => p !== 'body').join('.') ?? '';
          const msg = d.msg ?? 'is invalid';
          return field ? `${field}: ${msg}` : msg;
        })
        .join('; ');
    }
  }
  if (status === 502 || status === 504) return "Grocy isn't reachable right now. Try again in a moment.";
  if (status >= 500) return 'The server hit a problem. Try again in a moment.';
  return `Request failed (${status})`;
}

function errorFrom(status: number, body: unknown): ApiError {
  const code = body && typeof body === 'object' ? (body as { code?: unknown }).code : null;
  return new ApiError(status, messageFrom(status, body), typeof code === 'string' ? code : null);
}

let unauthorizedHandler: ((err: ApiError) => void) | null = null;

/**
 * Called whenever an API call answers 401: the session expired, or Grocy
 * rejected the account and the server signed the person out (see isAccountInvalid).
 */
export function onUnauthorized(handler: (err: ApiError) => void): void {
  unauthorizedHandler = handler;
}

function handleUnauthorized(err: ApiError, quiet = false): void {
  // Being signed out by Grocy is never quiet: the person has to be told why.
  if (err.status === 401 && (!quiet || isAccountInvalid(err))) unauthorizedHandler?.(err);
}

let signInAgain: (() => Promise<boolean>) | null = null;
let signingInAgain: Promise<boolean> | null = null;

/**
 * Asked when Grocy rejected the person's key and the server signed them out, before
 * anyone is told. If it resolves true they are signed in again (a single-sign-on
 * proxy vouches for them) and the request that found out is simply made again.
 */
export function onAccountInvalid(recover: () => Promise<boolean>): void {
  signInAgain = recover;
}

let proxySignInHandler: (() => void) | null = null;

/** Called when a single-sign-on proxy in front of the server answered in its place. */
export function onProxySignIn(handler: () => void): void {
  proxySignInHandler = handler;
}

/**
 * Whether an answer came from something in front of the server, not the server: a
 * single-sign-on proxy whose own session has run out answers every request with
 * its sign-in page until the person has been there. The server's API never
 * redirects, never answers with a web page, and its 401s always carry a `detail`.
 */
function answeredByProxy(res: Response, data: unknown): boolean {
  if (res.type === 'opaqueredirect') return true;
  if (res.status === 401) return !(data && typeof data === 'object' && 'detail' in data);
  return res.ok && (res.headers.get('content-type') ?? '').includes('text/html');
}

interface RequestOptions {
  body?: unknown;
  /** Don't trigger the global sign-out handler on a plain 401 (login, boot probe). */
  quiet401?: boolean;
  /** Set on the second attempt, after signing in again (see onAccountInvalid). */
  again?: boolean;
  signal?: AbortSignal;
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    // A redirect can only be a proxy's, to its sign-in page on another site, which a
    // fetch isn't allowed to follow anyway. Unfollowed, it can be told from being offline.
    redirect: 'manual',
    signal: opts.signal,
  };
  if (opts.body instanceof FormData) {
    init.body = opts.body;
  } else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
  }

  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }

  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (answeredByProxy(res, data)) {
    proxySignInHandler?.();
    throw new ApiError(0, 'Your sign-in has run out. Sign in again to carry on.', 'proxy_sign_in');
  }
  if (!res.ok) {
    const err = errorFrom(res.status, data);
    // Not for the sign-in calls themselves (quiet401): they are how it is done.
    if (isAccountInvalid(err) && signInAgain && !opts.quiet401 && !opts.again) {
      signingInAgain ??= signInAgain().finally(() => (signingInAgain = null));
      if (await signingInAgain) return request<T>(method, path, { ...opts, again: true });
    }
    handleUnauthorized(err, opts.quiet401);
    throw err;
  }
  return data as T;
}

const get = <T>(path: string, opts?: RequestOptions) => request<T>('GET', path, opts);
const post = <T>(path: string, body?: unknown, opts?: RequestOptions) =>
  request<T>('POST', path, { ...opts, body });
const put = <T>(path: string, body?: unknown) => request<T>('PUT', path, { body });
const patch = <T>(path: string, body?: unknown) => request<T>('PATCH', path, { body });
const del = <T>(path: string) => request<T>('DELETE', path);

/** Upload with progress reporting (fetch can't report upload progress). */
function uploadForm<T>(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api${path}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, "Can't reach the server. Check your connection and try again."));
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        data = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else {
        const err = errorFrom(xhr.status, data);
        handleUnauthorized(err);
        reject(err);
      }
    };
    xhr.send(form);
  });
}

export const api = {
  // auth: people sign in with their Grocy account
  status: () => get<StatusOut>('/status', { quiet401: true }),
  login: (body: LoginIn) => post<UserOut>('/auth/login', body, { quiet401: true }),
  logout: () => post<void>('/auth/logout', undefined, { quiet401: true }),
  me: () => get<UserOut>('/auth/me', { quiet401: true }),

  // settings: the "instance" (household default) AI scope is for admins, the rest is for anyone
  settings: () => get<SettingsOut>('/settings'),
  saveAI: (scope: AIScope, body: AISettingsIn) => put<SettingsOut>(`/settings/ai/${scope}`, body),
  testAI: (scope: AIScope) => post<TestResult>(`/settings/ai/${scope}/test`),
  /** Checks the caller's own connection to Grocy. */
  testGrocy: () => post<TestResult>('/settings/grocy/test'),

  // Grocy master data
  meta: () => get<GrocyMeta>('/grocy/meta'),
  products: (q: string, signal?: AbortSignal) =>
    get<ProductHit[]>(`/grocy/products?q=${encodeURIComponent(q)}&limit=20`, { signal }),
  createStore: (name: string) => post<IdName>('/grocy/stores', { name }),

  // trips
  trips: () => get<TripSummary[]>('/trips'),
  createTrip: (kind: TripKind = 'shopping', name = '') => post<TripOut>('/trips', { name, kind }),
  trip: (id: number) => get<TripOut>(`/trips/${id}`),
  /** Cheap check for changes made on another device; never signs the user out. */
  tripRevision: (id: number) => request<{ revision: number }>('GET', `/trips/${id}/revision`, { quiet401: true }),
  renameTrip: (id: number, name: string) => patch<TripOut>(`/trips/${id}`, { name }),
  deleteTrip: (id: number) => del<void>(`/trips/${id}`),
  scan: (id: number, barcode: string) => post<ScanOut>(`/trips/${id}/scan`, { barcode }),
  addItem: (id: number, body: ItemCreate) => post<TripOut>(`/trips/${id}/items`, body),
  patchItem: (id: number, itemId: number, body: ItemPatch) =>
    patch<TripOut>(`/trips/${id}/items/${itemId}`, body),
  patchItems: (id: number, body: BulkItemPatch) => patch<TripOut>(`/trips/${id}/items`, body),
  deleteItem: (id: number, itemId: number) => del<TripOut>(`/trips/${id}/items/${itemId}`),
  uploadReceipt: (id: number, files: Blob[], onProgress?: (f: number) => void) => {
    const form = new FormData();
    files.forEach((f, i) => form.append('files', f, `receipt-${i + 1}.jpg`));
    return uploadForm<TripOut>(`/trips/${id}/receipts`, form, onProgress);
  },
  patchReceipt: (receiptId: number, body: ReceiptPatch) => patch<TripOut>(`/receipts/${receiptId}`, body),
  deleteReceipt: (receiptId: number) => del<TripOut>(`/receipts/${receiptId}`),
  reprocessReceipt: (receiptId: number, useAI: boolean) =>
    post<TripOut>(`/receipts/${receiptId}/reprocess`, { use_ai: useAI }),
  patchLine: (lineId: number, body: LinePatch) => patch<TripOut>(`/receipt-lines/${lineId}`, body),
  lineToItem: (lineId: number, body: LineItemCreate) => post<TripOut>(`/receipt-lines/${lineId}/item`, body),
  rematch: (id: number, useAI = false) => post<TripOut>(`/trips/${id}/rematch${useAI ? '?use_ai=true' : ''}`),
  submit: (id: number) => post<SubmitResult>(`/trips/${id}/submit`),
  undo: (id: number) => post<TripOut>(`/trips/${id}/undo`),
};

/** Human message for anything thrown by the client. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
}
