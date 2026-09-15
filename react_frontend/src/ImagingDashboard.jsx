import { useEffect, useMemo, useState } from "react";
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
}) {
  const [view, setView] = useState(initialView === "processing" ? "processing" : "home");
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

  useEffect(() => {
    if (view === "processing") {
      loadState();
    }

    if (view === "metadata") {
      loadBidsState();
    }
  }, [view]);

  async function loadState() {
    const bridge = api();
    if (!bridge?.imaging_get_state) return;
    try {
      const state = await bridge.imaging_get_state();
      applyState(state);
    } catch (error) {
      appendLog(String(error));
    }
  }

  function applyState(state = {}) {
    setDicomSources(state.dicom_input_dirs ?? []);
    setNiftiSources(state.nifti_input_dirs ?? []);
    setRawDicom(state.raw_dicom_files ?? []);
    setRawNifti(state.raw_nifti_files ?? []);
    if (typeof state.derivatives_dir === "string") setDerivativesDir(state.derivatives_dir);
    if (typeof state.bids_output_dir === "string") setBidsOutputDir(state.bids_output_dir);
    if (state.status) setStatus(state.status);
    if (Array.isArray(state.logs)) setLogs(state.logs);
    if (state.log) appendLog(state.log);
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
    if (kind === "derivatives") setDerivativesDir(selected);
    else setBidsOutputDir(selected);
  }

  async function saveSettings(showConfirmation = true) {
    const bridge = api();
    if (!bridge?.imaging_save_settings) return null;

    const state = await bridge.imaging_save_settings({
      dicom_input_dirs: dicomSources,
      nifti_input_dirs: niftiSources,
      derivatives_dir: derivativesDir,
      bids_output_dir: bidsOutputDir,
    });

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
      setBidsState(state);
      setAcceptedImages(state?.records ?? []);
      setHeldImageCount(Number(state?.held_count ?? 0));
    } catch (error) {
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

    try {
      setBusy(true);
      setStatus(`Running: ${operation}`);

      const result = await bridge.imaging_run_operation({
        operation,
        dicom_input_dirs: dicomSources,
        nifti_input_dirs: niftiSources,
        derivatives_dir: derivativesDir,
        bids_output_dir: bidsOutputDir,
        overwrite,
      });

      if (result?.log) appendLog(result.log);
      if (result?.status) setStatus(result.status);

      if (operation === "review" && result?.ok !== false) {
        setView("review");
      }

      if (operation === "bids" && result?.ok !== false) {
        setAcceptedImages(result?.accepted_files ?? []);
        setHeldImageCount(Number(result?.held_count ?? 0));
        setView("metadata");
      }
    } catch (error) {
      setStatus(`Failed: ${operation}`);
      appendLog(String(error));
      alert(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function stopOperation() {
    try {
      await api()?.imaging_stop_operation?.();
    } finally {
      setBusy(false);
      setStatus("Stopped");
      appendLog("Operation stopped.");
    }
  }

  if (view === "home") {
    return (
      <Shell
        title="Imaging"
        siteId={siteId}
        onBack={onBack}
        onHome={onHome}
        onProcessImaging={() => setView("processing")}
        onPatientReview={onPatientReview}
      >
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
          <button className={styles.optionCard} onClick={() => setView("processing")}>
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
        onBack={() => setView("processing")}
        onHome={onHome}
        onProcessImaging={() => setView("processing")}
        onPatientReview={onPatientReview}
        onContinue={() => setView("metadata")}
      />
    );
  }

  if (view === "metadata") {
    return (
      <ImagingBidsStep
        siteId={siteId}
        bidsState={bidsState}
        overwrite={overwrite}
        onBack={() => setView("processing")}
        onHome={onHome}
        onProcessImaging={() => setView("processing")}
        onPatientReview={onPatientReview}
        onReload={loadBidsState}
        onLog={appendLog}
      />
    );
  }

  const dicomStudyCount = dicomSources.length;
  const niftiStudyCount = niftiSources.length;
  const selectedStudyCount = dicomStudyCount + niftiStudyCount;

  return (
    <Shell
      title="Process Imaging"
      siteId={siteId}
      onBack={() => setView("home")}
      onHome={onHome}
      onProcessImaging={() => setView("processing")}
      onPatientReview={onPatientReview}
      subtitle="De-identify and prepare MRI or CT data for CoCANoT. Follow the steps below to select your data, run the de-identification pipeline, and export BIDS-formatted output."
    >
      <WorkflowStepper current={openSection} />

      <WorkflowSection
        number={1}
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
        title="Set output folders"
        subtitle="Choose where to save processed files. A derivatives folder is required before processing can begin."
        open={openSection === 2}
        onToggle={() => setOpenSection(2)}
      >
        <div className={styles.outputCardGrid}>
          <FolderField
            label="Derivatives output folder"
            value={derivativesDir}
            onChange={setDerivativesDir}
            onBrowse={() => browseOutput("derivatives")}
            disabled={busy}
          />

          <FolderField
            label="BIDS output folder"
            value={bidsOutputDir}
            onChange={setBidsOutputDir}
            onBrowse={() => browseOutput("bids")}
            disabled={busy}
          />
        </div>

        <div className={styles.infoStrip}>
          The derivatives folder will contain converted_nifti, scrubbed_header,
          scrubbed_defaced, logs, and imaging_review_state.json.
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
        title="Process & review"
        subtitle="Run the de-identification pipeline and review outputs."
        open={openSection === 3}
        onToggle={() => setOpenSection(3)}
      >
        <div className={styles.processGrid}>
          <ProcessAction
            step="3A"
            title="Prepare NIfTI"
            description="Convert selected DICOM inputs and stage existing NIfTI files."
            disabled={busy}
            onClick={() => runOperation("prepare")}
          />

          <ProcessAction
            step="3B"
            title="Scrub Headers"
            description="Remove identifying values from staged NIfTI headers."
            disabled={busy}
            onClick={() => runOperation("scrub")}
          />

          <ProcessAction
            step="3C"
            title="Deface"
            description="Create defaced copies for imaging review."
            disabled={busy}
            onClick={() => runOperation("deface")}
          />

          <ProcessAction
            step="3D"
            title="Review"
            description="Compare raw and defaced images before accepting them."
            disabled={busy}
            onClick={() => runOperation("review")}
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
              Stop Current Operation
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
            disabled={busy}
            onClick={() => setOpenSection(4)}
          >
            Continue to Finalize & Export <ArrowRight size={16} />
          </button>
        </div>
      </WorkflowSection>

      <WorkflowSection
        number={4}
        title="Finalize & export"
        subtitle="Create BIDS-formatted output and complete the process."
        open={openSection === 4}
        onToggle={() => setOpenSection(4)}
      >
        <div className={styles.finalizePanel}>
          <div className={styles.finalizeIcon}><Check size={20} strokeWidth={2.2} /></div>
          <div>
            <strong>Metadata & BIDS</strong>
            <p>
              Continue with images accepted during review, complete the
              dictionary-driven Imaging metadata, check for existing exports,
              and launch BIDS conversion.
            </p>
          </div>
        </div>

        <div className={styles.sectionActions}>
          <button
            className={styles.secondaryButton}
            onClick={() => setOpenSection(3)}
          >
            Back to Process & Review
          </button>

          <button
            className={styles.ctaButton}
            disabled={busy}
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

function WorkflowStepper({ current }) {
  const steps = [
    ["Select Data", 1],
    ["Set Output Folders", 2],
    ["Process & Review", 3],
    ["Finalize & Export", 4],
  ];

  return (
    <div className={styles.stepper}>
      {steps.map(([label, number], index) => (
        <div className={styles.stepperItem} key={label}>
          <div
            className={`${styles.stepCircle} ${
              number === current
                ? styles.stepCircleActive
                : number < current
                  ? styles.stepCircleDone
                  : ""
            }`}
          >
            {number}
          </div>
          <span className={number === current ? styles.stepLabelActive : ""}>
            {label}
          </span>
          {index < steps.length - 1 && <div className={styles.stepLine} />}
        </div>
      ))}
    </div>
  );
}

function WorkflowSection({
  number,
  title,
  subtitle,
  open,
  onToggle,
  children,
}) {
  return (
    <section className={`${styles.workflowSection} ${open ? styles.workflowSectionOpen : ""}`}>
      <button className={styles.workflowSectionHeader} onClick={onToggle}>
        <div className={styles.sectionNumber}>{number}</div>
        <div className={styles.sectionTitleBlock}>
          <strong>{title}</strong>
          <span>{subtitle}</span>
        </div>

        {!open && <span className={styles.goSection}>Go to Section</span>}
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

function ProcessAction({
  step,
  title,
  description,
  disabled,
  onClick,
}) {
  return (
    <button className={styles.processAction} disabled={disabled} onClick={onClick}>
      <span className={styles.processStep}>{step}</span>
      <strong>{title}</strong>
      <p>{description}</p>
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

  useEffect(() => {
    const nextRecords = bidsState?.records ?? [];
    setRecords(nextRecords);
    setRules(bidsState?.rules ?? []);

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
  }, [bidsState]);

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

  function toggleInclude(id) {
    setRecords(current =>
      current.map(record =>
        record.id === id
          ? { ...record, include: !record.include }
          : record
      )
    );
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
    setRecords(current =>
      current.map(record =>
        selectedIds.includes(record.id)
          ? { ...record, include }
          : record
      )
    );
  }

  async function reviewAndConvert() {
    const bridge = api();

    if (!bridge?.imaging_bids_validate) {
      alert("The Imaging BIDS validation API is unavailable.");
      return;
    }

    try {
      setBusy(true);
      const result = await bridge.imaging_bids_validate({ records, overwrite });

      if (!result?.ok) {
        setProblems(result?.problems ?? ["Metadata validation failed."]);
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
      alert(
        `Imaging BIDS / CoCANoT conversion started for ${result.record_count} image(s).`
      );
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
                          record.existing_export
                            ? styles.duplicateBadge
                            : styles.newBadge
                        }
                      >
                        {record.existing_export
                          ? "Already exported"
                          : "New"}
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
                <strong>Existing BIDS record detected</strong>
                <p>
                  This accepted image is an exact SHA-256 match for a NIfTI
                  already in the BIDS output. It is excluded by default.
                </p>
              </div>

              <div className={styles.existingExportDetails}>
                <span>
                  Existing output: {active.existing_export.nifti_path}
                </span>
                <span>
                  Image ID: {active.existing_export.metadata?.ImageID ?? ""}
                </span>
                <span>
                  Patient: {active.existing_export.metadata?.CoCANoTPatientID ?? ""}
                </span>
              </div>
            </section>
          )}

          <section className={styles.card}>
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

      // Preserve dictionary ordering just like the original Tkinter listbox.
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
}) {
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [review, setReview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [editField, setEditField] = useState("");
  const [editValue, setEditValue] = useState("");
  const [rejectOpen, setRejectOpen] = useState(false);

  useEffect(() => {
    loadItems();
  }, []);

  async function loadItems() {
    const bridge = api();
    if (!bridge?.imaging_review_get_items) return;
    const result = await bridge.imaging_review_get_items();
    setItems(result ?? []);
    if (result?.length) {
      setSelectedId(String(result[0].id));
      await loadItem(String(result[0].id));
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
    await loadItem(selectedId, {
      x: axis === "x" ? Number(value) : review.x,
      y: axis === "y" ? Number(value) : review.y,
      z: axis === "z" ? Number(value) : review.z,
      volume: axis === "volume" ? Number(value) : review.volume,
    });
  }

  async function setStatus(status) {
    const bridge = api();
    if (!bridge?.imaging_review_set_status) return;
    await bridge.imaging_review_set_status(selectedId, status);
    setRejectOpen(false);
    await loadItems();
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
                  <label>
                    <span>Selected field</span>
                    <input value={editField} readOnly />
                  </label>
                  <label className={styles.headerEditValue}>
                    <span>Scrubbed value</span>
                    <input
                      value={editValue}
                      onChange={event => setEditValue(event.target.value)}
                      disabled={!review.header_rows.find(row => row.field === editField)?.editable}
                    />
                  </label>
                  <button
                    className={styles.secondaryButton}
                    disabled={!review.header_rows.find(row => row.field === editField)?.editable}
                    onClick={saveHeader}
                  >
                    Save Header Edit
                  </button>
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
                  <button className={styles.primaryButton} onClick={onContinue}>Metadata & BIDS</button>
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
  return (
    <label className={styles.sliderRow}>
      <span>{label}</span>
      <input
        type="range"
        min="0"
        max={Math.max(0, max)}
        step="1"
        value={value}
        disabled={disabled}
        onChange={event => onChange(event.target.value)}
      />
      <strong>{value} / {max}</strong>
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
