CoCANoT macOS packaging v1
==========================

Replace these project files:
- pipeline_config.py
- packaging/environment/environment-macos.yaml
- packaging/constructor/macos/construct.yaml
- packaging/scripts/post_install_macos.sh
- packaging/scripts/uninstall_macos.sh

Add these new files:
- packaging/scripts/build_macos.sh
- packaging/scripts/verify_install_macos.sh

Important:
- This bundle targets Apple Silicon (osx-arm64), matching the supplied environment snapshot.
- Node/npm are build-machine dependencies only; recipients do not need them.
- Python, pywebview, PyDeface, dcm2niix, and FSL/FLIRT are installed in CoCANoT's private prefix.
- Runtime pipeline settings move to ~/.cocanot/pipeline_settings.json.
- Full uninstall removes ~/.cocanot and the private CoCANoT runtime, but not user-selected source/derivatives/BIDS folders.

Build:
  chmod +x packaging/scripts/*.sh
  ./packaging/scripts/build_macos.sh

Verify after installing:
  ./packaging/scripts/verify_install_macos.sh

Before public distribution, code-sign and notarize the PKG/app.
