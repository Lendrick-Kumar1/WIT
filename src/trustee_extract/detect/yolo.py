"""`Detector` backed by a fine-tuned YOLO11 (ultralytics). Task 8.

ultralytics is imported lazily and is not a dependency yet; it is added when training starts.
Class names come from the trained weights and must match config `labelstudio.classes`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from trustee_extract.core.types import Box


class YoloDetector:
    def __init__(self, weights: Path, conf: float = 0.25, dpi: int = 144):
        from ultralytics import YOLO  # lazy: optional dependency

        self.model = YOLO(str(weights))
        self.conf = conf
        self.dpi = dpi

    def detect(self, page) -> list[Box]:
        scale = 72.0 / self.dpi  # pixels -> PDF points
        with tempfile.TemporaryDirectory() as tmp:
            png = page.render_png(Path(tmp) / "p.png", dpi=self.dpi)
            result = self.model.predict(str(png), conf=self.conf, device="cpu", verbose=False)[0]
        names = result.names
        return [
            Box(page.page, tuple(float(v) * scale for v in xyxy), names[int(k)], float(s), "yolo")
            for xyxy, k, s in zip(result.boxes.xyxy.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist())
        ]
