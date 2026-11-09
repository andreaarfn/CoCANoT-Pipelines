#!/usr/bin/env python3
"""Fail packaging builds when bundled Python source imports undeclared dependencies.

Uses Python's standard library only. Checks source imports against all platform
manifests, including legacy metadata modules that ship in the payload.
"""
from __future__ import annotations
import argparse
import ast
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "packaging" / "environment"
FILES = [ROOT / "react_dashboard.py", ROOT / "pipeline_config.py"]
for folder in ("app", "MetadataPipeline", "ImagingPipeline/scripts", "ElectrophysiologyPipeline/scripts"):
    FILES.extend(p for p in (ROOT / folder).rglob("*.py") if p.is_file())

# External import name -> package specification (Conda and/or pip name).
PACKAGES = {
    "PIL": "pillow", "fitz": "pymupdf", "yaml": "pyyaml",
    "webview": "pywebview", "numpy": "numpy", "scipy": "scipy",
    "matplotlib": "matplotlib", "nibabel": "nibabel",
    "pyedflib": "pyedflib", "openpyxl": "openpyxl",
    "requests": "requests", "flask": "flask", "nipype": "nipype",
    "networkx": "networkx", "traits": "traits",
    "pydot": "pydot", "rdflib": "rdflib", "lxml": "lxml",
    "tkinter": "tk",
    "clr": "pythonnet", "pythonnet": "pythonnet",
    "pydeface": "pydeface", "fsl": "fslpy",
}
LOCAL = {"app", "MetadataPipeline", "ImagingPipeline", "ElectrophysiologyPipeline", "pipeline_config", "react_dashboard"}
# Not every Python distribution exposes a same-named import; these are mandatory
# for the subprocess-based imaging and offline packaging paths.
REQUIRED = {
    "windows": {"numpy", "scipy", "nibabel", "matplotlib", "pillow", "pymupdf",
                "openpyxl", "pyedflib", "pyyaml", "dcm2niix", "flask", "pip",
                "pywebview", "nipype", "networkx", "requests", "tk", "pythonnet"},
    "macos": {"numpy", "scipy", "nibabel", "matplotlib", "pillow", "pymupdf",
              "openpyxl", "pyedflib", "pyyaml", "dcm2niix", "flask", "pip",
              "pywebview", "nipype", "networkx", "requests", "tk",
              "fsl-flirt", "fslpy", "pydeface"},
    "linux": {"numpy", "scipy", "nibabel", "matplotlib", "pillow", "pymupdf",
              "openpyxl", "pyedflib", "pyyaml", "dcm2niix", "flask", "pip",
              "pywebview", "nipype", "networkx", "requests", "tk",
              "fsl-flirt", "fslpy", "pydeface"},
}
def packages_in(path: Path) -> set[str]:
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("- "):
            line = line[2:].strip()
        match = re.match(r"^([A-Za-z][A-Za-z0-9_.-]*)\s*(?:[=<>!~].*)?$", line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    # Conda's matplotlib-base supplies the matplotlib Python import.
    if "matplotlib-base" in names:
        names.add("matplotlib")
    return names

def imports_in(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (SyntaxError, UnicodeError, OSError) as exc:
        raise RuntimeError(f"Cannot audit Python source {path.relative_to(ROOT)}: {exc}") from exc
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(x.name.split(".")[0] for x in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".")[0])
    return imports

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=REQUIRED, required=True)
    args = parser.parse_args()
    platform = args.platform
    conda = ENV / ("environment-" + platform + ".yaml")
    pip = ENV / ("requirements-pip-bundled.txt" if platform == "macos" else
                 "requirements-pip-" + platform + ".txt")
    declared = packages_in(conda) | packages_in(pip)
    missing_files = [str(p.relative_to(ROOT)) for p in FILES if not p.is_file()]
    if missing_files:
        print("Missing source files:", missing_files, file=sys.stderr)
        return 1
    imported = set()
    for path in sorted(set(FILES)):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        if not path.is_file():
            continue
        imported |= imports_in(path)
    required = REQUIRED[platform] | {
        PACKAGES[name] for name in imported if name in PACKAGES
        and not (platform == "windows" and name in {"pydeface", "fsl"})
    }
    missing = sorted(required - declared)
    # Unknown non-local imports are reported for manual review, avoiding false
    # positives from Python's conditional or optional standard-library modules.
    unknown = sorted(x for x in imported if x not in sys.stdlib_module_names
                     and x not in LOCAL and x not in PACKAGES and x != "__future__")
    print(f"{platform}: scanned {len(set(FILES))} source files; checked {len(required)} required packages")
    if unknown:
        print("Unclassified imports (review if third-party):", ", ".join(unknown))
    if missing:
        print("ERROR: missing dependency declarations:", ", ".join(missing), file=sys.stderr)
        return 1
    print("PASS: core pipeline dependency declarations are present")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
