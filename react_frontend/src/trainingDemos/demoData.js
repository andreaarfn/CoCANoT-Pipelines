export const DEMO_FILES = {
  imaging: {
    fileName: "testMRIScan.dcm",
    description: "Synthetic DICOM MRI scan",
  },
  electrophysiology: {
    fileName: "testEEGRecording.edf",
    description: "Synthetic EDF recording",
  },
};

export const DEMO_PATIENT = {
  patientId: "001",
  patientLevel: {
    primaryPayer: "Commercial",
  },
  clinical: [
    {
      id: "001",
      title: "Clinical Assessment 001",
      assessmentDate: "2022-01-20",
      seizureFrequency30d: 8,
      seizureStatus: "Active seizures",
    },
    {
      id: "002",
      title: "Clinical Assessment 002",
      assessmentDate: "2023-08-14",
      seizureFrequency30d: 5,
      seizureStatus: "Active seizures",
    },
    {
      id: "003",
      title: "Clinical Assessment 003",
      assessmentDate: "2025-02-10",
      seizureFrequency30d: 1,
      seizureStatus: "Improved, intermittent seizures",
    },
  ],
  surgical: [
    { id: "001", title: "Surgery 001" },
    { id: "002", title: "Surgery 002" },
  ],
  imaging: [
    { id: "001", title: "MRI 001", fileName: "testMRIScan.dcm" },
  ],
  electrophysiology: [
    { id: "001", title: "Recording 001", fileName: "testEEGRecording.edf" },
  ],
};
