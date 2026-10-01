import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Database,
  FileImage,
  FileText,
  FolderOpen,
  Home as HomeIcon,
  Images,
  PanelLeft,
  Play,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  Users,
} from "lucide-react";
import styles from "./ImagingDashboard.module.css";

function api() {
  return window.pywebview?.api ?? null;
}

export default function ImagingDashboard({
  siteId,
  initialView = "home",
  onBack,
  onHome,
  onPatientReview,
  onRouteChange,
  onCreateClinicalAssessment,
  resumeBidsState = null,
  autoValidateBids = false,
  attentionSourceKey = "",
  attentionRecordId = "",
}) {
  const [view, setView] = useState(
    ["processing", "review", "metadata"].includes(initialView)
      ? initialView
      : "home"
  );
  const [dicomSources, setDicomSources] = useState([]);
  const [niftiSources, setNiftiSources] = useState([]);
  const [rawDicom, setRawDicom] = useState([]);
  const [rawNifti, setRawNifti] = useState([]);
  const [selectedDicom, setSelectedDicom] = useState([]);
  const [selectedNifti, setSelectedNifti] = useState([]);
  const [derivativesDir, setDerivativesDir] = useState("");
  const [bidsOutputDir, setBidsOutputDir] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [logs, setLogs] = useState([]);
  const [acceptedImages, setAcceptedImages] = useState([]);
  const [heldImageCount, setHeldImageCount] = useState(0);
  const [bidsState, setBidsState] = useState(null);
  const [openSection, setOpenSection] = useState(1);
  const [processStages, setProcessStages] = useState({
    prepare: "not_started",
    scrub: "not_started",
    deface: "not_started",
    review: "not_started",
    metadata_bids: "not_started",
  });
  const [activeOperation, setActiveOperation] = useState("");
  const [awareness, setAwareness] = useState({ source: "unavailable", note: "" });
  const [completionNotice, setCompletionNotice] = useState(false);
  const outputSettingsDirtyRef = useRef(false);
  const metadataBidsTerminalRefreshRef = useRef("");
  const bidsRecordsRef = useRef([]);

  function showImagingHome() {
    setView("home");
    onRouteChange?.("imaging");
  }

  function showImagingProcessing() {
    setCompletionNotice(false);
    setView("processing");
    onRouteChange?.("imaging-processing");
  }

  useEffect(() => {
    if (["processing", "metadata"].includes(view)) {
      loadBidsState();
    }

    if (!["processing", "review", "metadata"].includes(view)) {
      return undefined;
    }

    loadState();

    const interval = window.setInterval(() => {
      loadState();
    }, 750);

    return () => window.clearInterval(interval);
  }, [view]);

  async function loadState() {
    const bridge = api();
    if (!bridge?.imaging_get_state) return;

    try {
      const state = await bridge.imaging_get_state();
      applyState(state);

      const metadataBidsState =
        state?.process_stages?.metadata_bids ?? "";

      const terminalKey =
        view === "metadata" &&
        state?.process_running === false &&
        ["complete", "failed", "stopped"].includes(metadataBidsState)
          ? metadataBidsState
          : "";

      if (
        terminalKey &&
        metadataBidsTerminalRefreshRef.current !== terminalKey
      ) {
        metadataBidsTerminalRefreshRef.current = terminalKey;
        await loadBidsState();
      }

      if (state?.process_running === true) {
        metadataBidsTerminalRefreshRef.current = "";
      }
    } catch (error) {
      appendLog(String(error));
    }
  }

  function applyState(state = {}) {
    setDicomSources(state.dicom_input_dirs ?? []);
    setNiftiSources(state.nifti_input_dirs ?? []);
    setRawDicom(state.raw_dicom_files ?? []);
    setRawNifti(state.raw_nifti_files ?? []);

    if (!outputSettingsDirtyRef.current) {
      if (typeof state.derivatives_dir === "string") {
        setDerivativesDir(state.derivatives_dir);
      }

      if (typeof state.bids_output_dir === "string") {
        setBidsOutputDir(state.bids_output_dir);
      }
    }

    if (state.status) {
      setStatus(state.status);
    }

    if (Array.isArray(state.logs)) {
      setLogs(state.logs);
    }

    if (state.process_stages && typeof state.process_stages === "object") {
      const nextStages = {
        ...state.process_stages,
      };

      if (
        ["processing", "metadata"].includes(view) &&
        nextStages.metadata_bids === "not_started" &&
        bidsRecordsRef.current.length > 0
      ) {
        const allCompleted = bidsRecordsRef.current.every(
          record => record.record_state === "completed_recorded"
        );

        const hasRealProblem = bidsRecordsRef.current.some(record =>
          [
            "output_record_deleted",
            "recorded_export_missing",
          ].includes(record.record_state)
        );

        nextStages.metadata_bids = allCompleted
          ? "complete"
          : hasRealProblem
            ? "failed"
            : "running";
      }

      setProcessStages(current => ({
        ...current,
        ...nextStages,
      }));
    }

    if (state.awareness && typeof state.awareness === "object") {
      setAwareness({
        source: state.awareness.source ?? "unavailable",
        note: state.awareness.note ?? "",
      });
    } else if (state.awareness_source) {
      setAwareness({
        source: state.awareness_source,
        note: state.awareness_note ?? "",
      });
    }

    if (typeof state.active_operation === "string") {
      setActiveOperation(state.active_operation);
    }

    if (typeof state.process_running === "boolean") {
      setBusy(state.process_running);
    }

    if (state.log) {
      appendLog(state.log);
    }
  }

  function appendLog(message) {
    setLogs(current => [...current, String(message)]);
  }

  async function chooseSource(kind, sourceType) {
    const bridge = api();

    if (!bridge) {
      alert("The Python bridge is unavailable.");
      return;
    }

    let fn = null;

    if (kind === "dicom" && sourceType === "files") {
      fn = bridge.imaging_add_dicom_files;
    } else if (kind === "dicom" && sourceType === "folders") {
      fn = bridge.imaging_add_dicom_folders;
    } else if (kind === "nifti" && sourceType === "files") {
      fn = bridge.imaging_add_nifti_files;
    } else if (kind === "nifti" && sourceType === "folders") {
      fn = bridge.imaging_add_nifti_folders;
    }

    if (!fn) {
      alert("The requested Imaging file-selection method is unavailable.");
      return;
    }

    try {
      const state = await fn();
      applyState(state);
    } catch (error) {
      alert(String(error));
    }
  }

  async function removeSources(kind) {
    const bridge = api();
    if (!bridge?.imaging_remove_sources) return;

    const selected = kind === "dicom" ? selectedDicom : selectedNifti;
    try {
      const state = await bridge.imaging_remove_sources(kind, selected);
      if (kind === "dicom") setSelectedDicom([]);
      else setSelectedNifti([]);
      applyState(state);
    } catch (error) {
      alert(String(error));
    }
  }

  async function browseOutput(kind) {
    const bridge = api();
    if (!bridge?.choose_folder) return;

    const selected = await bridge.choose_folder();
    if (!selected) return;

    const nextDerivativesDir = kind === "derivatives" ? selected : derivativesDir;
    const nextBidsOutputDir = kind === "bids" ? selected : bidsOutputDir;

    outputSettingsDirtyRef.current = true;
    setDerivativesDir(nextDerivativesDir);
    setBidsOutputDir(nextBidsOutputDir);

    if (
      bridge.imaging_save_settings &&
      nextDerivativesDir.trim() &&
      nextBidsOutputDir.trim()
    ) {
      try {
        const state = await bridge.imaging_save_settings({
          dicom_input_dirs: dicomSources,
          nifti_input_dirs: niftiSources,
          derivatives_dir: nextDerivativesDir,
          bids_output_dir: nextBidsOutputDir,
        });
        outputSettingsDirtyRef.current = false;
        applyState(state);
      } catch (error) {
        appendLog(String(error));
      }
    }
  }

  async function saveSettings(showConfirmation = true) {
    const bridge = api();
    if (!bridge?.imaging_save_settings) return null;
    if (!derivativesDir.trim() || !bidsOutputDir.trim()) return null;

    const state = await bridge.imaging_save_settings({
      dicom_input_dirs: dicomSources,
      nifti_input_dirs: niftiSources,
      derivatives_dir: derivativesDir,
      bids_output_dir: bidsOutputDir,
    });

    outputSettingsDirtyRef.current = false;
    applyState(state);
    if (showConfirmation) alert("Imaging folder settings were saved successfully.");
    return state;
  }

  async function loadBidsState() {
    const bridge = api();

    if (!bridge?.imaging_bids_get_state) {
      setBidsState(null);
      return;
    }

    try {
      const state = await bridge.imaging_bids_get_state();
      const records = state?.records ?? [];
      bidsRecordsRef.current = records;
      setBidsState(state);
      setAcceptedImages(records);
      setHeldImageCount(Number(state?.held_count ?? 0));

      if (records.length > 0) {
        const allCompleted = records.every(
          record => record.record_state === "completed_recorded"
        );

        const hasRealProblem = records.some(record =>
          [
            "output_record_deleted",
            "recorded_export_missing",
          ].includes(record.record_state)
        );

        setProcessStages(current => ({
          ...current,
          metadata_bids: allCompleted
            ? "complete"
            : hasRealProblem
              ? "failed"
              : "running",
        }));
      } else {
        setProcessStages(current => ({
          ...current,
          metadata_bids: "not_started",
        }));
      }
    } catch (error) {
      bidsRecordsRef.current = [];
      setBidsState(null);
      appendLog(String(error));
      alert(String(error));
    }
  }

  async function loadAcceptedImages() {
    const bridge = api();

    if (!bridge?.imaging_get_accepted_files) {
      setAcceptedImages([]);
      setHeldImageCount(0);
      return;
    }

    try {
      const result = await bridge.imaging_get_accepted_files();
      setAcceptedImages(result?.files ?? []);
      setHeldImageCount(Number(result?.held_count ?? 0));
    } catch (error) {
      setAcceptedImages([]);
      setHeldImageCount(0);
      appendLog(String(error));
    }
  }

  async function runOperation(operation) {
    const bridge = api();

    if (!bridge?.imaging_run_operation) {
      alert("The Imaging Python bridge is unavailable.");
      return;
    }

    const trackedOperation = [
      "prepare",
      "scrub",
      "deface",
      "review",
      "bids",
    ].includes(operation);

    const stageKey = operation === "bids"
      ? "metadata_bids"
      : operation;

    try {
      if (trackedOperation) {
        setProcessStages(current => ({
          ...current,
          [stageKey]: "running",
        }));
        setActiveOperation(
          ["prepare", "scrub", "deface"].includes(operation)
            ? operation
            : ""
        );
      }

      setBusy(operation !== "review");
      setStatus(`Starting: ${operation}`);

      const result = await bridge.imaging_run_operation({
        operation,
        dicom_input_dirs: dicomSources,
        nifti_input_dirs: niftiSources,
        derivatives_dir: derivativesDir,
        bids_output_dir: bidsOutputDir,
        overwrite,
      });

      if (result?.log) {
        appendLog(result.log);
      }

      if (result?.status) {
        setStatus(result.status);
      }

      if (result?.process_stages) {
        setProcessStages(current => ({
          ...current,
          ...result.process_stages,
        }));
      }

      if (typeof result?.active_operation === "string") {
        setActiveOperation(result.active_operation);
      }

      if (result?.state === "running") {
        setBusy(true);
      } else if (operation !== "review") {
        const state = await bridge.imaging_get_state?.();

        if (state) {
          applyState(state);
        } else {
          setBusy(false);
        }
      }

      if (operation === "review" && result?.ok !== false) {
        setBusy(false);
        setActiveOperation("");
        setView("review");
      }

      if (operation === "bids" && result?.ok !== false) {
        setBusy(false);
        setAcceptedImages(result?.accepted_files ?? []);
        setHeldImageCount(Number(result?.held_count ?? 0));
        setView("metadata");
      }
    } catch (error) {
      if (trackedOperation) {
        setProcessStages(current => ({
          ...current,
          [stageKey]: "failed",
        }));
      }

      setBusy(false);
      setActiveOperation("");
      setStatus(`Failed: ${operation}`);
      appendLog(String(error));
      alert(String(error));

      const state = await bridge.imaging_get_state?.();

      if (state) {
        applyState(state);
      }
    }
  }

  async function stopOperation() {
    const bridge = api();

    if (!bridge?.imaging_stop_operation) {
      return;
    }

    try {
      const result = await bridge.imaging_stop_operation();

      if (result?.cleanup_message) {
        appendLog(result.cleanup_message);
      }

      if (result?.process_stages) {
        setProcessStages(current => ({
          ...current,
          ...result.process_stages,
        }));
      }

      setStatus(result?.status || "Stopped");
      setBusy(Boolean(result?.process_running));
      setActiveOperation(result?.active_operation ?? "");

      const state = await bridge.imaging_get_state?.();

      if (state) {
        applyState(state);
      }
    } catch (error) {
      appendLog(String(error));
      alert(String(error));
    }
  }

  const dicomStudyCount = dicomSources.length;
  const niftiStudyCount = niftiSources.length;
  const selectedStudyCount = dicomStudyCount + niftiStudyCount;

  const workflowCompletion = useMemo(() => ({
    1: selectedStudyCount > 0,
    2: Boolean(derivativesDir.trim() && bidsOutputDir.trim()),
    3: ["prepare", "scrub", "deface"].every(key => processStages[key] === "complete"),
    4: processStages.review === "complete",
    5: processStages.metadata_bids === "complete",
  }), [
    selectedStudyCount,
    derivativesDir,
    bidsOutputDir,
    processStages.prepare,
    processStages.scrub,
    processStages.deface,
    processStages.review,
    processStages.metadata_bids,
  ]);

  if (view === "home") {
    return (
      <Shell
        title="Imaging"
        siteId={siteId}
        onBack={onBack}
        onHome={onHome}
        onProcessImaging={showImagingProcessing}
        onPatientReview={onPatientReview}
      >
        {completionNotice && (
          <section className={styles.completionBanner}>
            <CheckCircle2 size={22} strokeWidth={2} />
            <div>
              <strong>Imaging workflow complete</strong>
              <span>
                De-identification review, metadata validation, and BIDS export completed successfully.
              </span>
            </div>
          </section>
        )}

        <section className={styles.hero}>
          <div className={styles.heroIcon}><Images size={30} strokeWidth={1.8} /></div>
          <div>
            <span className={styles.eyebrow}>Imaging Pipeline</span>
            <h2>Prepare imaging data for research use</h2>
            <p>
              Convert DICOM to NIfTI, prepare existing NIfTI inputs, scrub headers,
              deface images, review the results, and convert accepted files to BIDS.
            </p>
          </div>
        </section>

        <section className={styles.optionGrid}>
          <button className={styles.optionCard} onClick={showImagingProcessing}>
            <span>01</span>
            <strong>Process imaging data</strong>
            <p>Open the complete five-step Imaging DeID workflow.</p>
          </button>

          <button className={styles.optionCard} onClick={onPatientReview}>
            <span>02</span>
            <strong>Review patient data</strong>
            <p>Review locally stored imaging and metadata records by patient.</p>
          </button>
        </section>
      </Shell>
    );
  }

  if (view === "review") {
    return (
      <ImagingReview
        siteId={siteId}
        onBack={showImagingProcessing}
        onHome={onHome}
        onProcessImaging={showImagingProcessing}
        onPatientReview={onPatientReview}
        stageState={processStages.review}
        completedSteps={workflowCompletion}
        onStateRefresh={loadState}
        onReviewSummary={({ total, accepted }) => {
          setProcessStages(current => ({
            ...current,
            review: total > 0 && accepted === total ? "complete" : "not_started",
          }));
        }}
        onContinue={() => {
          setOpenSection(5);
          setView("metadata");
        }}
      />
    );
  }

  if (view === "metadata") {
    return (
      <ImagingBidsStep
        siteId={siteId}
        bidsState={bidsState}
        overwrite={overwrite}
        onBack={() => setView("review")}
        onHome={onHome}
        onProcessImaging={showImagingProcessing}
        onPatientReview={onPatientReview}
        onReload={loadBidsState}
        onLog={appendLog}
        stageState={processStages.metadata_bids}
        completedSteps={workflowCompletion}
        onStateRefresh={loadState}
        resumeState={resumeBidsState}
        autoValidate={autoValidateBids}
        onCreateClinicalAssessment={onCreateClinicalAssessment}
        attentionSourceKey={attentionSourceKey}
        attentionRecordId={attentionRecordId}
      />
    );
  }

  return (
    <Shell
      title="Process Imaging"
      siteId={siteId}
      onBack={showImagingHome}
      onHome={onHome}
      onProcessImaging={showImagingProcessing}
      onPatientReview={onPatientReview}
      subtitle="De-identify and prepare MRI or CT data for CoCANoT. Follow the steps below to select your data, run the de-identification pipeline, and export BIDS-formatted output."
    >
      <WorkflowStepper current={openSection} completed={workflowCompletion} />

      <WorkflowSection
        number={1}
        complete={workflowCompletion[1]}
        title="Select imaging data"
        subtitle="Add DICOM or NIfTI files and/or folders to include in this session."
        open={openSection === 1}
        onToggle={() => setOpenSection(1)}
      >
        <div className={styles.uploadGrid}>
          <UploadCard
            title="Add DICOM files or folders"
            description="Select DICOM files or a directory containing DICOM studies."
            onChooseFiles={() => chooseSource("dicom", "files")}
            onChooseFolder={() => chooseSource("dicom", "folders")}
            disabled={busy}
          />

          <UploadCard
            title="Add NIfTI files or folders"
            description="Select NIfTI files or a directory containing NIfTI images."
            onChooseFiles={() => chooseSource("nifti", "files")}
            onChooseFolder={() => chooseSource("nifti", "folders")}
            disabled={busy}
          />
        </div>

        <div className={styles.selectedSummary}>
          <div className={styles.summaryIcon}><Database size={24} strokeWidth={1.8} /></div>
          <div className={styles.summaryCopy}>
            <strong>Selected data</strong>
            <span>
              {dicomStudyCount} DICOM source{dicomStudyCount === 1 ? "" : "s"}
              <span className={styles.summaryDivider}>|</span>
              {niftiStudyCount} NIfTI source{niftiStudyCount === 1 ? "" : "s"}
            </span>
          </div>

          <details className={styles.selectedDetails}>
            <summary>View Selected Data</summary>
            <div className={styles.selectedDetailsBody}>
              <SelectedSourceList
                title="DICOM sources"
                sources={dicomSources}
                selected={selectedDicom}
                setSelected={setSelectedDicom}
                remove={() => removeSources("dicom")}
              />

              <SelectedSourceList
                title="NIfTI sources"
                sources={niftiSources}
                selected={selectedNifti}
                setSelected={setSelectedNifti}
                remove={() => removeSources("nifti")}
              />

              <RawFileTable title="Raw DICOM Files" rows={rawDicom} />
              <RawFileTable title="Raw NIfTI Files" rows={rawNifti} />
            </div>
          </details>
        </div>

        <div className={styles.sectionActions}>
          <div />
          <button
            className={styles.ctaButton}
            disabled={selectedStudyCount === 0}
            onClick={() => setOpenSection(2)}
          >
            Continue to Output Folders <ArrowRight size={16} />
          </button>
        </div>
      </WorkflowSection>

      <WorkflowSection
        number={2}
        complete={workflowCompletion[2]}
        title="Set output folders"
        subtitle="Choose where to save processed files. A derivatives folder is required before processing can begin."
        open={openSection === 2}
        onToggle={() => setOpenSection(2)}
      >
        <div className={styles.outputCardGrid}>
          <FolderField
            label="Derivatives output folder"
            value={derivativesDir}
            onChange={value => {
              outputSettingsDirtyRef.current = true;
              setDerivativesDir(value);
            }}
            onBrowse={() => browseOutput("derivatives")}
            disabled={busy}
          />

          <div className={styles.infoStrip}>
            The derivatives folder will contain converted_nifti, scrubbed_header,
            scrubbed_defaced, logs, and imaging_review_state.json.
          </div>

          <FolderField
            label="Final output folder"
            value={bidsOutputDir}
            onChange={value => {
              outputSettingsDirtyRef.current = true;
              setBidsOutputDir(value);
            }}
            onBrowse={() => browseOutput("bids")}
            disabled={busy}
          />

          <div className={styles.infoStrip}>
            The final de-identified file and associated metadata will be stored here
            in a BIDS-compatible format.
          </div>
        </div>

        <div className={styles.sectionActions}>
          <button
            className={styles.secondaryButton}
            disabled={busy}
            onClick={() => saveSettings(true)}
          >
            Save Folder Settings
          </button>

          <button
            className={styles.ctaButton}
            disabled={!derivativesDir || !bidsOutputDir}
            onClick={() => setOpenSection(3)}
          >
            Continue to Process & Review <ArrowRight size={16} />
          </button>
        </div>
      </WorkflowSection>

      <WorkflowSection
        number={3}
        complete={workflowCompletion[3]}
        title="Process imaging data"
        subtitle="Prepare, scrub, and deface the selected imaging data."
        open={openSection === 3}
        onToggle={() => setOpenSection(3)}
      >
        {awareness.source === "manifest" &&
          [processStages.prepare, processStages.scrub, processStages.deface].some(
            stage => stage === "complete"
          ) && (
            <div className={styles.awarenessNotice}>
              <Database size={18} strokeWidth={1.8} />
              <div>
                <strong>Existing processing verified</strong>
                <span>
                  {awareness.note ||
                    "CoCANoT verified the existing derivative outputs for the current imaging selection."}
                </span>
              </div>
            </div>
          )}

        {awareness.source === "detected" && (
          <div className={styles.awarenessNotice}>
            <Database size={18} strokeWidth={1.8} />
            <div>
              <strong>Existing outputs matched</strong>
              <span>
                {awareness.note || "CoCANoT matched existing outputs to the current selected NIfTI data."}
              </span>
            </div>
          </div>
        )}

        <ProcessProgress
          stages={processStages}
          activeOperation={activeOperation}
        />

        <div className={styles.processGrid}>
          <ProcessAction
            step="3A"
            title="Prepare NIfTI"
            description="Convert selected DICOM inputs and stage existing NIfTI files."
            state={processStages.prepare}
            disabled={busy}
            onClick={() => runOperation("prepare")}
          />

          <ProcessAction
            step="3B"
            title="Scrub Headers"
            description="Remove identifying values from staged NIfTI headers."
            state={processStages.scrub}
            disabled={busy || processStages.prepare !== "complete"}
            onClick={() => runOperation("scrub")}
          />

          <ProcessAction
            step="3C"
            title="Deface"
            description="Create defaced copies for imaging review."
            state={processStages.deface}
            disabled={busy || processStages.scrub !== "complete"}
            onClick={() => runOperation("deface")}
          />

        </div>

        <div className={styles.processFooter}>
          <label className={styles.checkbox}>
            <input
              type="checkbox"
              checked={overwrite}
              onChange={event => setOverwrite(event.target.checked)}
              disabled={busy}
            />
            Overwrite existing stage outputs or exact BIDS outputs
          </label>

          {busy && (
            <button className={styles.stopButtonInline} onClick={stopOperation}>
              Stop Current Process
            </button>
          )}
        </div>

        <div className={styles.statusPanel}>
          <div className={styles.statusHeader}>
            <div>
              <strong>Pipeline status</strong>
              <span>{status}</span>
            </div>
            <button
              className={styles.logToggle}
              type="button"
              onClick={() => {
                const element = document.getElementById("imaging-pipeline-log");
                element?.scrollIntoView({ behavior: "smooth", block: "center" });
              }}
            >
              View Log
            </button>
          </div>

          <pre id="imaging-pipeline-log" className={styles.log}>
            {logs.length ? logs.join("\n") : "Dashboard ready."}
          </pre>
        </div>

        <div className={styles.sectionActions}>
          <div />
          <button
            className={styles.ctaButton}
            disabled={busy || processStages.deface !== "complete"}
            onClick={() => setOpenSection(4)}
          >
            Continue to Review <ArrowRight size={16} />
          </button>
        </div>
      </WorkflowSection>

      <WorkflowSection
        number={4}
        complete={workflowCompletion[4]}
        title="Review de-identification"
        subtitle="Compare the original and defaced images, then accept, replace, hold, or reject each image."
        open={openSection === 4}
        onToggle={() => setOpenSection(4)}
      >
        <WorkflowStatusCard
          title="Review processed images"
          description="Inspect the scrubbed headers and compare the original and defaced images before deciding which files can continue."
          state={processStages.review}
        />

        <div className={styles.sectionActions}>
          <button
            className={styles.secondaryButton}
            onClick={() => setOpenSection(3)}
          >
            Back to Processing
          </button>

          <button
            className={styles.ctaButton}
            disabled={busy || processStages.deface !== "complete"}
            onClick={() => runOperation("review")}
          >
            Open Imaging Review <ArrowRight size={16} />
          </button>
        </div>
      </WorkflowSection>

      <WorkflowSection
        number={5}
        complete={workflowCompletion[5]}
        title="Metadata & BIDS"
        subtitle="Add imaging metadata and create the final BIDS-compatible output."
        open={openSection === 5}
        onToggle={() => setOpenSection(5)}
      >
        <WorkflowStatusCard
          title="Complete metadata and export"
          description="Continue with images accepted during review, complete the dictionary-driven Imaging metadata, check for existing exports, and create the final BIDS-compatible output."
          state={processStages.metadata_bids}
        />

        <div className={styles.sectionActions}>
          <button
            className={styles.secondaryButton}
            onClick={() => setOpenSection(4)}
          >
            Back to Review
          </button>

          <button
            className={styles.ctaButton}
            disabled={busy || processStages.review !== "complete"}
            onClick={() => runOperation("bids")}
          >
            Open Metadata & BIDS <ArrowRight size={16} />
          </button>
        </div>
      </WorkflowSection>

      <div className={styles.supportBar}>
        <div className={styles.supportMessage}>
          <span className={styles.supportBulb}><CircleHelp size={18} strokeWidth={1.9} /></span>
          <strong>Need help?</strong>
          <span>Review the imaging workflow guidance or contact your CoCANoT support team.</span>
        </div>
      </div>
    </Shell>
  );
}

function WorkflowStepper({ current, completed = {} }) {
  const steps = [
    ["Select Data", 1],
    ["Set Output Folders", 2],
    ["Process", 3],
    ["Review", 4],
    ["Metadata & BIDS", 5],
  ];

  return (
    <div className={styles.stepper}>
      {steps.map(([label, number], index) => {
        const isComplete = Boolean(completed[number]);
        const isActive = number === current;

        return (
          <div className={styles.stepperItem} key={label}>
            <div
              className={`${styles.stepCircle} ${
                isComplete
                  ? styles.stepCircleDone
                  : isActive
                    ? styles.stepCircleActive
                    : ""
              }`}
            >
              {isComplete ? <Check size={15} strokeWidth={2.5} /> : number}
            </div>
            <span
              className={`${isActive ? styles.stepLabelActive : ""} ${
                isComplete ? styles.stepLabelDone : ""
              }`}
            >
              {label}
            </span>
            {index < steps.length - 1 && (
              <div
                className={`${styles.stepLine} ${
                  isComplete ? styles.stepLineDone : ""
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function WorkflowSection({
  number,
  title,
  subtitle,
  open,
  complete = false,
  onToggle,
  children,
}) {
  return (
    <section
      className={`${styles.workflowSection} ${open ? styles.workflowSectionOpen : ""} ${
        complete ? styles.workflowSectionComplete : ""
      }`}
    >
      <button className={styles.workflowSectionHeader} onClick={onToggle}>
        <div className={`${styles.sectionNumber} ${complete ? styles.sectionNumberComplete : ""}`}>
          {complete ? <Check size={17} strokeWidth={2.5} /> : number}
        </div>
        <div className={styles.sectionTitleBlock}>
          <strong>{title}</strong>
          <span>{subtitle}</span>
        </div>

        {!open && (
          <span className={complete ? styles.sectionCompleteLabel : styles.goSection}>
            {complete ? "Complete" : "Go to Section"}
          </span>
        )}
        <ChevronDown className={`${styles.chevron} ${open ? styles.chevronOpen : ""}`} size={18} />
      </button>

      {open && <div className={styles.workflowSectionBody}>{children}</div>}
    </section>
  );
}

function UploadCard({
  title,
  description,
  onChooseFiles,
  onChooseFolder,
  disabled,
}) {
  return (
    <div className={styles.uploadCard}>
      <div className={styles.fileIcon}><Upload size={24} strokeWidth={1.8} /></div>
      <div className={styles.uploadCopy}>
        <strong>{title}</strong>
        <span>{description}</span>

        <div className={styles.uploadActions}>
          <button
            className={styles.uploadButton}
            disabled={disabled}
            onClick={onChooseFiles}
          >
            Choose Files…
          </button>

          <button
            className={styles.folderLinkButton}
            disabled={disabled}
            onClick={onChooseFolder}
          >
            Choose Folder…
          </button>
        </div>
      </div>
    </div>
  );
}

function SelectedSourceList({
  title,
  sources,
  selected,
  setSelected,
  remove,
}) {
  function toggle(index) {
    setSelected(current =>
      current.includes(index)
        ? current.filter(value => value !== index)
        : [...current, index]
    );
  }

  return (
    <section className={styles.compactSourcePanel}>
      <div className={styles.compactSourceHeader}>
        <strong>{title}</strong>
        <button
          className={styles.textButton}
          disabled={selected.length === 0}
          onClick={remove}
        >
          Remove selected
        </button>
      </div>

      <div className={styles.compactSourceList}>
        {!sources.length ? (
          <span className={styles.mutedSmall}>No sources added.</span>
        ) : (
          sources.map((source, index) => (
            <label key={`${source}-${index}`}>
              <input
                type="checkbox"
                checked={selected.includes(index)}
                onChange={() => toggle(index)}
              />
              <span>{source}</span>
            </label>
          ))
        )}
      </div>
    </section>
  );
}

function WorkflowStatusCard({ title, description, state = "not_started" }) {
  const stateLabel = {
    not_started: "Not started",
    running: "In progress",
    complete: "Completed",
    failed: "Needs attention",
    stopped: "Stopped",
  }[state] ?? "Not started";

  return (
    <div className={`${styles.workflowStatusCard} ${styles[`workflowStatusCard_${state}`] ?? ""}`}>
      <div className={`${styles.workflowStatusIcon} ${styles[`workflowStatusIcon_${state}`] ?? ""}`}>
        {state === "complete" ? (
          <CheckCircle2 size={20} strokeWidth={2} />
        ) : state === "running" ? (
          <RefreshCw className={styles.processSpinner} size={20} strokeWidth={2} />
        ) : (
          <span className={styles.workflowStatusDot} />
        )}
      </div>

      <div className={styles.workflowStatusCopy}>
        <div className={styles.workflowStatusTitleRow}>
          <strong>{title}</strong>
          <span className={`${styles.processState} ${styles[`processState_${state}`] ?? ""}`}>
            {state === "complete" && <CheckCircle2 size={14} />}
            {state === "running" && <RefreshCw className={styles.processSpinner} size={14} />}
            {stateLabel}
          </span>
        </div>
        <p>{description}</p>
      </div>
    </div>
  );
}

function ProcessProgress({ stages, activeOperation }) {
  const order = ["prepare", "scrub", "deface"];
  const labels = {
    prepare: "Prepare NIfTI",
    scrub: "Scrub Headers",
    deface: "Deface",
  };

  const completedCount = order.filter(key => stages[key] === "complete").length;
  const activeIndex = activeOperation ? order.indexOf(activeOperation) : -1;
  const displayStep = activeIndex >= 0
    ? activeIndex + 1
    : Math.min(completedCount + 1, order.length);

  return (
    <div className={styles.processProgress}>
      <div className={styles.processProgressHeader}>
        <div>
          <strong>
            {activeOperation
              ? `Step ${displayStep} of ${order.length}: ${labels[activeOperation]}`
              : `${completedCount} of ${order.length} steps complete`}
          </strong>
          <span>
            {activeOperation
              ? "Processing is currently running."
              : completedCount === order.length
                ? "Processing is complete. Continue to image review."
                : "Complete each step in order before finalizing the export."}
          </span>
        </div>
        <span className={styles.processProgressCount}>
          {completedCount}/{order.length}
        </span>
      </div>

      <div className={styles.processProgressTrack}>
        <div
          className={styles.processProgressFill}
          style={{ width: `${(completedCount / order.length) * 100}%` }}
        />
      </div>
    </div>
  );
}

function ProcessAction({
  step,
  title,
  description,
  state = "not_started",
  disabled,
  onClick,
}) {
  const stateLabel = {
    not_started: "Not started",
    running: "In progress",
    complete: "Complete",
    failed: "Needs attention",
    stopped: "Stopped",
  }[state];

  return (
    <button
      className={`${styles.processAction} ${styles[`processAction_${state}`] ?? ""}`}
      disabled={disabled}
      onClick={onClick}
    >
      <div className={styles.processActionTop}>
        <span className={styles.processStep}>{step}</span>
        <span className={`${styles.processState} ${styles[`processState_${state}`] ?? ""}`}>
          {state === "complete" && <CheckCircle2 size={14} />}
          {state === "running" && <RefreshCw className={styles.processSpinner} size={14} />}
          {stateLabel}
        </span>
      </div>
      <strong>{title}</strong>
      <p>{description}</p>
      <span className={styles.processActionLabel}>
        {state === "complete"
          ? "Reprocess"
          : state === "failed" || state === "stopped"
            ? "Try again"
            : "Run"}
      </span>
      <ArrowRight className={styles.processArrow} size={17} />
    </button>
  );
}

function ImagingBidsStep({
  siteId,
  bidsState,
  overwrite,
  onBack,
  onHome,
  onProcessImaging,
  onPatientReview,
  onReload,
  onLog,
  stageState,
  completedSteps,
  onStateRefresh,
  resumeState,
  autoValidate,
  onCreateClinicalAssessment,
  attentionSourceKey,
  attentionRecordId,
}) {
  const [records, setRecords] = useState([]);
  const [rules, setRules] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [draftMetadata, setDraftMetadata] = useState({});
  const [project, setProject] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [problems, setProblems] = useState([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const resumeAppliedRef = useRef(false);
  const autoValidateStartedRef = useRef(false);
  const attentionAppliedRef = useRef(false);

  useEffect(() => {
    setRules(bidsState?.rules ?? []);

    if (resumeState && !resumeAppliedRef.current) {
      const resumedRecords = Array.isArray(resumeState.records)
        ? resumeState.records
        : [];

      resumeAppliedRef.current = true;
      setRecords(resumedRecords);
      setSelectedIds(resumeState.selectedIds ?? []);
      setActiveId(resumeState.activeId ?? resumedRecords[0]?.id ?? "");
      setDraftMetadata({ ...(resumeState.draftMetadata ?? {}) });
      setProject(resumeState.project ?? "");
      setProjectDescription(resumeState.projectDescription ?? "");
      setSessionId(resumeState.sessionId ?? "");
      return;
    }

    const nextRecords = bidsState?.records ?? [];
    setRecords(nextRecords);

    if (nextRecords.length > 0) {
      const first = nextRecords[0];
      setActiveId(first.id);
      setSelectedIds([first.id]);
      loadRecordIntoDraft(first);
    } else {
      setActiveId("");
      setSelectedIds([]);
      setDraftMetadata({});
      setProject("");
      setProjectDescription("");
      setSessionId("");
    }
  }, [bidsState, resumeState]);

  useEffect(() => {
    if (stageState === "complete") {
      onReload?.();
    }
  }, [stageState]);

  useEffect(() => {
    if (
      attentionAppliedRef.current ||
      records.length === 0 ||
      (!attentionSourceKey && !attentionRecordId)
    ) {
      return;
    }

    const target = records.find(record => {
      if (
        attentionSourceKey &&
        record.source_key === attentionSourceKey
      ) {
        return true;
      }

      if (!attentionRecordId) {
        return false;
      }

      return (
        String(
          record.cocanot_metadata?.["Image ID"] ?? ""
        ) === String(attentionRecordId) ||
        String(record.source_label ?? "") ===
          String(attentionRecordId)
      );
    });

    if (!target) {
      return;
    }

    attentionAppliedRef.current = true;
    setActiveId(target.id);
    setSelectedIds([target.id]);
    loadRecordIntoDraft(target);

    window.requestAnimationFrame(() => {
      document
        .getElementById("imaging-bids-editor")
        ?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
    });
  }, [
    attentionSourceKey,
    attentionRecordId,
    records,
  ]);

  useEffect(() => {
    if (!activeId) return;

    setRecords(current =>
      current.map(record =>
        record.id === activeId
          ? {
              ...record,
              project,
              project_description: projectDescription,
              session_id: sessionId,
              cocanot_metadata: JSON.parse(JSON.stringify(draftMetadata)),
            }
          : record
      )
    );

    const active = records.find(record => record.id === activeId);
    const bridge = api();
    if (!active?.source_key || !bridge?.imaging_bids_save_draft) return;

    bridge.imaging_bids_save_draft({
      source_key: active.source_key,
      include: Boolean(active.include),
      project,
      project_description: projectDescription,
      session_id: sessionId,
      cocanot_metadata: JSON.parse(JSON.stringify(draftMetadata)),
    }).catch(() => {});
  }, [
    activeId,
    draftMetadata,
    project,
    projectDescription,
    sessionId,
  ]);

  useEffect(() => {
    if (
      !autoValidate ||
      autoValidateStartedRef.current ||
      records.length === 0 ||
      (resumeState && !resumeAppliedRef.current)
    ) {
      return;
    }

    autoValidateStartedRef.current = true;
    reviewAndConvert();
  }, [autoValidate, records]);

  function loadRecordIntoDraft(record) {
    setDraftMetadata({ ...(record?.cocanot_metadata ?? {}) });
    setProject(record?.project ?? "");
    setProjectDescription(record?.project_description ?? "");
    setSessionId(record?.session_id ?? "");
  }

  function activeRecord() {
    return records.find(record => record.id === activeId) ?? null;
  }

  function selectRecord(record) {
    setActiveId(record.id);
    if (!selectedIds.includes(record.id)) {
      setSelectedIds([record.id]);
    }
    loadRecordIntoDraft(record);
  }

  function toggleSelected(id) {
    setSelectedIds(current =>
      current.includes(id)
        ? current.filter(value => value !== id)
        : [...current, id]
    );
  }

  function persistRecordDraft(record) {
    const bridge = api();

    if (
      !record?.source_key ||
      !bridge?.imaging_bids_save_draft
    ) {
      return;
    }

    const isActive = record.id === activeId;

    bridge.imaging_bids_save_draft({
      source_key: record.source_key,
      include: Boolean(record.include),
      project: isActive
        ? project
        : record.project ?? "",
      project_description: isActive
        ? projectDescription
        : record.project_description ?? "",
      session_id: isActive
        ? sessionId
        : record.session_id ?? "",
      cocanot_metadata: JSON.parse(
        JSON.stringify(
          isActive
            ? draftMetadata
            : record.cocanot_metadata ?? {}
        )
      ),
    }).catch(() => {});
  }

  function toggleInclude(id) {
    const record = records.find(
      item => item.id === id
    );

    if (!record) {
      return;
    }

    const updated = {
      ...record,
      include: !record.include,
    };

    setRecords(current =>
      current.map(item =>
        item.id === id
          ? updated
          : item
      )
    );

    if (updated.include) {
      setProblems(current =>
        current.filter(
          problem =>
            !String(problem).toLowerCase().includes(
              "choose at least one image to include"
            ) &&
            !String(problem).toLowerCase().includes(
              "include at least one image"
            )
        )
      );
    }

    persistRecordDraft(updated);
  }

  function setField(fieldName, value) {
    setDraftMetadata(current => ({
      ...current,
      [fieldName]: value,
    }));
  }

  function conditionMatches(rule) {
    if (!rule.required_if_field) {
      return true;
    }

    const current = draftMetadata[rule.required_if_field];
    const expected = rule.required_if_value;
    const operator = String(rule.required_if_operator ?? "").toLowerCase();

    const currentValues = Array.isArray(current)
      ? current.map(value => String(value).trim()).filter(Boolean)
      : [String(current ?? "").trim()].filter(Boolean);

    const expectedValues = Array.isArray(expected)
      ? expected.map(value => String(value).trim()).filter(Boolean)
      : [String(expected ?? "").trim()].filter(Boolean);

    const anyMatch = expectedValues.some(value =>
      currentValues.includes(value)
    );

    if (
      operator.includes("not") ||
      operator === "!=" ||
      operator === "not_equals"
    ) {
      return !anyMatch;
    }

    if (
      operator.includes("contain") ||
      operator === "in" ||
      operator === "equals" ||
      operator === "==" ||
      operator === "=" ||
      operator === ""
    ) {
      return anyMatch;
    }

    return anyMatch;
  }

  function applyToSelected() {
    if (selectedIds.length === 0) {
      alert("Select one or more images first.");
      return;
    }

    setRecords(current =>
      current.map(record => {
        if (!selectedIds.includes(record.id)) return record;

        return {
          ...record,
          project,
          project_description: projectDescription,
          session_id: sessionId,
          cocanot_metadata: JSON.parse(JSON.stringify(draftMetadata)),
          status: "Ready for validation",
        };
      })
    );

    setProblems([]);
  }

  function includeSelected(include) {
    const updatedRecords = records.map(record =>
      selectedIds.includes(record.id)
        ? { ...record, include }
        : record
    );

    setRecords(updatedRecords);

    if (
      include &&
      updatedRecords.some(record => Boolean(record.include))
    ) {
      setProblems(current =>
        current.filter(
          problem =>
            !String(problem).toLowerCase().includes(
              "choose at least one image to include"
            ) &&
            !String(problem).toLowerCase().includes(
              "include at least one image"
            )
        )
      );
    }

    updatedRecords
      .filter(record =>
        selectedIds.includes(record.id)
      )
      .forEach(persistRecordDraft);
  }

  function buildResumeState() {
    return {
      records,
      selectedIds,
      activeId,
      draftMetadata,
      project,
      projectDescription,
      sessionId,
    };
  }

  async function reviewAndConvert() {
    const bridge = api();

    if (!bridge?.imaging_bids_validate) {
      alert("The Imaging BIDS validation API is unavailable.");
      return;
    }

    const includedRecords = records.filter(
      record => Boolean(record.include)
    );

    if (includedRecords.length === 0) {
      setProblems([
        "Choose at least one image to include before reviewing metadata and converting."
      ]);
      return;
    }

    try {
      setBusy(true);
      const result = await bridge.imaging_bids_validate({ records, overwrite });

      if (!result?.ok) {
        const missingClinical = result?.missing_clinical_assessments ?? [];
        setProblems(result?.problems ?? ["Metadata validation failed."]);

        if (
          missingClinical.length > 0 &&
          onCreateClinicalAssessment
        ) {
          onCreateClinicalAssessment(
            missingClinical[0].patient_id,
            buildResumeState()
          );
        }

        return;
      }

      setProblems([]);
      setRecords(result.records ?? records);
      setConfirmOpen(true);
    } catch (error) {
      setProblems([String(error)]);
    } finally {
      setBusy(false);
    }
  }

  async function confirmAndConvert() {
    const bridge = api();

    if (!bridge?.imaging_bids_convert) {
      alert("The Imaging BIDS conversion API is unavailable.");
      return;
    }

    try {
      setBusy(true);
      const result = await bridge.imaging_bids_convert({ records, overwrite });

      if (!result?.ok) {
        setProblems(result?.problems ?? ["BIDS conversion could not start."]);
        setConfirmOpen(false);
        return;
      }

      setConfirmOpen(false);
      onLog?.(
        `Started Imaging BIDS / CoCANoT conversion for ${result.record_count} image(s).`
      );
      await onStateRefresh?.();
    } catch (error) {
      setProblems([String(error)]);
      setConfirmOpen(false);
    } finally {
      setBusy(false);
    }
  }

  const active = activeRecord();

  return (
    <Shell
      title="Imaging Metadata & BIDS Review"
      siteId={siteId}
      onBack={onBack}
      onHome={onHome}
      onProcessImaging={onProcessImaging}
      onPatientReview={onPatientReview}
    >
      <WorkflowStepper current={5} completed={completedSteps} />
      <WorkflowStatusCard
        title="Metadata & BIDS"
        description="Complete the imaging metadata, confirm the included images, and create the final BIDS-compatible output."
        state={stageState}
      />
      <section className={styles.card}>
        <div className={styles.bidsHeading}>
          <div>
            <span className={styles.eyebrow}>Step 5</span>
            <h2>Imaging Metadata & BIDS Review</h2>
            <p className={styles.muted}>
              CoCANoT fields come from the active Imaging metadata dictionary.
              Project and Session ID are used for BIDS dataset organization.
            </p>

            <p className={styles.databaseStatus}>
              Local metadata database:{" "}
              <strong>
                {bidsState?.local_database?.connected
                  ? `Connected — Site ${bidsState.local_database.site_id}`
                  : "Not connected"}
              </strong>
            </p>
          </div>

          <button className={styles.secondaryButton} onClick={onReload}>
            Reload Accepted Images
          </button>
        </div>

        {Number(bidsState?.held_count ?? 0) > 0 && (
          <div className={styles.notice}>
            {bidsState.held_count} image{bidsState.held_count === 1 ? "" : "s"} remain
            on hold and are not included in this step.
          </div>
        )}

        <div className={styles.bidsTableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Select</th>
                <th>Include</th>
                <th>Status</th>
                <th>File Name</th>
                <th>Project</th>
                <th>CoCANoT Patient ID</th>
                <th>Image ID</th>
                <th>Surgery ID</th>
                <th>Imaging Modality</th>
              </tr>
            </thead>
            <tbody>
              {records.length === 0 ? (
                <tr>
                  <td colSpan="9" className={styles.empty}>
                    No accepted images were found.
                  </td>
                </tr>
              ) : (
                records.map(record => (
                  <tr
                    key={record.id}
                    className={activeId === record.id ? styles.activeBidsRow : ""}
                    onClick={() => selectRecord(record)}
                  >
                    <td onClick={event => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(record.id)}
                        onChange={() => toggleSelected(record.id)}
                      />
                    </td>

                    <td onClick={event => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={Boolean(record.include)}
                        onChange={() => toggleInclude(record.id)}
                      />
                    </td>

                    <td>
                      <span
                        className={
                          record.record_state === "completed_recorded"
                            ? styles.recordedBadge
                            : record.record_state === "output_record_deleted"
                              ? styles.orphanedBadge
                              : styles.pendingBadge
                        }
                      >
                        {record.status}
                      </span>
                    </td>

                    <td>{record.source_label}</td>
                    <td>{record.project ?? ""}</td>
                    <td>{record.cocanot_metadata?.["CoCANoT Patient ID"] ?? ""}</td>
                    <td>{record.cocanot_metadata?.["Image ID"] ?? ""}</td>
                    <td>{record.cocanot_metadata?.["Surgery ID"] ?? ""}</td>
                    <td>{record.cocanot_metadata?.["Imaging Modality"] ?? ""}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {active && (
        <>
          {active.existing_export && (
            <section className={styles.existingExportBox}>
              <div>
                <strong>
                  {active.record_state === "completed_recorded"
                    ? "Completed BIDS output and CoCANoT record detected"
                    : "Processed BIDS output detected without a CoCANoT record"}
                </strong>
                <p>
                  {active.record_state === "completed_recorded"
                    ? "Step 5 was completed and the matching Imaging record is still present in the local CoCANoT database."
                    : "The processed BIDS files are still present in the final output folder, but the matching Imaging record is no longer present in the local CoCANoT database. Metadata stored with the existing output has been preloaded below so the record can be recreated without starting from scratch."}
                </p>
              </div>

              <div className={styles.existingExportDetails}>
                <span>
                  Existing output: {active.existing_export.nifti_path}
                </span>
              </div>
            </section>
          )}

          <section
            id="imaging-bids-editor"
            className={styles.card}
          >
            <h3>CoCANoT Imaging Metadata</h3>
            <p className={styles.helpText}>
              Requiredness, input type, allowed values, conditional fields, prompts,
              and help text come from the active machine-readable dictionary.
            </p>

            <div className={styles.metadataForm}>
              {rules
                .filter(rule => conditionMatches(rule))
                .map(rule => (
                  <MetadataField
                    key={rule.field_name}
                    rule={rule}
                    value={draftMetadata[rule.field_name]}
                    onChange={value => setField(rule.field_name, value)}
                  />
                ))}
            </div>
          </section>

          <section className={styles.card}>
            <h3>Dataset Organization</h3>

            <div className={styles.datasetGrid}>
              <label>
                <span>Project *</span>
                <input
                  value={project}
                  onChange={event => setProject(event.target.value)}
                />
              </label>

              <label>
                <span>Session ID</span>
                <input
                  value={sessionId}
                  onChange={event => setSessionId(event.target.value)}
                />
              </label>

              <label className={styles.fullField}>
                <span>Project Description</span>
                <input
                  value={projectDescription}
                  onChange={event => setProjectDescription(event.target.value)}
                />
              </label>
            </div>

            <p className={styles.helpText}>
              Project is required. Project Description and Session ID are optional.
              The BIDS subject label is derived from CoCANoT Patient ID.
            </p>
          </section>

          <section className={styles.bidsActions}>
            <div>
              <button
                className={styles.secondaryButton}
                onClick={() => includeSelected(true)}
              >
                Include Selected
              </button>

              <button
                className={styles.secondaryButton}
                onClick={() => includeSelected(false)}
              >
                Exclude Selected
              </button>

              <button className={styles.secondaryButton} onClick={applyToSelected}>
                Apply to Selected
              </button>
            </div>

            <button
              className={styles.primaryButton}
              disabled={busy}
              onClick={reviewAndConvert}
            >
              Review Metadata & Convert
            </button>
          </section>
        </>
      )}

      {problems.length > 0 && (
        <section className={styles.problemBox}>
          <strong>Metadata needs attention</strong>
          <ul>
            {problems.map((problem, index) => (
              <li key={`${problem}-${index}`}>{problem}</li>
            ))}
          </ul>
        </section>
      )}

      {confirmOpen && (
        <div className={styles.modalBackdrop}>
          <div className={styles.confirmModal}>
            <h3>Confirm Imaging Metadata</h3>
            <p>
              Confirm the included images below. Conversion will write the Imaging
              manifest and launch the existing NIfTI-to-BIDS converter.
            </p>

            <div className={styles.confirmList}>
              {records
                .filter(record => record.include)
                .map(record => (
                  <div key={record.id} className={styles.confirmRecord}>
                    <strong>{record.source_label}</strong>
                    <span>Project: {record.project}</span>
                    <span>
                      Patient: {record.cocanot_metadata?.["CoCANoT Patient ID"] ?? ""}
                    </span>
                    <span>
                      Image ID: {record.cocanot_metadata?.["Image ID"] ?? ""}
                    </span>
                  </div>
                ))}
            </div>

            <div className={styles.modalActions}>
              <button
                className={styles.secondaryButton}
                onClick={() => setConfirmOpen(false)}
              >
                Back to Edit
              </button>

              <button
                className={styles.primaryButton}
                disabled={busy}
                onClick={confirmAndConvert}
              >
                Confirm All & Convert
              </button>
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}

function MetadataField({ rule, value, onChange }) {
  const label = `${rule.ui_prompt}${
    rule.required
      ? " *"
      : rule.required_if_field
        ? " * when applicable"
        : ""
  }`;

  if (rule.input_type === "single_select") {
    return (
      <label className={styles.metadataField}>
        <span>
          {label}
          {rule.help_text && <small title={rule.help_text}> ?</small>}
        </span>

        <select
          value={value ?? ""}
          onChange={event => onChange(event.target.value)}
        >
          <option value="">Select…</option>
          {(rule.allowed_values ?? []).map(option => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (rule.input_type === "multi_select") {
    const allowed = rule.allowed_values ?? [];
    const selected = Array.isArray(value)
      ? value.map(String)
      : value
        ? [String(value)]
        : [];

    function setOption(option, checked) {
      const next = checked
        ? [...new Set([...selected, option])]
        : selected.filter(item => item !== option);

      const ordered = allowed.filter(option => next.includes(option));
      onChange(ordered);
    }

    return (
      <fieldset className={styles.multiField}>
        <div className={styles.multiLegendRow}>
          <legend>
            {label}
            {rule.help_text && <small title={rule.help_text}> ?</small>}
          </legend>

          <span className={styles.multiCount}>
            {selected.length} selected
          </span>
        </div>

        <div className={styles.multiToolbar}>
          <button
            type="button"
            className={styles.multiUtilityButton}
            onClick={() => onChange([...allowed])}
            disabled={allowed.length === 0}
          >
            Select all
          </button>

          <button
            type="button"
            className={styles.multiUtilityButton}
            onClick={() => onChange([])}
            disabled={selected.length === 0}
          >
            Clear
          </button>
        </div>

        <div className={styles.multiOptions}>
          {allowed.map(option => (
            <label
              key={option}
              className={
                selected.includes(option)
                  ? styles.multiOptionSelected
                  : ""
              }
            >
              <input
                type="checkbox"
                checked={selected.includes(option)}
                onChange={event =>
                  setOption(option, event.target.checked)
                }
              />
              <span>{option}</span>
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  return (
    <label className={styles.metadataField}>
      <span>
        {label}
        {rule.help_text && <small title={rule.help_text}> ?</small>}
      </span>

      <input
        value={value ?? ""}
        onChange={event => onChange(event.target.value)}
      />
    </label>
  );
}

function SourcePanel({
  title,
  sources,
  selected,
  setSelected,
  addFiles,
  addFolders,
  remove,
  fileLabel,
  folderLabel,
}) {
  function toggle(index) {
    setSelected(current =>
      current.includes(index)
        ? current.filter(value => value !== index)
        : [...current, index]
    );
  }

  return (
    <section className={styles.sourcePanel}>
      <h3>{title}</h3>
      <div className={styles.sourceList}>
        {sources.length === 0 ? (
          <div className={styles.empty}>No sources added.</div>
        ) : (
          sources.map((source, index) => (
            <label key={`${source}-${index}`} className={styles.sourceRow}>
              <input
                type="checkbox"
                checked={selected.includes(index)}
                onChange={() => toggle(index)}
              />
              <span>{source}</span>
            </label>
          ))
        )}
      </div>
      <div className={styles.sourceButtons}>
        <button className={styles.secondaryButton} onClick={addFiles}>{fileLabel}</button>
        <button className={styles.secondaryButton} onClick={addFolders}>{folderLabel}</button>
        <button className={styles.secondaryButton} onClick={remove}>Remove Selected</button>
      </div>
    </section>
  );
}

function RawFileTable({ title, rows }) {
  return (
    <section className={styles.rawPanel}>
      <h3>{title}</h3>
      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr><th>File Name</th><th>Source</th></tr>
          </thead>
          <tbody>
            {!rows.length ? (
              <tr><td colSpan="2" className={styles.empty}>No files found.</td></tr>
            ) : (
              rows.map((row, index) => (
                <tr key={`${row.file_name}-${index}`}>
                  <td>{row.file_name}</td>
                  <td>{row.source_name}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FolderField({ label, value, onChange, onBrowse, disabled }) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      <div className={styles.folderField}>
        <input value={value} onChange={event => onChange(event.target.value)} disabled={disabled} />
        <button type="button" className={styles.secondaryButton} onClick={onBrowse} disabled={disabled}>
          Browse…
        </button>
      </div>
    </label>
  );
}

function ImagingReview({
  siteId,
  onBack,
  onHome,
  onProcessImaging,
  onPatientReview,
  onContinue,
  stageState,
  completedSteps,
  onStateRefresh,
  onReviewSummary,
}) {
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [review, setReview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [editField, setEditField] = useState("");
  const [editValue, setEditValue] = useState("");
  const [rejectOpen, setRejectOpen] = useState(false);
  const reviewRequestRef = useRef(0);
  const reviewCoordsRef = useRef({ x: 0, y: 0, z: 0, volume: 0 });

  useEffect(() => {
    loadItems();
  }, []);

  async function loadItems() {
    const bridge = api();
    if (!bridge?.imaging_review_get_items) return;
    const result = await bridge.imaging_review_get_items();
    const nextItems = Array.isArray(result) ? result : [];
    setItems(nextItems);

    const accepted = nextItems.filter(
      item => String(item.status ?? "").trim().toLowerCase() === "accepted"
    ).length;
    onReviewSummary?.({ total: nextItems.length, accepted });

    if (nextItems.length) {
      setSelectedId(String(nextItems[0].id));
      await loadItem(String(nextItems[0].id));
    }
  }

  async function loadItem(id, coords = {}) {
    const bridge = api();
    if (!bridge?.imaging_review_get_item) return;
    try {
      setLoading(true);
      const data = await bridge.imaging_review_get_item(
        id,
        coords.x ?? null,
        coords.y ?? null,
        coords.z ?? null,
        coords.volume ?? null
      );
      setReview(data);
      reviewCoordsRef.current = {
        x: Number(data?.x ?? 0),
        y: Number(data?.y ?? 0),
        z: Number(data?.z ?? 0),
        volume: Number(data?.volume ?? 0),
      };
      setSelectedId(String(id));
      setEditField("");
      setEditValue("");
    } catch (error) {
      alert(String(error));
    } finally {
      setLoading(false);
    }
  }

  async function move(axis, value) {
    if (!review) return;

    const bridge = api();
    if (!bridge?.imaging_review_get_item) return;

    const nextCoords = {
      ...reviewCoordsRef.current,
      [axis]: Number(value),
    };
    reviewCoordsRef.current = nextCoords;

    const requestId = ++reviewRequestRef.current;

    try {
      const data = await bridge.imaging_review_get_item(
        selectedId,
        nextCoords.x,
        nextCoords.y,
        nextCoords.z,
        nextCoords.volume
      );

      if (requestId !== reviewRequestRef.current) return;

      setReview(data);
      reviewCoordsRef.current = {
        x: Number(data?.x ?? nextCoords.x),
        y: Number(data?.y ?? nextCoords.y),
        z: Number(data?.z ?? nextCoords.z),
        volume: Number(data?.volume ?? nextCoords.volume),
      };
    } catch (error) {
      if (requestId === reviewRequestRef.current) {
        alert(String(error));
      }
    }
  }

  async function setStatus(status) {
    const bridge = api();
    if (!bridge?.imaging_review_set_status) return;
    await bridge.imaging_review_set_status(selectedId, status);
    setRejectOpen(false);
    await loadItems();
    await onStateRefresh?.();
  }

  async function saveHeader() {
    if (!editField) return;
    const bridge = api();
    if (!bridge?.imaging_review_save_header) return;
    const data = await bridge.imaging_review_save_header(selectedId, editField, editValue);
    setReview(data);
  }

  async function chooseExternalReplacement() {
    const bridge = api();
    if (!bridge?.imaging_review_choose_external_defaced) {
      alert("External replacement API is unavailable.");
      return;
    }
    try {
      const result = await bridge.imaging_review_choose_external_defaced(selectedId);
      if (result?.ok) {
        setRejectOpen(false);
        await loadItems();
        await loadItem(selectedId);
        await onStateRefresh?.();
      }
    } catch (error) {
      alert(String(error));
    }
  }

  return (
    <Shell
      title="Imaging De-identification Review"
      siteId={siteId}
      onBack={onBack}
      onHome={onHome}
      onProcessImaging={onProcessImaging}
      onPatientReview={onPatientReview}
    >
      <WorkflowStepper current={4} completed={completedSteps} />
      <WorkflowStatusCard
        title="Review de-identification"
        description="Review each image and choose whether to accept it, replace it, place it on hold, or exclude it."
        state={stageState}
      />
      <div className={styles.reviewLayout}>
        <aside className={styles.reviewSidebar}>
          <h3>NIfTI files</h3>
          <div className={styles.reviewFileList}>
            {items.map(item => (
              <button
                key={item.id}
                className={`${styles.reviewFile} ${String(item.id) === selectedId ? styles.reviewFileActive : ""}`}
                onClick={() => loadItem(String(item.id))}
              >
                [{item.status}] {item.key}
              </button>
            ))}
          </div>
        </aside>

        <main className={styles.reviewMain}>
          {!review ? (
            <div className={styles.placeholder}>{loading ? "Loading…" : "No reviewable images were found."}</div>
          ) : (
            <>
              <section className={styles.card}>
                <h3>Raw header versus scrubbed header</h3>
                <div className={styles.headerTableWrap}>
                  <table className={styles.table}>
                    <thead>
                      <tr><th>Field</th><th>Raw</th><th>Scrubbed</th><th>Editable</th></tr>
                    </thead>
                    <tbody>
                      {review.header_rows.map(row => (
                        <tr
                          key={row.field}
                          className={editField === row.field ? styles.selectedHeader : ""}
                          onClick={() => {
                            setEditField(row.field);
                            setEditValue(row.scrubbed ?? "");
                          }}
                        >
                          <td>{row.field}</td>
                          <td>{row.raw}</td>
                          <td>{row.scrubbed}</td>
                          <td>{row.editable ? "Yes" : "No"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className={styles.headerEdit}>
                  <div className={styles.headerEditField}>
                    <span>Selected field</span>
                    <div className={styles.headerEditFieldValue}>
                      {editField || "Select an editable header field above"}
                    </div>
                  </div>

                  <label className={styles.headerEditValue}>
                    <span>Scrubbed value</span>
                    <input
                      type="text"
                      value={editValue}
                      placeholder={editField ? "Enter scrubbed value" : "Select an editable field first"}
                      onClick={event => event.stopPropagation()}
                      onPointerDown={event => event.stopPropagation()}
                      onChange={event => setEditValue(event.target.value)}
                      disabled={!review.header_rows.find(row => row.field === editField)?.editable}
                    />
                  </label>

                  <div className={styles.headerEditActions}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      disabled={!review.header_rows.find(row => row.field === editField)?.editable}
                      onClick={saveHeader}
                    >
                      Save Header Edit
                    </button>
                  </div>
                </div>
              </section>

              <section className={styles.card}>
                <h3>Interactive raw versus defaced image review</h3>
                <div className={styles.imageGrid}>
                  <ImageView label="Raw Axial" src={review.views.raw_axial} />
                  <ImageView label="Raw Coronal" src={review.views.raw_coronal} />
                  <ImageView label="Raw Sagittal" src={review.views.raw_sagittal} />
                  <ImageView label="Defaced Axial" src={review.views.defaced_axial} />
                  <ImageView label="Defaced Coronal" src={review.views.defaced_coronal} />
                  <ImageView label="Defaced Sagittal" src={review.views.defaced_sagittal} />
                </div>

                <Slider label="Sagittal X" value={review.x} max={review.limits.x_max} onChange={value => move("x", value)} />
                <Slider label="Coronal Y" value={review.y} max={review.limits.y_max} onChange={value => move("y", value)} />
                <Slider label="Axial Z" value={review.z} max={review.limits.z_max} onChange={value => move("z", value)} />
                {review.is_4d && (
                  <Slider
                    label="4D volume"
                    value={review.volume}
                    max={review.limits.volume_max}
                    onChange={value => move("volume", value)}
                  />
                )}

                <p className={styles.helpText}>
                  Use the sliders to move through the complete slice stack. All six panels stay linked.
                </p>
              </section>

              <div className={styles.reviewFooter}>
                <span>{review.key} | Review status: {review.status}</span>
                <div>
                  <button className={styles.secondaryButton} onClick={() => setRejectOpen(true)}>Reject</button>
                  <button className={styles.primaryButton} onClick={() => setStatus("Accepted")}>Accept</button>
                  <button
                    className={styles.primaryButton}
                    disabled={stageState !== "complete"}
                    onClick={onContinue}
                  >
                    Continue to Step 5: Metadata & BIDS
                  </button>
                </div>
              </div>
            </>
          )}
        </main>
      </div>

      {rejectOpen && (
        <div className={styles.modalBackdrop}>
          <div className={styles.modal}>
            <h3>Defacing Rejected</h3>
            <p>
              Choose what should happen to this image. Images placed on hold or rejected
              will not continue to Metadata & BIDS.
            </p>
            <button className={styles.primaryButton} onClick={chooseExternalReplacement}>Upload Replacement</button>
            <button className={styles.secondaryButton} onClick={() => setStatus("On Hold - Needs Defaced Replacement")}>Put on Hold</button>
            <button className={styles.secondaryButton} onClick={() => setStatus("Rejected - Not Included")}>Reject / Do Not Include</button>
            <button className={styles.secondaryButton} onClick={() => setRejectOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </Shell>
  );
}

function ImageView({ label, src }) {
  return (
    <div className={styles.imageView}>
      <span>{label}</span>
      <div className={styles.imageCanvas}>
        {src ? <img src={src} alt={label} /> : <div>Image unavailable</div>}
      </div>
    </div>
  );
}

function Slider({ label, value, max, onChange, disabled = false }) {
  const [localValue, setLocalValue] = useState(Number(value ?? 0));
  const timerRef = useRef(null);
  const draggingRef = useRef(false);

  useEffect(() => {
    if (!draggingRef.current) {
      setLocalValue(Number(value ?? 0));
    }
  }, [value]);

  useEffect(() => () => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
  }, []);

  function queueChange(nextValue) {
    const numericValue = Number(nextValue);
    setLocalValue(numericValue);

    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      onChange(numericValue);
    }, 90);
  }

  function finishChange() {
    draggingRef.current = false;
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
      onChange(localValue);
    }
  }

  return (
    <label className={styles.sliderRow}>
      <span>{label}</span>
      <input
        type="range"
        min="0"
        max={Math.max(0, max)}
        step="1"
        value={localValue}
        disabled={disabled}
        onPointerDown={() => { draggingRef.current = true; }}
        onPointerUp={finishChange}
        onPointerCancel={finishChange}
        onBlur={finishChange}
        onChange={event => queueChange(event.target.value)}
      />
      <strong>{localValue} / {max}</strong>
    </label>
  );
}

function Shell({
  title,
  subtitle,
  onBack,
  children,
}) {
  return (
    <div>
      <div className={styles.localTopbar}>
        {onBack && (
          <button className={styles.localBack} onClick={onBack}>
            <ArrowLeft size={16} />
            Back
          </button>
        )}
      </div>

      <div className={styles.pageHeading}>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>

      {children}
    </div>
  );
}
