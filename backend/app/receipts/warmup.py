"""``python -m app.receipts.warmup``: make sure the OCR engine can start.

RapidOCR's default models ship inside its wheel, so nothing is downloaded at
runtime. Running this during a Docker build proves that (the build fails
loudly otherwise) and pays the first-initialization cost up front.
"""

from __future__ import annotations

import sys

import numpy as np

from .ocr import get_engine, model_dir, run_ocr


def main() -> int:
    models = sorted(p.name for p in model_dir().glob("*.onnx"))
    if not models:
        print(f"No OCR models found in {model_dir()}", file=sys.stderr)
        return 1
    get_engine()
    run_ocr(np.full((64, 256, 3), 255, dtype=np.uint8))
    print(f"OCR engine ready; models in {model_dir()}: {', '.join(models)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
