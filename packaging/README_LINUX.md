# CoCANoT Linux installer (experimental)

Build on a Linux desktop with Node.js, Conda, constructor, and an architecture-compatible activated Conda environment:

```bash
git switch fix/ephys-imaging-parity-20261021
git pull --ff-only origin fix/ephys-imaging-parity-20261021
chmod +x packaging/scripts/{build_linux,verify_install_linux}.sh
./packaging/scripts/build_linux.sh
```

The output is a self-extracting Constructor shell installer, **not** an RPM, DEB, AppImage, or macOS PKG. The installer contains the React dist, Python backend, pipeline scripts, metadata dictionaries, Conda binaries, and wheel dependencies. It is architecture-specific: build on x86_64 for linux-64; build on aarch64 for linux-aarch64. Availability of FSL packages on aarch64 is not assured.

Install as the current user (do not use sudo):
```bash
bash packaging/constructor/linux/CoCANoT-Linux-x86_64.sh -b -p "$HOME/.local/share/CoCANoT/runtime"
./packaging/scripts/verify_install_linux.sh
~/.local/bin/cocanot
```

**GUI prerequisites:** an active Linux desktop session, GTK3, and an appropriate WebKit2GTK backend for pywebview. For Debian/Ubuntu, WebKit2GTK 4.1 packages are typically provided by the distro; check versions for your distribution. These graphical system libraries and GPU/display drivers cannot be made portable merely by bundling Python. PyDeface/FSL support may also require host compatibility.

This is an initial packaging workflow and must be tested on clean target Linux machines, including EDF preview/save, NIfTI defacing, dcm2niix, Step 5 export, JSON/dictionary lookup, and uninstall. It does not delete user research data.
