import {

  Activity,

  ArrowRight,

  Brain,

  Check,

  FileText,

  Pencil,

  Scissors,

  Stethoscope,

} from "lucide-react";

import { useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import DemoTutorialAccess from "./DemoTutorialAccess";

import DemoShell from "./DemoShell";

import TutorialSpotlight from "./TutorialSpotlight";

import LinkedPatientPreview from "./LinkedPatientPreview";

import { DEMO_PATIENT } from "./demoData";

import { resetDemoState } from "./demoSession";

import styles from "./PatientDemo.module.css";

const groups = [

  ["clinical", "Clinical Assessments", Stethoscope],

  ["surgical", "Surgical Records", Scissors],

  ["imaging", "Imaging", Brain],

  ["electrophysiology", "Electrophysiology", Activity],

];

export default function PatientDemo() {

  const [clinicalRecords, setClinicalRecords] = useState(DEMO_PATIENT.clinical);

  const [primaryPayer, setPrimaryPayer] = useState(

    DEMO_PATIENT.patientLevel.primaryPayer

  );

  const [selected, setSelected] = useState(null);

  const [linkedPreviewType, setLinkedPreviewType] = useState(null);

  const [tutorialStep, setTutorialStep] = useState(1);

  const [versionedDraft, setVersionedDraft] = useState("2");

  const [payerDraft, setPayerDraft] = useState("Medicare");

  const [flashIds, setFlashIds] = useState([]);

  const location = useLocation();
  const [tutorialEnabled, setTutorialEnabled] = useState(
    location.state?.tutorialChoice !== "no"
  );
  const [showTutorialHint, setShowTutorialHint] = useState(
    location.state?.tutorialChoice === "no"
  );

  const patient = useMemo(

    () => ({

      ...DEMO_PATIENT,

      clinical: clinicalRecords,

    }),

    [clinicalRecords]

  );

  const coach = useMemo(() => {

    if (linkedPreviewType === "imaging") {

      return {

        title: "Linked Imaging Patient Data Review",

        text: "This is the same linked imaging review shown after Step 5 of the Imaging demo: standardized image data beside the metadata that connects it to Patient 001.",

      };

    }

    if (linkedPreviewType === "electrophysiology") {

      return {

        title: "Linked Electrophysiology Patient Data Review",

        text: "This is the same linked signal review shown after Step 5 of the Electrophysiology demo: standardized recording data beside its associated metadata.",

      };

    }

    if (tutorialStep === 1) {

      return {

        title: "Start with the latest Clinical Assessment",

        text: "Open Clinical Assessment 003. We will first change an assessment-specific field to show how CoCANoT preserves longitudinal history.",

      };

    }

    if (tutorialStep === 2) {

      return {

        title: "Change an assessment-specific field",

        text: "Change 30-day seizure frequency from 1 to 2, then save. The demo creates Clinical Assessment 004 while preserving 001–003.",

      };

    }

    if (tutorialStep === 3) {

      return {

        title: "Now change a patient-level field",

        text: "Change Primary Payer from Commercial to Medicare. This updates the value across the patient's record without creating another Clinical Assessment ID.",

      };

    }

    if (tutorialStep === 4) {

      return {

        title: "Compare what changed",

        text: "Clinical Assessment 004 was created for the assessment-specific change. The payer update propagated across all assessments without changing their IDs.",

      };

    }

    return {

      title: selected ? "Explore the patient record" : "Explore one longitudinal patient",

      text: "Open any Clinical, Surgical, Imaging, or Electrophysiology record. Imaging and Electrophysiology open their full linked Patient Data Review views.",

    };

  }, [linkedPreviewType, tutorialStep, selected]);

  const spotlight = useMemo(() => {

    if (linkedPreviewType) return null;

    if (tutorialStep === 1) {

      return {

        target: "patient-ca-003",

        title: "Open Clinical Assessment 003",

        text: "Start with the latest existing Clinical Assessment.",

      };

    }

    if (tutorialStep === 2) {

      return {

        target: "patient-save-versioned",

        title: "Save the assessment-specific change",

        text: "Saving creates a new Clinical Assessment version while preserving the prior assessments.",

      };

    }

    if (tutorialStep === 3) {

      return {

        target: "patient-save-payer",

        title: "Update the patient-level field",

        text: "Primary Payer updates across Patient 001 without creating a new Clinical Assessment ID.",

      };

    }

    if (tutorialStep === 4) {

      return {

        target: "patient-result",

        title: "Compare the two behaviors",

        text: "Review the difference between assessment-specific versioning and patient-level propagation.",

      };

    }

    return null;

  }, [linkedPreviewType, tutorialStep]);

  function selectRecord(record, type) {

    if (type === "imaging") {

      setLinkedPreviewType("imaging");

      return;

    }

    if (type === "electrophysiology") {

      setLinkedPreviewType("electrophysiology");

      return;

    }

    setSelected({ ...record, type });

    if (type === "clinical" && record.id === "003" && tutorialStep === 1) {

      setTutorialStep(2);

    }

  }

  function saveVersionedClinicalChange() {

    const latest = clinicalRecords.find((record) => record.id === "003");

    if (!latest) return;

    const next = {

      ...latest,

      id: "004",

      title: "Clinical Assessment 004",

      seizureFrequency30d: Number(versionedDraft),

    };

    setClinicalRecords((current) => {

      if (current.some((record) => record.id === "004")) {

        return current.map((record) =>

          record.id === "004" ? next : record

        );

      }

      return [...current, next];

    });

    setSelected({ ...next, type: "clinical" });

    setFlashIds(["004"]);

    setTutorialStep(3);

    window.setTimeout(() => setFlashIds([]), 1600);

  }

  function savePatientLevelChange() {

    setPrimaryPayer(payerDraft);

    setFlashIds(

      clinicalRecords

        .map((record) => record.id)

        .concat(clinicalRecords.some((record) => record.id === "004") ? [] : ["004"])

    );

    setTutorialStep(4);

    window.setTimeout(() => setFlashIds([]), 1800);

  }

  function finishTutorial() {

    setTutorialStep(5);

    setTutorialEnabled(false);

  }

  function reset() {

    resetDemoState();

    setClinicalRecords(DEMO_PATIENT.clinical);

    setPrimaryPayer(DEMO_PATIENT.patientLevel.primaryPayer);

    setSelected(null);

    setLinkedPreviewType(null);

    setTutorialStep(1);

    setVersionedDraft("2");

    setPayerDraft("Medicare");

    setFlashIds([]);

    setTutorialEnabled(true);

  }

  return (

    <DemoShell

      title="Patient Data Review"

      subtitle="Explore preloaded synthetic records and see how clinical, surgical, imaging, and electrophysiology data remain linked around one patient."

      coachTitle={coach.title}

      coachText={coach.text}

      step={tutorialEnabled && !linkedPreviewType && tutorialStep <= 4 ? tutorialStep : undefined}

      totalSteps={tutorialEnabled && !linkedPreviewType && tutorialStep <= 4 ? 4 : undefined}

      onReset={reset}

    >

      <DemoTutorialAccess
      enabled={tutorialEnabled}
      showHint={showTutorialHint}
      onDismissHint={() => setShowTutorialHint(false)}
      onStart={() => {
        if (tutorialStep > 4) {
          setTutorialStep(1);
          setSelected(null);
          setLinkedPreviewType(null);
        }
        setTutorialEnabled(true);
      }}
    />
    {linkedPreviewType ? (

        <LinkedPatientPreview

          type={linkedPreviewType === "imaging" ? "imaging" : "ephys"}

          backLabel="Back to Patient Data Review"

          onBack={() => setLinkedPreviewType(null)}

        />

      ) : (

        <>

          <TutorialSpotlight

            enabled={tutorialEnabled && Boolean(spotlight)}

            target={spotlight?.target}

            title={spotlight?.title}

            text={spotlight?.text}

            step={tutorialStep}

            totalSteps={4}

            onSkip={() => {

              setTutorialEnabled(false);

              setTutorialStep(5);

            }}

          />

          {tutorialEnabled && tutorialStep <= 4 && (

            <TutorialStatus

              step={tutorialStep}

              hasCA004={clinicalRecords.some((record) => record.id === "004")}

              payer={primaryPayer}

            />

          )}

          <div className={styles.layout}>

            <aside className={styles.patient}>

              <span>DEMO PATIENT</span>

              <h2>Patient {patient.patientId}</h2>

              <div

                className={`${styles.patientLevelField} ${

                  tutorialEnabled && tutorialStep === 3 ? styles.tutorialHighlight : ""

                }`}

              >

                <div>

                  <small>PATIENT-LEVEL FIELD</small>

                  <strong>Primary Payer</strong>

                </div>

                <span>{primaryPayer}</span>

              </div>

              <p>

                Patient-level fields are shared across the patient's record

                rather than versioned separately by Clinical Assessment.

              </p>

            </aside>

            <section className={styles.records}>

              {groups.map(([key, label, Icon]) => {

                const records =

                  key === "clinical" ? clinicalRecords : patient[key];

                return (

                  <div key={key} className={styles.group}>

                    <div className={styles.groupHeader}>

                      <Icon size={18} />

                      <div>

                        <strong>{label}</strong>

                        <span>

                          {records.length} record

                          {records.length === 1 ? "" : "s"}

                        </span>

                      </div>

                    </div>

                    {records.map((record) => (

                      <button

                        key={`${key}-${record.id}`}

                        type="button"

                        data-tutorial-id={

                          key === "clinical" && record.id === "003"

                            ? "patient-ca-003"

                            : undefined

                        }

                        className={`${styles.record} ${

                          selected?.type === key &&

                          selected?.id === record.id

                            ? styles.recordActive

                            : ""

                        } ${

                          flashIds.includes(record.id) && key === "clinical"

                            ? styles.recordFlash

                            : ""

                        } ${

                          tutorialStep === 1 &&

                          key === "clinical" &&

                          record.id === "003"

                            ? styles.tutorialHighlight

                            : ""

                        }`}

                        onClick={() => selectRecord(record, key)}

                      >

                        <strong>{record.title}</strong>

                        <span>

                          {key === "imaging"

                            ? "Open linked image + metadata →"

                            : key === "electrophysiology"

                              ? "Open linked signal + metadata →"

                              : record.fileName ||

                                (key === "clinical"

                                  ? `${record.assessmentDate || "Synthetic assessment"} · Primary Payer: ${primaryPayer}`

                                  : `Record ID ${record.id}`)}

                        </span>

                      </button>

                    ))}

                  </div>

                );

              })}

            </section>

            <section className={styles.detail}>

              {!selected ? (

                <div className={styles.empty}>

                  <FileText size={28} />

                  <strong>Select a record</strong>

                  <p>

                    Clinical and Surgical records open here. Imaging and

                    Electrophysiology records open their full linked Patient

                    Data Review viewers.

                  </p>

                </div>

              ) : selected.type === "clinical" ? (

                <ClinicalRecordDetail

                  record={selected}

                  primaryPayer={primaryPayer}

                  tutorialStep={tutorialStep}

                  versionedDraft={versionedDraft}

                  onVersionedDraftChange={setVersionedDraft}

                  onSaveVersioned={saveVersionedClinicalChange}

                  payerDraft={payerDraft}

                  onPayerDraftChange={setPayerDraft}

                  onSavePayer={savePatientLevelChange}

                  onFinish={finishTutorial}

                />

              ) : (

                <SimpleMetadataDetail record={selected} />

              )}

            </section>

          </div>

        </>

      )}

    </DemoShell>

  );

}

function TutorialStatus({ step, hasCA004, payer }) {

  return (

    <section className={styles.tutorialStatus}>

      <div className={step > 1 ? styles.statusDone : styles.statusActive}>

        <span>{step > 1 ? <Check size={14} /> : "1"}</span>

        <strong>Open CA 003</strong>

      </div>

      <div

        className={

          step > 2

            ? styles.statusDone

            : step === 2

              ? styles.statusActive

              : ""

        }

      >

        <span>{step > 2 ? <Check size={14} /> : "2"}</span>

        <strong>Create a new assessment version</strong>

        {hasCA004 && <small>CA 004 created</small>}

      </div>

      <div

        className={

          step > 3

            ? styles.statusDone

            : step === 3

              ? styles.statusActive

              : ""

        }

      >

        <span>{step > 3 ? <Check size={14} /> : "3"}</span>

        <strong>Update patient-level payer</strong>

        {step > 3 && <small>{payer}</small>}

      </div>

      <div className={step === 4 ? styles.statusActive : ""}>

        <span>4</span>

        <strong>Compare the result</strong>

      </div>

    </section>

  );

}

function ClinicalRecordDetail({

  record,

  primaryPayer,

  tutorialStep,

  versionedDraft,

  onVersionedDraftChange,

  onSaveVersioned,

  payerDraft,

  onPayerDraftChange,

  onSavePayer,

  onFinish,

}) {

  return (

    <div>

      <span className={styles.eyebrow}>CLINICAL DATA REVIEW</span>

      <h2 className={styles.title}>{record.title}</h2>

      <p className={styles.subtitle}>

        Patient 001 · Clinical Assessment ID {record.id}

      </p>

      <dl className={styles.metadata}>

        <div>

          <dt>Patient ID</dt>

          <dd>001</dd>

        </div>

        <div>

          <dt>Clinical Assessment ID</dt>

          <dd>{record.id}</dd>

        </div>

        <div>

          <dt>Assessment date</dt>

          <dd>{record.assessmentDate || "Synthetic assessment"}</dd>

        </div>

        <div>

          <dt>Primary Payer</dt>

          <dd>{primaryPayer}</dd>

        </div>

      </dl>

      <div className={styles.fieldLegend}>

        <div>

          <i className={styles.versionedDot} />

          <span>

            <strong>Assessment-specific</strong>

            Versioned across Clinical Assessments

          </span>

        </div>

        <div>

          <i className={styles.patientDot} />

          <span>

            <strong>Patient-level</strong>

            Shared across the patient's history

          </span>

        </div>

      </div>

      <section

        className={`${styles.editDemoCard} ${

          tutorialStep === 2 ? styles.tutorialHighlight : ""

        }`}

      >

        <div className={styles.editDemoHeader}>

          <div>

            <span className={styles.versionedBadge}>

              ASSESSMENT-SPECIFIC

            </span>

            <strong>30-day seizure frequency</strong>

            <small>

              Changing this field creates a new Clinical Assessment version.

            </small>

          </div>

          <Pencil size={17} />

        </div>

        <div className={styles.editRow}>

          <div>

            <span>Current value</span>

            <strong>{record.seizureFrequency30d ?? 1}</strong>

          </div>

          <ArrowRight size={18} />

          <label>

            <span>New value</span>

            <input

              type="number"

              min="0"

              value={versionedDraft}

              disabled={tutorialStep !== 2}

              onChange={(event) =>

                onVersionedDraftChange(event.target.value)

              }

            />

          </label>

        </div>

        {tutorialStep === 2 && (

          <button

            type="button"

            data-tutorial-id="patient-save-versioned"

            className={styles.demoPrimary}

            onClick={onSaveVersioned}

          >

            Save Assessment Change

          </button>

        )}

      </section>

      <section

        className={`${styles.editDemoCard} ${

          tutorialEnabled && tutorialStep === 3 ? styles.tutorialHighlight : ""

        }`}

      >

        <div className={styles.editDemoHeader}>

          <div>

            <span className={styles.patientBadge}>PATIENT-LEVEL</span>

            <strong>Primary Payer</strong>

            <small>

              Changing this field updates the value across all Clinical

              Assessments without creating another Clinical Assessment ID.

            </small>

          </div>

          <Pencil size={17} />

        </div>

        <div className={styles.editRow}>

          <div>

            <span>Current value</span>

            <strong>{primaryPayer}</strong>

          </div>

          <ArrowRight size={18} />

          <label>

            <span>New value</span>

            <select

              value={payerDraft}

              disabled={tutorialStep !== 3}

              onChange={(event) =>

                onPayerDraftChange(event.target.value)

              }

            >

              <option>Commercial</option>

              <option>Medicare</option>

              <option>Medicaid</option>

              <option>Self-pay</option>

            </select>

          </label>

        </div>

        {tutorialStep === 3 && (

          <button

            type="button"

            data-tutorial-id="patient-save-payer"

            className={styles.demoPrimary}

            onClick={onSavePayer}

          >

            Update Patient-Level Field

          </button>

        )}

      </section>

      {tutorialStep === 4 && (

        <section

          data-tutorial-id="patient-result"

          className={styles.resultCard}

        >

          <strong>What CoCANoT preserved</strong>

          <div className={styles.resultGrid}>

            <div>

              <span>Assessment-specific edit</span>

              <strong>Created CA 004</strong>

              <small>

                CA 001, 002, and 003 remain historical records.

              </small>

            </div>

            <div>

              <span>Patient-level edit</span>

              <strong>Clinical Assessment IDs unchanged</strong>

              <small>

                Primary Payer now displays as {primaryPayer} across all

                assessments.

              </small>

            </div>

          </div>

          <button

            type="button"

            className={styles.demoPrimary}

            onClick={onFinish}

          >

            Continue Exploring Patient Data

          </button>

        </section>

      )}

    </div>

  );

}

function SimpleMetadataDetail({ record }) {

  return (

    <div>

      <span className={styles.eyebrow}>

        {record.type.toUpperCase()} DATA REVIEW

      </span>

      <h2 className={styles.title}>{record.title}</h2>

      <p className={styles.subtitle}>

        Patient 001 · Record {record.id}

      </p>

      <dl className={styles.metadata}>

        <div>

          <dt>Patient ID</dt>

          <dd>001</dd>

        </div>

        <div>

          <dt>Record ID</dt>

          <dd>{record.id}</dd>

        </div>

        <div>

          <dt>Record type</dt>

          <dd>{record.type}</dd>

        </div>

        <div>

          <dt>Status</dt>

          <dd>Standardized</dd>

        </div>

      </dl>

      <div className={styles.summary}>

        <strong>Stored synthetic metadata</strong>

        <p>

          This compact public view represents the selected metadata record.

        </p>

      </div>

    </div>

  );

}
