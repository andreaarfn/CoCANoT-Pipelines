# CoCANoT Windows x64 package (experimental)

The Windows desktop app is native: React dist + Python + pywebview + Imaging,
Electrophysiology, and patient metadata management. Packaging targets a
Conda Constructor NSIS **.exe installer**, built on a **Windows x64** machine.

## Important: PyDeface and FSL

FSL does not provide a native Windows installation. CoCANoT deliberately does
**not** bundle a pretend native Windows FSL or generate arbitrary masks.
Automatic MRI defacing delegates its PyDeface subprocess through WSL2. Other
Windows operations run natively. If WSL2, FSL, or PyDeface is missing, defacing
fails explicitly; it does not mark the image as defaced.

Install WSL2 Ubuntu following:
https://fsl.fmrib.ox.ac.uk/fsl/docs/install/windows.html

Install FSL **inside the WSL Linux filesystem**, and install PyDeface in that
same distro. From Ubuntu confirm both `command -v pydeface` and
`command -v flirt` succeed. The Windows app invokes the default WSL
distribution using `wsl.exe`, translates NIfTI paths with `wslpath`, and
allows the Python viewer to validate the output on the Windows-mounted drive.

WSL requires OS virtualization/administrative setup; the installer does not
make those system changes silently. **WSL2 support is experimental and needs
testing on clinical-site Windows PCs.** Research PHI must remain on approved
local drives; avoid cloud-syncing intermediate source data.

## Build

On a Windows x64 PC or Windows x64 virtual machine, install Node/npm, Conda,
Conda Constructor, and NSIS prerequisites; activate a Windows x64 Conda
build environment with Python and pip:

```powershell
git switch fix/ephys-imaging-parity-20261021
git pull --ff-only origin fix/ephys-imaging-parity-20261021
powershell -ExecutionPolicy Bypass -File packaging/scripts/build_windows.ps1
```

The build produces:
`packaging/constructor/windows/CoCANoT-Windows-x64.exe`

Install the EXE in the current-user AppData Local CoCANoT runtime directory.
Launch via `CoCANoT.bat` there; the native UI requires an Edge WebView2
runtime and graphical desktop. Run `verify_install_windows.ps1` and test
DICOM conversion, EDF waveform/saving, patient metadata, and imaging exports.

**Limitations:** No Windows installer has yet been built or tested. Conda
packages/wheels may require adjustment for Windows. Windows ARM64 is not
supported by this target. Signing and installer smoke testing are required
before distribution.
