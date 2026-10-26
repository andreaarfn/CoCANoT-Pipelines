import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { createPortal } from "react-dom";
import { FileImage, FolderOpen, Folder, ArrowLeft, X, Check } from "lucide-react";

import TutorialSpotlight from "./TutorialSpotlight";
import ImagingStep4Training from "./ImagingStep4Training";


import { DEMO_FILES } from "./demoData";

import { resetDemoState, saveDemoState } from "./demoSession";

import styles from "./WorkflowDemo.module.css";

const labels = ["Select Data", "Output Folders", "Process", "Review", "Metadata & BIDS"];

const STEP_INTRODUCTIONS = {
  1: "Choose DICOM or NIfTI files, either individually or by folder.",
  2: "Choose where intermediate and final processed files are stored.",
  3: "Prepare imaging files, scrub identifying information from headers, and deface images.",
  4: "Compare original and processed images, review header changes, and accept or reject the results.",
  5: "Complete the CoCANoT imaging metadata and export the accepted images in BIDS-compatible format.",
};

const IMAGING_GUIDED_DESCRIPTIONS = {
  1: "This is the first step, where you select imaging files for processing. You can choose a DICOM or NIfTI file, or an entire folder. Next, I'll show you how.",
  2: "This is the second step, where you select separate folders for the intermediate derivatives and the final BIDS-compatible files. Next, let's choose and save both locations.",
  3: "This is the third step, where we prepare a NIfTI image, scrub identifying header fields, and deface it. Next, I'll walk you through the processing actions.",
  4: "This is the fourth step, where you compare the raw and defaced image slices and inspect the de-identification results before accepting them. Next, we'll review the image.",
  5: "This is the fifth step, where you complete the CoCANoT imaging metadata and prepare your accepted images for BIDS-compatible export. Next, I'll show you the metadata editor.",
};

function StepIntroduction({ step, started, previewing, onShowHow, onSkip }) {
  return (
    <section
      aria-label={`Introduction to step ${step}`}
      className="mb-5 rounded-xl border border-sky-200 bg-white px-5 py-4 shadow-sm md:px-6"
    >
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-navy/60">
        {previewing ? "GUIDE · STEP " : "STEP "}{step} OF 5
      </p>
      <h2 className="mt-2 font-serif text-2xl text-navy">{labels[step - 1]}</h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-700 md:text-base">
        {previewing ? IMAGING_GUIDED_DESCRIPTIONS[step] : STEP_INTRODUCTIONS[step]}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onShowHow}
          className="rounded-full bg-navy px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-navy"
        >
          {previewing ? "Next →" : started ? "Restart tutorial" : "Show me how →"}
        </button>
        {started && <button
          type="button"
          onClick={onSkip}
          className="rounded-full px-4 py-2.5 text-sm font-semibold text-navy/70 hover:bg-slate-100"
        >
          Skip tutorial
        </button>}
      </div>
    </section>
  );
}


function GuideOverview({ step, linked = false, wrapUp = false, onNext, onExplore, onSkip }) {
  const cardRef = useRef(null);

  useEffect(() => {
    const highlighted = Array.from(document.querySelectorAll(".imaging-public-demo .imaging-guide-focus-step"));
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
      linked ? ".imaging-linked-public-review .imaging-guide-focus-step" : ".imaging-public-demo .imaging-guide-focus-step"
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

  const heading = wrapUp ? "Take a moment to explore" : linked ? "Review Linked Image" : labels[step - 1];
  const description = wrapUp
    ? (step === 1 ? "The imaging scan is selected. Take a moment to inspect your selected source before choosing output folders."
      : step === 2 ? "Both output folders are saved. You can explore their settings before processing the imaging data."
      : step === 3 ? "Image preparation, header scrubbing, and defacing are complete. Review the processing results at your own pace."
      : step === 4 ? "The defaced image has been reviewed and accepted. Inspect the results before completing metadata."
      : "Your imaging metadata and BIDS-compatible output are ready. Explore the completed record before opening linked-image review.")
    : linked ? "Explore the linked, defaced image and its CoCANoT metadata."
    : IMAGING_GUIDED_DESCRIPTIONS[step];
  return (
    <div className="imaging-guide-overview-backdrop" role="presentation">
      <section ref={cardRef} className="imaging-guide-overview-card" style={{ top: cardPlacement.top, left: cardPlacement.left, visibility: cardPlacement.ready ? "visible" : "hidden" }} role="dialog" aria-modal="true" aria-label={`Guided introduction: ${heading}`}>
        <p className="imaging-guide-overview-eyebrow">{wrapUp ? `GUIDE · STEP ${step} COMPLETE` : linked ? "GUIDE · LINKED RECORDING REVIEW" : `GUIDE · STEP ${step} OF 5`}</p>
        <h2>{heading}</h2>
        <p className="imaging-guide-overview-description">{description}</p>
        <div className="imaging-guide-overview-actions">
          <button type="button" className="imaging-guide-overview-next" onClick={onNext}>{wrapUp ? "Show me where to continue" : "Next"} <span aria-hidden="true">→</span></button>
          {wrapUp && <button type="button" className="imaging-guide-overview-explore" onClick={onExplore}>or explore this step</button>}
          <button type="button" className="imaging-guide-overview-skip" onClick={onSkip}>Skip tutorial</button>
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
    <div className="imaging-guide-small-explore">
      <button type="button" onClick={onExplore}>or explore this step</button>
    </div>,
    footerHost
  );
}


const PURPOSE_OPTIONS = [

  "Diagnostic evaluation",

  "Presurgical evaluation",

  "Neuromodulation Planning",

  "Electrode Localization",

  "Postoperative Evaluation (<30 days)",

  "Follow-up Evaluation (>30 days after surgery)",

  "Other",

  "Unknown",

];

const FINDING_OPTIONS = [

  "No structural abnormality identified",

  "Mesial temporal sclerosis / hippocampal sclerosis",

  "Malformation of cortical development",

  "Neoplasm",

  "Stroke / cerebrovascular lesion",

  "Traumatic brain injury / traumatic lesion",

  "Hypoxic-ischemic injury",

  "Neurocutaneous syndrome-associated abnormality",

  "Other",

  "Unknown",

];

const initialMetadata = {

  patientId: "001",

  imageId: "001",

  clinicalAssessmentId: "003",

  surgeryId: "001",

  modality: "MRI",

  sequence: "T1",

  purpose: ["Presurgical evaluation"],

  timing: "Preoperative",

  findings: ["No structural abnormality identified"],

  comments: "",

};

export default function ImagingDemo() {

  const [step, setStep] = useState(1);

  const [selected, setSelected] = useState(false);
  const [selectionType, setSelectionType] = useState(null);
  const [selectedDataExpanded, setSelectedDataExpanded] = useState(false);
  const [finderMode, setFinderMode] = useState(null);
  const [finderFolderOpen, setFinderFolderOpen] = useState(false);
  const [outputFinderKind, setOutputFinderKind] = useState(null);
  const [derivativesFolder, setDerivativesFolder] = useState("");
  const [finalFolder, setFinalFolder] = useState("");
  const [folderSettingsSaved, setFolderSettingsSaved] = useState(false);

  const [prepare, setPrepare] = useState("not_started");

  const [scrub, setScrub] = useState("not_started");

  const [deface, setDeface] = useState("not_started");

  const [reviewed, setReviewed] = useState(false);

  const [metadata, setMetadata] = useState(initialMetadata);

  const [metadataSaved, setMetadataSaved] = useState(false);

  const [exported, setExported] = useState(false);

  const location = useLocation();
  const navigate = useNavigate();
  const [tutorialEnabled, setTutorialEnabled] = useState(
    location.state?.tutorialChoice === "yes"
  );
  const [tutorialPhase, setTutorialPhase] = useState("overview");
  const [tutorialStartedSteps, setTutorialStartedSteps] = useState(() => location.state?.tutorialChoice === "yes" ? { 1: true } : {});
  const [exploreAcknowledged, setExploreAcknowledged] = useState({});
  const [tutorialRestartKey, setTutorialRestartKey] = useState(0);

  const [showLinkedRecord, setShowLinkedRecord] = useState(false);

  const [linkedRecordVisited, setLinkedRecordVisited] = useState(false);
  const [linkedGuidePhase, setLinkedGuidePhase] = useState("idle");
  const [linkedGuideStarted, setLinkedGuideStarted] = useState(false);
  const [linkedGuideStep, setLinkedGuideStep] = useState(0);
  const [linkedGuideKey, setLinkedGuideKey] = useState(0);
  const linkedGuide = [
    { target: "imaging-linked-edit", title: "Review the linked metadata", text: "Click Review / Edit Metadata to examine and update the information associated with this image." },
    { target: "imaging-linked-metadata-editor", title: "Review and edit CoCANoT metadata", text: "The fields open inside the existing metadata card. Review the values, then save any changes." },
    { target: "imaging-linked-save", title: "Save the linked metadata", text: "Save these metadata changes to return to the record summary." },
    { target: "imaging-linked-views", title: "Inspect the defaced image", text: "These three windows show axial, coronal, and sagittal slices of the processed NIfTI volume." },
    { target: "imaging-linked-sliders", title: "Move through the image slices", text: "Move any slider to inspect slices in its corresponding orientation." },
  ][Math.min(linkedGuideStep, 4)];

  const complete = [

    selected,

    step > 2,

    prepare === "complete" && scrub === "complete" && deface === "complete",

    reviewed,

    exported,

  ];

  const stepActionsFinished = step === 1 ? selected
    : step === 2 ? folderSettingsSaved
    : step === 3 ? prepare === "complete" && scrub === "complete" && deface === "complete"
    : step === 4 ? reviewed
    : step === 5 ? exported
    : false;

  const tutorial = useMemo(() => {

    if (step === 1 && !selected) {
      if (finderMode && !finderFolderOpen) {
        return {
          target: "imaging-finder-folder",
          title: "Open the imagingdata folder",
          text: "In the simulated Finder, click the imagingdata folder to browse its contents.",
        };
      }
      if (finderMode === "file") {
        return {
          target: "imaging-finder-file",
          title: "Open the sample DICOM file",
          text: `Click ${DEMO_FILES.imaging.fileName} to select the synthetic scan.`,
        };
      }
      if (finderMode === "folder") {
        return {
          target: "imaging-finder-select-folder",
          title: "Select the imagingdata folder",
          text: "Click Select This Folder to include the synthetic DICOM file inside it.",
        };
      }
      return {
        target: "imaging-choose-files",
        title: "Select a file or folder",
        text: "Click Choose Files to select the sample DICOM scan. You can also use Choose Folder to include the whole imagingdata directory.",
      };
    }

    if (step === 1 && selected) {

      if (!selectedDataExpanded) {
        return {
          target: "imaging-view-selected-data",
          title: "View the selected data",
          text: "Click View Selected Data to expand the panel and inspect the synthetic DICOM file or folder you chose.",
        };
      }

      return {

        target: "imaging-continue-1",

        title: "Continue to output folders",

        text: "The sample image is selected. Continue to the protected demo folders.",

      };

    }

    if (step === 2) {
      if (outputFinderKind) {
        const targetFolder = outputFinderKind === "derivatives" ? "imaging_derivatives" : "imaging_final";
        return {
          target: "imaging-output-target-folder",
          title: `Choose ${targetFolder}`,
          text: `Select ${targetFolder} in the simulated Finder. After selecting it, confirm with Choose Folder.`,
        };
      }
      if (!derivativesFolder) return {
        target: "imaging-derivatives-browse",
        title: "Select the derivatives folder",
        text: "Click Browse and select imaging_derivatives. Intermediate processing files are stored here.",
      };
      if (!finalFolder) return {
        target: "imaging-final-browse",
        title: "Select the final output folder",
        text: "Click Browse and select imaging_final. The accepted image and metadata will be stored here.",
      };
      if (!folderSettingsSaved) return {
        target: "imaging-save-folder-settings",
        title: "Save folder settings",
        text: "Both output folders are selected. Save the folder settings before continuing.",
      };
      return {
        target: "imaging-continue-2",
        title: "Continue to processing",
        text: "Your output folders are saved. Continue to prepare, scrub and deface the image.",
      };
    }

    if (step === 3 && prepare !== "complete") {

      return {

        target: "imaging-prepare",

        title: "Prepare NIfTI",

        text: "Simulate preparing the source image for the de-identification workflow.",

      };

    }

    if (step === 3 && scrub !== "complete") {

      return {

        target: "imaging-scrub",

        title: "Scrub image headers",

        text: "Simulate removing identifying header values.",

      };

    }

    if (step === 3 && deface !== "complete") {

      return {

        target: "imaging-deface",

        title: "Deface the image",

        text: "Simulate the facial de-identification step.",

      };

    }

    if (step === 3) {

      return {

        target: "imaging-continue-review",

        title: "Review de-identification",

        text: "The processing steps are complete. Continue to the review window.",

      };

    }

    if (step === 4 && !reviewed) {

      return {

        target: "imaging-accept",

        title: "Accept the reviewed image",

        text: "Accept the synthetic image after reviewing the raw and defaced views.",

      };

    }

    if (step === 5 && !metadataSaved) {

      return {

        target: "imaging-metadata-editor",

        title: "Complete CoCANoT imaging metadata",

        text: "Step 5 is where the accepted image is linked to structured CoCANoT metadata. Edit the fields, then save the metadata before creating the standardized output.",

      };

    }

    if (step === 5 && metadataSaved && !exported) {

      return {

        target: "imaging-export",

        title: "Create the standardized output",

        text: "The CoCANoT metadata is saved. Now simulate creating the linked BIDS-compatible output.",

      };

    }

    if (step === 5 && exported && !showLinkedRecord && !linkedRecordVisited) {

      return {

        target: "imaging-view-linked",

        title: "View the linked patient record",

        text: "Open Patient Data Review to see the standardized image and its saved metadata together.",

      };

    }

    return null;

  }, [

    step,

    selected,
    selectedDataExpanded,
    finderMode,
    finderFolderOpen,
    outputFinderKind,
    derivativesFolder,
    finalFolder,
    folderSettingsSaved,

    prepare,

    scrub,

    deface,

    reviewed,

    metadataSaved,

    exported,

    showLinkedRecord,

    linkedRecordVisited,

  ]);

  function remember(patch) {

    saveDemoState({

      imaging: {

        step,

        selected,

        prepare,

        scrub,

        deface,

        reviewed,

        metadataSaved,

        exported,

        ...patch,

      },

    });

  }

  function go(next) {
    if (next !== step && tutorialEnabled) {
      setTutorialPhase("overview");
      setTutorialStartedSteps(current => ({ ...current, [next]: true }));
    }
    setStep(next);

    remember({ step: next });

  }

  async function run(setter, key) {

    setter("running");

    remember({ [key]: "running" });

    await new Promise((resolve) => setTimeout(resolve, 700));

    setter("complete");

    remember({ [key]: "complete" });

  }

  function toggleMulti(field, value) {

    setMetadata((current) => {

      const selectedValues = current[field] ?? [];

      const exclusive = value === "Unknown" || value === "No structural abnormality identified";

      if (selectedValues.includes(value)) {

        return {

          ...current,

          [field]: selectedValues.filter((item) => item !== value),

        };

      }

      if (exclusive) {

        return { ...current, [field]: [value] };

      }

      return {

        ...current,

        [field]: selectedValues

          .filter((item) => item !== "Unknown" && item !== "No structural abnormality identified")

          .concat(value),

      };

    });

    setMetadataSaved(false);

    setExported(false);

  }

  function setField(field, value) {

    setMetadata((current) => ({ ...current, [field]: value }));

    setMetadataSaved(false);

    setExported(false);

  }

  function openFinder(mode) {
    setFinderMode(mode);
    setFinderFolderOpen(false);
    setSelected(false);
    setSelectionType(null);
    remember({ selected: false });
  }

  function chooseFromFinder(mode) {
    setSelected(true);
    setSelectionType(mode);
    setFinderMode(null);
    setFinderFolderOpen(false);
    remember({ selected: true });
  }

  function reset() {

    resetDemoState();

    setStep(1);

    setSelected(false);
    setSelectionType(null);
    setFinderMode(null);
    setFinderFolderOpen(false);
    setOutputFinderKind(null);
    setDerivativesFolder("");
    setFinalFolder("");
    setFolderSettingsSaved(false);

    setPrepare("not_started");

    setScrub("not_started");

    setDeface("not_started");

    setReviewed(false);

    setMetadata(initialMetadata);

    setMetadataSaved(false);

    setExported(false);

    setTutorialEnabled(true);
    setTutorialPhase("overview");
    setTutorialStartedSteps({});
    setExploreAcknowledged({});
    setTutorialRestartKey(0);

    setShowLinkedRecord(false);

    setLinkedRecordVisited(false);
    setLinkedGuidePhase("idle");
    setLinkedGuideStarted(false);
    setLinkedGuideStep(0);

  }

  return (
    <div className="imaging-public-demo">
      <nav className="mb-5 flex flex-wrap items-center justify-between gap-3" aria-label="Demo navigation">
        <button type="button" onClick={() => window.dispatchEvent(new Event("atlas-training-back"))} className="inline-flex items-center gap-2 text-sm font-semibold text-navy hover:underline">
          <ArrowLeft size={16} aria-hidden="true" /> Back to Site Training
        </button>
        <button type="button" onClick={reset} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50">
          Reset Demo
        </button>
      </nav>
      <header className="imaging-page-heading mb-6 px-1 md:mb-8">
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-navy md:text-4xl">Process Imaging</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600 md:text-base">A guided public version of the CoCANoT imaging workflow.</p>
      </header>
      <style>{`
        .imaging-public-demo {
          position: relative;
          box-sizing: border-box;
          width: 100%;
          min-height: 100vh;
          padding: 28px clamp(20px, 4.35vw, 72px) 68px;
          background: linear-gradient(145deg, #edf5fb 0%, #f3f7fc 43%, #eaf3fa 100%);
          color: #172b49;
        }
        .imaging-public-demo::before {
          content: "";
          position: absolute;
          inset: 0 calc(50% - 50vw);
          z-index: -1;
          background: linear-gradient(145deg, #edf5fb 0%, #f3f7fc 43%, #eaf3fa 100%);
          pointer-events: none;
        }
        .imaging-public-demo > nav,
        .imaging-public-demo > header,
        .imaging-public-demo > section,
        .imaging-public-demo > div:not([role="dialog"]) {
          width: 100%;
          max-width: 1440px;
          margin-left: auto;
          margin-right: auto;
          box-sizing: border-box;
        }
        .imaging-public-demo > nav { margin-bottom: 28px; }
        .imaging-public-demo > .imaging-page-heading {
          margin-bottom: 30px;
          padding-left: 4px;
        }
        .imaging-public-demo .imaging-ref-stepCard { width: 100%; }
        @media (max-width: 700px) {
          .imaging-public-demo { padding: 18px 16px 48px; }
          .imaging-public-demo > nav { margin-bottom: 22px; }
          .imaging-public-demo > .imaging-page-heading { margin-bottom: 22px; }
        }
      `}</style>
      <style>{`.imaging-picker-guide{position:relative;display:grid;gap:5px;margin:14px 20px 0;padding:10px 14px 15px;border:1px solid #a5cde7;border-radius:9px;background:#ecf7ff;color:#234f70;font-size:12px;line-height:1.45}.imaging-picker-guide strong{font-size:10px;letter-spacing:.09em;color:#1767b1}.imaging-picker-guide-arrow{position:absolute;bottom:-9px;left:30px;color:#1767b1;font-size:21px;font-weight:900}.imaging-picker-target{position:relative!important;z-index:1!important;outline:3px solid #2470ae!important;outline-offset:3px!important;box-shadow:0 0 0 7px rgba(36,112,174,.17)!important}.imaging-picker-confirm-target{overflow:visible!important}.imaging-picker-confirm-hint{position:absolute;bottom:calc(100% + 9px);right:0;white-space:nowrap;padding:5px 8px;border-radius:6px;background:#1767b1;color:#fff;font-size:10px;font-weight:850;box-shadow:0 2px 10px rgba(0,0,0,.17)}.imaging-picker-confirm-hint:after{content:"";position:absolute;top:100%;right:25px;border:6px solid transparent;border-top-color:#1767b1}`}</style>
      <style>{`
.imaging-output-finder-backdrop{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:18px;background:rgba(18,32,47,.56)}
.imaging-output-finder{width:min(720px,100%);overflow:hidden;border-radius:16px;border:1px solid #d5e0e8;background:#fff;box-shadow:0 24px 70px rgba(12,27,41,.25)}
.imaging-output-finder header{display:flex;align-items:center;justify-content:space-between;padding:17px 20px;border-bottom:1px solid #e3e9ef;background:#f8fafc}
.imaging-output-finder header h3{margin:0;font-family:Georgia,serif;font-size:22px;font-weight:750;color:#25394f}
.imaging-output-finder header p{margin:5px 0;color:#6a7e90;font-size:12px}
.imaging-output-finder header button{border:0;background:transparent;color:#546e84;cursor:pointer}
.imaging-output-finder-path{display:flex;align-items:center;gap:12px;padding:10px 20px;border-bottom:1px solid #eef2f6;font-size:12px;color:#546e84}
.imaging-output-finder-items{display:grid;gap:10px;min-height:210px;align-content:start;padding:20px}
.imaging-output-finder-item{display:flex;align-items:center;gap:12px;width:100%;padding:15px;border:1px solid #bcd6e9;border-radius:10px;background:#f2f9fd;text-align:left;color:#2c688b;cursor:pointer}
.imaging-output-finder-item strong,.imaging-output-finder-item small{display:block}
.imaging-output-finder-item small{margin-top:3px;color:#718496;font-size:11px}
.imaging-output-finder-selected{outline:2px solid #2470ae}
.imaging-output-finder-inline-hint{margin-left:auto!important;padding:7px 10px;border-radius:7px;background:#dceeff;color:#124d7e!important;font-size:11px;font-weight:850;white-space:nowrap;pointer-events:none}
.imaging-output-finder footer{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap;padding:14px 20px;border-top:1px solid #e3e9ef;background:#f8fafc}
.imaging-output-finder footer>span{flex:1;color:#718496;font-size:11px}
.imaging-output-finder-primary,.imaging-output-finder-secondary{min-height:36px;padding:0 12px;border-radius:7px;font-size:12px;font-weight:800;cursor:pointer}
.imaging-output-finder-secondary{border:1px solid #c9d5df;background:#fff;color:#314961}
.imaging-output-finder-primary{position:relative;border:1px solid #2470ae;background:#2470ae;color:#fff}
.imaging-output-finder-primary:disabled{opacity:.52;cursor:not-allowed}
.imaging-output-finder .imaging-picker-confirm-hint{bottom:calc(100% + 12px);right:0;min-width:185px;padding:9px 12px;border:1px solid #9fc5e2;border-radius:8px;background:#eaf5ff;color:#124d7e;font-size:11px}
.imaging-output-finder .imaging-picker-confirm-hint:after{border-top-color:#eaf5ff}
@media(max-width:560px){.imaging-output-finder-inline-hint{font-size:9px;padding:5px}.imaging-output-finder-items{padding:14px}.imaging-output-finder footer{padding:12px}}
`}</style>
      <style>{IMAGING_REFERENCE_CSS}</style>
      <style>{`/* High-contrast step introduction: the full step remains visible, but the guide is unmistakable. */
.imaging-guide-overview-backdrop{position:fixed!important;inset:0!important;z-index:1200!important;display:block;padding:0;background:rgba(9,23,43,.72);width:100%!important;max-width:none!important;margin:0!important;box-sizing:border-box;pointer-events:auto}
.imaging-guide-overview-card{position:fixed;z-index:1204;width:min(390px,calc(100vw - 32px));max-height:min(290px,calc(100vh - 48px));overflow:auto;box-sizing:border-box;padding:clamp(20px,2.5vw,27px);border:1px solid #70b8eb;border-radius:18px;background:#132b49;color:#fff;box-shadow:0 28px 90px rgba(0,0,0,.42),0 0 0 4px rgba(110,191,245,.18)}
.imaging-guide-overview-eyebrow{margin:0!important;color:#8bd6ff!important;font-size:12px!important;font-weight:850;letter-spacing:.13em;text-transform:uppercase}
.imaging-guide-overview-card h2{margin:10px 0 10px!important;color:#fff!important;font-family:Georgia,serif;font-size:clamp(23px,2.5vw,29px);font-weight:700;line-height:1.18}
.imaging-guide-overview-description{margin:0!important;color:#eef7ff!important;font-size:14px!important;line-height:1.6!important}
.imaging-guide-overview-actions{display:flex;align-items:center;gap:13px;flex-wrap:wrap;margin-top:18px}
.imaging-guide-overview-next{display:inline-flex;align-items:center;justify-content:center;gap:13px;min-height:47px;padding:0 23px;border:2px solid #fff;border-radius:999px;background:#fff;color:#13365b;font-size:14px;font-weight:850;cursor:pointer}
.imaging-guide-overview-next:hover{background:#dcf2ff}
.imaging-guide-overview-next span{font-size:20px}
.imaging-guide-overview-skip{min-height:45px;padding:0 15px;border:1px solid rgba(255,255,255,.42);border-radius:999px;background:transparent;color:#fff;font-size:13px;font-weight:750;cursor:pointer}
.imaging-guide-overview-skip:hover{background:rgba(255,255,255,.12)}
.imaging-guide-overview-explore{padding:10px 2px;border:0;background:transparent;color:#c9e8ff;font-size:13px;font-weight:700;text-decoration:underline;text-underline-offset:3px;cursor:pointer}.imaging-guide-overview-explore:hover{color:#fff}
.imaging-guide-overview-next:focus-visible,.imaging-guide-overview-explore:focus-visible,.imaging-guide-overview-skip:focus-visible{outline:3px solid #8bd6ff;outline-offset:4px}
@media(max-width:560px){.imaging-guide-overview-backdrop{padding:16px}.imaging-guide-overview-card{padding:24px}.imaging-guide-overview-description{font-size:14px!important}}
/* Highlight the actual active workflow section, rather than covering it with the introduction. */
.imaging-public-demo .imaging-guide-focus-step{position:relative!important;z-index:1202!important;outline:4px solid #80cdff!important;outline-offset:5px!important;box-shadow:0 0 0 9px rgba(80,177,239,.27),0 16px 60px rgba(0,0,0,.32)!important;background:#fff}
.imaging-public-demo .imaging-guide-focus-step{pointer-events:none!important;user-select:none!important} .imaging-guide-overview-backdrop .imaging-guide-overview-card{pointer-events:auto}
@media(max-width:680px){.imaging-guide-overview-backdrop{padding:0}.imaging-guide-overview-card{width:min(390px,calc(100vw - 32px));max-height:42vh}.imaging-guide-overview-description{font-size:13px!important}}

.imaging-guide-small-explore{margin-top:8px;padding-top:8px;border-top:1px solid #e6edf4;text-align:left}
.imaging-guide-small-explore button{border:0;background:transparent;padding:3px 0;color:#28648f;font-size:12px;font-weight:700;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.imaging-guide-small-explore button:hover{color:#0b3153}`}</style>
      <style>{NIFTI_REVIEW_CSS}</style>
      <style>{`.imaging-ref-dashboardHeader { display:flex; align-items:center; gap:13px; min-height:76px; padding:14px 18px; background:#f9fbfd; border-bottom:1px solid #e4ebf1; }
        .imaging-ref-dashboardHeader > div:last-child { flex:1; min-width:0; }
        .imaging-ref-dashboardHeader strong { display:block; color:#17233a; font-size:15px; }
        .imaging-ref-dashboardHeader span { display:block; color:#708295; font-size:12px; line-height:1.45; margin-top:4px; }
        .imaging-ref-dashboardBody { padding:20px; }
        @media(max-width:760px) { .imaging-ref-dashboardBody { padding:14px; } }`}</style>
      <style>{`.imaging-public-demo [class*="coach"], .imaging-public-demo [class*="Coach"], .imaging-public-demo [class*="guideCard"], .imaging-public-demo [class*="guidePanel"] { display: none !important; }`}</style>

      {outputFinderKind && (
        <ImagingOutputFinder
          guided={tutorialEnabled && tutorialPhase === "spotlight"}
          kind={outputFinderKind}
          onClose={() => setOutputFinderKind(null)}
          onChoose={(folder) => {
            if (outputFinderKind === "derivatives") setDerivativesFolder(`/demo/${folder}`);
            else setFinalFolder(`/demo/${folder}`);
            setFolderSettingsSaved(false);
            setOutputFinderKind(null);
          }}
        />
      )}
      {finderMode && (
        <ImagingFakeFinder
          guided={tutorialEnabled && tutorialPhase === "spotlight"}
          mode={finderMode}
          folderOpen={finderFolderOpen}
          onFolderOpen={() => setFinderFolderOpen(true)}
          onBack={() => setFinderFolderOpen(false)}
          onClose={() => { setFinderMode(null); setFinderFolderOpen(false); }}
          onChoose={chooseFromFinder}
        />
      )}
    {showLinkedRecord ? (
        <div className="imaging-linked-public-review">
          <section className="mb-5 rounded-xl border border-sky-200 bg-white px-5 py-4 shadow-sm md:px-6" aria-label="Linked image tutorial introduction">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-navy/60">LINKED IMAGE REVIEW</p>
            <h2 className="mt-2 font-serif text-2xl text-navy">Review Linked Image</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-700 md:text-base">Explore the defaced MRI and its linked CoCANoT metadata. Review the three orientations using the slice sliders.</p>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button type="button" className="rounded-full bg-navy px-5 py-2.5 text-sm font-semibold text-white" onClick={() => {
                if (linkedGuidePhase === "overview") {
                  setLinkedGuidePhase("spotlight");
                } else {
                  setLinkedGuideStarted(true);
                  setLinkedGuideStep(0);
                  setLinkedGuidePhase("overview");
                }
                setLinkedGuideKey(k => k + 1);
              }}>{linkedGuidePhase === "overview" ? "Next →" : linkedGuideStarted ? "Restart tutorial" : "Show me how →"}</button>
              {linkedGuideStarted && <button type="button" className="rounded-full px-4 py-2.5 text-sm font-semibold text-navy/70 hover:bg-slate-100" onClick={() => {setLinkedGuideStarted(false);setLinkedGuidePhase("idle");}}>Skip tutorial</button>}
            </div>
          </section>
          {linkedGuidePhase === "overview" && <GuideOverview linked onNext={() => {setLinkedGuidePhase("spotlight");setLinkedGuideKey(k=>k+1);}} onSkip={() => {setLinkedGuidePhase("idle");setLinkedGuideStarted(false);}} />}
          <TutorialSpotlight key={`imaging-linked-${linkedGuideKey}-${linkedGuideStep}`} enabled={linkedGuidePhase === "spotlight"} target={linkedGuide.target} title={linkedGuide.title} text={linkedGuide.text} step={Math.min(linkedGuideStep + 1,5)} totalSteps={5} onSkip={() => setLinkedGuidePhase("idle")}/>
          <div data-tutorial-id="imaging-linked-review-content" className={linkedGuidePhase === "overview" ? "imaging-guide-focus-step" : ""}>
            <ImagingLinkedImageReview
              metadata={metadata}
              guided={linkedGuidePhase === "spotlight"}
              onGuideAction={(action) => {
                if (action === "edit" && linkedGuideStep === 0) setLinkedGuideStep(1);
                if (action === "save" && linkedGuideStep <= 2) setLinkedGuideStep(3);
                if (action === "slider" && linkedGuideStep === 4) setLinkedGuidePhase("idle");
              }}
              onSaveMetadata={(updated) => {
                setMetadata(updated);
                setMetadataSaved(true);
                remember({ metadataSaved: true, exported: true });
              }}
              onBack={() => {setShowLinkedRecord(false);setLinkedGuidePhase("idle");}}
            />
          </div>
          {linkedGuidePhase === "spotlight" && linkedGuideStep === 1 && <button type="button" className="imaging-linked-guide-next rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white" onClick={() => setLinkedGuideStep(2)}>Next: Save metadata →</button>}
          {linkedGuidePhase === "spotlight" && linkedGuideStep === 3 && <button type="button" className="imaging-linked-guide-next rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white" onClick={() => setLinkedGuideStep(4)}>Next: Explore the sliders →</button>}
        </div>
      ) : (

        <>

          <StepIntroduction
            step={step}
            started={tutorialEnabled && Boolean(tutorialStartedSteps[step])}
            previewing={tutorialEnabled && tutorialPhase === "overview"}
            onShowHow={() => {
              setTutorialEnabled(true);
              setTutorialStartedSteps(current => ({ ...current, [step]: true }));
              setExploreAcknowledged(current => ({ ...current, [step]: false }));
              if (tutorialPhase === "overview") {
                setTutorialPhase("spotlight");
                setTutorialRestartKey(current => current + 1);
              } else {
                setTutorialPhase("overview");
              }
            }}
            onSkip={() => {
              setTutorialEnabled(false);
              setTutorialPhase("overview");
              setTutorialStartedSteps({});
            }}
          />
          {tutorialEnabled && tutorialPhase === "overview" && Boolean(tutorialStartedSteps[step]) && (
            <GuideOverview
              step={step}
              onNext={() => {
                setTutorialPhase("spotlight");
                setTutorialRestartKey(current => current + 1);
              }}
              onSkip={() => {
                setTutorialEnabled(false);
                setTutorialPhase("overview");
                setTutorialStartedSteps({});
              }}
            />
          )}
          {step !== 4 && tutorialEnabled && tutorialPhase === "spotlight" && stepActionsFinished && !exploreAcknowledged[step] && !finderMode && !outputFinderKind && (
            <SpotlightExploreLink
              guideTitle={tutorial?.title}
              onExplore={() => {
                setExploreAcknowledged(current => ({ ...current, [step]: true }));
                setTutorialPhase("explore");
              }}
            />
          )}
          <TutorialSpotlight
            key={`${step}-${tutorialRestartKey}`}
            enabled={step !== 4 && tutorialEnabled && tutorialPhase === "spotlight" && Boolean(tutorial) && !finderMode && !outputFinderKind}
            target={tutorial?.target}
            title={tutorial?.title}
            text={tutorial?.text}
            step={step}
            totalSteps={5}
            onSkip={() => setTutorialPhase("explore")}
          />

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
              <section className={`${styles.card} imaging-ref-stepCard ${tutorialEnabled && tutorialPhase === "overview" ? "imaging-guide-focus-step" : ""}`}>
                <div className={"imaging-ref-sectionHeading"}>
                  <span className={"imaging-ref-stepNumber"}>1</span>
                  <div>
                    <strong>Select imaging data</strong>
                    <p>Add DICOM files or a directory containing DICOM studies.</p>
                  </div>
                  {selected && <span className={"imaging-ref-completeBadge"}>✓ Complete</span>}
                </div>

                <div className={"imaging-ref-stepBody"}>
                  <div className={"imaging-ref-uploadGrid"}>
                    <div className={"imaging-ref-uploadCard"} data-tutorial-id="imaging-select-options">
                      <div className={"imaging-ref-uploadIcon"}><FileImage size={23} aria-hidden="true" /></div>
                      <div className={"imaging-ref-uploadCopy"}>
                        <strong>Add DICOM files or folders</strong>
                        <p>Select a DICOM file or a directory containing a DICOM study.</p>
                        <div className={"imaging-ref-uploadActions"}>
                          <button type="button" data-tutorial-id="imaging-choose-files" className={"imaging-ref-chooseFiles"} onClick={() => openFinder("file")}>Choose Files…</button>
                          <button type="button" className={"imaging-ref-chooseFolder"} onClick={() => openFinder("folder")}>Choose Folder…</button>
                        </div>
                      </div>
                    </div>

                  </div>

                  <div className={"imaging-ref-selectedSummary"}>
                    <span className={"imaging-ref-summaryIcon"}><FolderOpen size={21} /></span>
                    <div className={"imaging-ref-summaryCopy"}>
                      <strong>Selected data</strong>
                      <span>{selected ? "1 DICOM source  |  0 NIfTI sources" : "0 DICOM sources  |  0 NIfTI sources"}</span>
                    </div>
                    {selected && <span className={"imaging-ref-sourceChip"}>{selectionType === "folder" ? "imagingdata/" : DEMO_FILES.imaging.fileName}</span>}
                  </div>
                  {selected && (
                    <details className={"imaging-ref-selectedDetails"} onToggle={event => { if (event.currentTarget.open) setSelectedDataExpanded(true); }}>
                      <summary data-tutorial-id="imaging-view-selected-data">View Selected Data</summary>
                      <div><strong>{selectionType === "folder" ? "DICOM folder" : "DICOM file"}</strong><span>{selectionType === "folder" ? `imagingdata/ · Includes ${DEMO_FILES.imaging.fileName}` : `imagingdata/${DEMO_FILES.imaging.fileName}`}</span></div>
                    </details>
                  )}
                  <div className={"imaging-ref-sectionActions"}>
                    <button data-tutorial-id="imaging-continue-1" type="button" className={"imaging-ref-continueButton"} disabled={!selected} onClick={() => go(2)}>
                      Continue to Output Folders <span aria-hidden="true">→</span>
                    </button>
                  </div>
                </div>
              </section>
            )}

            {step === 2 && (
              <section className={`${styles.card} imaging-ref-stepCard ${tutorialEnabled && tutorialPhase === "overview" ? "imaging-guide-focus-step" : ""}`}>
                <div className={"imaging-ref-sectionHeading"}>
                  <span className={"imaging-ref-stepNumber"}>2</span>
                  <div>
                    <strong>Set output folders</strong>
                    <p>Choose where intermediate and final processed files are stored.</p>
                  </div>
                  {folderSettingsSaved && <span className={"imaging-ref-completeBadge"}>✓ Complete</span>}
                </div>
                <div className={"imaging-ref-stepBody"}>
                  <div className={"imaging-ref-outputFolderGrid"}>
                    <div className={"imaging-ref-outputFolderField"}>
                      <label htmlFor="imaging-derivatives-field">Derivatives output folder</label>
                      <div className={"imaging-ref-outputFolderInput"}>
                        <input id="imaging-derivatives-field" readOnly value={derivativesFolder} placeholder="Choose derivatives folder…" />
                        <button type="button" data-tutorial-id="imaging-derivatives-browse" className={"imaging-ref-browseButton"} onClick={() => setOutputFinderKind("derivatives")}>Browse…</button>
                      </div>
                    </div>
                    <div className={"imaging-ref-outputInfoStrip"}>
                      The derivatives folder will contain converted_nifti, scrubbed_header, scrubbed_defaced, logs, and imaging_review_state.json.
                    </div>
                    <div className={"imaging-ref-outputFolderField"}>
                      <label htmlFor="imaging-final-field">Final output folder</label>
                      <div className={"imaging-ref-outputFolderInput"}>
                        <input id="imaging-final-field" readOnly value={finalFolder} placeholder="Choose final output folder…" />
                        <button type="button" data-tutorial-id="imaging-final-browse" className={"imaging-ref-browseButton"} onClick={() => setOutputFinderKind("final")}>Browse…</button>
                      </div>
                    </div>
                    <div className={"imaging-ref-outputInfoStrip"}>
                      The final de-identified file and its associated metadata will be stored here in a BIDS-compatible format.
                    </div>
                  </div>
                  {folderSettingsSaved && <p role="status" className={"imaging-ref-outputSaved"}>✓ Folder settings saved.</p>}
                  <div className={"imaging-ref-outputFooter"}>
                    <button type="button" className={"imaging-ref-browseButton"} onClick={() => go(1)}>Back</button>
                    <div className={"imaging-ref-outputFooterRight"}>
                      <button type="button" data-tutorial-id="imaging-save-folder-settings" className={"imaging-ref-browseButton"} disabled={!derivativesFolder || !finalFolder} onClick={() => setFolderSettingsSaved(true)}>Save Folder Settings</button>
                      <button type="button" data-tutorial-id="imaging-continue-2" className={"imaging-ref-continueButton"} disabled={!folderSettingsSaved} onClick={() => go(3)}>Continue to Process & Review <span aria-hidden="true">→</span></button>
                    </div>
                  </div>
                </div>
              </section>
            )}

            {step === 3 && (

              <section className={`${styles.card} imaging-ref-stepCard ${tutorialEnabled && tutorialPhase === "overview" ? "imaging-guide-focus-step" : ""}`}>

                <div className={`${styles.cardHeader} imaging-ref-dashboardHeader`}>

                  <div className="imaging-ref-stepNumber">3</div>

                  <div>

                    <strong>Process imaging data</strong>

                    <span>Simulate the main de-identification operations.</span>

                  </div>

                </div>

                <div className={`${styles.body} imaging-ref-dashboardBody`}>

                  <div className={styles.processGrid}>

                    <ProcessButton

                      tutorialId="imaging-prepare"

                      stage="3A"

                      label="Prepare NIfTI"

                      status={prepare}

                      onClick={() => run(setPrepare, "prepare")}

                    />

                    <ProcessButton

                      tutorialId="imaging-scrub"

                      stage="3B"

                      label="Scrub Headers"

                      status={scrub}

                      disabled={prepare !== "complete"}

                      onClick={() => run(setScrub, "scrub")}

                    />

                    <ProcessButton

                      tutorialId="imaging-deface"

                      stage="3C"

                      label="Deface"

                      status={deface}

                      disabled={scrub !== "complete"}

                      onClick={() => run(setDeface, "deface")}

                    />

                  </div>

                  <div className={styles.actions}>

                    <button className={styles.secondary} onClick={() => go(2)}>Back</button>

                    <button

                      data-tutorial-id="imaging-continue-review"

                      className={styles.primary}

                      disabled={deface !== "complete"}

                      onClick={() => go(4)}

                    >

                      Continue to Review

                    </button>

                  </div>

                </div>

              </section>

            )}

            {step === 4 && (
              <section className={`${styles.card} imaging-ref-stepCard ${tutorialEnabled && tutorialPhase === "overview" ? "imaging-guide-focus-step" : ""}`}>
                <div className={`${styles.cardHeader} imaging-ref-dashboardHeader`}>
                  <div className="imaging-ref-stepNumber">4</div>
                  <div><strong>Review de-identification</strong><span>Review raw and scrubbed headers, image slices, decisions, and linked metadata.</span></div>
                </div>
                <div className={styles.body}>
                  <ImagingStep4Training
                    key={tutorialRestartKey}
                    ImageReview={ImagingNiftiReview}
                    guided={tutorialEnabled}
                    onBack={() => go(3)}
                    onComplete={() => {setReviewed(true);remember({reviewed:true});go(5);}}
                  />
                </div>
              </section>
            )}

            {step === 5 && (

              <section className={`${styles.card} imaging-ref-stepCard ${tutorialEnabled && tutorialPhase === "overview" ? "imaging-guide-focus-step" : ""}`}>

                <div className={`${styles.cardHeader} imaging-ref-dashboardHeader`}>

                  <div className="imaging-ref-stepNumber">5</div>

                  <div>

                    <strong>Metadata & BIDS</strong>

                    <span>

                      Complete the CoCANoT Imaging metadata, then create the standardized output.

                    </span>

                  </div>

                </div>

                <div className={`${styles.body} imaging-ref-dashboardBody`}>

                  <div className={styles.metadataIntro}>

                    <strong>CoCANoT Imaging Metadata</strong>

                    <p>

                      These fields mirror the Phase 1.0 Imaging metadata dictionary. Required fields are marked with an asterisk. Clinical Assessment ID is system-generated and shown as read-only.

                    </p>

                  </div>

                  <div

                    data-tutorial-id="imaging-metadata-editor"

                    className={styles.metadataEditor}

                  >

                    <div className={styles.metadataGrid}>

                      <TextField

                        label="CoCANoT Patient ID *"

                        value={metadata.patientId}

                        onChange={(value) => setField("patientId", value)}

                      />

                      <TextField

                        label="Image ID *"

                        value={metadata.imageId}

                        onChange={(value) => setField("imageId", value)}

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

                        label="Imaging Modality *"

                        value={metadata.modality}

                        options={["MRI", "CT"]}

                        onChange={(value) => setField("modality", value)}

                      />

                      {metadata.modality === "MRI" && (

                        <SelectField

                          label="MRI Sequence(s) (if applicable)"

                          value={metadata.sequence}

                          options={["T1", "T2", "FLAIR", "DWI", "SWI"]}

                          onChange={(value) => setField("sequence", value)}

                        />

                      )}

                      <SelectField

                        label="Timing Relative to Surgery *"

                        value={metadata.timing}

                        options={[

                          "Preoperative",

                          "Intraoperative",

                          "Immediate Postoperative (<30 days after surgery)",

                          "Follow-up (>30 days after surgery)",

                          "Unknown",

                        ]}

                        onChange={(value) => setField("timing", value)}

                      />

                    </div>

                    <MultiSelectField

                      label="Purpose of Imaging *"

                      values={metadata.purpose}

                      options={PURPOSE_OPTIONS}

                      onToggle={(value) => toggleMulti("purpose", value)}

                    />

                    <MultiSelectField

                      label="Imaging Findings *"

                      values={metadata.findings}

                      options={FINDING_OPTIONS}

                      onToggle={(value) => toggleMulti("findings", value)}

                    />

                    <label className={styles.metadataFieldFull}>

                      <span>Comments</span>

                      <textarea

                        value={metadata.comments}

                        onChange={(event) => setField("comments", event.target.value)}

                        placeholder="Optional notes. Avoid protected health information."

                      />

                    </label>

                    <div className={styles.metadataSaveBar}>

                      <div>

                        <strong>{metadataSaved ? "Metadata saved ✓" : "Unsaved metadata changes"}</strong>

                        <span>

                          In the full CoCANoT application, these values are validated against the active machine-readable dictionary before export.

                        </span>

                      </div>

                      <button

                        type="button"

                        className={styles.secondary}

                        onClick={() => setMetadataSaved(true)}

                      >

                        Save Metadata

                      </button>

                    </div>

                  </div>

                  {metadataSaved && (

                    <div className={styles.output}>

                      <strong>Metadata ready for standardized export</strong>

                      <code>sub-001/anat/sub-001_T1w.nii.gz</code>

                      <code>sub-001/anat/sub-001_T1w.json</code>

                    </div>

                  )}

                  <div className={styles.actions}>

                    <button className={styles.secondary} onClick={() => go(4)}>Back</button>

                    {!exported ? (

                      <button

                        data-tutorial-id="imaging-export"

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

                        data-tutorial-id="imaging-view-linked"

                        className={styles.primary}

                        onClick={() => {

                          setLinkedRecordVisited(true);

                          setShowLinkedRecord(true);
                          setLinkedGuideStep(0);
                          setLinkedGuideStarted(Boolean(tutorialEnabled));
                          setLinkedGuidePhase(tutorialEnabled ? "overview" : "idle");

                        }}

                      >

                        Next: View Linked Image

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


// Bundle MRI examples from src/demoData/imaging; public/demoData/imaging is also supported.
const NIFTI_ASSET_URLS = import.meta.glob(["../demoData/imaging/*sample.nii.gz", "./demoData/imaging/*sample.nii.gz"], {
  eager: true,
  query: "?url",
  import: "default",
});

const NIFTI_REVIEW_CSS = `
.imaging-nifti-review { margin-bottom: 18px; }
.imaging-nifti-review .nifti-header { display:flex; gap:9px; align-items:center; justify-content:space-between; flex-wrap:wrap; margin-bottom:12px; }
.imaging-nifti-review .nifti-header strong {font-size:14px;color:#25394f;}
.imaging-nifti-review .nifti-source {font-size:11px;color:#6d8092;}
.imaging-nifti-review .nifti-message {padding:15px;border:1px solid #d9e4ec;border-radius:9px;background:#f8fbfd;color:#52687d;font-size:12px;line-height:1.6;}
.imaging-nifti-review .nifti-columns {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:11px;}
.imaging-nifti-review .nifti-panel {overflow:hidden;border:1px solid #dbe4ea;border-radius:9px;background:#111a24;min-width:0;}
.imaging-nifti-review .nifti-panel-title {display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 10px;background:#f6f9fb;color:#40576d;font-size:11px;font-weight:800;}
.imaging-nifti-review .nifti-panel-title span {font-size:10px;font-weight:600;color:#8493a3;}
.imaging-nifti-review canvas {width:100%;height:225px;display:block;object-fit:contain;image-rendering:auto;}
.imaging-nifti-review .nifti-section-label {display:flex;align-items:center;justify-content:space-between;gap:8px;margin:16px 0 9px;color:#25394f;font-size:13px;font-weight:800;}
.imaging-nifti-review .nifti-section-label:first-of-type {margin-top:6px;}
.imaging-nifti-review .nifti-sliders {margin-top:17px;padding:15px;border:1px solid #dbe4eb;border-radius:9px;background:#f9fbfd;display:grid;gap:12px;}
.imaging-nifti-review .nifti-slider {display:grid;grid-template-columns:90px minmax(0,1fr) 84px;align-items:center;gap:12px;color:#52687d;font-size:11px;}
.imaging-nifti-review .nifti-slider input {width:100%;accent-color:#2470ae;cursor:pointer;}
.imaging-nifti-review .nifti-slider output {font-size:11px;color:#325a79;text-align:right;font-weight:750;font-variant-numeric:tabular-nums;}
.imaging-nifti-review .nifti-help {margin:10px 0 0;font-size:11px;color:#718395;line-height:1.5;}
@media(max-width:760px){.imaging-nifti-review .nifti-columns{grid-template-columns:1fr 1fr;}.imaging-nifti-review canvas{height:185px;}.imaging-nifti-review .nifti-slider{grid-template-columns:78px minmax(0,1fr) 68px;gap:7px;}}
@media(max-width:460px){.imaging-nifti-review .nifti-columns{grid-template-columns:1fr;}.imaging-nifti-review canvas{height:250px;}}
`;

function getNiftiAssetUrl(name) {
  return NIFTI_ASSET_URLS[`../demoData/imaging/${name}`] || NIFTI_ASSET_URLS[`./demoData/imaging/${name}`] || `/demoData/imaging/${name}`;
}

async function fetchNifti(name, signal) {
  const assetUrl = getNiftiAssetUrl(name);
  const response = await fetch(assetUrl, { signal });
  if (!response.ok) throw new Error(`Could not load ${name} (HTTP ${response.status}).`);
  const bytes = await response.arrayBuffer();
  const gzip = new Uint8Array(bytes);
  let data = bytes;
  if (gzip[0] === 31 && gzip[1] === 139) {
    if (!('DecompressionStream' in window)) {
      throw new Error('This browser cannot decompress .nii.gz files. Use a current Chrome, Edge, Safari, or Firefox browser.');
    }
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    data = await new Response(stream).arrayBuffer();
  }
  return decodeNifti(data);
}

function decodeNifti(bytes) {
  const view = new DataView(bytes);
  if (bytes.byteLength < 352) throw new Error('NIfTI file is too short.');
  let little = true;
  if (view.getInt32(0, true) !== 348) {
    if (view.getInt32(0, false) !== 348) throw new Error('Only NIfTI-1 .nii.gz volumes are supported in the web preview.');
    little = false;
  }
  const dim = [view.getInt16(42, little), view.getInt16(44, little), view.getInt16(46, little)];
  if (dim.some(n => n < 1 || n > 4096)) throw new Error('Invalid NIfTI volume dimensions.');
  const datatype = view.getInt16(70, little);
  const readers = {
    2: [1, (o) => view.getUint8(o)],
    4: [2, (o) => view.getInt16(o, little)],
    8: [4, (o) => view.getInt32(o, little)],
    16: [4, (o) => view.getFloat32(o, little)],
    64: [8, (o) => view.getFloat64(o, little)],
    256: [1, (o) => view.getInt8(o)],
    512: [2, (o) => view.getUint16(o, little)],
    768: [4, (o) => view.getUint32(o, little)],
  };
  const reader = readers[datatype];
  if (!reader) throw new Error(`Unsupported NIfTI datatype: ${datatype}.`);
  const offset = Math.max(352, Math.floor(view.getFloat32(108, little)));
  const voxelCount = dim[0] * dim[1] * dim[2];
  if (offset + voxelCount * reader[0] > bytes.byteLength) {
    throw new Error('NIfTI image data is incomplete.');
  }
  const slope = view.getFloat32(112, little);
  const intercept = view.getFloat32(116, little);
  const valueAt = (x, y, z) => {
    const i = x + dim[0] * (y + dim[1] * z);
    const raw = reader[1](offset + i * reader[0]);
    return raw * (slope && Number.isFinite(slope) ? slope : 1) + (Number.isFinite(intercept) ? intercept : 0);
  };
  // Percentile intensity window from a sparse sample across the entire 3D volume.
  const sample = [];
  const stride = Math.max(1, Math.floor(voxelCount / 18000));
  for (let i = 0; i < voxelCount; i += stride) {
    const val = reader[1](offset + i * reader[0]);
    if (Number.isFinite(val)) sample.push(val);
  }
  sample.sort((a, b) => a - b);
  const pick = (q) => sample[Math.floor((sample.length - 1) * q)] ?? 0;
  const windowMin = pick(0.02);
  const windowMax = pick(0.99);
  return { dim, valueAt, low: windowMin * (slope || 1) + intercept, high: windowMax * (slope || 1) + intercept };
}

function NiftiSliceCanvas({ volume, orientation, slice }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !volume) return;
    const [nx, ny, nz] = volume.dim;
    const width = orientation === 'sagittal' ? ny : nx;
    const height = orientation === 'axial' ? ny : nz;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) return;
    const image = context.createImageData(width, height);
    const range = Math.max(1e-10, volume.high - volume.low);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const a = width - 1 - x;
        const b = height - 1 - y;
        const value = orientation === 'axial'
          ? volume.valueAt(a, b, slice)
          : orientation === 'coronal'
            ? volume.valueAt(a, slice, b)
            : volume.valueAt(slice, a, b);
        const intensity = Math.max(0, Math.min(255, Math.round(((value - volume.low) / range) * 255)));
        const pos = (y * width + x) * 4;
        image.data[pos] = intensity;
        image.data[pos + 1] = intensity;
        image.data[pos + 2] = intensity;
        image.data[pos + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
  }, [volume, orientation, slice]);
  return <canvas ref={canvasRef} role="img" aria-label={`${orientation} MRI slice ${slice + 1}`} />;
}

function ImagingNiftiReview() {
  const [volumes, setVolumes] = useState(null);
  const [error, setError] = useState('');
  const [slices, setSlices] = useState({ x: 0, y: 0, z: 0 });
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchNifti('rawsample.nii.gz', controller.signal),
      fetchNifti('defacedsample.nii.gz', controller.signal),
    ]).then(([raw, defaced]) => {
      if (controller.signal.aborted) return;
      setVolumes({ raw, defaced });
      setSlices({ x: Math.floor(raw.dim[0] / 2), y: Math.floor(raw.dim[1] / 2), z: Math.floor(raw.dim[2] / 2) });
    }).catch(err => { if (!controller.signal.aborted) setError(err.message || String(err)); });
    return () => controller.abort();
  }, []);
  const axes = [
    { name: 'Sagittal', key: 'x', dim: 0, orientation: 'sagittal' },
    { name: 'Coronal', key: 'y', dim: 1, orientation: 'coronal' },
    { name: 'Axial', key: 'z', dim: 2, orientation: 'axial' },
  ];
  return (
    <div className="imaging-nifti-review">
      <div className="nifti-header">
        <strong>Interactive raw versus defaced image review</strong>
        <span className="nifti-source">Synthetic example · NIfTI (.nii.gz)</span>
      </div>
      {error ? (
        <div className="nifti-message" role="alert">
          {error} Ensure <code>rawsample.nii.gz</code> and <code>defacedsample.nii.gz</code> are in <code>src/demoData/imaging/</code> (or <code>public/demoData/imaging/</code>).
        </div>
      ) : !volumes ? (
        <div className="nifti-message" role="status">Loading raw and defaced MRI volumes…</div>
      ) : (
        <>
          {[
            { key: 'raw', label: 'Raw Image', filename: 'rawsample.nii.gz' },
            { key: 'defaced', label: 'Defaced Image', filename: 'defacedsample.nii.gz' },
          ].map(group => (
            <div key={group.key}>
              <div className="nifti-section-label">
                <span>{group.label}</span>
                <span className="nifti-source">{group.filename}</span>
              </div>
              <div className="nifti-columns">
                {axes.map(axis => {
                  const rawLast = volumes.raw.dim[axis.dim] - 1;
                  const thisLast = volumes[group.key].dim[axis.dim] - 1;
                  const normalized = rawLast > 0 ? slices[axis.key] / rawLast : 0;
                  const imageSlice = Math.min(thisLast, Math.max(0, Math.round(normalized * thisLast)));
                  return (
                    <div className="nifti-panel" key={axis.key}>
                      <div className="nifti-panel-title">{axis.name} <span>{imageSlice + 1} / {thisLast + 1}</span></div>
                      <NiftiSliceCanvas volume={volumes[group.key]} orientation={axis.orientation} slice={imageSlice} />
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
          <div className="nifti-sliders" data-tutorial-id="imaging-review-sliders">
            {axes.map(axis => (
              <label className="nifti-slider" key={axis.key}>
                <span>{axis.name}</span>
                <input type="range" min="0" max={volumes.raw.dim[axis.dim] - 1} step="1"
                  value={slices[axis.key]}
                  onChange={event => setSlices(current => ({ ...current, [axis.key]: Number(event.target.value) }))}
                  aria-label={`${axis.name} slice`} />
                <output>{slices[axis.key] + 1} / {volumes.raw.dim[axis.dim]}</output>
              </label>
            ))}
          </div>
          <p className="nifti-help">Move the sliders through the MRI volume. Each adjustment updates the original and defaced views together.</p>
        </>
      )}
    </div>
  );
}


const LINKED_IMAGING_CSS = `
.imaging-linked-review { width:100%; }
.imaging-linked-public-review .imaging-linked-guide-next{position:fixed;z-index:1300;right:24px;bottom:28px;box-shadow:0 6px 22px rgba(0,0,0,.3)}
.imaging-linked-public-review .imaging-guide-focus-step{position:relative!important;z-index:1202!important;outline:4px solid #80cdff!important;outline-offset:5px!important;background:white!important;box-shadow:0 0 0 9px rgba(80,177,239,.27)!important}
.imaging-linked-review .linked-review-back {display:inline-flex;align-items:center;gap:7px;background:none;border:0;color:#1767b1;font-size:13px;font-weight:750;cursor:pointer;padding:8px 0;}
.imaging-linked-review .linked-review-header {display:flex;gap:13px;align-items:flex-start;margin:8px 0 18px;}
.imaging-linked-review .linked-review-icon {display:grid;place-items:center;flex:none;width:48px;height:48px;border-radius:10px;background:#e8f2f8;color:#2b6684;}
.imaging-linked-review .linked-review-header small {display:block;letter-spacing:.12em;color:#47728b;font-size:10px;font-weight:850;}
.imaging-linked-review .linked-review-header h2 {font-family:Georgia,serif;font-size:28px;color:#172a43;margin:5px 0;}
.imaging-linked-review .linked-review-header p {font-size:13px;color:#61778b;line-height:1.5;margin:0;}
.imaging-linked-review .linked-review-top {display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;}
.imaging-linked-review .linked-review-edit,.imaging-linked-review .linked-review-refresh,.imaging-linked-review .linked-review-save {display:inline-flex;align-items:center;gap:7px;padding:9px 13px;border:1px solid #2470ae;border-radius:8px;background:#fff;color:#1767b1;font-size:12px;font-weight:800;cursor:pointer;}
.imaging-linked-review .linked-review-save {background:#2470ae;color:#fff;}
.imaging-linked-review .linked-review-metadata-actions {display:flex;justify-content:flex-end;margin:-3px 0 16px;}
.imaging-linked-review .linked-review-metadata-actions .linked-review-edit {background:#2470ae;color:#fff;}
.imaging-linked-review .linked-review-card {margin:14px 0;background:#fff;border:1px solid #d5e0e8;border-radius:11px;overflow:hidden;}
.imaging-linked-review .linked-review-card-head {padding:14px 16px;background:#f7fafc;border-bottom:1px solid #dce5ec;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;}
.imaging-linked-review .linked-review-card-head strong {font-size:13px;color:#29465f;}
.imaging-linked-review .linked-review-card-head span {font-size:11px;color:#6b7f91;}
.imaging-linked-review .linked-review-metadata {display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:15px;padding:17px;}
.imaging-linked-review .linked-review-metadata div {min-width:0;}
.imaging-linked-review .linked-review-metadata dt {font-size:10px;font-weight:800;color:#6b7f91;margin-bottom:5px;}
.imaging-linked-review .linked-review-metadata dd {font-size:12px;font-weight:700;color:#243d55;margin:0;overflow-wrap:anywhere;}
.imaging-linked-review .linked-review-editor {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;padding:17px;}
.imaging-linked-review .linked-review-editor label {display:grid;gap:6px;font-size:11px;font-weight:750;color:#3c5167;}
.imaging-linked-review .linked-review-editor input,.imaging-linked-review .linked-review-editor select,.imaging-linked-review .linked-review-editor textarea {width:100%;min-width:0;padding:10px;border:1px solid #cbd7e1;border-radius:7px;background:white;color:#22354c;font:inherit;font-size:12px;}
.imaging-linked-review .linked-review-editor textarea {min-height:80px;resize:vertical;}
.imaging-linked-review .linked-review-editor .linked-review-wide {grid-column:1/-1;}
.imaging-linked-review .linked-review-editor .linked-review-checkboxes {display:flex;flex-wrap:wrap;gap:7px;}
.imaging-linked-review .linked-review-editor .linked-review-checkboxes label {display:flex;align-items:center;gap:6px;padding:7px;border:1px solid #e1e7ec;border-radius:6px;background:#fafcfd;font-size:10px;font-weight:550;}
.imaging-linked-review .linked-review-editor .linked-review-checkboxes input {width:auto;}
.imaging-linked-review .linked-review-editor-actions {display:flex;justify-content:flex-end;gap:9px;grid-column:1/-1;}
.imaging-linked-review .linked-review-views {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:16px;}
.imaging-linked-review .linked-review-panel {min-width:0;border:1px solid #dce5ec;border-radius:8px;overflow:hidden;background:#111a24;}
.imaging-linked-review .linked-review-panel .linked-review-label {display:block;padding:9px 11px;color:#486176;font-size:11px;font-weight:850;background:#f7fafc;}
.imaging-linked-review .linked-review-panel canvas {width:100%;height:255px;display:block;object-fit:contain;}
.imaging-linked-review .linked-review-sliders {padding:3px 16px 16px;display:grid;gap:7px;}
.imaging-linked-review .linked-review-slider {display:grid;grid-template-columns:90px 1fr 70px;align-items:center;gap:10px;padding:8px 0;font-size:11px;color:#506a7f;}
.imaging-linked-review .linked-review-slider input {width:100%;accent-color:#2470ae;}
.imaging-linked-review .linked-review-slider output {text-align:right;font-weight:750;white-space:nowrap;color:#304c64;}
.imaging-linked-review .linked-review-note {padding:0 16px 16px;font-size:11px;color:#6b7f91;}
@media(max-width:800px){.imaging-linked-review .linked-review-views{grid-template-columns:1fr;}.imaging-linked-review .linked-review-panel canvas{height:285px;}.imaging-linked-review .linked-review-editor{grid-template-columns:1fr;}}
`;

function ImagingLinkedImageReview({ metadata, onSaveMetadata, onBack, onGuideAction }) {
  const [volume, setVolume] = useState(null);
  const [error, setError] = useState('');
  const [slices, setSlices] = useState({ x: 0, y: 0, z: 0 });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => ({ ...metadata }));
  const [savedNotice, setSavedNotice] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    setVolume(null);
    fetchNifti('defacedsample.nii.gz', controller.signal).then(result => {
      if (controller.signal.aborted) return;
      setVolume(result);
      setSlices({ x: Math.floor(result.dim[0]/2), y: Math.floor(result.dim[1]/2), z: Math.floor(result.dim[2]/2) });
    }).catch(err => { if (!controller.signal.aborted) setError(err.message || String(err)); });
    return () => controller.abort();
  }, [reloadKey]);

  function beginEdit() { onGuideAction?.("edit"); setDraft({ ...metadata, purpose:[...(metadata.purpose || [])], findings:[...(metadata.findings || [])] }); setEditing(true); setSavedNotice(false); }
  function changeField(field, value) { setDraft(current => ({ ...current, [field]: value })); }
  function toggleField(field, option) {
    setDraft(current => {
      const values = current[field] || [];
      const next = values.includes(option) ? values.filter(item => item !== option) : [...values, option];
      return { ...current, [field]: next };
    });
  }
  const metadataRows = [
    ['CoCANoT Patient ID', metadata.patientId], ['Image ID', metadata.imageId],
    ['Clinical Assessment ID', metadata.clinicalAssessmentId], ['Surgery ID', metadata.surgeryId],
    ['Imaging Modality', metadata.modality], ['Imaging Sequence', metadata.sequence],
    ['Timing Relative to Surgery', metadata.timing],
    ['Purpose of Imaging', (metadata.purpose || []).join(', ')],
    ['Imaging Findings', (metadata.findings || []).join(', ')],
    ['Comments', metadata.comments || '—'],
  ];
  const axes = [
    { name:'Axial', key:'z', dim:2, orientation:'axial' },
    { name:'Coronal', key:'y', dim:1, orientation:'coronal' },
    { name:'Sagittal', key:'x', dim:0, orientation:'sagittal' },
  ];
  return (
    <div className="imaging-linked-review">
      <style>{LINKED_IMAGING_CSS}</style>
      <div className="linked-review-top">
        <button type="button" className="linked-review-back" onClick={onBack}><ArrowLeft size={16}/> Back to Imaging Workflow</button>
      </div>
      <section className="linked-review-card">
        <div className="linked-review-card-head"><strong>Linked metadata</strong><span>Image record {metadata.imageId}</span></div>
        {editing ? (
          <div className="linked-review-editor" data-tutorial-id="imaging-linked-metadata-editor">
            {[
              ['patientId','CoCANoT Patient ID'],['imageId','Image ID'],
              ['surgeryId','Surgery ID'],
            ].map(([key,label]) => <label key={key}>{label}<input value={draft[key] || ''} onChange={e => changeField(key,e.target.value)}/></label>)}
            <label>Clinical Assessment ID<input value={draft.clinicalAssessmentId || ''} readOnly title="System-generated link"/></label>
            <label>Imaging Modality<select value={draft.modality || 'MRI'} onChange={e => changeField('modality',e.target.value)}>{['MRI','CT','PET','Other'].map(v => <option key={v}>{v}</option>)}</select></label>
            <label>Imaging Sequence<select value={draft.sequence || 'T1'} onChange={e => changeField('sequence',e.target.value)}>{['T1','T2','FLAIR','DWI','SWI','Other'].map(v => <option key={v}>{v}</option>)}</select></label>
            <label>Timing Relative to Surgery<select value={draft.timing || 'Preoperative'} onChange={e => changeField('timing',e.target.value)}>{['Preoperative','Intraoperative','Immediate Postoperative (<30 days after surgery)','Follow-up (>30 days after surgery)','Unknown'].map(v => <option key={v}>{v}</option>)}</select></label>
            <div className="linked-review-wide"><strong className="text-xs">Purpose of Imaging</strong><div className="linked-review-checkboxes">{PURPOSE_OPTIONS.map(option => <label key={option}><input type="checkbox" checked={(draft.purpose || []).includes(option)} onChange={() => toggleField('purpose',option)}/>{option}</label>)}</div></div>
            <div className="linked-review-wide"><strong className="text-xs">Imaging Findings</strong><div className="linked-review-checkboxes">{FINDING_OPTIONS.map(option => <label key={option}><input type="checkbox" checked={(draft.findings || []).includes(option)} onChange={() => toggleField('findings',option)}/>{option}</label>)}</div></div>
            <label className="linked-review-wide">Comments<textarea value={draft.comments || ''} onChange={e => changeField('comments',e.target.value)} placeholder="Optional notes. Avoid protected health information."/></label>
            <div className="linked-review-editor-actions"><button className="linked-review-refresh" type="button" onClick={() => setEditing(false)}>Cancel</button><button className="linked-review-save" data-tutorial-id="imaging-linked-save" type="button" onClick={() => { onSaveMetadata(draft); setEditing(false); setSavedNotice(true); onGuideAction?.("save"); }}>Save Metadata</button></div>
          </div>
        ) : (
          <dl className="linked-review-metadata">{metadataRows.map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value || '—'}</dd></div>)}</dl>
        )}
      </section>
      {!editing && (
        <div className="linked-review-metadata-actions">
          <button type="button" className="linked-review-edit" data-tutorial-id="imaging-linked-edit" onClick={beginEdit}>
            Review / Edit Metadata
          </button>
        </div>
      )}
      {savedNotice && <p role="status" className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">Imaging metadata updated for this simulated linked record.</p>}
      <section className="linked-review-card">
        <div className="linked-review-card-head"><div><strong>defacedsample.nii.gz</strong><span style={{display:'block',marginTop:4}}>{volume ? `Shape: ${volume.dim.join(' × ')}` : 'De-identified NIfTI image'}</span></div><button type="button" className="linked-review-refresh" onClick={() => setReloadKey(k => k+1)}>Refresh</button></div>
        {error ? <div className="nifti-message" role="alert" style={{margin:16}}>{error}. Check <code>src/demoData/imaging/defacedsample.nii.gz</code>.</div> : !volume ? <div className="nifti-message" role="status" style={{margin:16}}>Loading linked NIfTI…</div> : <>
          <div className="linked-review-views" data-tutorial-id="imaging-linked-views">{axes.map(axis => <div className="linked-review-panel" key={axis.key}><span className="linked-review-label">{axis.name}</span><NiftiSliceCanvas volume={volume} orientation={axis.orientation} slice={slices[axis.key]}/></div>)}</div>
          <div className="linked-review-sliders" data-tutorial-id="imaging-linked-sliders">{axes.slice().reverse().map(axis => <label className="linked-review-slider" key={axis.key}><span>{axis.name} {axis.key.toUpperCase()}</span><input type="range" min="0" max={volume.dim[axis.dim]-1} value={slices[axis.key]} onChange={e => (setSlices(current => ({...current,[axis.key]: Number(e.target.value)})), onGuideAction?.("slider"))}/><output>{slices[axis.key]+1} / {volume.dim[axis.dim]}</output></label>)}</div>
          <p className="linked-review-note">All three views are generated from the actual defaced NIfTI volume. Move the sliders to inspect individual slices.</p>
        </>}
      </section>
    </div>
  );
}

function ProcessButton({ tutorialId, stage, label, status, onClick, disabled }) {

  return (

    <button

      data-tutorial-id={tutorialId}

      className={styles.processButton}

      disabled={disabled || status === "running"}

      onClick={onClick}

    >

      <span>{stage}</span>

      <strong>{label}</strong>

      <small>Simulated browser-only processing step.</small>

      <em>

        {status === "complete"

          ? "Complete ✓"

          : status === "running"

            ? "Processing..."

            : "Not started"}

      </em>

    </button>

  );

}

function TextField({ label, value, onChange, readOnly, help }) {

  return (

    <label className={styles.metadataField}>

      <span>{label}</span>

      <input

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


const IMAGING_REFERENCE_CSS = '.imaging-ref-stepCard { padding: 0 !important; overflow: hidden; border: 1px solid #bed2e1 !important; border-radius: 12px !important; box-shadow: 0 7px 22px rgba(33,69,100,.05); }\n.imaging-ref-sectionHeading { display:flex; align-items:center; gap:13px; min-height:76px; padding:14px 18px; background:#f9fbfd; border-bottom:1px solid #e4ebf1; }\n.imaging-ref-stepNumber { flex:0 0 36px; height:36px; display:grid; place-items:center; border-radius:9px; background:#eaf3f9; color:#2c688b; font-size:12px; font-weight:900; }\n.imaging-ref-sectionHeading > div { flex:1; min-width:0; }\n.imaging-ref-sectionHeading strong { display:block; color:#17233a; font-size:15px; }\n.imaging-ref-sectionHeading p { margin:4px 0 0; color:#708295; font-size:12px; line-height:1.45; }\n.imaging-ref-completeBadge { color:#2f7754; font-size:11px; font-weight:800; white-space:nowrap; }\n.imaging-ref-stepBody { padding:20px; }\n.imaging-ref-uploadGrid { display:grid; grid-template-columns:minmax(0,1fr); gap:14px; }\n.imaging-ref-uploadCard { display:grid; grid-template-columns:48px minmax(0,1fr); gap:14px; min-height:155px; padding:18px; border:1px dashed #aebfcd; border-radius:11px; background:#fafcfe; }\n.imaging-ref-uploadIcon { width:44px; height:44px; display:grid; place-items:center; border-radius:10px; background:#e8f2f8; color:#2f6d91; }\n.imaging-ref-uploadCopy { display:flex; flex-direction:column; align-items:flex-start; min-width:0; }\n.imaging-ref-uploadCopy strong { color:#24364f; font-size:14px; }\n.imaging-ref-uploadCopy p { margin:5px 0 0; color:#6a7d8f; font-size:12px; line-height:1.5; }\n.imaging-ref-uploadActions { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:auto; padding-top:15px; }\n.imaging-ref-chooseFiles, .imaging-ref-chooseFolder { cursor:pointer; min-height:35px; padding:0 13px; border-radius:7px; font-size:12px; font-weight:800; }\n.imaging-ref-chooseFiles { border:1px solid #2470ae; background:#2470ae; color:white; }\n.imaging-ref-chooseFiles:hover { background:#1f6298; }\n.imaging-ref-chooseFolder { border:1px solid #c8d5df; color:#355068; background:#fff; }\n.imaging-ref-chooseFolder:hover { background:#e8f2f8; }\n.imaging-ref-helpCard { padding:17px; border:1px solid #dce5ec; border-radius:11px; background:#f7fafc; }\n.imaging-ref-helpCard strong { color:#24364f; font-size:13px; }\n.imaging-ref-helpCard p { color:#61778b; font-size:12px; line-height:1.6; margin:8px 0 14px; }\n.imaging-ref-helpCard span { display:flex; align-items:center; gap:7px; overflow-wrap:anywhere; color:#376f92; font-size:11px; font-weight:750; }\n.imaging-ref-selectedSummary { display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin-top:15px; padding:14px 15px; border:1px solid #d9e3eb; border-radius:10px; background:white; }\n.imaging-ref-summaryIcon { display:grid; place-items:center; flex:0 0 40px; height:40px; border-radius:9px; background:#eff5f9; color:#436f8b; }\n.imaging-ref-summaryCopy { flex:1; min-width:150px; display:grid; gap:4px; }\n.imaging-ref-summaryCopy strong { color:#26384f; font-size:13px; }\n.imaging-ref-summaryCopy span { color:#718395; font-size:11px; }\n.imaging-ref-sourceChip { max-width:100%; padding:7px 10px; border-radius:7px; background:#eaf6ef; color:#2f7754; font-size:11px; overflow-wrap:anywhere; }\n.imaging-ref-selectedDetails { padding:10px 15px 0; font-size:12px; color:#236b9e; }\n.imaging-ref-selectedDetails summary { cursor:pointer; font-weight:750; }\n.imaging-ref-selectedDetails > div { display:grid; gap:4px; padding:12px; margin-top:9px; background:#fafcfd; border:1px solid #e1e7ec; border-radius:8px; color:#52687d; }\n.imaging-ref-sectionActions { display:flex; justify-content:flex-end; margin-top:18px; padding-top:15px; border-top:1px solid #e7edf2; }\n.imaging-ref-continueButton { display:inline-flex; align-items:center; gap:9px; justify-content:center; padding:0 15px; min-height:40px; border:1px solid #2470ae; border-radius:8px; background:#2470ae; color:white; font-size:12px; font-weight:800; cursor:pointer; }\n.imaging-ref-continueButton:hover:not(:disabled) { background:#1f6298; }\n.imaging-ref-continueButton:disabled { cursor:not-allowed; opacity:.5; }\n@media(max-width:760px) { .imaging-ref-uploadGrid{grid-template-columns:1fr;} .imaging-ref-sectionHeading{align-items:flex-start;} .imaging-ref-stepBody{padding:14px;} .imaging-ref-sectionActions .imaging-ref-continueButton{width:100%;} }\n\n.imaging-ref-outputFolderGrid { display:grid; grid-template-columns:minmax(0,1fr); gap:11px; }\n.imaging-ref-outputFolderField { display:grid; gap:7px; }\n.imaging-ref-outputFolderField label { color:#3c5167; font-size:12px; font-weight:800; }\n.imaging-ref-outputFolderInput { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; }\n.imaging-ref-outputFolderInput input { width:100%; min-width:0; height:38px; padding:0 10px; border:1px solid #cbd7e1; border-radius:7px; background:white; color:#22354c; font:inherit; font-size:12px; }\n.imaging-ref-browseButton { min-height:38px; display:inline-flex; align-items:center; justify-content:center; gap:7px; padding:0 13px; border:1px solid #c8d5df; border-radius:8px; background:#fff; color:#355068; font-size:12px; font-weight:800; cursor:pointer; }\n.imaging-ref-browseButton:hover:not(:disabled) { border-color:#a7bbc9; background:#f8fafc; }\n.imaging-ref-browseButton:disabled { opacity:.5; cursor:not-allowed; }\n.imaging-ref-outputInfoStrip { padding:10px 12px; border:1px solid #dce5ec; border-radius:8px; background:#f7fafc; color:#61778b; font-size:12px; line-height:1.5; }\n.imaging-ref-outputSaved { padding:10px 12px; margin-top:12px; border:1px solid #bfd9c9; border-radius:8px; background:#fbfefc; color:#2f7754; font-size:12px; font-weight:750; }\n.imaging-ref-outputFooter { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-top:18px; padding-top:15px; border-top:1px solid #e7edf2; }\n.imaging-ref-outputFooterRight { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:9px; }\n@media (max-width:760px) { .imaging-ref-outputFooter,.imaging-ref-outputFooterRight{align-items:stretch;flex-direction:column;} .imaging-ref-outputFolderInput{grid-template-columns:1fr;} }\n';

function ImagingFakeFinder({ guided = false, mode, folderOpen, onFolderOpen, onBack, onClose, onChoose }) {
  const fileName = "testMRIScan.dcm";
  const isFile = mode === "file";
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/55 px-4 py-6" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="imaging-finder-title" className="flex w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-4">
          <div>
            <h3 id="imaging-finder-title" className="font-serif text-xl text-navy">{isFile ? "Open imaging file" : "Select imaging folder"}</h3>
            <p className="mt-1 text-xs text-slate-600">Simulated file browser · Synthetic data only</p>
          </div>
          <button type="button" aria-label="Close file browser" onClick={onClose} className="rounded-lg p-2 text-slate-600 hover:bg-slate-200"><X size={20}/></button>
        </header>
        <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-3 text-sm text-slate-600">
          <button type="button" onClick={onBack} disabled={!folderOpen} aria-label="Go back" className="rounded-lg p-2 hover:bg-slate-100 disabled:opacity-30"><ArrowLeft size={17}/></button>
          <span className="font-medium">Demo Files / {folderOpen ? "imagingdata" : ""}</span>
        </div>
        {guided && <ImagingPickerGuidance>{!folderOpen
          ? "Click the highlighted imagingdata folder to open it."
          : isFile ? "Select the highlighted testMRIScan.dcm file."
          : "The scan is inside this folder. Click Select This Folder below to confirm."}</ImagingPickerGuidance>}
        <div className="min-h-56 px-5 py-5">
          {!folderOpen ? (
            <button type="button" data-tutorial-id="imaging-finder-folder" onClick={onFolderOpen} className={`flex w-full items-center gap-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-4 text-left text-navy hover:border-sky-400 hover:bg-sky-100 ${guided ? "imaging-picker-target" : ""}`}>
              <Folder size={32} className="shrink-0 fill-sky-200 text-sky-700"/>
              <span><strong className="block">imagingdata</strong><small className="text-slate-600">Folder · Contains a synthetic DICOM scan</small></span>
            </button>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm text-slate-600"><Folder size={17}/> imagingdata</div>
              <button type="button" data-tutorial-id="imaging-finder-file" disabled={!isFile} onClick={() => isFile && onChoose("file")} className={`flex w-full items-center gap-4 rounded-xl border px-4 py-4 text-left ${guided && isFile ? "imaging-picker-target" : ""} ${isFile ? "border-sky-200 bg-sky-50 text-navy hover:border-sky-400 hover:bg-sky-100" : "cursor-default border-slate-200 bg-slate-50 text-slate-600"}`}>
                <FileImage size={30} className="shrink-0 text-sky-700"/>
                <span><strong className="block">{fileName}</strong><small className="text-slate-600">Synthetic DICOM image{isFile ? " · Click to open" : " · Included when the folder is selected"}</small></span>
              </button>
            </div>
          )}
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-5 py-4">
          <p className="text-xs text-slate-600">{isFile ? "Open imagingdata, then click the DCM file." : "Choose the imagingdata folder to include its sample file."}</p>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100">Cancel</button>
            {!isFile && <button type="button" data-tutorial-id="imaging-finder-select-folder" disabled={!folderOpen} onClick={() => onChoose("folder")} className={`rounded-full bg-navy px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40 ${guided && folderOpen ? "imaging-picker-target imaging-picker-confirm-target" : ""}`}>Select This Folder{guided && folderOpen && <span className="imaging-picker-confirm-hint">CLICK HERE TO CONFIRM ↓</span>}</button>}
          </div>
        </footer>
      </section>
    </div>
  );
}

function ImagingPickerGuidance({ children }) {
  return <div className="imaging-picker-guide" role="status">
    <strong>GUIDE · YOUR NEXT ACTION</strong>
    <span>{children}</span>
    <span aria-hidden="true" className="imaging-picker-guide-arrow">↓</span>
  </div>;
}

const FOLDERS = ["imaging_derivatives", "imaging_final"];

/** A simulated folder chooser; it never accesses the visitor's filesystem. */
function ImagingOutputFinder({ guided = false, kind, onChoose, onClose }) {
  const expected = kind === "derivatives" ? FOLDERS[0] : FOLDERS[1];
  const [selectedFolder, setSelectedFolder] = useState("");
  const ready = selectedFolder === expected;

  useEffect(() => {
    const onKeyDown = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="imaging-output-finder-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="imaging-output-finder-title" className="imaging-output-finder">
        <header>
          <div>
            <h3 id="imaging-output-finder-title">Select {kind === "derivatives" ? "derivatives" : "final output"} folder</h3>
            <p>Simulated folder browser · No files are written</p>
          </div>
          <button type="button" aria-label="Close folder picker" onClick={onClose}><X size={20}/></button>
        </header>
        <div className="imaging-output-finder-path">Demo Files / Output</div>
        <div className="imaging-output-finder-items">
          {FOLDERS.map((folder) => {
            const isGuideTarget = guided && !ready && folder === expected;
            return (
              <button
                key={folder}
                type="button"
                data-tutorial-id={folder === expected ? "imaging-output-target-folder" : undefined}
                onClick={() => setSelectedFolder(folder)}
                className={`imaging-output-finder-item ${selectedFolder === folder ? "imaging-output-finder-selected" : ""} ${isGuideTarget ? "imaging-picker-target" : ""}`}
              >
                <Folder size={30}/>
                <span>
                  <strong>{folder}</strong>
                  <small>{isGuideTarget ? "← Click this folder to select it" : "Demo output folder"}</small>
                </span>
                {isGuideTarget && <span className="imaging-output-finder-inline-hint" aria-hidden="true">← SELECT THIS FOLDER</span>}
              </button>
            );
          })}
        </div>
        <footer>
          <span>{guided ? ready ? `Selected ${expected}. Now click Choose Folder →` : `Select ${expected} above.` : selectedFolder && !ready ? `Select ${expected} for this output destination.` : "Select a folder and confirm."}</span>
          <button type="button" className="imaging-output-finder-secondary" onClick={onClose}>Cancel</button>
          <button
            type="button"
            data-tutorial-id="imaging-output-confirm-folder"
            className={`imaging-output-finder-primary ${guided && ready ? "imaging-picker-target imaging-picker-confirm-target" : ""}`}
            disabled={!ready}
            onClick={() => onChoose(selectedFolder)}
          >
            Choose Folder
            {guided && ready && <span className="imaging-picker-confirm-hint" aria-hidden="true">CLICK HERE TO CONFIRM ↓</span>}
          </button>
        </footer>
      </section>
    </div>
  );
}

