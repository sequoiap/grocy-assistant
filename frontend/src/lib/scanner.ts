// Camera access and barcode detection, independent of any UI.

export const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'qr_code', 'data_matrix'] as const;

export interface Detected {
  rawValue: string;
  format: string;
}

export interface Detector {
  readonly native: boolean;
  detect(source: HTMLVideoElement): Promise<Detected[]>;
}

interface NativeDetectorCtor {
  new (opts?: { formats?: string[] }): { detect(source: CanvasImageSource): Promise<Detected[]> };
  getSupportedFormats(): Promise<string[]>;
}

let detectorPromise: Promise<Detector> | null = null;

export function getDetector(): Promise<Detector> {
  detectorPromise ??= createDetector().catch((err) => {
    detectorPromise = null;
    throw err;
  });
  return detectorPromise;
}

async function createDetector(): Promise<Detector> {
  const Native = (globalThis as { BarcodeDetector?: NativeDetectorCtor }).BarcodeDetector;
  if (Native) {
    try {
      const supported = await Native.getSupportedFormats();
      const formats = FORMATS.filter((f) => supported.includes(f));
      if (formats.includes('ean_13')) {
        const d = new Native({ formats: [...formats] });
        return { native: true, detect: (src) => d.detect(src) };
      }
    } catch {
      /* fall through to the bundled reader */
    }
  }
  const { BarcodeDetector } = await import('./zxing');
  const d = new BarcodeDetector({ formats: [...FORMATS] });
  return {
    native: false,
    detect: async (src) => (await d.detect(src)).map((b) => ({ rawValue: b.rawValue, format: b.format })),
  };
}

export type CameraProblem = 'insecure' | 'unsupported' | 'denied' | 'notfound' | 'busy' | 'other';

export class CameraError extends Error {
  readonly kind: CameraProblem;
  constructor(kind: CameraProblem, message: string = kind) {
    super(message);
    this.kind = kind;
  }
}

export async function openCamera(deviceId?: string): Promise<MediaStream> {
  if (!window.isSecureContext) throw new CameraError('insecure');
  if (!navigator.mediaDevices?.getUserMedia) throw new CameraError('unsupported');
  const video: MediaTrackConstraints = deviceId
    ? { deviceId: { exact: deviceId } }
    : { facingMode: { ideal: 'environment' } };
  video.width = { ideal: 1280 };
  video.height = { ideal: 720 };
  try {
    return await navigator.mediaDevices.getUserMedia({ video, audio: false });
  } catch (err) {
    const name = err instanceof DOMException ? err.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError') throw new CameraError('denied');
    if (name === 'NotFoundError' || name === 'OverconstrainedError') throw new CameraError('notfound');
    if (name === 'NotReadableError' || name === 'AbortError') throw new CameraError('busy');
    throw new CameraError('other', err instanceof Error ? err.message : String(err));
  }
}

export async function listCameras(): Promise<MediaDeviceInfo[]> {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === 'videoinput');
  } catch {
    return [];
  }
}

type TorchCapabilities = MediaTrackCapabilities & { torch?: boolean };

export function torchSupported(stream: MediaStream): boolean {
  const track = stream.getVideoTracks()[0];
  if (!track || typeof track.getCapabilities !== 'function') return false;
  return Boolean((track.getCapabilities() as TorchCapabilities).torch);
}

export async function setTorch(stream: MediaStream, on: boolean): Promise<void> {
  const track = stream.getVideoTracks()[0];
  if (!track) return;
  await track.applyConstraints({ advanced: [{ torch: on } as MediaTrackConstraintSet] });
}

export function stopStream(stream: MediaStream | null): void {
  stream?.getTracks().forEach((t) => t.stop());
}
