// Fallback barcode reader for browsers without a native BarcodeDetector.
// Loaded lazily; the wasm is bundled by Vite and served from this app (never a CDN).
import { BarcodeDetector, prepareZXingModule } from 'barcode-detector/ponyfill';
import wasmUrl from 'zxing-wasm/reader/zxing_reader.wasm?url';

prepareZXingModule({
  overrides: {
    locateFile: (path: string, prefix: string) => (path.endsWith('.wasm') ? wasmUrl : prefix + path),
  },
});

export { BarcodeDetector };
