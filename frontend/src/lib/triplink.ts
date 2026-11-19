// The link a second device opens (or scans as a QR code) to work on the same trip.

export function tripLink(id: number): string {
  return `${location.origin}/trips/${id}/scan`;
}

/** The trip id if `text` is a trip link from this app, else null. */
export function tripIdFromLink(text: string): number | null {
  let path: string;
  try {
    // The host is deliberately ignored: the same server is often reached under
    // different names (LAN name on the computer, tailnet name on the phone).
    path = new URL(text.trim()).pathname;
  } catch {
    return null;
  }
  const m = /^\/trips\/(\d+)(?:\/(?:scan|receipts|review))?\/?$/.exec(path);
  return m ? Number(m[1]) : null;
}

/**
 * Why a link to this page, opened on a phone, wouldn't work there: "local" when it
 * was opened as localhost (that means the phone itself), "insecure" on plain http
 * (phones only allow the camera on HTTPS). Null when it's fine.
 */
export function phoneLinkProblem(): 'local' | 'insecure' | null {
  if (['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)) return 'local';
  return location.protocol !== 'https:' ? 'insecure' : null;
}
