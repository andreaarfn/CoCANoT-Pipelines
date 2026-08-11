# CoCANoT Pipelines

CoCANoT Pipelines is a cross-platform software suite for standardized neuroimaging and electrophysiology data processing.

The project currently contains two independent pipelines:

- **Imaging Pipeline**
  - DICOM → NIfTI conversion
  - NIfTI de-identification
  - MRI defacing
  - BIDS conversion

- **Electrophysiology Pipeline**
  - EDF metadata de-identification
  - Quality-control comparison
  - BIDS conversion

Both pipelines share a common configuration system and are packaged for simple installation on supported operating systems.

---

# Repository Structure

```
CoCANoT-Pipelines/

├── pipeline_config.py
├── pipeline_settings.json
│
├── ImagingPipeline/
│   ├── dashboard.py
│   └── scripts/
│
├── ElectrophysiologyPipeline/
│   ├── dashboard.py
│   └── scripts/
│
└── packaging/
```

---

# Project Components

## Shared Configuration

### `pipeline_config.py`

Loads and validates the shared pipeline configuration used by both pipelines.

### `pipeline_settings.json`

Stores user-specific settings, including selected input and output directories.

---

## ImagingPipeline

Contains the MRI processing pipeline.

### `dashboard.py`

Graphical interface for configuring and running the imaging workflow.

### `scripts/`

| File | Purpose |
|------|---------|
| `dicom_to_nifti.py` | Converts DICOM images to NIfTI format using dcm2niix. |
| `scrub_nifti_header.py` | Removes identifying metadata from NIfTI headers. |
| `deface_nifti_with_pydeface.py` | Removes facial features from MRI volumes using PyDeface and FSL. |
| `nifti_to_bids.py` | Organizes processed imaging data into BIDS format. |

---

## ElectrophysiologyPipeline

Contains the EEG processing pipeline.

### `dashboard.py`

Graphical interface for configuring and running the electrophysiology workflow.

### `scripts/`

| File | Purpose |
|------|---------|
| `scrub_edf_metadata.py` | Removes identifying metadata from EDF files. |
| `compare_raw_and_scrubbed_edf.py` | Compares original and scrubbed EDF files for quality control. |
| `convert_edf_to_bids.py` | Converts EDF recordings into BIDS format. |

---

## packaging

Contains everything required to build platform-specific installers.

```
packaging/

├── environment-macos.yaml
├── environment-linux.yaml
├── environment-windows.yaml
│
├── constructor/
│   ├── macos/
│   ├── linux/
│   └── windows/
│
└── scripts/
```

### Environment files

Define the software dependencies installed for each operating system.

### Constructor

Contains platform-specific installer configuration files.

### Packaging scripts

Contains post-install scripts executed after installation.

---

# Installation

## macOS

Download the latest macOS installer:

```
CoCANoT-Pipelines-<version>-MacOSX.pkg
```

Double-click the installer and follow the installation instructions.

No separate installation of Python, Conda, Homebrew, dcm2niix, or FSL is required.

---

## Linux

Download the latest Linux installer:

```
CoCANoT-Pipelines-<version>-Linux.sh
```

Run

```bash
chmod +x CoCANoT-Pipelines-<version>-Linux.sh

./CoCANoT-Pipelines-<version>-Linux.sh
```

---

## Windows

Download the latest Windows installer:

```
CoCANoT-Pipelines-<version>-Windows.exe
```

Run the installer and follow the installation instructions.

The Imaging Pipeline uses Windows Subsystem for Linux (WSL) for FSL-based processing.

---

# Development

## Repository

Clone the repository

```bash
git clone https://github.com/andreaarfn/CoCANoT-Pipelines.git
```

---

## Building installers

### macOS

```bash
constructor packaging/constructor/macos
```

### Linux

```bash
constructor packaging/constructor/linux
```

### Windows

```bash
constructor packaging\constructor\windows
```

---

# Software Dependencies

## Shared

- Python
- Tk

## Imaging

- dcm2niix
- NumPy
- NiBabel
- Matplotlib
- PyDeface
- FSL / FLIRT

## Electrophysiology

- PyEDFlib
- Flask

All required dependencies are bundled with the platform installers.

---

# License

This project is under active development with the Epilepsy Institute for Care and Cure