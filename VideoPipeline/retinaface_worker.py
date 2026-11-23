"""Dedicated RetinaFace worker; JSON-lines progress and final response on stdout."""
from __future__ import annotations

import contextlib
import json
import sys


def emit(item: dict) -> None:
    sys.stdout.write(json.dumps(item) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("Invalid scanner request.")
        def progress(stage: str, current: int, total: int) -> None:
            emit({"event": "progress", "stage": stage,
                  "current": int(current), "total": int(total)})

        progress("Loading RetinaFace model", 0, 0)
        # Model and OpenCV may emit diagnostic messages; keep protocol clean.
        with contextlib.redirect_stdout(sys.stderr):
            from VideoPipeline.ai_retinaface import scan_faces
            result = scan_faces(
                str(request["path"]), float(request["start"]),
                float(request["end"]), progress=progress
            )
        emit({"event": "result", "result": result})
        return 0
    except Exception as exc:
        emit({"event": "error", "error": str(exc) or type(exc).__name__})
        return 1


if __name__ == "__main__":
    sys.exit(main())
