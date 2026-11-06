# CoCANoT Windows x64: single BAT installer

The GitHub Actions Windows target produces exactly **one downloadable file**:
`CoCANoT-Windows-x64.bat` (inside the GitHub Actions artifact ZIP).
No Windows EXE, installer payload ZIP, checksum, or PowerShell script is published as a separate artifact.

## Mandatory manual prerequisite: WSL 2 with Ubuntu 24.04 LTS

Before running the BAT, users independently install **WSL version 2** and the
**Ubuntu 24.04 LTS** distribution. This is *not* WSL version 1, and
"24.04" refers to the Ubuntu Linux version, not the WSL version.

1. Open PowerShell as Administrator and run `wsl --install -d Ubuntu-24.04`.
2. Restart Windows when prompted.
3. Open Ubuntu 24.04 from the Start Menu and complete first-run Linux username/password creation.
4. Run `wsl --list --verbose`. Confirm `Ubuntu-24.04` shows **VERSION 2**.
   If necessary, manually run `wsl --set-version Ubuntu-24.04 2`.
5. Set `Ubuntu-24.04` as the default distribution with
   `wsl --set-default Ubuntu-24.04`, because CoCANoT's defacing pipeline uses the default WSL distro.

Microsoft instructions: https://learn.microsoft.com/windows/wsl/install

The CoCANoT BAT does **not** run `wsl --install`, `wsl --update`, DISM,
Windows feature installers, or WSL distribution setup. It checks for the
already initialized WSL 2 Ubuntu 24.04 installation and stops with instructions
if it is missing. This does not modify the user's WSL installation.

## Running the installer

On **Windows x64** with Internet access, download the GitHub Actions Windows
artifact, extract `CoCANoT-Windows-x64.bat`, and double-click it.

The BAT is a network bootstrapper, **not an offline installer**. It downloads
a revision-pinned CoCANoT source archive and bootstrap script, Miniforge,
a Node.js 22 runtime, native Windows Conda dependencies (Python 3.12,
dcm2niix, pyedflib, nibabel, PyMuPDF, etc.), pip dependencies, and builds
the React frontend locally. It installs into
`%LOCALAPPDATA%\CoCANoT` and creates a Start Menu CoCANoT shortcut.

MRI Step 3C additionally requires Linux FSL FLIRT and PyDeface.
After installation, use **Start Menu > CoCANoT > Install MRI defacing dependencies**
to install those dependencies *inside the existing Ubuntu 24.04 distribution*.
That utility never installs WSL itself. Other application workflows do
not depend on FSL/PyDeface.

## GitHub Actions build

Go to **Actions > Build CoCANoT installers > Run workflow**,
choose the desired branch and the **windows-x64** target.
The target defaults to Windows; choosing `all` explicitly also builds
macOS/Linux installers in their separate jobs.

The Windows job creates and uploads only the BAT. GitHub Actions itself
delivers artifacts wrapped in a ZIP, which must be extracted before running.
The BAT references the exact commit that produced it.

**Status:** This new BAT approach still requires a successful GitHub Actions
run and an installation test on a Windows x64 computer before clinical distribution.
Consider code signing, checksum verification of downloaded third-party
installers, and validating installation on restricted site machines before
broad deployment.
