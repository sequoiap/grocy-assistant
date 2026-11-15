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
