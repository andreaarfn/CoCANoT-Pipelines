# CoCANoT Pipelines

CoCANoT Pipelines is a desktop application for deidentifying, standardizing, validating, and managing clinical research data collected by participating CoCANoT centers.

The application provides a unified interface for processing neuroimaging and electrophysiology data, managing clinical and surgical metadata, and reviewing patient records according to the CoCANoT metadata dictionary.

## Application Overview

The desktop application uses React for its interface, Python for data processing, and PyWebView to connect the frontend with the processing pipelines.

The application includes five primary components.

| Component | Function |
|---|---|
| Imaging | DICOM conversion, NIfTI header deidentification, MRI defacing, quality control, metadata validation, and BIDS export |
| Electrophysiology | EDF metadata deidentification, quality control, metadata validation, and BIDS export |
| Metadata Management | Creation, editing, validation, and management of clinical, surgical, imaging, and electrophysiology metadata |
| Patient Data Review | Review of patient records, associated metadata, and linked data files |
| Help & Support | Direct submission of bug reports to the development team's private GitHub repository |

The application also includes a Needs Attention dashboard for identifying records that require further review.

## Repository Structure

```text
CoCANoT-Pipelines/
├── react_dashboard.py
├── react_frontend/
│   ├── src/
│   └── dist/
├── ImagingPipeline/
│   └── scripts/
├── ElectrophysiologyPipeline/
│   └── scripts/
├── MetadataPipeline/
│   ├── dictionaries/
│   ├── forms/
│   ├── storage/
│   └── validation/
├── app/
│   └── site_access.py
├── config/
└── packaging/
    └── constructor/
        └── macos/
```

## Data Processing

### Imaging

The imaging workflow supports DICOM and NIfTI inputs and includes:

1. DICOM to NIfTI conversion
2. NIfTI header deidentification
3. MRI defacing using PyDeface
4. Quality control and review of processed images
5. CoCANoT metadata completion, validation, and BIDS conversion

### Electrophysiology

The electrophysiology workflow currently processes EDF recordings and includes:

1. Selection and preparation of recordings
2. EDF metadata deidentification
3. Quality control through comparison of original and processed recordings
4. Review of accepted recordings
5. CoCANoT metadata completion, validation, and BIDS conversion

### Metadata Management

Clinical, surgical, imaging, and electrophysiology metadata are managed according to the CoCANoT metadata dictionary.

The application supports individual record entry, bulk metadata uploads, field validation, and management of existing patient records. Related assessments and processed files are linked through CoCANoT identifiers.

Metadata and record associations are maintained in the application's local storage system.

## Site Authentication

Participating centers access the application using their assigned Site ID and Access Code.

Credentials are verified through a centralized Google Apps Script authentication service. A successful login establishes a temporary authenticated session.

Each center's records are associated with its Site ID.

## Bug Reporting

The Help & Support section allows users to submit bug reports directly from the desktop application.

Reports include the reporting Site ID, a short summary, a description of the problem, and steps to reproduce it.

Submissions are processed through Google Apps Script and automatically created as GitHub Issues in the private CoCANoT repository. Users do not need a GitHub account or access to the repository.

The application confirms successful submission and uses request identifiers to prevent duplicate issues when a report is retried.

**Bug reports must not contain patient identifiers, protected health information, or other sensitive data.**

## Installation

### macOS

Download the latest available macOS installer from the repository's [Releases](https://github.com/andreaarfn/CoCANoT-Pipelines/releases) section.

Open the `.pkg` file and follow the installation instructions.

Once installed, launch CoCANoT and sign in using your assigned Site ID and Access Code.

The application requires an internet connection for authentication and bug report submission. Data processing workflows operate locally.

### Other Operating Systems

The repository includes pipeline components and packaging configurations for Linux and Windows. The current unified React desktop application is being developed and tested for macOS.

## Development

### Frontend

The user interface is developed with React and JavaScript.

To build the frontend:

```bash
cd react_frontend
npm install
npm run build
```

### Python Application

The desktop application is launched through `react_dashboard.py`, which uses PyWebView to expose Python processing functions to the React interface.

```bash
python react_dashboard.py
```

Python dependencies and required processing tools must be available in the development environment.

### Packaging

macOS installer configuration is maintained in `packaging/constructor/macos`.

Installer builds use Constructor to package the application and its required runtime dependencies.

## Data Privacy

CoCANoT processing workflows are designed to remove identifying information from imaging and electrophysiology data before standardized export.

Processed data and metadata must be reviewed and validated before sharing. Automated deidentification does not replace site responsibility for confirming that outputs contain no identifying information.

Authentication and bug reporting communicate with the external reporting service. Patient data should not be included in these requests.

## Project Status

CoCANoT Pipelines is under active development and testing as part of the CoCANoT consortium.

The project is developed in collaboration with the Epilepsy Institute for Care and Cure.
