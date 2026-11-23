"""Isolated RetinaFace scan worker.

Only receives a JSON request over stdin; never uploads frames or writes video.
Do not import this module in the CoCANoT GUI process.
"""
from __future__ import annotations

import contextlib
import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Invalid scanner request.")
        # Keep third-party diagnostic output away from the JSON protocol.
        with contextlib.redirect_stdout(sys.stderr):
            from VideoPipeline.ai_retinaface import scan_faces
            result = scan_faces(
                str(payload["path"]), float(payload["start"]), float(payload["end"])
            )
        sys.stdout.write(json.dumps({"ok": True, "result": result}) + "\n")
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({
            "ok": False,
            "error": str(exc) or type(exc).__name__
        }) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
