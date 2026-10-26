import { useEffect, useMemo, useState } from "react";

import {

  Activity,

  ArrowLeft,

  Brain,

  ChevronLeft,

  ChevronRight,

  Layers3,

  ListPlus,

  RefreshCw,

  Pencil,
  Save,
  X,

} from "lucide-react";

import TutorialSpotlight from "./TutorialSpotlight";
import EphysTrainingSignalViewer from "./EphysTrainingSignalViewer";

import styles from "./LinkedPatientPreview.module.css";

const imagingMetadata = [

  ["Patient ID", "001"],

  ["Imaging ID", "001"],

  ["Clinical Assessment ID", "003"],

  ["Modality", "MRI"],

  ["Acquisition", "T1-weighted"],

  ["Status", "Standardized"],

];

const ephysMetadata = [

  ["Patient ID", "001"],

  ["Electrophysiology ID", "001"],

  ["Clinical Assessment ID", "003"],

  ["Recording Type", "EEG"],

  ["Source", "Synthetic demo signal"],

  ["Status", "Standardized"],

];

const CHANNELS = [

  "Fp1",

  "Fp2",

  "F3",

  "F4",

  "C3",

  "C4",

  "P3",

  "P4",

  "O1",

  "O2",

  "F7",

  "F8",

];

const OVERLAP_COLORS = [

  "#0057D9",

  "#D63A00",

  "#0B8F55",

  "#7A3FB5",

  "#C98A00",

  "#007C91",

  "#D11D65",

  "#4F6500",

  "#5B3FFF",

  "#9E2A2B",

  "#0083B0",

  "#8A4F00",

];

export default function LinkedPatientPreview({

  type,

  onBack,

  backLabel,

  startViewerTour = false,

  onViewerTourExit,
  linkedMetadata,
  onSaveLinkedMetadata,
  savedEphysReview,

}) {

  const imaging = type === "imaging";
  const [editingMetadata, setEditingMetadata] = useState(false);
  const [reviewMetadata, setReviewMetadata] = useState(null);
  const [draftMetadata, setDraftMetadata] = useState({});
  const currentMetadata = reviewMetadata ?? linkedMetadata ?? {};
  const metadataFields = [
    ["patientId", "CoCANoT Patient ID"],
    ["recordingId", "Recording ID"],
    ["clinicalAssessmentId", "Clinical Assessment ID"],
    ["surgeryId", "Surgery ID"],
    ["modality", "Recording Modality"],
    ["timing", "Recording Timing"],
    ["purpose", "Recording Purpose"],
    ["duration", "Recording Duration"],
    ["seizuresCaptured", "Seizures Captured"],
    ["localization", "Primary Seizure Onset Localization"],
    ["comments", "Comments"],
  ];
  const displayMetadata = imaging ? imagingMetadata : metadataFields.map(([key, label]) => [
    label,
    Array.isArray(currentMetadata[key]) ? currentMetadata[key].join(", ") : String(currentMetadata[key] ?? ""),
  ]);

  function beginMetadataEdit() {
    setDraftMetadata({ ...currentMetadata });
    setEditingMetadata(true);
  }
  function saveMetadataEdit() {
    setReviewMetadata({ ...draftMetadata });
    onSaveLinkedMetadata?.({ ...draftMetadata });
    setEditingMetadata(false);
  }

  return (

    <div className={`${styles.page} ${!imaging ? "linked-ephys-review" : ""}`}>

      <div className={styles.topActions}>

        <button className={styles.backButton} onClick={onBack}>

          <ArrowLeft size={16} />

          {backLabel ||

            `Back to ${imaging ? "Imaging" : "Electrophysiology"} Demo`}

        </button>

      </div>

      {imaging && (
      <header className={styles.heading}>

        <div className={styles.headingIcon}>

          {imaging ? <Brain size={26} /> : <Activity size={26} />}

        </div>

        <div>

          {imaging && <span>IMAGING DATA REVIEW</span>}

          <h1>

            {imaging

              ? "Review linked image"

              : "Explore linked electrophysiology"}

          </h1>

          <p>

            {imaging

              ? "View the standardized image associated with this patient together with the metadata that keeps it linked to the longitudinal patient record."

              : "Explore a synthetic EEG signal associated with this demo patient. The guided viewer will show you how to add channels, switch between stacked and overlap views, change the time window, and move through the recording."}

          </p>

        </div>

      </header>

      )}

      {!imaging && <section className="linked-review-card" style={{marginBottom:18}}>
        <div className="linked-review-card-head"><strong>Saved EDF header comparison · Step 4</strong><span>Raw versus scrubbed</span></div>
        <div style={{padding:16,overflowX:"auto"}}>
          <table style={{width:"100%",borderCollapse:"collapse",fontSize:13,textAlign:"left"}}>
            <thead><tr><th style={{padding:9}}>EDF field</th><th>Raw value</th><th>Scrubbed value</th></tr></thead>
            <tbody>{(savedEphysReview?.rawHeader||[]).map(([field,raw])=><tr key={field} style={{borderTop:"1px solid #e4edf3"}}>
              <td style={{padding:9,fontWeight:650}}>{field}</td><td>{raw}</td><td>{savedEphysReview?.scrubbedHeader?.find(([name])=>name===field)?.[1]??"—"}</td>
            </tr>)}</tbody>
          </table>
          {!savedEphysReview?.rawHeader?.length&&<p>No saved EDF header review is available.</p>}
        </div>
      </section>}
      {!imaging && <section className="linked-review-card" style={{marginBottom:18}}>
        <div className="linked-review-card-head"><strong>EDF annotations · Step 4</strong><span>Recording event positions</span></div>
        <div style={{padding:16,overflowX:"auto"}}>
          <p style={{fontSize:12,color:"#536e83",margin:"0 0 12px"}}>Choose View on any annotation to jump directly to its time in the recording. The event is highlighted on the waveform below.</p>
          <LinkedAnnotationSignal annotations={savedEphysReview?.scrubbedAnnotations||[]} />
          <table style={{width:"100%",borderCollapse:"collapse",fontSize:13,textAlign:"left"}}>
            <thead><tr><th style={{padding:9}}>Onset (s)</th><th>Duration (s)</th><th>Scrubbed description</th></tr></thead>
            <tbody>{(savedEphysReview?.scrubbedAnnotations||[]).map((item,i)=><tr key={i} style={{borderTop:"1px solid #e4edf3"}}><td style={{padding:9}}>{item.onset}</td><td>{item.duration}</td><td>{item.description}</td></tr>)}</tbody>
          </table>
        </div>
      </section>}
      {!imaging && <section className="linked-review-card" style={{marginBottom:18}}>
        <div className="linked-review-card-head"><strong>Linked EDF JSON sidecar · Step 4</strong><span>sub-001_task-rest_eeg.json</span></div>
        <pre style={{margin:16,padding:16,overflowX:"auto",background:"#f3f8fb",borderRadius:9,fontSize:12,lineHeight:1.6,color:"#183c54"}}>{savedEphysReview?.sidecar ? JSON.stringify(savedEphysReview.sidecar,null,2) : "No JSON metadata was saved in Step 4."}</pre>
      </section>}
      {imaging ? (
        <MetadataSummary title="Linked metadata" recordLabel="Image record 001" rows={displayMetadata} />
      ) : (
        <>
          <section className="linked-review-card">
            <div className="linked-review-card-head">
              <strong>Linked metadata</strong><span>Electrophysiology record {currentMetadata.recordingId || "001"}</span>
            </div>
            {editingMetadata ? (
              <div className="linked-review-editor">
                {metadataFields.filter(([key]) => !["purpose", "localization", "comments"].includes(key)).map(([key, label]) => (
                  <label key={key}>{label}
                    {key === "modality" || key === "timing" ? (
                      <select value={draftMetadata[key] ?? ""} onChange={event => setDraftMetadata(current => ({...current,[key]:event.target.value}))}>
                        {["", ...(key === "modality" ? ["Scalp EEG", "Intracranial EEG", "MEG", "DBS", "Other"] : ["Preoperative", "Intraoperative", "Postoperative", "Follow-up", "Unknown"])].map(option => <option key={option} value={option}>{option || "Select…"}</option>)}
                      </select>
                    ) : (
                      <input value={String(draftMetadata[key] ?? "")} readOnly={key === "clinicalAssessmentId"} title={key === "clinicalAssessmentId" ? "Linked clinical assessment" : undefined} onChange={event => setDraftMetadata(current => ({...current,[key]:event.target.value}))}/>
                    )}
                  </label>
                ))}
                {[
                  ["purpose", "Recording Purpose", ["Diagnostic evaluation", "Presurgical evaluation", "Neuromodulation Planning", "Seizure Localization", "Postoperative Evaluation (<30 days)", "Follow-up Evaluation (>30 days after surgery)", "Other", "Unknown"]],
                  ["localization", "Primary Seizure Onset Localization", ["Medial temporal", "Temporal neocortical", "Frontal", "Parietal", "Occipital", "Insula", "Thalamus: Anterior nucleus", "Thalamus: Centromedian", "Thalamus: Pulvinar", "Vagus Nerve", "Other", "N/A", "Unknown"]],
                ].map(([key,label,options]) => {
                  const selected = Array.isArray(draftMetadata[key]) ? draftMetadata[key] : draftMetadata[key] ? [draftMetadata[key]] : [];
                  return (
                    <div className="linked-review-wide" key={key}>
                      <strong>{label}</strong>
                      <div className="linked-review-checkboxes">
                        {options.map(option => (
                          <label key={option}><input type="checkbox" checked={selected.includes(option)} onChange={() => setDraftMetadata(current => ({...current,[key]:selected.includes(option) ? selected.filter(value => value !== option) : [...selected,option]}))}/>{option}</label>
                        ))}
                      </div>
                    </div>
                  );
                })}
                <label className="linked-review-wide">Comments
                  <textarea value={draftMetadata.comments ?? ""} onChange={event => setDraftMetadata(current => ({...current,comments:event.target.value}))} placeholder="Optional notes. Avoid protected health information." />
                </label>
                <div className="linked-review-editor-actions">
                  <button className="linked-review-refresh" type="button" onClick={() => setEditingMetadata(false)}>Cancel</button>
                  <button className="linked-review-save" type="button" onClick={saveMetadataEdit}>Save Metadata</button>
                </div>
              </div>
            ) : (
              <dl className="linked-review-metadata">
                {displayMetadata.map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value || "—"}</dd></div>)}
              </dl>
            )}
          </section>
          {!editingMetadata && (
            <div className="linked-review-metadata-actions">
              <button className="linked-review-edit" type="button" onClick={beginMetadataEdit}>Review / Edit Metadata</button>
            </div>
          )}
        </>
      )}
      <style>{`
.linked-ephys-review .linked-review-edit,.linked-ephys-review .linked-review-refresh,.linked-ephys-review .linked-review-save {display:inline-flex;align-items:center;gap:7px;padding:9px 13px;border:1px solid #2470ae;border-radius:8px;background:#fff;color:#1767b1;font-size:12px;font-weight:800;cursor:pointer;}
.linked-ephys-review .linked-review-save {background:#2470ae;color:#fff;}
.linked-ephys-review .linked-review-metadata-actions {display:flex;justify-content:flex-end;margin:-3px 0 16px;}
.linked-ephys-review .linked-review-metadata-actions .linked-review-edit {background:#2470ae;color:#fff;}
.linked-ephys-review .linked-review-card {margin:14px 0;background:#fff;border:1px solid #d5e0e8;border-radius:11px;overflow:hidden;}
.linked-ephys-review .linked-review-card-head {padding:14px 16px;background:#f7fafc;border-bottom:1px solid #dce5ec;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;}
.linked-ephys-review .linked-review-card-head strong {font-size:13px;color:#29465f;}
.linked-ephys-review .linked-review-card-head span {font-size:11px;color:#6b7f91;}
.linked-ephys-review .linked-review-metadata {display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:15px;padding:17px;}
.linked-ephys-review .linked-review-metadata div {min-width:0;}
.linked-ephys-review .linked-review-metadata dt {font-size:10px;font-weight:800;color:#6b7f91;margin-bottom:5px;}
.linked-ephys-review .linked-review-metadata dd {font-size:12px;font-weight:700;color:#243d55;margin:0;overflow-wrap:anywhere;}
.linked-ephys-review .linked-review-editor {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;padding:17px;}
.linked-ephys-review .linked-review-editor label {display:grid;gap:6px;font-size:11px;font-weight:750;color:#3c5167;}
.linked-ephys-review .linked-review-editor input,.linked-ephys-review .linked-review-editor select,.linked-ephys-review .linked-review-editor textarea {width:100%;min-width:0;padding:10px;border:1px solid #cbd7e1;border-radius:7px;background:white;color:#22354c;font:inherit;font-size:12px;}
.linked-ephys-review .linked-review-editor textarea {min-height:80px;resize:vertical;}
.linked-ephys-review .linked-review-editor .linked-review-wide {grid-column:1/-1;}
.linked-ephys-review .linked-review-editor .linked-review-checkboxes {display:flex;flex-wrap:wrap;gap:7px;}
.linked-ephys-review .linked-review-editor .linked-review-checkboxes label {display:flex;align-items:center;gap:6px;padding:7px;border:1px solid #e1e7ec;border-radius:6px;background:#fafcfd;font-size:10px;font-weight:550;}
.linked-ephys-review .linked-review-editor .linked-review-checkboxes input {width:auto;}
.linked-ephys-review .linked-review-editor-actions {display:flex;justify-content:flex-end;gap:9px;grid-column:1/-1;}

.linked-ephys-review .linked-review-editor input[readonly]{background:#f7fafc;color:#536b7d;}
.linked-ephys-review .linked-review-editor .linked-review-wide>strong{display:block;color:#3c5167;font-size:11px;margin-bottom:8px;}
.linked-ephys-review .linked-review-editor .linked-review-checkboxes input{accent-color:#2470ae;margin:0;}
.linked-ephys-review .linked-review-card{margin-top:0;}
.linked-ephys-review .linked-review-metadata{margin:0;}
      `}</style>

      {imaging ? <ImagingViewer /> : <InteractiveEphysViewer startViewerTour={startViewerTour} onTourExit={onViewerTourExit} />}

    </div>

  );

}

function LinkedAnnotationSignal({annotations}){
  const [selected,setSelected]=useState(null);
  return <div style={{border:"1px solid #d3e4ef",borderRadius:10,padding:12,marginBottom:12,background:"#f8fbfe"}}>
    <div style={{display:"flex",flexWrap:"wrap",gap:8,alignItems:"center",marginBottom:12}}>
      <strong style={{fontSize:13}}>Annotation navigator</strong>
      {annotations.map((annotation,i)=><button type="button" key={i} onClick={()=>setSelected({index:i,onset:Number(annotation.onset)})}
        style={{padding:"7px 11px",border:"1px solid #bed3e3",borderRadius:7,background:selected?.index===i?"#d8edfc":"white",cursor:"pointer",fontSize:12}}>
        View {Number(annotation.onset).toFixed(1)}s · {annotation.description||"Event"}
      </button>)}
    </div>
    <EphysTrainingSignalViewer key={selected ? selected.index+"-"+selected.onset : "initial"} annotations={annotations} initialOnset={selected?.onset ?? 0} />
    {selected&&<p role="status" style={{fontSize:12,color:"#235c80"}}>Viewing annotation at {selected.onset.toFixed(2)} seconds. Orange marker indicates the saved event.</p>}
  </div>;
}

function MetadataSummary({ title, recordLabel, rows }) {

  return (

    <section className={styles.metadataCard}>
      <div className="linked-metadata-summary-header">
        <strong>{title}</strong>
        {recordLabel ? <span>{recordLabel}</span> : null}
      </div>

      <dl>

        {rows.map(([label, value]) => (

          <div key={label}>

            <dt>{label}</dt>

            <dd>{value}</dd>

          </div>

        ))}

      </dl>

    </section>

  );

}

function ImagingViewer() {

  return (

    <section className={styles.viewerCard}>

      <div className={styles.viewerHeader}>

        <div>

          <strong>sub-001_T1w.nii.gz</strong>

          <span>Shape: 256 × 256 × 176</span>

        </div>

        <button className={styles.refreshButton} type="button">

          <RefreshCw size={15} />

          Refresh

        </button>

      </div>

      <div className={styles.imageGrid}>

        <ImagePanel label="Axial" variant="axial" />

        <ImagePanel label="Coronal" variant="coronal" />

        <ImagePanel label="Sagittal" variant="sagittal" />

      </div>

      <div className={styles.sliderStack}>

        <ReviewSlider label="Sagittal X" value={128} max={255} />

        <ReviewSlider label="Coronal Y" value={128} max={255} />

        <ReviewSlider label="Axial Z" value={88} max={175} />

      </div>

    </section>

  );

}

function ImagePanel({ label, variant }) {

  return (

    <div className={styles.imagePanel}>

      <span>{label}</span>

      <div

        className={`${styles.brainPreview} ${styles[variant]}`}

      >

        <div className={styles.brainOuter}>

          <div className={styles.brainInner} />

        </div>

      </div>

    </div>

  );

}

function ReviewSlider({ label, value, max }) {

  return (

    <label className={styles.sliderRow}>

      <span>{label}</span>

      <input

        type="range"

        min="0"

        max={max}

        value={value}

        readOnly

      />

      <strong>

        {value} / {max}

      </strong>

    </label>

  );

}

function InteractiveEphysViewer({ startViewerTour = false, onTourExit }) {

  const [selectedChannels, setSelectedChannels] = useState([

    "Fp1",

    "Fp2",

    "F3",

    "F4",

    "C3",

    "C4",

    "P3",

    "P4",

  ]);

  const [mode, setMode] = useState("stacked");

  const [windowSeconds, setWindowSeconds] = useState(10);

  const [startTime, setStartTime] = useState(24);

  const [showChannelPicker, setShowChannelPicker] = useState(false);

  const [guideStep, setGuideStep] = useState(1);

  const [guideEnabled, setGuideEnabled] = useState(false);

  useEffect(() => {
    if (startViewerTour) {
      setGuideStep(1);
      setGuideEnabled(true);
    } else {
      setGuideEnabled(false);
    }
  }, [startViewerTour]);

  const visibleChannels = useMemo(

    () => CHANNELS.filter((channel) => selectedChannels.includes(channel)),

    [selectedChannels]

  );

  const guide = useMemo(() => {

    if (!guideEnabled) return null;

    if (guideStep === 1) {

      return {

        target: "ephys-viewer-channels",

        title: "Choose which channels are visible",

        text: "Open the channel selector. You can add or remove channels at any time.",

      };

    }

    if (guideStep === 2) {

      return {

        target: "ephys-viewer-add-o1",

        title: "Add another channel",

        text: "Turn on O1 to add it to the signal viewer.",

      };

    }

    if (guideStep === 3) {

      return {

        target: "ephys-viewer-overlap",

        title: "Switch to overlap view",

        text: "Overlap view draws the selected channels together using high-contrast colors so you can compare them directly.",

      };

    }

    if (guideStep === 4) {

      return {

        target: "ephys-viewer-stacked",

        title: "Switch back to stacked view",

        text: "Stacked view separates channels into individual rows for easier channel-by-channel inspection.",

      };

    }

    if (guideStep === 5) {

      return {

        target: "ephys-viewer-window",

        title: "Change the time window",

        text: "Try a different window size to view more or less of the simulated recording at once.",

      };

    }

    if (guideStep === 6) {

      return {

        target: "ephys-viewer-position",

        title: "Move through the recording",

        text: "Drag the recording-position slider to explore a different part of the synthetic EEG.",

      };

    }

    return null;

  }, [guideEnabled, guideStep]);

  function toggleChannel(channel) {

    setSelectedChannels((current) =>

      current.includes(channel)

        ? current.filter((item) => item !== channel)

        : [...current, channel]

    );

    if (guideEnabled && guideStep === 2 && channel === "O1") {

      setGuideStep(3);

    }

  }

  function moveWindow(delta) {

    const next = Math.max(

      0,

      Math.min(120 - windowSeconds, startTime + delta)

    );

    setStartTime(next);

  }

  function resetViewer() {

    setSelectedChannels([

      "Fp1",

      "Fp2",

      "F3",

      "F4",

      "C3",

      "C4",

      "P3",

      "P4",

    ]);

    setMode("stacked");

    setWindowSeconds(10);

    setStartTime(24);

    setShowChannelPicker(false);

  }

  function replayGuide() {

    resetViewer();

    setGuideStep(1);

    setGuideEnabled(true);

  }

  return (

    <>

      <TutorialSpotlight

        enabled={Boolean(guide)}

        target={guide?.target}

        title={guide?.title}

        text={guide?.text}

        step={guideStep}

        totalSteps={6}

        onSkip={() => { setGuideEnabled(false); onTourExit?.(); }}

      />

      <div id="linked-ephys-signal-viewer" />
      <section className={styles.ephysToolbar}>

        <div className={styles.recordingInfo}>

          <div>

            <strong>Synthetic EEG demo signal</strong>

            <span>No EDF file required</span>

          </div>

          <div className={styles.recordingFacts}>

            <span>256 Hz</span>

            <span>120 s simulated</span>

            <span>{visibleChannels.length} visible channels</span>

          </div>

        </div>

        <div className={styles.controlRows}>

          <div className={styles.controlGroup}>

            <button

              type="button"

              data-tutorial-id="ephys-viewer-stacked"

              className={`${styles.modeButton} ${

                mode === "stacked" ? styles.modeActive : ""

              }`}

              onClick={() => {

                setMode("stacked");

                if (guideEnabled && guideStep === 4) {

                  setGuideStep(5);

                }

              }}

            >

              <ListPlus size={15} />

              Stacked

            </button>

            <button

              type="button"

              data-tutorial-id="ephys-viewer-overlap"

              className={`${styles.modeButton} ${

                mode === "overlap" ? styles.modeActive : ""

              }`}

              onClick={() => {

                setMode("overlap");

                if (guideEnabled && guideStep === 3) {

                  setGuideStep(4);

                }

              }}

            >

              <Layers3 size={15} />

              Overlap

            </button>

          </div>

          <div className={styles.controlGroup}>

            <button

              type="button"

              data-tutorial-id="ephys-viewer-channels"

              className={styles.channelButton}

              onClick={() => {

                setShowChannelPicker((current) => !current);

                if (guideEnabled && guideStep === 1) {

                  setGuideStep(2);

                  setShowChannelPicker(true);

                }

              }}

            >

              Channels ({visibleChannels.length})

            </button>

            <button

              type="button"

              className={styles.resetViewerButton}

              onClick={resetViewer}

            >

              Reset viewer

            </button>

          </div>

        </div>

        {showChannelPicker && (

          <div className={styles.channelPicker}>

            <div className={styles.channelPickerHeader}>

              <strong>Visible channels</strong>

              <span>Select or remove channels from the viewer.</span>

            </div>

            <div className={styles.channelOptions}>

              {CHANNELS.map((channel) => (

                <label

                  key={channel}

                  data-tutorial-id={

                    channel === "O1" ? "ephys-viewer-add-o1" : undefined

                  }

                >

                  <input

                    type="checkbox"

                    checked={selectedChannels.includes(channel)}

                    onChange={() => toggleChannel(channel)}

                  />

                  <span>{channel}</span>

                </label>

              ))}

            </div>

          </div>

        )}

        <div className={styles.navigationControls}>

          <button type="button" onClick={() => moveWindow(-windowSeconds)}>

            <ChevronLeft size={15} />

            Previous

          </button>

          <button type="button" onClick={() => moveWindow(windowSeconds)}>

            Next

            <ChevronRight size={15} />

          </button>

          <label data-tutorial-id="ephys-viewer-window">

            <span>Window</span>

            <select

              value={windowSeconds}

              onChange={(event) => {

                const next = Number(event.target.value);

                setWindowSeconds(next);

                setStartTime((current) =>

                  Math.min(current, 120 - next)

                );

                if (guideEnabled && guideStep === 5) {

                  setGuideStep(6);

                }

              }}

            >

              <option value={5}>5 seconds</option>

              <option value={10}>10 seconds</option>

              <option value={20}>20 seconds</option>

              <option value={30}>30 seconds</option>

            </select>

          </label>

        </div>

        <label

          className={styles.timelineControl}

          data-tutorial-id="ephys-viewer-position"

        >

          <div>

            <span>Recording position</span>

            <strong>

              {startTime}s – {Math.min(120, startTime + windowSeconds)}s

            </strong>

          </div>

          <input

            type="range"

            min="0"

            max={120 - windowSeconds}

            value={startTime}

            onChange={(event) => {

              setStartTime(Number(event.target.value));

              if (guideEnabled && guideStep === 6) {

                setGuideEnabled(false);

                setGuideStep(7);

              }

            }}

          />

        </label>

      </section>

      <section className={styles.signalCard}>

        <div className={styles.channelHeader}>

          <div>

            <strong>

              {mode === "stacked"

                ? "Stacked channel view"

                : "Overlap channel view"}

            </strong>

            <span>

              Synthetic signal generated in the browser for demonstration only.

            </span>

          </div>

        </div>

        {visibleChannels.length === 0 ? (

          <div className={styles.noChannels}>

            <Activity size={26} />

            <strong>No channels selected</strong>

            <span>

              Open Channels and select one or more channels to display.

            </span>

          </div>

        ) : mode === "stacked" ? (

          <StackedSignals

            channels={visibleChannels}

            startTime={startTime}

            windowSeconds={windowSeconds}

          />

        ) : (

          <OverlapSignals

            channels={visibleChannels}

            startTime={startTime}

            windowSeconds={windowSeconds}

          />

        )}

        <TimeAxis

          startTime={startTime}

          windowSeconds={windowSeconds}

        />

      </section>

    </>

  );

}

function StackedSignals({

  channels,

  startTime,

  windowSeconds,

}) {

  return channels.map((channel) => {

    const seed = CHANNELS.indexOf(channel);

    return (

      <div className={styles.signalStrip} key={channel}>

        <div className={styles.signalLabel}>

          <strong>{channel}</strong>

          <span>EEG</span>

          <small>µV</small>

        </div>

        <svg viewBox="0 0 900 90" preserveAspectRatio="none">

          <line

            x1="0"

            x2="900"

            y1="45"

            y2="45"

            className={styles.zeroLine}

          />

          <path

            className={styles.signalLine}

            d={makeWavePath({

              seed,

              startTime,

              windowSeconds,

              centerY: 45,

            })}

          />

        </svg>

      </div>

    );

  });

}

function OverlapSignals({

  channels,

  startTime,

  windowSeconds,

}) {

  return (

    <div className={styles.overlapCanvas}>

      <div className={styles.overlapLegend}>

        {channels.map((channel) => {

          const channelIndex = CHANNELS.indexOf(channel);

          return (

            <span key={channel}>

              <i

                style={{

                  backgroundColor:

                    OVERLAP_COLORS[

                      channelIndex % OVERLAP_COLORS.length

                    ],

                }}

              />

              {channel}

            </span>

          );

        })}

      </div>

      <svg viewBox="0 0 900 430" preserveAspectRatio="none">

        {[0, 1, 2, 3, 4].map((line) => (

          <line

            key={line}

            x1="0"

            x2="900"

            y1={70 + line * 72}

            y2={70 + line * 72}

            className={styles.gridLine}

          />

        ))}

        {channels.map((channel, index) => {

          const channelIndex = CHANNELS.indexOf(channel);

          return (

            <path

              key={channel}

              className={styles.overlapLine}

              style={{

                stroke:

                  OVERLAP_COLORS[

                    channelIndex % OVERLAP_COLORS.length

                  ],

                opacity: 0.96,

                strokeWidth: 2 + (index % 2) * 0.25,

              }}

              d={makeWavePath({

                seed: channelIndex,

                startTime,

                windowSeconds,

                centerY:

                  215 +

                  (index - (channels.length - 1) / 2) * 5,

              })}

            />

          );

        })}

      </svg>

    </div>

  );

}

function TimeAxis({ startTime, windowSeconds }) {

  const ticks = 5;

  return (

    <div className={styles.timeAxis}>

      <span className={styles.timeAxisLabel}>Time (seconds)</span>

      <div className={styles.timeTicks}>

        {Array.from({ length: ticks + 1 }, (_, index) => {

          const value =

            startTime + (windowSeconds / ticks) * index;

          return <span key={index}>{value.toFixed(1)}</span>;

        })}

      </div>

    </div>

  );

}

function makeWavePath({

  seed,

  startTime,

  windowSeconds,

  centerY,

}) {

  const points = [];

  for (let x = 0; x <= 900; x += 4) {

    const t =

      startTime +

      (x / 900) * windowSeconds;

    const alpha =

      Math.sin((t * 2 * Math.PI * (8 + seed * 0.16)) + seed) * 5.2;

    const theta =

      Math.sin((t * 2 * Math.PI * (4 + seed * 0.08)) + seed * 0.6) * 2.4;

    const slow =

      Math.sin((t * 2 * Math.PI * (0.45 + seed * 0.02)) + seed * 0.4) * 4;

    const transient =

      Math.sin((t * 2 * Math.PI * (17 + seed * 0.1)) + seed * 0.3) *

      Math.max(0, Math.sin(t * 0.72 + seed)) *

      1.5;

    const y =

      centerY -

      (alpha + theta + slow + transient);

    points.push(`${x},${y.toFixed(2)}`);

  }

  return `M ${points.join(" L ")}`;

}
