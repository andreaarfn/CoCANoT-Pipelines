import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Folder, FileAudio, FolderOpen, X, Save, Upload, Database, RefreshCw } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { createPortal } from "react-dom";




import TutorialSpotlight from "./TutorialSpotlight";
import EphysTrainingSignalViewer from "./EphysTrainingSignalViewer";

import LinkedPatientPreview from "./LinkedPatientPreview";

import { DEMO_FILES } from "./demoData";

import { resetDemoState, saveDemoState } from "./demoSession";

import styles from "./WorkflowDemo.module.css";

const labels = ["Select Data", "Output Folders", "Process", "Review", "Metadata & BIDS"];

const STEP_INTRODUCTIONS = {
  1: "Choose EDF recordings, either individually or by folder.",
  2: "Choose where intermediate and final processed recordings will be stored.",
  3: "Scrub identifying EDF header information before review.",
  4: "Compare raw and scrubbed EDF headers and annotations, correct missed identifiers, then accept the recording.",
  5: "Review and edit the CoCANoT electrophysiology metadata before creating BIDS-compatible output.",
};

const GUIDED_STEP_DESCRIPTIONS = {
  1: "This is the first step, where you select the EDF recordings you want to process. You can choose individual files or an entire folder. Next, I'll show you exactly where to click.",
  2: "This is the second step, where you choose separate folders for intermediate derivatives and the final processed recordings. Next, I'll guide you through selecting and saving both locations.",
  3: "This is the third step, where identifying information is scrubbed from the selected EDF recording. Next, I'll show you how to start the simulated process.",
  4: "This is the fourth step, where you compare raw and scrubbed EDF headers and annotations, correct anything missed, and accept the result. Next, we'll review it together.",
  5: "This is the fifth step, where you review and edit the CoCANoT electrophysiology metadata and prepare the accepted recording for BIDS-compatible export. Next, I'll guide you through it.",
};

function StepIntroduction({ step, started, previewing, onShowHow, onSkip }) {
  return <section className="mb-5 rounded-xl border border-sky-200 bg-white px-5 py-4 shadow-sm md:px-6" aria-label={`Introduction to step ${step}`}>
    <p className="text-xs font-bold uppercase tracking-[0.16em] text-navy/60">{previewing ? `GUIDE · STEP ${step} OF 5` : `STEP ${step} OF 5`}</p>
    <h2 className="mt-2 font-serif text-2xl text-navy">{labels[step - 1]}</h2>
    <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-700 md:text-base">{previewing ? GUIDED_STEP_DESCRIPTIONS[step] : STEP_INTRODUCTIONS[step]}</p>
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button type="button" onClick={onShowHow} className="rounded-full bg-navy px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90">{previewing ? "Next →" : started ? "Restart tutorial" : "Show me how →"}</button>
      {started && <button type="button" onClick={onSkip} className="rounded-full px-4 py-2.5 text-sm font-semibold text-navy/70 hover:bg-slate-100">Skip tutorial</button>}
    </div>
  </section>;
}

function GuideOverview({ step, linked = false, wrapUp = false, onNext, onExplore, onSkip }) {
  const cardRef = useRef(null);

  useEffect(() => {
    const highlighted = Array.from(document.querySelectorAll(".ephys-public-demo .ephys-guide-focus-step"));
    const original = highlighted.map(element => element.inert);
    highlighted.forEach(element => { element.inert = true; });
    const focusFrame = requestAnimationFrame(() => {
      cardRef.current?.querySelector("button")?.focus();
    });
    return () => {
      cancelAnimationFrame(focusFrame);
      highlighted.forEach((element, index) => { element.inert = original[index]; });
    };
  }, []);
  const [cardPlacement, setCardPlacement] = useState({ top: 16, left: 16, ready: false });

  useEffect(() => {
    let frame = 0;
    const target = document.querySelector(
      linked ? ".ephys-linked-public-review .ephys-guide-focus-step" : ".ephys-public-demo .ephys-guide-focus-step"
    );
    if (!target) return undefined;

    const positionCard = () => {
      const rect = target.getBoundingClientRect();
      const cardHeight = cardRef.current?.getBoundingClientRect().height || 245;
      const cardWidth = cardRef.current?.getBoundingClientRect().width || 390;
      const top = Math.max(12, rect.top - cardHeight - 18);
      const left = Math.max(16, Math.min(rect.left + 8, window.innerWidth - cardWidth - 16));
      setCardPlacement(current =>
        current.top === Math.round(top) && current.left === Math.round(left) && current.ready
          ? current
          : { top: Math.round(top), left: Math.round(left), ready: true }
      );
    };

    // Leave space for the guide ABOVE the highlighted section, then follow it as the page scrolls.
    const cardHeight = cardRef.current?.getBoundingClientRect().height || 245;
    const desiredTop = Math.min(window.innerHeight - 120, cardHeight + 38);
    const rect = target.getBoundingClientRect();
    const scrollTarget = Math.max(0, window.scrollY + rect.top - desiredTop);
    window.scrollTo({ top: scrollTarget, behavior: "smooth" });

    const onMove = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(positionCard);
    };
    positionCard();
    window.addEventListener("scroll", onMove, { passive: true });
    window.addEventListener("resize", onMove);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onMove);
      window.removeEventListener("resize", onMove);
    };
  }, [step, linked]);

  const heading = wrapUp ? "Take a moment to explore" : linked ? "Review Linked Recording" : labels[step - 1];
  const description = wrapUp
    ? (step === 1 ? "You have selected the sample recording. Take a moment to inspect the selected data before moving to output folders."
      : step === 2 ? "Both output folders are saved. You can explore these settings before starting the processing step."
      : step === 3 ? "EDF scrubbing is complete. Take a moment to review this step before opening the header comparison."
      : step === 4 ? "The corrected EDF is accepted. You can inspect the review results before continuing to metadata."
      : "Your demo output has been created. You can explore the completed metadata and output before opening the linked recording review.")
    : linked
      ? "This is the linked recording review, where you can inspect the processed EDF signal and its associated CoCANoT metadata. Next, I'll show you the viewer and its controls."
      : GUIDED_STEP_DESCRIPTIONS[step];
  return (
    <div className="ephys-guide-overview-backdrop" role="presentation">
      <section ref={cardRef} className="ephys-guide-overview-card" style={{ top: cardPlacement.top, left: cardPlacement.left, visibility: cardPlacement.ready ? "visible" : "hidden" }} role="dialog" aria-modal="true" aria-label={`Guided introduction: ${heading}`}>
        <p className="ephys-guide-overview-eyebrow">{wrapUp ? `GUIDE · STEP ${step} COMPLETE` : linked ? "GUIDE · LINKED RECORDING REVIEW" : `GUIDE · STEP ${step} OF 5`}</p>
        <h2>{heading}</h2>
        <p className="ephys-guide-overview-description">{description}</p>
        <div className="ephys-guide-overview-actions">
          <button type="button" className="ephys-guide-overview-next" onClick={onNext}>{wrapUp ? "Show me where to continue" : "Next"} <span aria-hidden="true">→</span></button>
          {wrapUp && <button type="button" className="ephys-guide-overview-explore" onClick={onExplore}>or explore this step</button>}
          <button type="button" className="ephys-guide-overview-skip" onClick={onSkip}>Skip tutorial</button>
        </div>
      </section>
    </div>
  );
}

// An unobtrusive option inside the existing white tutorial tooltip after the
// step's interactive actions are finished. The shared TutorialSpotlight remains
// unchanged, so this demo still needs just one updated JSX file.
function SpotlightExploreLink({ guideTitle, onExplore }) {
  const [footerHost, setFooterHost] = useState(null);

  useEffect(() => {
    if (!guideTitle) return undefined;
    let observer;
    let frame;

    function findWhiteGuide() {
      const possibleTitles = [...document.querySelectorAll("strong,h1,h2,h3,h4,p,span,div")]
        .filter(node => node.textContent?.trim() === guideTitle &&
          ![...node.children].some(child => child.textContent?.trim() === guideTitle));
      for (const title of possibleTitles.reverse()) {
        let parent = title.parentElement;
        for (let i = 0; parent && i < 6; i++, parent = parent.parentElement) {
          const rect = parent.getBoundingClientRect();
          const background = getComputedStyle(parent).backgroundColor;
          if (rect.width >= 220 && rect.width <= 550 && rect.height >= 95 && rect.height <= 470 &&
              /rgba?\(\s*25[0-5]\s*,\s*25[0-5]\s*,\s*25[0-5]/.test(background) &&
              rect.width < window.innerWidth - 24) {
            setFooterHost(parent);
            observer?.disconnect();
            return;
          }
        }
      }
    }

    frame = requestAnimationFrame(findWhiteGuide);
    observer = new MutationObserver(findWhiteGuide);
    observer.observe(document.body, { subtree: true, childList: true });
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      setFooterHost(null);
    };
  }, [guideTitle]);

  if (!footerHost) return null;
  return createPortal(
    <div className="ephys-guide-small-explore">
      <button type="button" onClick={onExplore}>or explore this step</button>
    </div>,
    footerHost
  );
}

const RAW_HEADER = [

  ["patient_id", "DEMO-SUBJECT-001"],

  ["patient_name", "Jamie Example"],

  ["recording_start_date", "07-OCT-2026"],

  ["technician", "A. Sample"],

  ["hospital", "Demo Epilepsy Center"],

  ["recording_notes", "Follow-up EEG for Jamie Example"],

  ["equipment", "Synthetic EDF Recorder"],

];

const INITIAL_SCRUBBED_HEADER = [

  ["patient_id", "[removed]"],

  ["patient_name", "[removed]"],

  ["recording_start_date", "[shifted]"],

  ["technician", "[removed]"],

  ["hospital", "[removed]"],

  ["recording_notes", "Follow-up EEG for Jamie Example"],

  ["equipment", "Synthetic EDF Recorder"],

];

const PURPOSE_OPTIONS = [

  "Diagnostic evaluation",

  "Presurgical evaluation",

  "Neuromodulation Planning",

  "Seizure Localization",

  "Postoperative Evaluation (<30 days)",

  "Follow-up Evaluation (>30 days after surgery)",

  "Other",

  "Unknown",

];

const LOCALIZATION_OPTIONS = [

  "Medial temporal",

  "Temporal neocortical",

  "Frontal",

  "Parietal",

  "Occipital",

  "Insula",

  "Thalamus: Anterior nucleus",

  "Thalamus: Centromedian",

  "Thalamus: Pulvinar",

  "Vagus Nerve",

  "Other",

  "N/A",

];

const THALAMIC_NUCLEI = [

  "Anterior nucleus",

  "Centromedian nucleus",

  "Pulvinar",

  "Mediodorsal nucleus (MD)",

  "Other",

  "Unknown",

];

const initialMetadata = {

  patientId: "001",

  recordingId: "001",

  clinicalAssessmentId: "003",

  surgeryId: "001",

  modality: "Scalp EEG",

  purpose: ["Presurgical evaluation"],

  timing: "Preoperative",

  thalamusRecorded: "No",

  thalamicNuclei: [],

  thalamicLaterality: "Left",

  stimulationAssessment: "No",

  nonThalamicStimulation: "No",

  duration: "24",

  seizuresCaptured: "3",

  localization: ["Medial temporal"],

  comments: "",

};

export default function EphysDemo() {

  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState(1);
  const [finderMode, setFinderMode] = useState(null);
  const [finderFolderOpen, setFinderFolderOpen] = useState(false);
  const [selectedSource, setSelectedSource] = useState("");
  const [derivativesFolder, setDerivativesFolder] = useState("");
  const [finalFolder, setFinalFolder] = useState("");
  const [outputFinderKind, setOutputFinderKind] = useState(null);
  const [folderSettingsSaved, setFolderSettingsSaved] = useState(false);
  const [rawAnnotations] = useState([{ onset: 0, duration: 4, description: "Recording start" }, { onset: 320, duration: 8, description: "Jamie Example seizure event" }]);
  const [scrubbedAnnotations, setScrubbedAnnotations] = useState([{ onset: 0, duration: 4, description: "Recording start" }, { onset: 320, duration: 8, description: "[removed] seizure event" }]);
  const [annotationsSaved, setAnnotationsSaved] = useState(false);
  const [sidecarText, setSidecarText] = useState(() => JSON.stringify({PatientID:"001",RecordingID:"001",Modality:"EEG",SamplingFrequency:256,RecordingDuration:600,Comments:"John Doe - synthetic EEG recording"},null,2));
  const [savedSidecar, setSavedSidecar] = useState(null);
  const [sidecarError, setSidecarError] = useState("");
  const [annotationCursor, setAnnotationCursor] = useState(315);
  const [viewerExplored, setViewerExplored] = useState(false);
  const [annotationAdded, setAnnotationAdded] = useState(false);
  const [reviewStatus, setReviewStatus] = useState("Pending");
  const [project, setProject] = useState("CoCANoT Phase 1");
  const [sessionId, setSessionId] = useState("01");
  const [projectDescription, setProjectDescription] = useState("Synthetic public demonstration");
  const [tutorialPhase, setTutorialPhase] = useState("overview");
  const [tutorialStartedSteps, setTutorialStartedSteps] = useState(() => location.state?.tutorialChoice === "yes" ? {1:true} : {});
  const [tutorialRestartKey, setTutorialRestartKey] = useState(0);
  const [wrapUpAcknowledged, setWrapUpAcknowledged] = useState({});
  const [linkedTutorialStarted, setLinkedTutorialStarted] = useState(false);
  const [linkedTutorialActive, setLinkedTutorialActive] = useState(false);
  const [linkedExploring, setLinkedExploring] = useState(false);
  const [linkedTutorialKey, setLinkedTutorialKey] = useState(0);

  const [selected, setSelected] = useState(false);
  const [selectedDataExpanded, setSelectedDataExpanded] = useState(false);

  const [scrub, setScrub] = useState("not_started");

  const [reviewed, setReviewed] = useState(false);

  const [metadata, setMetadata] = useState(initialMetadata);

  const [metadataSaved, setMetadataSaved] = useState(false);

  const [exported, setExported] = useState(false);

  const [tutorialEnabled, setTutorialEnabled] = useState(location.state?.tutorialChoice === "yes");

  const [showLinkedRecord, setShowLinkedRecord] = useState(false);

  const [linkedRecordVisited, setLinkedRecordVisited] = useState(false);

  const [scrubbedHeader, setScrubbedHeader] = useState(INITIAL_SCRUBBED_HEADER);

  const [editingMissedValue, setEditingMissedValue] = useState(false);

  const [missedValueDraft, setMissedValueDraft] = useState("Follow-up EEG for Jamie Example");

  const [missedValueFixed, setMissedValueFixed] = useState(false);

  const [reviewFocus, setReviewFocus] = useState("difference");

  const complete = [selected, folderSettingsSaved, scrub === "complete", reviewed, exported];

  // Wait at the end of the guided actions before pointing to the next-step button.
  // Choosing to explore dismisses guidance only for this step; it resumes on navigation.
  const stepActionsFinished = step === 1 ? selected
    : step === 2 ? folderSettingsSaved
    : step === 3 ? scrub === "complete"
    : step === 4 ? reviewed
    : step === 5 ? exported
    : false;

  const tutorial = useMemo(() => {

    if (step === 1 && !selected) {

      return {

        target: "ephys-choose-files",

        title: "Choose an EDF recording",

        text: "Open the simulated Finder and choose the synthetic EDF file, or select its folder.",

      };

    }

    if (step === 1 && selected && !selectedDataExpanded) return {target:"ephys-view-selected-data",title:"View the selected recording",text:"Click View Selected Data to expand the list and confirm which EDF recording was selected."};

    if (step === 1 && selected) {

      return {

        target: "ephys-continue-1",

        title: "Move to output folders",

        text: "The recording is selected. Continue to the next step.",

      };

    }

    if (step === 2) {
      if (!derivativesFolder) return {
        target: "ephys-output-browse",
        title: "Choose the derivatives folder",
        text: "Click Browse, choose ephys_derivatives in the simulated folder picker, and confirm.",
      };
      if (!finalFolder) return {
        target: "ephys-final-browse",
        title: "Choose the final output folder",
        text: "Select the final BIDS-compatible output location using Browse.",
      };
      if (!folderSettingsSaved) return {
        target: "ephys-save-folder-settings",
        title: "Save the selected output folders",
        text: "Save both folders before continuing to processing.",
      };
      return {
        target: "ephys-continue-process",
        title: "Continue to processing",
        text: "Both output locations are saved. Continue to scrub the EDF recording.",
      };
    }

    if (step === 3 && scrub !== "complete") {

      return {

        target: "ephys-scrub",

        title: "Scrub the header",

        text: "Run the de-identification step to create the simulated scrubbed header.",

      };

    }

    if (step === 3) {

      return {

        target: "ephys-continue-review",

        title: "Review the header changes",

        text: "The scrub is complete. Continue to the side-by-side header review.",

      };

    }

    if (step === 4 && !missedValueFixed) {
      return {
        target: "ephys-missed-header",
        title: "Review and correct the missed header value",
        text: editingMissedValue
          ? "Edit the synthetic identifying text, then click Save."
          : "Compare raw and scrubbed headers, then select Edit missed value in the recording_notes row.",
      };
    }
    if (step === 4 && !viewerExplored) return {target:"ephys-training-signal",title:"Explore the EEG recording",text:"Navigate the 10-second EEG windows, then click a waveform to automatically create an annotation at that time. The marker appears on the recording and in the editor below."};
    if (step === 4 && !annotationAdded) return {target:"ephys-training-signal",title:"Add an annotation on the recording",text:"Click directly on the synthetic EEG waveform to create an annotation at that time. The event appears automatically below, where you can edit its start, duration, and comment."};
    if (step === 4 && !reviewed) {
      return {
        target: "ephys-review-accept",
        title: "Accept the corrected EDF",
        text: "Once the missed header value is corrected, accept the de-identified recording.",
      };
    }
    if (step === 4 && !savedSidecar) {
      let hasRemovedName = false;
      try {
        const data = JSON.parse(sidecarText);
        hasRemovedName = typeof data?.Comments === "string" && data.Comments.trim() !== "" && !/john\s+doe/i.test(data.Comments);
      } catch (_) { /* Show editing instruction until JSON is valid. */ }
      return hasRemovedName
        ? { target: "ephys-step4-save-json", title: "Save the corrected JSON metadata", text: "You removed John Doe from Comments. Click Save JSON Metadata to validate and save the synthetic EDF sidecar before continuing." }
        : { target: "ephys-step4-json-editor", title: "Remove patient information from linked metadata", text: "Privacy reminder: the JSON metadata Comments field contains the patient name John Doe. Delete John Doe from Comments with your keyboard, keep a non-identifying description and valid JSON, and then click Save JSON Metadata." };
    }
    if (step === 4) {
      return {
        target: "ephys-accept",
        title: "Continue to metadata",
        text: "Before continuing, confirm that you removed John Doe from the linked JSON Comments field and saved your changes. Then continue to Step 5.",
      };
    }

    if (step === 5 && !metadataSaved) {

      return {

        target: "ephys-save-metadata",

        title: "Complete CoCANoT electrophysiology metadata",

        text: "Review and edit the CoCANoT fields and dataset information above, then click Save Metadata to continue.",

      };

    }

    if (step === 5 && metadataSaved && !exported) {

      return {

        target: "ephys-export",

        title: "Create the standardized output",

        text: "The CoCANoT metadata is saved. Now simulate creating the linked BIDS-compatible output.",

      };

    }

    if (step === 5 && exported && !showLinkedRecord && !linkedRecordVisited) {

      return {

        target: "ephys-view-linked",

        title: "Explore the linked patient record",

        text: "Open Patient Data Review to explore the synthetic electrophysiology signal and its saved metadata.",

      };

    }

    return null;

  }, [

    step,

    selected,
    selectedDataExpanded,
    derivativesFolder,
    finalFolder,
    folderSettingsSaved,
    editingMissedValue,
    reviewed,
    scrub,

    missedValueFixed,
    viewerExplored,
    annotationAdded,
    savedSidecar,
    sidecarText,

    reviewFocus,

    metadataSaved,

    exported,

    showLinkedRecord,

    linkedRecordVisited,

  ]);

  function remember(patch) {

    saveDemoState({

      ephys: {

        step,

        selected,

        scrub,

        reviewed,

        metadataSaved,

        exported,

        ...patch,

      },

    });

  }

  function go(next) {

    // Keep guidance active when advancing or returning to another step.
    setTutorialPhase("overview");
    if (tutorialEnabled) setTutorialStartedSteps(current => ({ ...current, [next]: true }));
    setStep(next);

    remember({ step: next });


  }

  async function runScrub() {

    setScrub("running");

    remember({ scrub: "running" });

    await new Promise((resolve) => setTimeout(resolve, 900));

    setScrub("complete");

    remember({ scrub: "complete" });

  }

  function saveMissedHeaderValue() {

    setScrubbedHeader((current) =>

      current.map(([key, value]) =>

        key === "recording_notes"

          ? [key, missedValueDraft.trim() || "[removed]"]

          : [key, value]

      )

    );

    setEditingMissedValue(false);

    setMissedValueFixed(true);

  }

  function setField(field, value) {

    setMetadata((current) => ({ ...current, [field]: value }));

    setMetadataSaved(false);

    setExported(false);

  }

  function toggleMulti(field, value) {

    setMetadata((current) => {

      const currentValues = current[field] ?? [];

      if (currentValues.includes(value)) {

        return {

          ...current,

          [field]: currentValues.filter((item) => item !== value),

        };

      }

      if (value === "Unknown" || value === "N/A") {

        return { ...current, [field]: [value] };

      }

      return {

        ...current,

        [field]: currentValues

          .filter((item) => item !== "Unknown" && item !== "N/A")

          .concat(value),

      };

    });

    setMetadataSaved(false);

    setExported(false);

  }

  function reset() {

    resetDemoState();

    setStep(1);

    setSelected(false);
    setSelectedSource(""); setFinderMode(null); setFinderFolderOpen(false);
    setDerivativesFolder(""); setFinalFolder(""); setOutputFinderKind(null);
    setFolderSettingsSaved(false);
    setScrubbedAnnotations([{ onset: 0, duration: 4, description: "Recording start" }, { onset: 320, duration: 8, description: "[removed] seizure event" }]);
    setAnnotationsSaved(false); setReviewStatus("Pending");
    setProject("CoCANoT Phase 1"); setSessionId("01"); setProjectDescription("Synthetic public demonstration");
    setTutorialPhase("overview"); setTutorialStartedSteps(location.state?.tutorialChoice === "yes" ? {1:true} : {}); setTutorialRestartKey(0); setWrapUpAcknowledged({});
    setLinkedTutorialStarted(false); setLinkedTutorialActive(false); setLinkedExploring(false); setLinkedTutorialKey(0);

    setScrub("not_started");

    setReviewed(false);

    setMetadata(initialMetadata);

    setMetadataSaved(false);

    setExported(false);

    setTutorialEnabled(location.state?.tutorialChoice === "yes");

    setShowLinkedRecord(false);

    setLinkedRecordVisited(false);

    setScrubbedHeader(INITIAL_SCRUBBED_HEADER);

    setEditingMissedValue(false);

    setMissedValueDraft("Follow-up EEG for Jamie Example");

    setMissedValueFixed(false);

    setReviewFocus("difference");

  }

  return (
    <div className="ephys-public-demo">
      <nav className="mb-5 flex flex-wrap items-center justify-between gap-3" aria-label="Demo navigation">
        <button type="button" onClick={() => window.dispatchEvent(new Event("atlas-training-back"))} className="inline-flex items-center gap-2 text-sm font-semibold text-navy hover:underline"><ArrowLeft size={16}/> Back to Site Training</button>
        <button type="button" onClick={reset} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50">Reset Demo</button>
      </nav>
      <header className="ephys-page-heading mb-6 px-1 md:mb-8">
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-navy md:text-4xl">Process Recordings</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600 md:text-base">A guided public version of the CoCANoT electrophysiology workflow.</p>
      </header>
      <style>{EPHYS_PUBLIC_CSS}</style>
      {finderMode && <EphysFakeFinder guided={tutorialEnabled && tutorialPhase === "spotlight" && Boolean(tutorialStartedSteps[1])} mode={finderMode} folderOpen={finderFolderOpen} onFolderOpen={() => setFinderFolderOpen(true)} onBack={() => setFinderFolderOpen(false)} onClose={() => {setFinderMode(null); setFinderFolderOpen(false);}} onChoose={(kind) => {setSelected(true);setSelectedSource(kind === "file" ? "demoData/electrophysiology/sampleRecording.edf" : "demoData/electrophysiology/");setFinderMode(null);setFinderFolderOpen(false);remember({selected:true});}} />}
      {outputFinderKind && <EphysOutputFinder guided={tutorialEnabled && tutorialPhase === "spotlight" && Boolean(tutorialStartedSteps[2])} kind={outputFinderKind} onClose={() => setOutputFinderKind(null)} onChoose={(folder) => {if(outputFinderKind === "derivatives") setDerivativesFolder(`/demo/${folder}`);else setFinalFolder(`/demo/${folder}`);setFolderSettingsSaved(false);setOutputFinderKind(null);}} />}
    {showLinkedRecord ? (
      <div className="ephys-linked-public-review">
        <section className="mb-5 rounded-xl border border-sky-200 bg-white px-5 py-4 shadow-sm md:px-6" aria-label="Linked recording review introduction">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-navy/60">{linkedTutorialStarted && !linkedTutorialActive && !linkedExploring ? "GUIDE · LINKED RECORDING REVIEW" : "LINKED RECORDING"}</p>
          <h2 className="mt-2 font-serif text-2xl text-navy">Review Linked Recording</h2>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-700 md:text-base">{linkedTutorialStarted && !linkedTutorialActive && !linkedExploring ? "This is the linked recording review, where you can inspect the processed EDF signal and its associated CoCANoT metadata. Click Next to see the recording viewer and its controls." : "Explore the processed recording and its linked CoCANoT metadata. Use the interactive controls to review the synthetic recording."}</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button type="button" className="rounded-full bg-navy px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90" onClick={() => {setTutorialEnabled(true);setLinkedTutorialStarted(true);setLinkedExploring(false);if(linkedTutorialStarted && !linkedTutorialActive && !linkedExploring){setLinkedTutorialActive(true);}else{setLinkedTutorialActive(false);}setLinkedTutorialKey(key => key + 1);}}>
              {linkedTutorialStarted && !linkedTutorialActive && !linkedExploring ? "Next →" : linkedTutorialStarted ? "Restart tutorial" : "Show me how →"}
            </button>
            {linkedTutorialStarted && <button type="button" className="rounded-full px-4 py-2.5 text-sm font-semibold text-navy/70 hover:bg-slate-100" onClick={() => {setTutorialEnabled(false);setTutorialPhase("overview");setLinkedTutorialActive(false);setLinkedTutorialStarted(false);}}>Skip tutorial</button>}
          </div>
        </section>
        {tutorialEnabled && linkedTutorialStarted && !linkedTutorialActive && !linkedExploring && (
          <GuideOverview linked onNext={() => {setLinkedTutorialActive(true);setLinkedExploring(false);setLinkedTutorialKey(key => key + 1);}} onExplore={() => {setLinkedExploring(true);setLinkedTutorialActive(false);}} onSkip={() => {setTutorialEnabled(false);setLinkedTutorialActive(false);setLinkedTutorialStarted(false);}} />
        )}
        
        <div data-tutorial-id="ephys-linked-review-content" className={tutorialEnabled && linkedTutorialStarted && !linkedTutorialActive && !linkedExploring ? "ephys-guide-focus-step" : ""}>
          <LinkedPatientPreview type="ephys" linkedMetadata={metadata} savedEphysReview={{rawHeader:RAW_HEADER,scrubbedHeader,rawAnnotations,scrubbedAnnotations,sidecar:savedSidecar,reviewStatus}} onSaveLinkedMetadata={(next) => {setMetadata(next); setMetadataSaved(true);}} startViewerTour={linkedTutorialActive} onViewerTourExit={() => setLinkedTutorialActive(false)} onBack={() => {setShowLinkedRecord(false);setLinkedTutorialActive(false);setLinkedTutorialStarted(false);}} />
        </div>
      </div>
      ) : (

        <>

          <StepIntroduction step={step} started={tutorialEnabled && Boolean(tutorialStartedSteps[step])} previewing={tutorialEnabled && tutorialPhase === "overview"} onShowHow={() => {setTutorialEnabled(true);setTutorialPhase("spotlight");setTutorialStartedSteps(current=>({...current,[step]:true}));setTutorialRestartKey(current=>current+1);}} onSkip={() => {setTutorialEnabled(false);setTutorialPhase("overview");setTutorialStartedSteps({});setLinkedTutorialActive(false);setLinkedTutorialStarted(false);}} />
          {tutorialEnabled && tutorialPhase === "overview" && Boolean(tutorialStartedSteps[step]) && (
            <GuideOverview step={step} onNext={() => {setTutorialPhase("spotlight");setTutorialRestartKey(current => current + 1);}} onSkip={() => {setTutorialEnabled(false);setTutorialPhase("overview");setTutorialStartedSteps({});setLinkedTutorialActive(false);setLinkedTutorialStarted(false);}} />
          )}
          {tutorialEnabled && tutorialPhase === "spotlight" && stepActionsFinished && !wrapUpAcknowledged[step] && !finderMode && !outputFinderKind && (
            <SpotlightExploreLink
              guideTitle={tutorial?.title}
              onExplore={() => {
                setWrapUpAcknowledged(current => ({ ...current, [step]: true }));
                setTutorialPhase("explore");
              }}
            />
          )}
          <TutorialSpotlight key={`${step}-${tutorialRestartKey}`} enabled={tutorialEnabled && tutorialPhase === "spotlight" && Boolean(tutorial) && !finderMode && !outputFinderKind} target={tutorial?.target} title={tutorial?.title} text={tutorial?.text} step={step} totalSteps={5} onSkip={() => {setTutorialPhase("overview");}} />
          <div className={styles.workflow}>

            <div className={styles.stepper}>

              {labels.map((label, index) => (

                <div

                  key={label}

                  className={`${styles.step} ${

                    step === index + 1 ? styles.active : ""

                  } ${complete[index] ? styles.done : ""}`}

                >

                  <strong>{complete[index] ? "✓" : index + 1}</strong>

                  <span>{label}</span>

                </div>

              ))}

            </div>

            {step === 1 && (
              <section className={`ephys-step-card ${tutorialEnabled && tutorialPhase === "overview" ? "ephys-guide-focus-step" : ""}` }>
                <EphysSectionHeader number={1} title="Select recordings" subtitle="Add EDF files and/or folders to include in this session." />
                <div className="ephys-step-body">
                  <div className="ephys-upload-card">
                    <div className="ephys-upload-icon"><Upload size={27}/></div>
                    <div><strong>Add EDF files or folders</strong><p>Select EDF files or a directory containing electrophysiology recordings.</p>
                      <div className="ephys-upload-actions">
                        <button data-tutorial-id="ephys-choose-files" className="ephys-primary" onClick={() => setFinderMode("file")}>Choose Files…</button>
                        <button className="ephys-secondary" onClick={() => setFinderMode("folder")}>Choose Folder…</button>
                      </div>
                    </div>
                  </div>
                  <div className="ephys-selection-summary"><Database size={26}/><div><strong>Selected data</strong><span>{selected ? "1 source · 1 EDF file selected" : "0 sources · 0 EDF files selected"}</span></div><details onToggle={event=>setSelectedDataExpanded(event.currentTarget.open)}><summary data-tutorial-id="ephys-view-selected-data">View Selected Data</summary><div className="ephys-selected-details">{selected ? <label><input type="checkbox" checked={selected} onChange={event => setSelected(event.target.checked)}/> {selectedSource} · sampleRecording.edf</label> : "No recordings selected."}</div></details></div>
                  <div className="ephys-actions"><button className="ephys-primary" data-tutorial-id="ephys-continue-1" disabled={!selected} onClick={()=>go(2)}>Continue to Output Folders →</button></div>
                </div>
              </section>
            )}

            {step === 2 && (
              <section className={`ephys-step-card ${tutorialEnabled && tutorialPhase === "overview" ? "ephys-guide-focus-step" : ""}` }>
                <EphysSectionHeader number={2} title="Set output folders" subtitle="Choose where to save the derivatives and final BIDS-compatible recordings." />
                <div className="ephys-step-body">
                  <div className="ephys-folder-stack">
                    <label className="ephys-folder-field" data-tutorial-id="ephys-output-browse"><span>Derivatives output folder</span><div><input value={derivativesFolder} onChange={e=>{setDerivativesFolder(e.target.value);setFolderSettingsSaved(false);}} placeholder="Select an output folder"/><button onClick={()=>setOutputFinderKind("derivatives")}><FolderOpen size={16}/> Browse…</button></div></label>
                    <p className="ephys-info-strip">The derivatives folder contains staged recordings, scrubbed EDFs, review files, and processing logs.</p>
                    <label className="ephys-folder-field" data-tutorial-id="ephys-final-browse"><span>Final output folder</span><div><input value={finalFolder} onChange={e=>{setFinalFolder(e.target.value);setFolderSettingsSaved(false);}} placeholder="Select an output folder"/><button onClick={()=>setOutputFinderKind("final")}><FolderOpen size={16}/> Browse…</button></div></label>
                    <p className="ephys-info-strip">Accepted, de-identified recordings and their CoCANoT metadata are exported here in a BIDS-compatible structure.</p>
                  </div>
                  {folderSettingsSaved && <p className="ephys-success">✓ Output folder settings saved for this demonstration.</p>}
                  <div className="ephys-actions ephys-actions-between"><button className="ephys-secondary" onClick={()=>go(1)}>Back</button><div><button data-tutorial-id="ephys-save-folder-settings" className="ephys-secondary" disabled={!derivativesFolder||!finalFolder} onClick={()=>setFolderSettingsSaved(true)}><Save size={15}/> Save Folder Settings</button><button data-tutorial-id="ephys-continue-process" className="ephys-primary" disabled={!folderSettingsSaved} onClick={()=>go(3)}>Continue to Process →</button></div></div>
                </div>
              </section>
            )}

            {step === 3 && (

              <section className={`${styles.card} ${tutorialEnabled && tutorialPhase === "overview" ? "ephys-guide-focus-step" : ""}`}>

                <div className={styles.cardHeader}>

                  <div className={styles.number}>3</div>

                  <div>

                    <strong>Process recordings</strong>

                    <span>Scrub identifying information from the synthetic EDF header.</span>

                  </div>

                </div>

                <div className={styles.body}>

                  <div className={styles.processGrid}>

                    <button

                      data-tutorial-id="ephys-scrub"

                      className={styles.processButton}

                      disabled={scrub === "running"}

                      onClick={runScrub}

                    >

                      <span>3A</span>

                      <strong>Scrub Included EDFs</strong>

                      <small>Create a simulated de-identified EDF header.</small>

                      <em>

                        {scrub === "complete"

                          ? "Complete ✓"

                          : scrub === "running"

                            ? "Processing..."

                            : "Not started"}

                      </em>

                    </button>

                  </div>

                  <div className={styles.actions}>

                    <button className={styles.secondary} onClick={() => go(2)}>Back</button>

                    <button

                      data-tutorial-id="ephys-continue-review"

                      className={styles.primary}

                      disabled={scrub !== "complete"}

                      onClick={() => go(4)}

                    >

                      Continue to Review

                    </button>

                  </div>

                </div>

              </section>

            )}

            {step === 4 && (

              <section className={`${styles.card} ${tutorialEnabled && tutorialPhase === "overview" ? "ephys-guide-focus-step" : ""}`}>

                <div className={styles.cardHeader}>

                  <div className={styles.number}>4</div>

                  <div>

                    <strong>Review de-identification</strong>

                    <span>Compare raw and scrubbed header values before accepting the recording.</span>

                  </div>

                </div>

                <div className={styles.body}>

                  <div

                    data-tutorial-id="ephys-header-differences"

                    className={styles.headerComparison}

                  >

                    <div className={styles.headerComparisonTitle}>

                      <strong>Raw vs. scrubbed EDF header</strong>

                      <span>

                        Changed values are highlighted. One synthetic value was intentionally left behind for review.

                      </span>

                    </div>

                    <div className={styles.headerComparisonGrid}>

                      <div className={styles.headerColumnHeader}>Raw header</div>

                      <div className={styles.headerColumnHeader}>Scrubbed header</div>

                      {RAW_HEADER.map(([key, rawValue], index) => {

                        const scrubbedValue = scrubbedHeader[index]?.[1] ?? "";

                        const changed = rawValue !== scrubbedValue;

                        const missed = key === "recording_notes";

                        return (

                          <div

                            key={key}

                            className={`${styles.headerComparisonRow} ${

                              changed ? styles.headerChanged : ""

                            } ${missed ? styles.headerMissed : ""}`}

                          >

                            <div className={styles.headerCell}>

                              <span>{key}</span>

                              <strong>{rawValue}</strong>

                            </div>

                            <div

                              className={styles.headerCell}

                              data-tutorial-id={missed ? "ephys-missed-header" : undefined}

                            >

                              <span>{key}</span>

                              {missed && editingMissedValue ? (

                                <div className={styles.headerEditRow}>

                                  <input

                                    value={missedValueDraft}

                                    onChange={(event) => setMissedValueDraft(event.target.value)}

                                  />

                                  <button

                                    className={styles.headerSaveButton}

                                    onClick={saveMissedHeaderValue}

                                  >

                                    Save

                                  </button>

                                </div>

                              ) : (

                                <>

                                  <strong>{scrubbedValue}</strong>

                                  {missed && !missedValueFixed && (

                                    <button

                                      className={styles.headerEditButton}

                                      onClick={() => {

                                        setMissedValueDraft("Follow-up EEG for Jamie Example");

                                        setEditingMissedValue(true);

                                      }}

                                    >

                                      Edit missed value

                                    </button>

                                  )}

                                  {missedValueFixed && missed && (

                                    <small className={styles.fixedLabel}>

                                      Corrected during review ✓

                                    </small>

                                  )}

                                </>

                              )}

                            </div>

                          </div>

                        );

                      })}

                    </div>

                  </div>

                  <div className="ephys-annotation-review">
                    <div style={{padding:"16px 18px 5px"}}>
                      <h3 style={{margin:"0 0 8px",fontSize:18,color:"#214b6b"}}>EDF recording · Visual annotation placement</h3>
                      <p style={{fontSize:13,color:"#53728b",margin:"0 0 10px"}}>Click the EEG waveform to add an annotation immediately. Orange markers appear on the recording, and new annotations appear in the editor below.</p>
                      <EphysTrainingSignalViewer
                        annotations={scrubbedAnnotations}
                        onChooseTime={value=>{setAnnotationCursor(value);setViewerExplored(true);setScrubbedAnnotations(current=>[...current,{onset:value,duration:0,description:"New event"}]);setAnnotationsSaved(false);setAnnotationAdded(true);}}
                        onChangeWindow={()=>setViewerExplored(true)}
                      />
                    </div>
                    <div className="ephys-annotation-heading"><div><strong>Annotations</strong><p>Click the waveform above to add an annotation automatically. Edit its start time, duration, or comment below; the waveform updates with the event.</p></div><button className="ephys-secondary" onClick={()=>setAnnotationsSaved(true)}><Save size={15}/> Save Scrubbed EDF</button></div>
                    <div className="ephys-annotation-grid"><div><h3>Raw EDF annotations</h3><div className="ephys-annotation-column-labels"><span>Start time (seconds)</span><span>Duration (seconds)</span><span>Comments</span></div>{rawAnnotations.map((row,i)=><div className="ephys-raw-annotation" key={i}><span>{row.onset}s</span><span>{row.duration}s</span><span>{row.description}</span></div>)}</div>
                      <div><div className="ephys-annotation-heading"><h3>Scrubbed EDF annotations</h3><button data-tutorial-id="ephys-training-add-annotation" className="ephys-secondary" onClick={()=>{setScrubbedAnnotations(v=>[...v,{onset:annotationCursor,duration:0,description:"New event"}]);setAnnotationsSaved(false);setAnnotationAdded(true);}}>Add</button></div><div className="ephys-annotation-column-labels ephys-edit-labels"><span>Start time (seconds)</span><span>Duration (seconds)</span><span>Comments</span><span>Action</span></div>{scrubbedAnnotations.map((row,i)=><div className="ephys-edit-annotation" key={i}><input aria-label="Start time (seconds)" type="number" value={row.onset} onChange={e=>{setScrubbedAnnotations(v=>v.map((r,j)=>j===i?{...r,onset:+e.target.value}:r));setAnnotationsSaved(false);}}/><input aria-label="Duration (seconds)" type="number" value={row.duration} onChange={e=>{setScrubbedAnnotations(v=>v.map((r,j)=>j===i?{...r,duration:+e.target.value}:r));setAnnotationsSaved(false);}}/><input aria-label="Annotation comments" value={row.description} onChange={e=>{setScrubbedAnnotations(v=>v.map((r,j)=>j===i?{...r,description:e.target.value}:r));setAnnotationsSaved(false);}}/><button className="ephys-secondary" onClick={()=>{setScrubbedAnnotations(v=>v.filter((_,j)=>i!==j));setAnnotationsSaved(false);}}>Remove</button></div>)}</div>
                    </div>{annotationsSaved && <p className="ephys-success">✓ Scrubbed EDF edits saved in this demonstration.</p>}
                  </div>
                  <section style={{marginTop:18,padding:18,border:"1px solid #c9dce9",borderRadius:11,background:"#fff"}}>
                    <h3 style={{fontSize:17,fontWeight:750,margin:"0 0 5px",color:"#234863"}}>Linked EDF JSON metadata · Step 4</h3>
                    <p style={{fontSize:13,color:"#60788b",margin:"0 0 12px"}}>Synthetic sidecar: sub-001_task-rest_eeg.json. Remove the identifying name John Doe from Comments, then save valid JSON. The original recording is not changed.</p>
                    <textarea data-tutorial-id="ephys-step4-json-editor" aria-label="Edit synthetic EDF JSON metadata" value={sidecarText} onChange={event=>{setSidecarText(event.target.value);setSavedSidecar(null);setSidecarError("");}} spellCheck={false} rows={12} style={{display:"block",width:"100%",boxSizing:"border-box",padding:13,fontFamily:"ui-monospace,monospace",fontSize:13,lineHeight:1.6,border:"1px solid #afc6d6",borderRadius:8,color:"#243d52",background:"#f8fbfe"}}/>
                    <button type="button" data-tutorial-id="ephys-step4-save-json" className="ephys-secondary" style={{marginTop:12}} onClick={()=>{
                      try{const data=JSON.parse(sidecarText);
                        if(!data||typeof data!=="object"||Array.isArray(data))throw Error("The sidecar must be a JSON object.");
                        if(data.PatientID!=="001"||data.RecordingID!=="001")throw Error("Preserve PatientID and RecordingID.");
                        if(typeof data.Comments!=="string"||!data.Comments.trim()||/john\s+doe/i.test(data.Comments))throw Error("Remove John Doe from the Comments field before saving.");
                        setSavedSidecar(data);setSidecarText(JSON.stringify(data,null,2));setSidecarError("");
                      }catch(error){setSavedSidecar(null);setSidecarError(error.message||String(error));}
                    }}>Save JSON Metadata</button>
                    {sidecarError&&<p role="alert" style={{color:"#a93431",marginTop:9}}>{sidecarError}</p>}
                    {savedSidecar&&<p role="status" style={{color:"#21784e",marginTop:9}}>✓ Synthetic JSON metadata saved.</p>}
                  </section>
                  <div className="ephys-review-decision"><span>Review status: <strong>{reviewStatus}</strong></span><button className="ephys-secondary" onClick={()=>{setReviewStatus("Rejected - Not Included");setReviewed(false);}}>Reject & Exclude</button><button data-tutorial-id="ephys-review-accept" className="ephys-primary" disabled={!missedValueFixed} onClick={()=>{setReviewStatus("Accepted");setReviewed(true);remember({reviewed:true});}}>Accept</button></div>
                  <div className={styles.actions}>

                    <button className={styles.secondary} onClick={() => go(3)}>Back</button>

                    <button

                      data-tutorial-id="ephys-accept"

                      className={styles.primary}

                      disabled={!reviewed || !savedSidecar}

                      onClick={() => {

                        setReviewed(true);

                        remember({ reviewed: true });

                        go(5);

                      }}

                    >

                      Continue to Step 5: Metadata & BIDS

                    </button>

                  </div>

                </div>

              </section>

            )}

            {step === 5 && (

              <section className={`${styles.card} ${tutorialEnabled && tutorialPhase === "overview" ? "ephys-guide-focus-step" : ""}`}>

                <div className={styles.cardHeader}>

                  <div className={styles.number}>5</div>

                  <div>

                    <strong>Metadata & BIDS</strong>

                    <span>

                      Complete the CoCANoT Electrophysiology metadata, then create the standardized output.

                    </span>

                  </div>

                </div>

                <div className={styles.body}>

                  <div className={styles.metadataIntro}>

                    <strong>CoCANoT Electrophysiology Metadata</strong>

                    <p>

                      These fields mirror the Phase 1.0 Electrophysiology metadata dictionary. Required fields are marked with an asterisk. Clinical Assessment ID is system-generated and shown as read-only. Conditional fields appear when they apply.

                    </p>

                  </div>

                  <div

                    data-tutorial-id="ephys-metadata-editor"

                    className={styles.metadataEditor}

                  >

                    <div className={styles.metadataGrid}>

                      <TextField

                        label="CoCANoT Patient ID *"

                        value={metadata.patientId}

                        onChange={(value) => setField("patientId", value)}

                      />

                      <TextField

                        label="Recording ID *"

                        value={metadata.recordingId}

                        onChange={(value) => setField("recordingId", value)}

                      />

                      <TextField

                        label="Clinical Assessment ID *"

                        value={metadata.clinicalAssessmentId}

                        readOnly

                        help="System-generated"

                      />

                      <TextField

                        label="Surgery ID"

                        value={metadata.surgeryId}

                        onChange={(value) => setField("surgeryId", value)}

                      />

                      <SelectField

                        label="Recording Modality *"

                        value={metadata.modality}

                        options={[

                          "Scalp EEG",

                          "Stereo EEG (SEEG)",

                          "Subdural grid",

                          "Subdural strips",

                          "Depth electrodes (not SEEG)",

                          "Intraoperative electrocorticography (ECoG)",

                          "Magnetoencephalography (MEG)",

                          "Other",

                          "Unknown",

                        ]}

                        onChange={(value) => setField("modality", value)}

                      />

                      <SelectField

                        label="Timing Relative to Surgery *"

                        value={metadata.timing}

                        options={[

                          "Preoperative",

                          "Intraoperative",

                          "Immediate Postoperative (<30 days after surgery)",

                          "Follow-up (>30 days after surgery)",

                        ]}

                        onChange={(value) => setField("timing", value)}

                      />

                      <SelectField

                        label="Thalamus Recorded *"

                        value={metadata.thalamusRecorded}

                        options={["Yes", "No"]}

                        onChange={(value) => setField("thalamusRecorded", value)}

                      />

                      <SelectField

                        label="Thalamic Stimulation / Evoked Potential Assessment Performed *"

                        value={metadata.stimulationAssessment}

                        options={["Yes", "No", "Unknown"]}

                        onChange={(value) => setField("stimulationAssessment", value)}

                      />

                      <SelectField

                        label="Non-thalamic Brain Stimulation for Seizure Elicitation Performed *"

                        value={metadata.nonThalamicStimulation}

                        options={["Yes", "No", "Unknown"]}

                        onChange={(value) => setField("nonThalamicStimulation", value)}

                      />

                      <TextField

                        label="Recording Duration (hours) *"

                        value={metadata.duration}

                        type="number"

                        onChange={(value) => setField("duration", value)}

                      />

                      <TextField

                        label="Number of Seizures Captured *"

                        value={metadata.seizuresCaptured}

                        type="number"

                        onChange={(value) => setField("seizuresCaptured", value)}

                      />

                    </div>

                    <MultiSelectField

                      label="Purpose of Recording *"

                      values={metadata.purpose}

                      options={PURPOSE_OPTIONS}

                      onToggle={(value) => toggleMulti("purpose", value)}

                    />

                    {metadata.thalamusRecorded === "Yes" && (

                      <div className={styles.conditionalMetadataBlock}>

                        <div>

                          <strong>Conditional thalamic recording fields</strong>

                          <span>Shown because Thalamus Recorded is set to Yes.</span>

                        </div>

                        <MultiSelectField

                          label="Thalamic Nuclei Recorded"

                          values={metadata.thalamicNuclei}

                          options={THALAMIC_NUCLEI}

                          onToggle={(value) => toggleMulti("thalamicNuclei", value)}

                        />

                        <SelectField

                          label="Thalamic Recording Laterality"

                          value={metadata.thalamicLaterality}

                          options={["Left", "Right", "Bilateral"]}

                          onChange={(value) => setField("thalamicLaterality", value)}

                        />

                      </div>

                    )}

                    <MultiSelectField

                      label="Primary Seizure Onset Localization *"

                      values={metadata.localization}

                      options={LOCALIZATION_OPTIONS}

                      onToggle={(value) => toggleMulti("localization", value)}

                    />

                    <label className={styles.metadataFieldFull}>

                      <span>Comments</span>

                      <textarea

                        value={metadata.comments}

                        onChange={(event) => setField("comments", event.target.value)}

                        placeholder="Optional notes. Avoid protected health information."

                      />

                    </label>

                    <div className="ephys-dataset"><h3>Dataset Organization</h3><div className="ephys-dataset-grid"><label>Project *<input value={project} onChange={e=>{setProject(e.target.value);setMetadataSaved(false);}}/></label><label>Session ID *<input value={sessionId} onChange={e=>{setSessionId(e.target.value);setMetadataSaved(false);}}/></label><label className="ephys-dataset-full">Project Description<input value={projectDescription} onChange={e=>setProjectDescription(e.target.value)}/></label></div></div>
                    <div className={styles.metadataSaveBar}>

                      <div>

                        <strong>{metadataSaved ? "Metadata saved ✓" : "Unsaved metadata changes"}</strong>

                        <span>

                          The full CoCANoT application validates these values and conditional requirements against the active machine-readable dictionary before export.

                        </span>

                      </div>

                      <button

                        type="button"

                        className={styles.secondary}
                        data-tutorial-id="ephys-save-metadata"
                        onClick={() => setMetadataSaved(true)}
                        disabled={!project.trim() || !sessionId.trim() || !metadata.patientId.trim() || !metadata.recordingId.trim()}

                      >

                        Save Metadata

                      </button>

                    </div>

                  </div>

                  {metadataSaved && (

                    <div className={styles.output}>

                      <strong>Metadata ready for standardized export</strong>

                      <code>sub-001/eeg/sub-001_task-rest_eeg.edf</code>

                      <code>sub-001/eeg/sub-001_task-rest_eeg.json</code>

                    </div>

                  )}

                  <div className={styles.actions}>

                    <button className={styles.secondary} onClick={() => go(4)}>Back</button>

                    {!exported ? (

                      <button

                        data-tutorial-id="ephys-export"

                        className={styles.primary}

                        disabled={!metadataSaved}

                        onClick={() => {

                          setExported(true);
                          remember({ metadataSaved: true, exported: true });

                        }}

                      >

                        Create Demo Output

                      </button>

                    ) : (

                      <button

                        data-tutorial-id="ephys-view-linked"

                        className={styles.primary}

                        onClick={() => {

                          setLinkedRecordVisited(true);

                          // Carry guided mode into linked review, starting with the navy overview.
                          // Visitors exploring independently still see the viewer without an overlay.
                          setLinkedTutorialStarted(tutorialEnabled);
                          setLinkedTutorialActive(false);
                          setLinkedExploring(false);
                          setShowLinkedRecord(true);

                        }}

                      >

                        Next: View Linked Recording

                      </button>

                    )}

                  </div>

                </div>

              </section>

            )}

          </div>

        </>

      )}
    </div>
  );
}

function TextField({ label, value, onChange, readOnly, help, type = "text" }) {

  return (

    <label className={styles.metadataField}>

      <span>{label}</span>

      <input

        type={type}

        value={value}

        readOnly={readOnly}

        onChange={(event) => onChange?.(event.target.value)}

      />

      {help && <small>{help}</small>}

    </label>

  );

}

function SelectField({ label, value, options, onChange }) {

  return (

    <label className={styles.metadataField}>

      <span>{label}</span>

      <select value={value} onChange={(event) => onChange(event.target.value)}>

        {options.map((option) => (

          <option key={option}>{option}</option>

        ))}

      </select>

    </label>

  );

}

function MultiSelectField({ label, values, options, onToggle }) {

  return (

    <fieldset className={styles.metadataMulti}>

      <legend>{label}</legend>

      <div className={styles.metadataChoices}>

        {options.map((option) => (

          <label key={option}>

            <input

              type="checkbox"

              checked={values.includes(option)}

              onChange={() => onToggle(option)}

            />

            <span>{option}</span>

          </label>

        ))}

      </div>

    </fieldset>

  );

}

function EphysSectionHeader({ number, title, subtitle }) {
  return <div className="ephys-section-heading"><span>{number}</span><div><strong>{title}</strong><p>{subtitle}</p></div></div>;
}

function PickerGuidance({ children, direction = "down" }) {
  return <div className={`ephys-picker-guide ephys-picker-guide-${direction}`} role="status">
    <strong>GUIDE · YOUR NEXT ACTION</strong>
    <span>{children}</span>
    <span className="ephys-picker-guide-arrow" aria-hidden="true">{direction === "down" ? "↓" : "↑"}</span>
  </div>;
}

function EphysFakeFinder({ guided, mode, folderOpen, onFolderOpen, onBack, onClose, onChoose }) {
  const isFile = mode === "file";
  return <div className="ephys-modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label="Choose EDF demo data" className="ephys-finder">
      <header><div><h3>{isFile ? "Open EDF recording" : "Select EDF folder"}</h3><p>Simulated Finder · Synthetic data only</p></div><button onClick={onClose} aria-label="Close"><X size={20}/></button></header>
      <div className="ephys-finder-path"><button onClick={onBack} disabled={!folderOpen}><ArrowLeft size={16}/></button> Demo Files / {folderOpen ? "electrophysiology" : ""}</div>
      {guided && <PickerGuidance direction="down">{!folderOpen ? "Click the highlighted electrophysiology folder to open it." : isFile ? "Now select the highlighted sampleRecording.edf file." : "The EDF is inside this folder. Confirm with Select This Folder below."}</PickerGuidance>}
      {!guided && <p className="ephys-finder-instruction">{!folderOpen ? "Open the electrophysiology folder to find the sample recording." : isFile ? "Click sampleRecording.edf to select it and return to the workflow." : "Click Select This Folder to include its recording."}</p>}
      <div className="ephys-finder-items">
        {!folderOpen ? <button data-tutorial-id="ephys-finder-folder" className={`ephys-finder-item ${guided ? "ephys-picker-target" : ""}`} onClick={onFolderOpen}><Folder size={30}/><span><strong>electrophysiology</strong><small>Folder · Contains an EDF recording</small></span></button>
        : <button data-tutorial-id="ephys-finder-edf" className={`ephys-finder-item ${guided && isFile ? "ephys-picker-target" : ""}`} onClick={() => isFile && onChoose("file")} disabled={!isFile}><FileAudio size={30}/><span><strong>sampleRecording.edf</strong><small>Synthetic EDF recording{isFile ? " · Click to open" : " · Included with folder"}</small></span></button>}
      </div>
      <footer><span>{isFile ? "Open electrophysiology, then select sampleRecording.edf." : "Choose the electrophysiology folder to include its EDF recording."}</span><button className="ephys-secondary" onClick={onClose}>Cancel</button>{!isFile && <button data-tutorial-id="ephys-finder-confirm" className={`ephys-primary ${guided && folderOpen ? "ephys-picker-target" : ""}`} disabled={!folderOpen} onClick={() => onChoose("folder")}>Select This Folder</button>}</footer>
    </section>
  </div>;
}

function EphysOutputFinder({ guided, kind, onChoose, onClose }) {
  const [selected, setSelected] = useState("");
  const expected = kind === "derivatives" ? "ephys_derivatives" : "ephys_final";
  const ready = selected === expected;
  return <div className="ephys-modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label="Select output folder" className="ephys-finder">
      <header><div><h3>Select {kind === "derivatives" ? "derivatives" : "final output"} folder</h3><p>Simulated folder browser · No files are written</p></div><button onClick={onClose} aria-label="Close"><X size={20}/></button></header>
      <div className="ephys-finder-path">Demo Files / Output</div>
      <div className="ephys-finder-items">
        {["ephys_derivatives", "ephys_final"].map(folder => {
          const isGuideTarget = guided && !ready && folder === expected;
          return <button key={folder} type="button" data-tutorial-id={`ephys-picker-${folder}`} onClick={() => setSelected(folder)} className={`ephys-finder-item ${selected === folder ? "ephys-finder-selected" : ""} ${isGuideTarget ? "ephys-picker-target" : ""}`}>
            <Folder size={30}/><span><strong>{folder}</strong><small>{isGuideTarget ? "← Click this folder to select it" : "Demo output folder"}</small></span>
            {isGuideTarget && <span className="ephys-picker-inline-hint" aria-hidden="true">← SELECT THIS FOLDER</span>}
          </button>;
        })}
      </div>
      <footer><span>{guided ? ready ? `Selected ${expected}. Now click Choose Folder →` : `Select ${expected} above.` : selected && selected !== expected ? `Select ${expected} for this output destination.` : "Select a folder and confirm."}</span><button className="ephys-secondary" onClick={onClose}>Cancel</button><button data-tutorial-id="ephys-picker-confirm" className={`ephys-primary ${guided && ready ? "ephys-picker-target ephys-picker-confirm-target" : ""}`} onClick={() => onChoose(selected)} disabled={!ready}>Choose Folder{guided && ready && <span className="ephys-picker-confirm-hint" aria-hidden="true">CLICK HERE TO CONFIRM ↓</span>}</button></footer>
    </section>
  </div>;
}

const EPHYS_PUBLIC_CSS = `
/* High-contrast step introduction: the full step remains visible, but the guide is unmistakable. */
.ephys-guide-overview-backdrop{position:fixed!important;inset:0!important;z-index:1200!important;display:block;padding:0;background:transparent;width:100%!important;max-width:none!important;margin:0!important;box-sizing:border-box;pointer-events:auto}
.ephys-guide-overview-card{position:fixed;z-index:1204;width:min(390px,calc(100vw - 32px));max-height:min(290px,calc(100vh - 48px));overflow:auto;box-sizing:border-box;padding:clamp(20px,2.5vw,27px);border:1px solid #70b8eb;border-radius:18px;background:#132b49;color:#fff;box-shadow:0 28px 90px rgba(0,0,0,.42),0 0 0 4px rgba(110,191,245,.18)}
.ephys-guide-overview-eyebrow{margin:0!important;color:#8bd6ff!important;font-size:12px!important;font-weight:850;letter-spacing:.13em;text-transform:uppercase}
.ephys-guide-overview-card h2{margin:10px 0 10px!important;color:#fff!important;font-family:Georgia,serif;font-size:clamp(23px,2.5vw,29px);font-weight:700;line-height:1.18}
.ephys-guide-overview-description{margin:0!important;color:#eef7ff!important;font-size:14px!important;line-height:1.6!important}
.ephys-guide-overview-actions{display:flex;align-items:center;gap:13px;flex-wrap:wrap;margin-top:18px}
.ephys-guide-overview-next{display:inline-flex;align-items:center;justify-content:center;gap:13px;min-height:47px;padding:0 23px;border:2px solid #fff;border-radius:999px;background:#fff;color:#13365b;font-size:14px;font-weight:850;cursor:pointer}
.ephys-guide-overview-next:hover{background:#dcf2ff}
.ephys-guide-overview-next span{font-size:20px}
.ephys-guide-overview-skip{min-height:45px;padding:0 15px;border:1px solid rgba(255,255,255,.42);border-radius:999px;background:transparent;color:#fff;font-size:13px;font-weight:750;cursor:pointer}
.ephys-guide-overview-skip:hover{background:rgba(255,255,255,.12)}
.ephys-guide-overview-explore{padding:10px 2px;border:0;background:transparent;color:#c9e8ff;font-size:13px;font-weight:700;text-decoration:underline;text-underline-offset:3px;cursor:pointer}.ephys-guide-overview-explore:hover{color:#fff}
.ephys-guide-overview-next:focus-visible,.ephys-guide-overview-explore:focus-visible,.ephys-guide-overview-skip:focus-visible{outline:3px solid #8bd6ff;outline-offset:4px}
@media(max-width:560px){.ephys-guide-overview-backdrop{padding:16px}.ephys-guide-overview-card{padding:24px}.ephys-guide-overview-description{font-size:14px!important}}
/* Highlight the actual active workflow section, rather than covering it with the introduction. */
.ephys-public-demo .ephys-guide-focus-step{position:relative!important;z-index:1202!important;outline:4px solid #80cdff!important;outline-offset:5px!important;box-shadow:0 0 0 9px rgba(80,177,239,.27),0 16px 60px rgba(0,0,0,.32)!important;background:#fff}
.ephys-public-demo .ephys-guide-focus-step{pointer-events:none!important;user-select:none!important} .ephys-guide-overview-backdrop .ephys-guide-overview-card{pointer-events:auto}
@media(max-width:680px){.ephys-guide-overview-backdrop{padding:0}.ephys-guide-overview-card{width:min(390px,calc(100vw - 32px));max-height:42vh}.ephys-guide-overview-description{font-size:13px!important}}
/* Match the public Imaging demo page frame and spacing exactly. */
.ephys-public-demo {
 position:relative;box-sizing:border-box;width:100%;min-height:100vh;
 padding:28px clamp(20px,4.35vw,72px) 68px;
 background:linear-gradient(145deg,#edf5fb 0%,#f3f7fc 43%,#eaf3fa 100%);
 color:#172b49;
}
.ephys-public-demo::before {
 content:"";position:absolute;inset:0 calc(50% - 50vw);z-index:-1;
 background:linear-gradient(145deg,#edf5fb 0%,#f3f7fc 43%,#eaf3fa 100%);
 pointer-events:none;
}
.ephys-public-demo>nav,.ephys-public-demo>header,.ephys-public-demo>section,.ephys-public-demo>div:not([role="dialog"]) {
 width:100%;max-width:1440px;margin-left:auto;margin-right:auto;box-sizing:border-box;
}
.ephys-public-demo>nav {margin-bottom:28px}
.ephys-public-demo>.ephys-page-heading {margin-bottom:30px;padding-left:4px}
.ephys-public-demo>section[aria-label^="Introduction to step"] {
 width:100%;border:1px solid #bae1fa;border-radius:12px;background:#fff;
 box-shadow:0 2px 3px rgba(33,69,100,.07);
 margin-bottom:20px;
}
.ephys-public-demo>.ephys-page-heading h1 {margin:0}
.ephys-public-demo>.ephys-page-heading p {margin-top:8px}
.ephys-public-demo .ephys-step-card {width:100%;}
.ephys-public-demo [class*="coach"],.ephys-public-demo [class*="Coach"]{display:none!important}
.ephys-public-demo .${styles.workflow}{max-width:none}
.ephys-public-demo .${styles.card}{width:100%;max-width:none;box-sizing:border-box}
.ephys-public-demo .${styles.processGrid}{max-width:none;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.ephys-public-demo .${styles.metadataEditor}{width:100%;max-width:none}
.ephys-public-demo .${styles.metadataGrid}{grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.ephys-public-demo .${styles.headerComparison}{width:100%;max-width:none}
.ephys-step-card{width:100%;overflow:hidden;border:1px solid #bed2e1;border-radius:12px;background:white;box-shadow:0 7px 22px rgba(33,69,100,.05)}
.ephys-section-heading{display:flex;align-items:center;gap:13px;min-height:76px;padding:14px 18px;background:#f9fbfd;border-bottom:1px solid #e4ebf1}
.ephys-section-heading>span{display:grid;place-items:center;flex:0 0 36px;height:36px;border-radius:9px;background:#eaf3f9;color:#2c688b;font-size:12px;font-weight:900}
.ephys-section-heading strong{display:block;font-size:15px;color:#17233a}.ephys-section-heading p{margin:4px 0 0;color:#708295;font-size:12px;line-height:1.45}
.ephys-step-body{padding:20px}.ephys-upload-card{min-height:155px;display:grid;grid-template-columns:48px minmax(0,1fr);gap:14px;padding:18px;border:1px dashed #aebfcd;border-radius:11px;background:#fafcfe}
.ephys-upload-icon{display:grid;place-items:center;width:44px;height:44px;border-radius:10px;background:#e8f2f8;color:#2f6d91}
.ephys-upload-card strong{color:#24364f;font-size:14px}.ephys-upload-card p{margin:5px 0;color:#6a7d8f;font-size:12px}.ephys-upload-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:19px}
.ephys-primary,.ephys-secondary{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:38px;padding:0 13px;border-radius:8px;font-size:12px;font-weight:800;cursor:pointer}
.ephys-primary{border:1px solid #2470ae;background:#2470ae;color:white}.ephys-secondary{border:1px solid #c8d5df;background:white;color:#355068}
.ephys-primary:disabled,.ephys-secondary:disabled{opacity:.48;cursor:not-allowed}
.ephys-selection-summary{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-top:15px;padding:14px 15px;border:1px solid #d9e3eb;border-radius:10px;background:white}
.ephys-selection-summary>svg{padding:9px;box-sizing:content-box;border-radius:9px;background:#eff5f9;color:#436f8b}
.ephys-selection-summary>div{display:grid;gap:3px;flex:1}.ephys-selection-summary strong{font-size:13px}.ephys-selection-summary span{font-size:11px;color:#718395}
.ephys-selection-summary details{color:#236b9e;font-size:12px;font-weight:700}.ephys-selection-summary summary{cursor:pointer}.ephys-selected-details{padding:12px 0 0;line-height:2}
.ephys-actions{display:flex;justify-content:flex-end;align-items:center;gap:10px;flex-wrap:wrap;margin-top:19px;padding-top:15px;border-top:1px solid #e7edf2}.ephys-actions-between{justify-content:space-between}.ephys-actions-between>div{display:flex;flex-wrap:wrap;gap:8px}
.ephys-folder-stack{display:grid;gap:11px}.ephys-folder-field{display:grid;gap:7px;font-size:12px;font-weight:800;color:#3c5167}.ephys-folder-field>div{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}
.ephys-folder-field input,.ephys-dataset input{width:100%;min-width:0;box-sizing:border-box;height:39px;padding:0 11px;border:1px solid #cbd7e1;border-radius:7px;background:white;color:#22354c;font:inherit;font-size:12px}
.ephys-folder-field button{display:flex;align-items:center;gap:6px;padding:0 13px;border:1px solid #c8d5df;border-radius:8px;background:white;color:#355068;font-weight:800;font-size:12px;cursor:pointer}
.ephys-info-strip{margin:0;padding:10px 12px;border:1px solid #dce5ec;border-radius:8px;background:#f7fafc;color:#61778b;font-size:12px;line-height:1.5}.ephys-success{padding:10px 12px;margin:12px 0 0;border:1px solid #bfd9c9;border-radius:8px;background:#fbfefc;color:#2f7754;font-size:12px;font-weight:750}
.ephys-overwrite{display:flex;gap:8px;align-items:center;margin:16px 0;color:#61778b;font-size:12px}.ephys-status{overflow:hidden;margin-top:16px;border:1px solid #d7e1e9;border-radius:10px;background:white}.ephys-status>div{display:grid;gap:3px;padding:12px 14px}.ephys-status strong{font-size:12px}.ephys-status span{font-size:11px;color:#718496}.ephys-status pre{max-height:220px;overflow:auto;margin:0;padding:15px;background:#172433;color:#d5e0e8;font-size:11px;white-space:pre-wrap}
.ephys-annotation-review{margin-top:18px;padding:16px;border:1px solid #d9e3ec;border-radius:10px}.ephys-annotation-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.ephys-annotation-heading strong{font-size:15px}.ephys-annotation-heading h3{font-size:12px;font-weight:800}.ephys-annotation-heading p{margin:5px 0;font-size:11px;color:#6b7f91}.ephys-annotation-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-top:15px}.ephys-annotation-grid h3{font-size:12px;font-weight:800}
.ephys-annotation-grid{grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:24px}.ephys-annotation-grid>div{min-width:0}.ephys-annotation-column-labels{display:grid;grid-template-columns:110px 110px minmax(120px,1fr);gap:10px;padding:12px 10px 8px;font-size:11px;font-weight:800;color:#48647a}.ephys-annotation-column-labels.ephys-edit-labels{grid-template-columns:minmax(105px,1fr) minmax(105px,1fr) minmax(175px,2fr) 100px;padding-left:0}.ephys-edit-annotation{grid-template-columns:minmax(105px,1fr) minmax(105px,1fr) minmax(175px,2fr) 100px!important;gap:10px!important;align-items:center;margin-bottom:12px!important}.ephys-edit-annotation input{min-height:40px;font-size:12px!important;padding:9px!important}.ephys-raw-annotation{grid-template-columns:110px 110px minmax(120px,1fr)!important;gap:10px!important;padding:13px 10px!important;font-size:12px!important}@media(max-width:1000px){.ephys-annotation-grid{grid-template-columns:1fr}.ephys-annotation-grid>div{overflow-x:auto}}
.ephys-raw-annotation{display:grid;grid-template-columns:60px 60px 1fr;gap:8px;padding:10px;border-bottom:1px solid #edf1f4;color:#566c80;font-size:11px}
.ephys-edit-annotation{display:grid;grid-template-columns:75px 75px minmax(80px,1fr) auto;gap:6px;margin-bottom:8px}.ephys-edit-annotation input{width:100%;min-width:0;padding:8px;border:1px solid #cbd7e1;border-radius:6px;font-size:11px}
.ephys-review-decision{display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-wrap:wrap;margin-top:15px}.ephys-review-decision>span{margin-right:auto;font-size:12px;color:#607589}
.ephys-dataset{margin-top:20px;padding:18px;border:1px solid #d9e3ec;border-radius:10px;background:#fbfcfd}.ephys-dataset h3{font-weight:800;font-size:16px;margin:0 0 15px}.ephys-dataset-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.ephys-dataset-grid label{display:grid;gap:7px;font-size:12px;font-weight:700}.ephys-dataset-full{grid-column:1/-1}
.ephys-modal-backdrop{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:18px;background:rgba(18,32,47,.56)}.ephys-finder,.ephys-confirm-modal{width:min(720px,100%);overflow:hidden;border-radius:16px;border:1px solid #d5e0e8;background:white;box-shadow:0 24px 70px rgba(12,27,41,.25)}
.ephys-finder header{display:flex;align-items:center;justify-content:space-between;padding:17px 20px;border-bottom:1px solid #e3e9ef;background:#f8fafc}.ephys-finder header h3,.ephys-confirm-modal h3{margin:0;font-size:20px;font-weight:750;color:#25394f}.ephys-finder header p,.ephys-confirm-modal p{margin:5px 0;color:#6a7e90;font-size:12px}.ephys-finder header button{border:0;background:transparent;color:#546e84;cursor:pointer}
.ephys-finder-path{display:flex;align-items:center;gap:12px;padding:10px 20px;border-bottom:1px solid #eef2f6;font-size:12px;color:#546e84}.ephys-finder-path button{padding:5px;border:0;background:white;cursor:pointer}.ephys-finder-path button:disabled{opacity:.3}
.ephys-finder-instruction{margin:0;padding:12px 20px 0;font-size:12px;color:#2c688b;font-weight:650}.ephys-finder-items{display:grid;gap:10px;min-height:210px;align-content:start;padding:20px}.ephys-finder-item{display:flex;align-items:center;gap:12px;width:100%;padding:15px;border:1px solid #bcd6e9;border-radius:10px;background:#f2f9fd;text-align:left;color:#2c688b;cursor:pointer}.ephys-finder-item:disabled{cursor:default;opacity:.75}.ephys-finder-item strong,.ephys-finder-item small{display:block}.ephys-finder-item small{margin-top:3px;color:#718496;font-size:11px}.ephys-finder-selected{outline:2px solid #2470ae}
.ephys-finder footer{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap;padding:14px 20px;border-top:1px solid #e3e9ef;background:#f8fafc}.ephys-finder footer span{flex:1;color:#718496;font-size:11px}
.ephys-picker-guide{position:relative;margin:14px 20px 0;padding:11px 14px;border:1px solid #9fc5e2;border-radius:10px;background:#edf7ff;color:#244966;display:flex;flex-direction:column;gap:4px;font-size:12px;line-height:1.45}
.ephys-picker-guide strong{font-size:10px;letter-spacing:.08em;color:#1767b1}
.ephys-picker-guide-arrow{font-size:22px;font-weight:900;line-height:1;color:#1767b1}
.ephys-picker-guide-up .ephys-picker-guide-arrow{display:none}
.ephys-picker-target{position:relative;outline:3px solid #2470ae!important;outline-offset:2px;box-shadow:0 0 0 6px rgba(36,112,174,.14)!important;z-index:1}
.ephys-picker-target:focus-visible{outline:4px solid #124d7e!important}
.ephys-picker-inline-hint{margin-left:auto!important;padding:7px 10px;border-radius:7px;background:#dceeff;color:#124d7e!important;font-size:11px;font-weight:850;white-space:nowrap;pointer-events:none}
.ephys-picker-confirm-target{position:relative!important;isolation:isolate}
.ephys-picker-confirm-hint{position:absolute;bottom:calc(100% + 12px);right:0;min-width:185px;padding:9px 12px;border:1px solid #9fc5e2;border-radius:8px;background:#eaf5ff;color:#124d7e;font-size:11px;font-weight:850;box-shadow:0 4px 14px rgba(20,70,110,.16);pointer-events:none;white-space:nowrap}
.ephys-picker-confirm-hint:after{content:"";position:absolute;top:100%;right:28px;border:7px solid transparent;border-top-color:#eaf5ff}
@media(max-width:560px){.ephys-picker-inline-hint{font-size:9px;padding:5px}.ephys-picker-confirm-hint{right:-6px}}

.ephys-confirm-modal{padding:22px;width:min(520px,100%)}.ephys-confirm-record{display:grid;gap:6px;padding:14px;border:1px solid #d9e3ec;border-radius:9px;background:#f8fafc;color:#63788b;font-size:12px}.ephys-confirm-record strong{color:#30445a}
@media(max-width:760px){.ephys-public-demo{padding:18px 16px 48px}.ephys-step-body{padding:14px}.ephys-folder-field>div,.ephys-annotation-grid,.ephys-dataset-grid{grid-template-columns:1fr}.ephys-edit-annotation{grid-template-columns:1fr 1fr}.ephys-edit-annotation input:nth-child(3){grid-column:1/-1}.ephys-actions-between{align-items:stretch;flex-direction:column}.ephys-actions-between>div{flex-direction:column}.ephys-public-demo>nav{margin-bottom:22px}.ephys-public-demo>.ephys-page-heading{margin-bottom:22px}}
.ephys-guide-small-explore{margin-top:8px;padding-top:8px;border-top:1px solid #e6edf4;text-align:left}
.ephys-guide-small-explore button{border:0;background:transparent;padding:3px 0;color:#28648f;font-size:12px;font-weight:700;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.ephys-guide-small-explore button:hover{color:#0b3153}
`;
