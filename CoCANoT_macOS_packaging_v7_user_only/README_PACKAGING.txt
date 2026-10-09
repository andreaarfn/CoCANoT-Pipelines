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

v2 fix:
- Constructor's PKG prefix is /Library/cocanot-pipelines.
- pip-installed packages from the working environment are now downloaded at
  build time and embedded in the PKG for an offline post-install.
- This fixes the observed missing pydeface executable and also ensures
  pywebview and the other pypi_0 dependencies are present on recipient Macs.

v3 fix:
- Constructor no longer uses ~/.conda/constructor.
- Constructor and Conda package caches are created under packaging/stage,
  so a root-owned ~/.conda directory from prior sudo installer tests cannot
  block future builds.

v4 destination-safety fix:
- The PKG is restricted to the local system domain only.
- "Just Me" / current-user-home installation is disabled.
- A pre-install guard refuses any PREFIX other than /Library/cocanot-pipelines.
- The uninstaller will NEVER remove ~/Library/cocanot-pipelines, protecting
  a developer Conda environment with that name.

v5 offline pip fix:
- Removed proxy-tools from the explicit offline pip bundle. Its source archive
  was trying to create an isolated build environment during installation and
  then look online for setuptools.
- The build now accepts wheel files only for bundled pip dependencies.
- The recipient install performs one strict offline, no-deps, wheel-only pip
  install. If a required package cannot be bundled as a wheel, the BUILD fails
  on the developer machine instead of the INSTALL failing for a site.

v6 current-user-only installation:
- The PKG now allows ONLY "Install for me only".
- System-wide/all-users installation is disabled.
- The private runtime is installed to:
    ~/Library/CoCANoT/runtime
- This deliberately does NOT use:
    ~/Library/cocanot-pipelines
  so it cannot collide with the developer Conda environment.
- CoCANoT.app and Uninstall CoCANoT.app are installed to:
    ~/Applications
- The uninstaller performs only per-user cleanup and does not request
  administrator privileges.
- No files are written to /Library or /Applications by CoCANoT's post-install.

v7 pywebview runtime fix:
- Restored proxy-tools==0.1.0 because pywebview requires it at runtime.
- proxy-tools is built into a wheel on the developer machine during packaging.
- Recipient Macs still install entirely offline and never build source packages.
- All other pip dependencies are required to have binary wheels at build time.
- Post-install now verifies both proxy_tools and webview imports and leaves a
  useful traceback in /var/log/install.log if either fails.
