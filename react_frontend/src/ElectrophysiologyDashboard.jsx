import { useEffect, useMemo, useRef, useState } from "react";

import {

  Activity,

  ArrowLeft,

  ArrowRight,

  Check,

  CheckCircle2,

  ChevronDown,

  CircleHelp,

  Database,

  FileAudio,

  FolderOpen,

  Info,

  Play,

  RefreshCw,

  Save,

  Upload,

} from "lucide-react";

import styles from "./ElectrophysiologyDashboard.module.css";

const api = () => window.pywebview?.api ?? null;

export default function ElectrophysiologyDashboard({

  initialView = "home",

  onNavigate,

  onRouteChange,

  resumeBidsState = null,

  autoValidateBids = false,

  onCreateClinicalAssessment,

}) {

  const [view, setView] = useState(

    ["processing", "review", "bids"].includes(initialView)
      ? initialView
      : "home"

  );

  const [openSection, setOpenSection] = useState(1);

  const [state, setState] = useState({

    input_dirs: [],

    records: [],

    derivatives_dir: "",

    bids_output_dir: "",

    logs: [],

    status: "Ready",

  });

  const [records, setRecords] = useState([]);

  const [selectedSources, setSelectedSources] = useState([]);

  const [overwrite, setOverwrite] = useState(false);

  const [reviewPairs, setReviewPairs] = useState([]);

  const [review, setReview] = useState(null);

  const [bidsState, setBidsState] = useState(null);

  const [processRunning, setProcessRunning] = useState(false);

  const [processStages, setProcessStages] = useState({

    scrub: "not_started",

    review: "not_started",

    metadata_bids: "not_started",

  });
  const outputSettingsDirtyRef = useRef(false);
  const bidsRecordsRef = useRef([]);

  function showEphysHome() {

    setView("home");

    onRouteChange?.("ephys");

  }

  function showEphysProcessing() {

    setView("processing");

    onRouteChange?.("ephys-processing");

  }

  useEffect(() => {

    let cancelled = false;

    if (view === "processing") {

      async function loadProcessingOverview() {

        const nextState = await loadState();

        if (cancelled) return;

        const pairs = await refreshReviewPairs();

        if (cancelled) return;

        await refreshBidsAwareness(
          nextState ?? state,
          pairs ?? []
        );

      }

      loadProcessingOverview();

      const interval = window.setInterval(() => {

        refreshProcessState();

      }, 750);

      return () => {
        cancelled = true;
        window.clearInterval(interval);
      };

    }

    if (view === "review") loadReview();

    if (view === "bids") loadBids();

    return () => {
      cancelled = true;
    };

  }, [view]);

  function deriveMetadataBidsStage(
    records = bidsRecordsRef.current,
    fallback = "not_started"
  ) {
    if (!Array.isArray(records) || records.length === 0) {
      return fallback;
    }

    const allCompleted = records.every(
      record => record.record_state === "completed_recorded"
    );

    if (allCompleted) {
      return "complete";
    }

    const hasRealProblem = records.some(record =>
      [
        "output_record_deleted",
        "recorded_export_missing",
      ].includes(record.record_state)
    );

    return hasRealProblem ? "failed" : "running";
  }

  async function loadState() {

    const next = await api()?.ephys_get_state?.();

    if (!next) return;

    setState(current => ({
      ...next,
      derivatives_dir: outputSettingsDirtyRef.current
        ? current.derivatives_dir
        : (next.derivatives_dir ?? ""),
      bids_output_dir: outputSettingsDirtyRef.current
        ? current.bids_output_dir
        : (next.bids_output_dir ?? ""),
    }));
    setRecords(next.records ?? []);
    setProcessRunning(Boolean(next.process_running));

    if (next.process_stages) {

      const nextStages = {
        ...next.process_stages,
      };

      if (
        nextStages.metadata_bids === "not_started" &&
        bidsRecordsRef.current.length > 0
      ) {
        nextStages.metadata_bids =
          deriveMetadataBidsStage(
            bidsRecordsRef.current,
            "not_started"
          );
      }

      setProcessStages(current => ({
        ...current,
        ...nextStages,
      }));

    }

    return next;

  }

  async function refreshReviewPairs() {

    const pairs = await api()?.ephys_review_get_pairs?.();

    const nextPairs = pairs ?? [];

    setReviewPairs(nextPairs);

    return nextPairs;

  }

  async function refreshProcessState() {

    const bridge = api();

    if (!bridge?.ephys_get_state) return;

    try {

      const next = await bridge.ephys_get_state();

      if (!next) return;

      setState(current => ({
      ...current,
      input_dirs: next.input_dirs ?? current.input_dirs,
      derivatives_dir: outputSettingsDirtyRef.current
        ? current.derivatives_dir
        : (next.derivatives_dir ?? current.derivatives_dir),
      bids_output_dir: outputSettingsDirtyRef.current
        ? current.bids_output_dir
        : (next.bids_output_dir ?? current.bids_output_dir),
      logs: next.logs ?? current.logs,
      status: next.status ?? current.status,
      process_running: Boolean(next.process_running),
    }));

      if (next.process_stages) {

        const nextStages = {
          ...next.process_stages,
        };

        if (
          nextStages.metadata_bids === "not_started" &&
          bidsRecordsRef.current.length > 0
        ) {
          nextStages.metadata_bids =
            deriveMetadataBidsStage(
              bidsRecordsRef.current,
              "not_started"
            );
        }

        setProcessStages(current => ({
          ...current,
          ...nextStages,
        }));

      }

      const running = Boolean(next.process_running);

      setProcessRunning(running);

      if (!running) {

        const pairs = await refreshReviewPairs();

        await refreshBidsAwareness(
          next,
          pairs ?? []
        );

      }

    } catch (error) {

      setState(current => ({

        ...current,

        status: `Error: ${String(error)}`,

      }));

    }

  }

  async function choose(kind) {

    const bridge = api();

    const next =

      kind === "files"

        ? await bridge?.ephys_choose_files?.()

        : await bridge?.ephys_choose_folders?.();

    if (next) {

      setState(next);

      setRecords(next.records ?? []);

    }

  }

  async function removeSources() {

    const ids = selectedSources.map(index => `source:${index}`);

    const next = await api()?.ephys_remove_sources?.(ids);

    if (next) {

      setState(next);

      setRecords(next.records ?? []);

      setSelectedSources([]);

    }

  }

  async function refreshBidsAwareness(
    nextState = state,
    pairsOverride = reviewPairs
  ) {
    const inputDirs = Array.isArray(nextState?.input_dirs)
      ? nextState.input_dirs.filter(Boolean)
      : [];
    const derivativesDir = String(
      nextState?.derivatives_dir ?? ""
    ).trim();
    const bidsOutputDir = String(
      nextState?.bids_output_dir ?? ""
    ).trim();
    const pairs = Array.isArray(pairsOverride)
      ? pairsOverride
      : [];
    const hasAcceptedRecording = pairs.some(
      pair => String(pair?.status ?? "") === "Accepted"
    );

    if (
      inputDirs.length === 0 ||
      !derivativesDir ||
      !bidsOutputDir ||
      !hasAcceptedRecording
    ) {
      bidsRecordsRef.current = [];
      setBidsState(null);
      return;
    }

    try {
      const next = await api()?.ephys_bids_get_state?.();

      if (next) {
        setBidsState(next);

        const outputRecords = next.records ?? [];
        bidsRecordsRef.current = outputRecords;

        const derivedMetadataStage =
          deriveMetadataBidsStage(
            outputRecords,
            next.process_stages?.metadata_bids ??
              "not_started"
          );

        setProcessStages(current => ({
          ...current,
          ...(next.process_stages ?? {}),
          metadata_bids: derivedMetadataStage,
        }));
      }
    } catch {
      setBidsState(null);

      setProcessStages(current => ({
        ...current,
        metadata_bids:
          current.metadata_bids === "running"
            ? "running"
            : "not_started",
      }));
    }
  }

  async function persistOutputSettings(nextState) {
    const inputDirs = Array.isArray(nextState?.input_dirs)
      ? nextState.input_dirs.filter(Boolean)
      : [];
    const derivativesDir = String(
      nextState?.derivatives_dir ?? ""
    ).trim();
    const bidsOutputDir = String(
      nextState?.bids_output_dir ?? ""
    ).trim();

    if (
      inputDirs.length === 0 ||
      !derivativesDir ||
      !bidsOutputDir
    ) {
      return null;
    }

    const saved = await api()?.ephys_save_settings?.({
      input_dirs: nextState.input_dirs,
      derivatives_dir: derivativesDir,
      bids_output_dir: bidsOutputDir,
    });

    if (saved) {
      outputSettingsDirtyRef.current = false;

      const mergedState = {
        ...nextState,
        ...saved,
        derivatives_dir:
          saved.derivatives_dir ?? derivativesDir,
        bids_output_dir:
          saved.bids_output_dir ?? bidsOutputDir,
      };

      setState(current => ({
        ...current,
        ...mergedState,
      }));

      await refreshBidsAwareness(mergedState);
    }

    return saved;
  }

  async function browseOutput(key) {
    const selected = await api()?.choose_folder?.();
    if (!selected) return;

    outputSettingsDirtyRef.current = true;

    const nextState = {
      ...state,
      [key]: selected,
    };

    setState(nextState);

    const hasInputs =
      Array.isArray(nextState.input_dirs) &&
      nextState.input_dirs.some(Boolean);
    const hasBothFolders = Boolean(
      String(nextState.derivatives_dir ?? "").trim() &&
      String(nextState.bids_output_dir ?? "").trim()
    );

    if (!hasInputs || !hasBothFolders) {
      return;
    }

    try {
      await persistOutputSettings(nextState);
    } catch (error) {
      setState(current => ({
        ...current,
        status: `Could not save output folders: ${String(error)}`,
      }));
    }
  }

  async function saveSettings() {
    outputSettingsDirtyRef.current = true;

    const hasInputs =
      Array.isArray(state.input_dirs) &&
      state.input_dirs.some(Boolean);
    const hasBothFolders = Boolean(
      String(state.derivatives_dir ?? "").trim() &&
      String(state.bids_output_dir ?? "").trim()
    );

    if (!hasInputs) {
      setState(current => ({
        ...current,
        status: "Add at least one EDF file or folder before saving output settings.",
      }));
      return;
    }

    if (!hasBothFolders) {
      setState(current => ({
        ...current,
        status: "Select both output folders before saving.",
      }));
      return;
    }

    try {
      await persistOutputSettings(state);
    } catch (error) {
      setState(current => ({
        ...current,
        status: `Could not save output folders: ${String(error)}`,
      }));
    }
  }

  async function run(operation) {

    const bridge = api();

    if (!bridge?.ephys_run_operation) {

      alert("The Electrophysiology Python bridge is unavailable.");

      return;

    }

    if (operation === "scrub") {

      if (!records.some(record => record.include)) {

        alert("Include at least one EDF recording before running Step 3A.");

        return;

      }

      if (!state.derivatives_dir || !state.bids_output_dir) {

        alert("Select and save both output folders before running Step 3A.");

        return;

      }

      setProcessRunning(true);

      setState(current => ({

        ...current,

        status: "Starting EDF metadata scrubbing",

      }));

    }

    try {

      await persistOutputSettings(state);

      const result = await bridge.ephys_run_operation({

        operation,

        records,

        derivatives_dir: state.derivatives_dir,

        bids_output_dir: state.bids_output_dir,

        overwrite,

      });

      if (result?.status || result?.log) {

        setState(current => ({

          ...current,

          status: result?.status ?? current.status,

          logs: result?.log

            ? [...(current.logs ?? []), result.log]

            : current.logs,

        }));

      }

      if (operation === "review" && result?.ok) {

        setView("review");

        return;

      }

      if (operation === "bids" && result?.ok) {

        setView("bids");

        return;

      }

      await refreshProcessState();

      await refreshBidsAwareness();

    } catch (error) {

      setProcessRunning(false);

      const message = String(error);

      setState(current => ({

        ...current,

        status: `Failed: ${message}`,

        logs: [...(current.logs ?? []), message],

      }));

      alert(message);

    }

  }

  function toggleRecord(id, include) {

    setRecords(current =>

      current.map(record =>

        record.id === id

          ? { ...record, include }

          : record

      )

    );

  }

  async function loadReview() {

    const pairs = await api()?.ephys_review_get_pairs?.();

    setReviewPairs(pairs ?? []);

    if (pairs?.length) {

      setReview(

        await api()?.ephys_review_get_pair?.(pairs[0].id)

      );

    }

  }

  async function selectPair(id) {

    setReview(await api()?.ephys_review_get_pair?.(id));

  }

  async function saveReview() {

    if (!review) return;

    setReview(

      await api()?.ephys_review_save_pair?.(

        review.id,

        review.scrubbed.header,

        review.scrubbed.annotations

      )

    );

  }

  async function setReviewStatus(status) {

    if (!review) return;

    const next = await api()?.ephys_review_set_status?.(

      review.id,

      status

    );

    if (next) {

      setReview(next);

    }

    const pairs = await api()?.ephys_review_get_pairs?.();

    setReviewPairs(pairs ?? []);

    const acceptedExists = (pairs ?? []).some(
      pair => String(pair?.status ?? "") === "Accepted"
    );

    if (acceptedExists) {
      await refreshBidsAwareness(state);
    } else {
      setBidsState(null);
    }

    const currentState = await api()?.ephys_get_state?.();

    if (currentState?.process_stages) {

      const nextStages = {
        ...currentState.process_stages,
      };

      if (
        nextStages.metadata_bids === "not_started" &&
        bidsRecordsRef.current.length > 0
      ) {
        nextStages.metadata_bids =
          deriveMetadataBidsStage(
            bidsRecordsRef.current,
            "not_started"
          );
      }

      setProcessStages(current => ({

        ...current,

        ...nextStages,

      }));

    }

  }

  async function loadBids() {

    await refreshBidsAwareness();

  }

  const includedCount = useMemo(

    () => records.filter(record => record.include).length,

    [records]

  );

  const existingBidsOutputComplete = useMemo(() => {

    const outputRecords = bidsState?.records ?? [];

    return (

      outputRecords.length > 0 &&

      outputRecords.every(record => record.record_state === "completed_recorded")

    );

  }, [bidsState]);

  const workflowCompletion = useMemo(() => ({

    1: records.length > 0,

    2: Boolean(state.derivatives_dir && state.bids_output_dir),

    3: processStages.scrub === "complete" || (includedCount > 0 && reviewPairs.length >= includedCount),

    4: processStages.review === "complete",

    5: processStages.metadata_bids === "complete" || existingBidsOutputComplete,

  }), [

    records.length,

    state.derivatives_dir,

    state.bids_output_dir,

    reviewPairs.length,

    includedCount,

    processStages.scrub,

    processStages.review,

    processStages.metadata_bids,

    existingBidsOutputComplete,

  ]);

  if (view === "home") {

    return (

      <div>

        <div className={styles.localTopbar}>
          <button
            className={styles.localBack}
            onClick={() => onNavigate?.("home")}
          >
            <ArrowLeft size={16} />
            Home
          </button>

          <span className={styles.localBreadcrumbChevron}>
            ›
          </span>

          <span className={styles.localBreadcrumbCurrent}>
            Electrophysiology
          </span>
        </div>

        <PageHeading

          eyebrow="ELECTROPHYSIOLOGY PIPELINE"

          title="Prepare electrophysiology data for research use"

          text="Select EDF recordings, scrub identifying header information, review the results, and convert accepted recordings to BIDS."

        />

        <div className={styles.homeCards}>

          <button onClick={showEphysProcessing}>

            <Activity size={28} />

            <strong>Process electrophysiology data</strong>

            <span>Open the complete EDF de-identification workflow.</span>

          </button>

          <button onClick={() => onNavigate("patient-review")}>

            <Database size={28} />

            <strong>Review patient data</strong>

            <span>Review stored electrophysiology and metadata records.</span>

          </button>

        </div>

      </div>

    );

  }

  if (view === "review") {

    return (

      <EDFReview

        pairs={reviewPairs}

        review={review}

        onSelect={selectPair}

        onChange={setReview}

        onSave={saveReview}

        onSetStatus={setReviewStatus}

        onBack={showEphysProcessing}

        completedSteps={workflowCompletion}

        stageState={processStages.review}

        onContinue={() => setView("bids")}

      />

    );

  }

  if (view === "bids") {

    return (

      <EphysBids

        state={bidsState}

        overwrite={overwrite}

        completedSteps={workflowCompletion}

        stageState={workflowCompletion[5] ? "complete" : processStages.metadata_bids}

        onBack={() => setView("review")}

        resumeState={resumeBidsState}

        autoValidate={autoValidateBids}

        onCreateClinicalAssessment={onCreateClinicalAssessment}

        onStarted={() => {

          setOpenSection(5);

          setProcessStages(current => ({

            ...current,

            metadata_bids: "running",

          }));

          setProcessRunning(true);

          setView("processing");

          onRouteChange?.("ephys-processing");

        }}

      />

    );

  }

  return (

    <div>

      <div className={styles.localTopbar}>
        <button
          className={styles.localBack}
          onClick={showEphysHome}
        >
          <ArrowLeft size={16} />
          Electrophysiology
        </button>

        <span className={styles.localBreadcrumbChevron}>
          ›
        </span>

        <span className={styles.localBreadcrumbCurrent}>
          Process Recordings
        </span>
      </div>

      <PageHeading

        title="Process Recordings"

        text="Add EDF files or folders, choose the recordings to process, scrub headers and metadata, review outputs, and export BIDS-formatted data."

      />

      <WorkflowStepper current={openSection} completed={workflowCompletion} />

      <WorkflowSection

        number={1}

        complete={workflowCompletion[1]}

        title="Select recordings"

        subtitle="Add EDF files and/or folders to include in this session."

        open={openSection === 1}

        onOpen={() => setOpenSection(1)}

      >

        <div className={styles.uploadGridSingle}>

          <UploadCard

            title="Add EDF files or folders"

            text="Select EDF files or a directory containing electrophysiology recordings."

            onChooseFiles={() => choose("files")}

            onChooseFolder={() => choose("folders")}

          />

        </div>

        <div className={styles.selectedBar}>

          <Database size={24} />

          <div>

            <strong>Selected data</strong>

            <span>

              {(state.input_dirs ?? []).length} source{(state.input_dirs ?? []).length === 1 ? "" : "s"}

              <em>|</em>

              {includedCount} EDF file{includedCount === 1 ? "" : "s"} selected

            </span>

          </div>

          <details className={styles.selectedDetails}>

            <summary>View Selected Data</summary>

            <div className={styles.selectedPopover}>

              <section>

                <div className={styles.popoverHeader}>

                  <strong>Source files / folders</strong>

                  <button disabled={!selectedSources.length} onClick={removeSources}>

                    Remove selected

                  </button>

                </div>

                {(state.input_dirs ?? []).map((source, index) => (

                  <label key={`${source}-${index}`}>

                    <input

                      type="checkbox"

                      checked={selectedSources.includes(index)}

                      onChange={() =>

                        setSelectedSources(current =>

                          current.includes(index)

                            ? current.filter(item => item !== index)

                            : [...current, index]

                        )

                      }

                    />

                    <span>{source}</span>

                  </label>

                ))}

              </section>

              <table className={styles.table}>

                <thead>

                  <tr>

                    <th>Include</th>

                    <th>File Name</th>

                    <th>Source</th>

                  </tr>

                </thead>

                <tbody>

                  {records.map(record => (

                    <tr key={record.id}>

                      <td>

                        <input

                          type="checkbox"

                          checked={Boolean(record.include)}

                          onChange={event =>

                            toggleRecord(record.id, event.target.checked)

                          }

                        />

                      </td>

                      <td>{record.file_name}</td>

                      <td>{record.source_name}</td>

                    </tr>

                  ))}

                </tbody>

              </table>

            </div>

          </details>

        </div>

        <div className={styles.sectionFooter}>

          <div />

          <button

            className={styles.primary}

            disabled={!records.length}

            onClick={() => setOpenSection(2)}

          >

            Continue to Output Folders

            <ArrowRight size={16} />

          </button>

        </div>

      </WorkflowSection>

      <WorkflowSection

        number={2}

        complete={workflowCompletion[2]}

        title="Set output folders"

        subtitle="Choose where to save processed files. A derivatives folder is required before processing can begin."

        open={openSection === 2}

        onOpen={() => setOpenSection(2)}

      >

        <div className={styles.folderStack}>

          <FolderField

            label="Derivatives output folder"

            value={state.derivatives_dir}

            onChange={value => {
            outputSettingsDirtyRef.current = true;
            setState(current => ({
              ...current,
              derivatives_dir: value,
            }));
          }}

            onBrowse={() => browseOutput("derivatives_dir")}

          />

          <div className={styles.folderDescription}>

            The derivatives folder will contain staged recordings, scrubbed EDFs, review files, and processing logs.

          </div>

          <FolderField

            label="Final output folder"

            value={state.bids_output_dir}

            onChange={value => {
            outputSettingsDirtyRef.current = true;
            setState(current => ({
              ...current,
              bids_output_dir: value,
            }));
          }}

            onBrowse={() => browseOutput("bids_output_dir")}

          />

          <div className={styles.folderDescription}>

            The final de-identified recordings and associated metadata will be stored here in a BIDS-compatible format.

          </div>

        </div>

        <div className={styles.sectionFooter}>

          <button className={styles.secondary} onClick={saveSettings}>

            <Save size={15} />

            Save Folder Settings

          </button>

          <button

            className={styles.primary}

            disabled={!state.derivatives_dir || !state.bids_output_dir}

            onClick={() => setOpenSection(3)}

          >

            Continue to Process

            <ArrowRight size={16} />

          </button>

        </div>

      </WorkflowSection>

      <WorkflowSection

        number={3}

        complete={workflowCompletion[3]}

        title="Process recordings"

        subtitle="Scrub identifying header information from the selected EDF recordings."

        open={openSection === 3}

        onOpen={() => setOpenSection(3)}

      >

        <div className={styles.processGridSingle}>

          <ProcessCard

            number="3A"

            title="Scrub Included EDFs"

            text="Create de-identified EDF copies from the recordings currently included."

            state={processStages.scrub === "running" ? "running" : workflowCompletion[3] ? "complete" : processStages.scrub}

            disabled={processRunning || includedCount === 0 || !state.derivatives_dir || !state.bids_output_dir}

            onClick={() => run("scrub")}

          />

        </div>

        <label className={styles.overwrite}>

          <input

            type="checkbox"

            checked={overwrite}

            onChange={event => setOverwrite(event.target.checked)}

          />

          Overwrite existing staged, scrubbed, or exact BIDS outputs

        </label>

        <div className={styles.statusPanel}>

          <div className={styles.statusHeader}>

            <div>

              <strong>Pipeline status</strong>

              <span>{state.status}</span>

            </div>

          </div>

          <pre className={styles.log}>

            {(state.logs ?? []).join("\n") || "Dashboard ready."}

          </pre>

        </div>

        <div className={styles.sectionFooter}>

          <div />

          <button

            className={styles.primary}

            disabled={processRunning || !workflowCompletion[3]}

            onClick={() => setOpenSection(4)}

          >

            Continue to Review

            <ArrowRight size={16} />

          </button>

        </div>

      </WorkflowSection>

      <WorkflowSection

        number={4}

        complete={workflowCompletion[4]}

        title="Review de-identification"

        subtitle="Compare the raw and scrubbed EDF headers and annotations before continuing."

        open={openSection === 4}

        onOpen={() => setOpenSection(4)}

      >

        <WorkflowStatusCard

          title="Review processed recordings"

          description="Inspect the raw and scrubbed EDF headers and annotations, then save any supported edits before continuing."

          state={workflowCompletion[4] ? "complete" : processStages.review}

        />

        <div className={styles.sectionFooter}>

          <button className={styles.secondary} onClick={() => setOpenSection(3)}>

            Back to Processing

          </button>

          <button className={styles.primary} onClick={() => run("review")}>

            Open EDF Review

            <ArrowRight size={16} />

          </button>

        </div>

      </WorkflowSection>

      <WorkflowSection

        number={5}

        complete={workflowCompletion[5]}

        title="Metadata & BIDS"

        subtitle="Add electrophysiology metadata and create the final BIDS-compatible output."

        open={openSection === 5}

        onOpen={() => setOpenSection(5)}

      >

        <WorkflowStatusCard

          title="Complete metadata and export"

          description="Continue with the reviewed recordings, complete the dictionary-driven Electrophysiology metadata, and create the final BIDS-compatible output."

          state={workflowCompletion[5] ? "complete" : processStages.metadata_bids}

        />

        {(processStages.metadata_bids === "running" || processStages.metadata_bids === "failed" || workflowCompletion[5]) && (

          <div className={styles.statusPanel}>

            <div className={styles.statusHeader}>

              <div>

                <strong>Pipeline status</strong>

                <span>{state.status}</span>

              </div>

            </div>

            <pre className={styles.log}>

              {(state.logs ?? []).join("\n") || "Dashboard ready."}

            </pre>

          </div>

        )}

        <div className={styles.sectionFooter}>

          <button className={styles.secondary} onClick={() => setOpenSection(4)}>

            Back to Review

          </button>

          <button

            className={styles.primary}

            disabled={processRunning}

            onClick={() => run("bids")}

          >

            {workflowCompletion[5] ? "Review Metadata & BIDS" : "Open Metadata & BIDS"}

            <ArrowRight size={16} />

          </button>

        </div>

      </WorkflowSection>

      <div className={styles.helpBar}>

        <CircleHelp size={20} />

        <strong>Need help?</strong>

        <span>

          Review the electrophysiology workflow guidance or contact the CoCANoT support team.

        </span>

      </div>

    </div>

  );

}

function WorkflowStepper({ current, completed = {} }) {

  const steps = [

    [1, "Select Data"],

    [2, "Set Output Folders"],

    [3, "Process"],

    [4, "Review"],

    [5, "Metadata & BIDS"],

  ];

  return (

    <div className={styles.stepper}>

      {steps.map(([number, label], index) => {

        const isComplete = Boolean(completed[number]);

        const isActive = number === current;

        return (

          <div className={styles.stepItem} key={label}>

            <div

              className={`${styles.stepCircle} ${

                isComplete

                  ? styles.stepDone

                  : isActive

                    ? styles.stepActive

                    : ""

              }`}

            >

              {isComplete ? <Check size={15} strokeWidth={2.5} /> : number}

            </div>

            <span className={isComplete ? styles.stepLabelDone : ""}>{label}</span>

            {index < steps.length - 1 && (

              <div className={`${styles.stepLine} ${isComplete ? styles.stepLineDone : ""}`} />

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

  onOpen,

  children,

}) {

  return (

    <section

      className={`${styles.workflowSection} ${open ? styles.workflowOpen : ""} ${

        complete ? styles.workflowComplete : ""

      }`}

    >

      <button className={styles.workflowHeader} onClick={onOpen}>

        <span className={`${styles.sectionNumber} ${complete ? styles.sectionNumberDone : ""}`}>

          {complete ? <Check size={17} strokeWidth={2.5} /> : number}

        </span>

        <span className={styles.workflowTitle}>

          <strong>{title}</strong>

          <small>{subtitle}</small>

        </span>

        {!open && (

          <span className={complete ? styles.completeLabel : styles.goButton}>

            {complete ? "Complete" : "Go to Section"}

          </span>

        )}

        <ChevronDown

          size={18}

          className={open ? styles.chevronOpen : ""}

        />

      </button>

      {open && <div className={styles.workflowBody}>{children}</div>}

    </section>

  );

}

function UploadCard({

  title,

  text,

  onChooseFiles,

  onChooseFolder,

}) {

  return (

    <div className={styles.uploadCard}>

      <div className={styles.uploadIcon}>

        <Upload size={26} strokeWidth={1.8} />

      </div>

      <div className={styles.uploadCopy}>

        <strong>{title}</strong>

        <p>{text}</p>

        <div className={styles.uploadActions}>

          <button className={styles.uploadPrimary} onClick={onChooseFiles}>

            Choose Files…

          </button>

          <button className={styles.uploadLink} onClick={onChooseFolder}>

            Choose Folder…

          </button>

        </div>

      </div>

    </div>

  );

}

function WorkflowStatusCard({ title, description, state = "not_started" }) {

  const label = {

    not_started: "Not started",

    running: "In progress",

    complete: "Completed",

    failed: "Needs attention",

  }[state] ?? "Not started";

  return (

    <div className={`${styles.workflowStatusCard} ${styles[`workflowStatus_${state}`] ?? ""}`}>

      <div className={`${styles.workflowStatusIcon} ${styles[`workflowStatusIcon_${state}`] ?? ""}`}>

        {state === "complete" ? (

          <CheckCircle2 size={20} strokeWidth={2} />

        ) : state === "running" ? (

          <RefreshCw
            className={styles.workflowStatusSpinner}
            size={20}
            strokeWidth={2}
          />

        ) : (

          <span className={styles.workflowStatusDot} />

        )}

      </div>

      <div className={styles.workflowStatusCopy}>

        <div className={styles.workflowStatusTitleRow}>

          <strong>{title}</strong>

          <span className={`${styles.workflowStatusBadge} ${styles[`workflowStatusBadge_${state}`] ?? ""}`}>

            {state === "complete" && <CheckCircle2 size={14} />}

            {state === "running" && (
              <RefreshCw
                className={styles.workflowStatusSpinner}
                size={13}
              />
            )}

            {label}

          </span>

        </div>

        <p>{description}</p>

      </div>

    </div>

  );

}

function ProcessCard({

  number,

  title,

  text,

  state = "not_started",

  disabled = false,

  onClick,

}) {

  const label =

    state === "running"

      ? "Running…"

      : state === "complete"

        ? "Reprocess"

        : "Run";

  return (

    <button

      type="button"

      className={`${styles.processCard} ${

        state === "complete" ? styles.processCardComplete : ""

      } ${state === "running" ? styles.processCardRunning : ""}`}

      disabled={disabled}

      onClick={onClick}

    >

      <span>{number}</span>

      <strong>{title}</strong>

      <p>{text}</p>

      <span className={styles.processCardAction}>{label}</span>

      <Play size={17} />

    </button>

  );

}

function PageHeading({ eyebrow, title, text }) {

  return (

    <header className={styles.heading}>

      {eyebrow && <span>{eyebrow}</span>}

      <h1>{title}</h1>

      <p>{text}</p>

    </header>

  );

}

function FolderField({ label, value, onChange, onBrowse }) {

  return (

    <label className={styles.folderField}>

      <span>{label}</span>

      <div>

        <input

          value={value ?? ""}

          onChange={event => onChange(event.target.value)}

        />

        <button onClick={onBrowse}>

          <FolderOpen size={16} />

          Browse…

        </button>

      </div>

    </label>

  );

}

function EDFReview({

  pairs,

  review,

  onSelect,

  onChange,

  onSave,

  onSetStatus,

  onBack,

  onContinue,

  completedSteps,

  stageState,

}) {

  const [rejectOpen, setRejectOpen] = useState(false);

  const acceptedCount = pairs.filter(

    pair => pair.status === "Accepted"

  ).length;

  const rejectedCount = pairs.filter(

    pair => pair.status === "Rejected - Not Included"

  ).length;

  const pendingCount = pairs.filter(

    pair => !["Accepted", "Rejected - Not Included"].includes(pair.status)

  ).length;

  const reviewComplete = pairs.length > 0 && pendingCount === 0;

  const canContinue = reviewComplete && acceptedCount > 0;

  function setHeader(field, value) {

    onChange({

      ...review,

      scrubbed: {

        ...review.scrubbed,

        header: {

          ...review.scrubbed.header,

          [field]: value,

        },

      },

    });

  }

  function updateAnnotation(index, key, value) {

    const next = [...review.scrubbed.annotations];

    next[index] = { ...next[index], [key]: value };

    onChange({

      ...review,

      scrubbed: {

        ...review.scrubbed,

        annotations: next,

      },

    });

  }

  function addAnnotation() {

    onChange({

      ...review,

      scrubbed: {

        ...review.scrubbed,

        annotations: [

          ...(review.scrubbed.annotations ?? []),

          { onset: 0, duration: 0, description: "" },

        ],

      },

    });

  }

  function removeAnnotation(index) {

    onChange({

      ...review,

      scrubbed: {

        ...review.scrubbed,

        annotations: review.scrubbed.annotations.filter(

          (_, itemIndex) => itemIndex !== index

        ),

      },

    });

  }

  async function acceptCurrent() {

    await onSetStatus("Accepted");

  }

  async function rejectCurrent() {

    await onSetStatus("Rejected - Not Included");

    setRejectOpen(false);

  }

  return (

    <div>

      <button className={styles.backLink} onClick={onBack}>

        <ArrowLeft size={16} />

        Back to Processing

      </button>

      <PageHeading

        title="Electrophysiology De-identification Review"

        text="Compare each raw and scrubbed EDF, confirm the de-identification result, and decide which recordings can continue."

      />

      <WorkflowStepper current={4} completed={completedSteps} />

      <WorkflowStatusCard

        title="Review processed recordings"

        description={`${acceptedCount} accepted, ${rejectedCount} rejected, ${pendingCount} pending. Review every recording before continuing.`}

        state={reviewComplete ? "complete" : stageState}

      />

      <div className={styles.reviewLayout}>

        <aside className={styles.pairList}>

          <h3>EDF files</h3>

          <div className={styles.pairListStack}>

            {pairs.map(pair => (

              <button

                key={pair.id}

                onClick={() => onSelect(pair.id)}

                className={review?.id === pair.id ? styles.activePair : ""}

              >

                <span className={styles.pairStatus}>

                  [{pair.status ?? "Pending"}]

                </span>

                <span>{pair.label}</span>

              </button>

            ))}

          </div>

        </aside>

        <div className={styles.reviewMain}>

          {!review ? (

            <div className={styles.empty}>No matching EDF pairs.</div>

          ) : (

            <>

              <section className={styles.reviewOverview}>

                <div>

                  <span>Current recording</span>

                  <strong>{review.label}</strong>

                </div>

                <div>

                  <span>Review status</span>

                  <strong>{review.status ?? "Pending"}</strong>

                </div>

                <div>

                  <span>Raw annotations</span>

                  <strong>{review.raw.annotations?.length ?? 0}</strong>

                </div>

                <div>

                  <span>Scrubbed annotations</span>

                  <strong>{review.scrubbed.annotations?.length ?? 0}</strong>

                </div>

              </section>

              <section className={styles.card}>

                <div className={styles.reviewCardHeading}>

                  <div>

                    <h2>Raw EDF versus scrubbed EDF</h2>

                    <p>Raw values are read-only. Supported scrubbed values can be edited before the recording is accepted or rejected.</p>

                  </div>

                  <button className={styles.secondary} onClick={onSave}>

                    <Save size={16} />

                    Save Scrubbed EDF

                  </button>

                </div>

                <table className={styles.table}>

                  <thead>

                    <tr>

                      <th>Field</th>

                      <th>Raw EDF</th>

                      <th>Scrubbed EDF</th>

                    </tr>

                  </thead>

                  <tbody>

                    {Array.from(

                      new Set([

                        ...Object.keys(review.raw.header ?? {}),

                        ...Object.keys(review.scrubbed.header ?? {}),

                      ])

                    )

                      .sort()

                      .map(field => {

                        const editable = review.editable_header_fields?.includes(field);

                        return (

                          <tr key={field}>

                            <td>{field}</td>

                            <td>{String(review.raw.header?.[field] ?? "")}</td>

                            <td>

                              {editable ? (

                                <input

                                  value={String(review.scrubbed.header?.[field] ?? "")}

                                  onChange={event => setHeader(field, event.target.value)}

                                />

                              ) : (

                                String(review.scrubbed.header?.[field] ?? "")

                              )}

                            </td>

                          </tr>

                        );

                      })}

                  </tbody>

                </table>

              </section>

              <section className={styles.card}>

                <h2>Annotations</h2>

                <div className={styles.annotationGrid}>

                  <div>

                    <h3>Raw EDF annotations</h3>

                    {(review.raw.annotations ?? []).length === 0 ? (

                      <div className={styles.annotationEmpty}>No annotations.</div>

                    ) : (

                      (review.raw.annotations ?? []).map((row, index) => (

                        <div className={styles.annotationRow} key={index}>

                          <span>{row.onset}</span>

                          <span>{row.duration}</span>

                          <span>{row.description}</span>

                        </div>

                      ))

                    )}

                  </div>

                  <div>

                    <div className={styles.annotationHeader}>

                      <h3>Scrubbed EDF annotations</h3>

                      <button onClick={addAnnotation}>Add</button>

                    </div>

                    {(review.scrubbed.annotations ?? []).length === 0 ? (

                      <div className={styles.annotationEmpty}>No annotations.</div>

                    ) : (

                      (review.scrubbed.annotations ?? []).map((row, index) => (

                        <div className={styles.annotationEdit} key={index}>

                          <input

                            type="number"

                            value={row.onset}

                            onChange={event => updateAnnotation(index, "onset", Number(event.target.value))}

                          />

                          <input

                            type="number"

                            value={row.duration}

                            onChange={event => updateAnnotation(index, "duration", Number(event.target.value))}

                          />

                          <input

                            value={row.description}

                            onChange={event => updateAnnotation(index, "description", event.target.value)}

                          />

                          <button onClick={() => removeAnnotation(index)}>Remove</button>

                        </div>

                      ))

                    )}

                  </div>

                </div>

              </section>

              <div className={styles.reviewDecisionFooter}>

                <div>

                  <strong>{review.label}</strong>

                  <span>Review status: {review.status ?? "Pending"}</span>

                </div>

                <div className={styles.reviewDecisionActions}>

                  <button className={styles.secondary} onClick={() => setRejectOpen(true)}>

                    Reject

                  </button>

                  <button className={styles.primary} onClick={acceptCurrent}>

                    Accept

                  </button>

                  <button className={styles.primary} disabled={!canContinue} onClick={onContinue}>

                    Continue to Step 5: Metadata & BIDS

                    <ArrowRight size={16} />

                  </button>

                </div>

              </div>

              {!reviewComplete && (

                <div className={styles.reviewHint}>

                  Review all recordings before continuing. Accepted recordings continue to Step 5; rejected recordings remain local and are excluded from export.

                </div>

              )}

              {reviewComplete && acceptedCount === 0 && (

                <div className={styles.reviewHint}>

                  All recordings have been reviewed, but none are accepted. Accept at least one recording to continue to Metadata & BIDS.

                </div>

              )}

            </>

          )}

        </div>

      </div>

      {rejectOpen && review && (

        <div className={styles.modalBackdrop}>

          <div className={styles.reviewModal}>

            <h3>Reject this recording?</h3>

            <p>This recording will remain in the local derivatives folder but will not be included in Metadata & BIDS or the final export.</p>

            <div className={styles.modalActions}>

              <button className={styles.secondary} onClick={() => setRejectOpen(false)}>

                Cancel

              </button>

              <button className={styles.rejectButton} onClick={rejectCurrent}>

                Reject & Exclude

              </button>

            </div>

          </div>

        </div>

      )}

    </div>

  );

}

function EphysBids({

  state,

  overwrite,

  completedSteps,

  stageState,

  onBack,

  onStarted,

  resumeState,

  autoValidate,

  onCreateClinicalAssessment,

}) {

  const [records, setRecords] = useState([]);

  const [rules, setRules] = useState([]);

  const [activeId, setActiveId] = useState("");

  const [selectedIds, setSelectedIds] = useState([]);

  const [draft, setDraft] = useState({});

  const [project, setProject] = useState("");

  const [projectDescription, setProjectDescription] = useState("");

  const [sessionId, setSessionId] = useState("");

  const [problems, setProblems] = useState([]);

  const [confirmOpen, setConfirmOpen] = useState(false);

  const [busy, setBusy] = useState(false);

  const resumeAppliedRef = useRef(false);

  const autoValidateStartedRef = useRef(false);

  useEffect(() => {

    setRules(state?.rules ?? []);

    if (resumeState && !resumeAppliedRef.current) {

      const resumedRecords = Array.isArray(resumeState.records)
        ? resumeState.records
        : [];

      resumeAppliedRef.current = true;
      setRecords(resumedRecords);
      setSelectedIds(resumeState.selectedIds ?? []);
      setActiveId(
        resumeState.activeId ?? resumedRecords[0]?.id ?? ""
      );
      setDraft({ ...(resumeState.draft ?? {}) });
      setProject(resumeState.project ?? "");
      setProjectDescription(
        resumeState.projectDescription ?? ""
      );
      setSessionId(resumeState.sessionId ?? "");
      return;
    }

    const nextRecords = state?.records ?? [];

    setRecords(nextRecords);

    if (nextRecords.length > 0) {
      selectRecord(nextRecords[0]);
    } else {
      setActiveId("");
      setSelectedIds([]);
      setDraft({});
      setProject("");
      setProjectDescription("");
      setSessionId("");
    }

  }, [state, resumeState]);

  useEffect(() => {

    if (
      !autoValidate ||
      autoValidateStartedRef.current ||
      records.length === 0
    ) {
      return;
    }

    autoValidateStartedRef.current = true;
    reviewMetadata();

  }, [autoValidate, records]);

  function selectRecord(record) {

    setActiveId(record.id);

    if (!selectedIds.includes(record.id)) {

      setSelectedIds([record.id]);

    }

    setDraft({ ...(record.cocanot_metadata ?? {}) });

    setProject(record.project ?? "");

    setProjectDescription(record.project_description ?? "");

    setSessionId(record.session_id ?? "");

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

  function preparedRecords() {

    return records.map(record =>

      selectedIds.includes(record.id)

        ? {

            ...record,

            project,

            project_description: projectDescription,

            session_id: sessionId,

            cocanot_metadata: structuredClone(draft),

          }

        : record

    );

  }

  function applySelected() {

    if (selectedIds.length === 0) {

      return;

    }

    setRecords(preparedRecords());

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

  function conditionMatches(rule) {

    if (!rule.required_if_field) {

      return true;

    }

    const current = draft[rule.required_if_field];

    const expected = rule.required_if_value;

    const operator = String(rule.required_if_operator ?? "").toLowerCase();

    const currentValues = Array.isArray(current)

      ? current.map(value => String(value).trim()).filter(Boolean)

      : [String(current ?? "").trim()].filter(Boolean);

    const expectedValues = Array.isArray(expected)

      ? expected.map(value => String(value).trim()).filter(Boolean)

      : [String(expected ?? "").trim()].filter(Boolean);

    const anyMatch = expectedValues.some(value => currentValues.includes(value));

    if (

      operator.includes("not") ||

      operator === "!=" ||

      operator === "not_equals"

    ) {

      return !anyMatch;

    }

    return anyMatch;

  }

  function buildResumeState(nextRecords = records) {

    return {
      records: nextRecords,
      selectedIds,
      activeId,
      draft: structuredClone(draft),
      project,
      projectDescription,
      sessionId,
    };

  }

  async function reviewMetadata() {

    const nextRecords = preparedRecords();

    setRecords(nextRecords);

    setBusy(true);

    try {

      const validation = await api()?.ephys_bids_validate?.({

        records: nextRecords,

        overwrite,

      });

      if (!validation?.ok) {

        const missingClinical =
          validation?.missing_clinical_assessments ?? [];

        setProblems(
          validation?.problems ?? ["Validation failed."]
        );

        if (
          missingClinical.length > 0 &&
          onCreateClinicalAssessment
        ) {
          onCreateClinicalAssessment(
            missingClinical[0].patient_id,
            buildResumeState(nextRecords)
          );
        }

        return;

      }

      setProblems([]);

      setRecords(validation.records ?? nextRecords);

      setConfirmOpen(true);

    } catch (error) {

      setProblems([String(error)]);

    } finally {

      setBusy(false);

    }

  }

  async function confirmAndConvert() {

    setBusy(true);

    try {

      const result = await api()?.ephys_bids_convert?.({

        records,

        overwrite,

      });

      if (!result?.ok) {

        setProblems(result?.problems ?? ["Conversion could not start."]);

        setConfirmOpen(false);

        return;

      }

      setProblems([]);

      setConfirmOpen(false);

      onStarted?.();

    } catch (error) {

      setProblems([String(error)]);

      setConfirmOpen(false);

    } finally {

      setBusy(false);

    }

  }

  const active = records.find(record => record.id === activeId);

  const derivedFields = new Set(state?.derived_fields ?? []);

  const visibleRules = rules.filter(rule =>

    !rule.system_generated &&

    !derivedFields.has(rule.field_name) &&

    conditionMatches(rule)

  );

  return (

    <div>

      <button className={styles.backLink} onClick={onBack}>

        <ArrowLeft size={16} />

        Back to Review

      </button>

      <PageHeading

        title="Electrophysiology Metadata & BIDS Review"

        text="Complete the dictionary-driven electrophysiology metadata, confirm the included recordings, and create the final BIDS-compatible output."

      />

      <WorkflowStepper current={5} completed={completedSteps} />

      <WorkflowStatusCard

        title="Metadata & BIDS"

        description="Complete the electrophysiology metadata, confirm the included recordings, and create the final BIDS-compatible output."

        state={stageState}

      />

      <section className={styles.card}>

        <div className={styles.bidsHeading}>

          <div>

            <span className={styles.eyebrow}>Step 5</span>

            <h2>Electrophysiology Metadata & BIDS Review</h2>

            <p className={styles.muted}>

              CoCANoT fields come from the active Electrophysiology metadata dictionary.

              Questions are shown in dictionary order. Project and Session ID are used for BIDS dataset organization.

            </p>

            {state?.local_database && (

              <p className={styles.databaseStatus}>

                Local metadata database:{" "}

                <strong>

                  {state.local_database.connected

                    ? `Connected — Site ${state.local_database.site_id}`

                    : "Not connected"}

                </strong>

              </p>

            )}

          </div>

        </div>

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

                <th>Recording ID</th>

                <th>Surgery ID</th>

                <th>Recording Modality</th>

              </tr>

            </thead>

            <tbody>

              {records.length === 0 ? (

                <tr>

                  <td colSpan="9" className={styles.empty}>

                    No accepted recordings were found.

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

                    <td>{record.cocanot_metadata?.["Recording ID"] ?? ""}</td>

                    <td>{record.cocanot_metadata?.["Surgery ID"] ?? ""}</td>

                    <td>{record.cocanot_metadata?.["Recording Modality"] ?? ""}</td>

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

                    ? "Step 5 was completed and the matching Electrophysiology record is still present in the local CoCANoT database."

                    : "The processed BIDS files are still present in the final output folder, but the matching Electrophysiology record is no longer present in the local CoCANoT database. Metadata stored with the existing output has been preloaded below so the record can be recreated without starting from scratch."}

                </p>

              </div>

              <div className={styles.existingExportDetails}>

                <span>

                  Existing output: {active.existing_export.edf_path ?? active.existing_export.path ?? ""}

                </span>

              </div>

            </section>

          )}

          <section className={styles.card}>

            <h2>CoCANoT Electrophysiology Metadata</h2>

            <p className={styles.helpText}>

              Requiredness, input type, allowed values, conditional fields, prompts, and help text come from the active machine-readable dictionary.

            </p>

            <div className={styles.metadataForm}>

              {visibleRules.map(rule => (

                <EphysMetadataField

                  key={rule.field_name}

                  rule={rule}

                  values={draft}

                  value={draft[rule.field_name]}

                  onChange={value =>

                    setDraft(current => ({

                      ...current,

                      [rule.field_name]: value,

                    }))

                  }

                />

              ))}

            </div>

          </section>

          <section className={styles.card}>

            <h2>Dataset Organization</h2>

            <div className={styles.datasetGrid}>

              <label>

                <span>Project *</span>

                <input

                  value={project}

                  onChange={event => setProject(event.target.value)}

                />

              </label>

              <label>

                <span>Session ID *</span>

                <input

                  value={sessionId}

                  onChange={event => setSessionId(event.target.value)}

                />

              </label>

              <label className={styles.full}>

                <span>Project Description</span>

                <input

                  value={projectDescription}

                  onChange={event => setProjectDescription(event.target.value)}

                />

              </label>

            </div>

          </section>

          <section className={styles.bidsActions}>

            <div>

              <button className={styles.secondary} onClick={() => includeSelected(true)}>

                Include Selected

              </button>

              <button className={styles.secondary} onClick={() => includeSelected(false)}>

                Exclude Selected

              </button>

              <button className={styles.secondary} onClick={applySelected}>

                Apply to Selected

              </button>

            </div>

            <button

              className={styles.primary}

              disabled={busy}

              onClick={reviewMetadata}

            >

              Review Metadata & Convert

            </button>

          </section>

        </>

      )}

      {problems.length > 0 && (

        <section className={styles.errorBox}>

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

            <h3>Confirm Electrophysiology Metadata</h3>

            <p>

              Confirm the included recordings below. Conversion will create the final electrophysiology BIDS output using the metadata shown here.

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

                      Recording ID: {record.cocanot_metadata?.["Recording ID"] ?? ""}

                    </span>

                  </div>

                ))}

            </div>

            <div className={styles.modalActions}>

              <button

                className={styles.secondary}

                onClick={() => setConfirmOpen(false)}

              >

                Back to Edit

              </button>

              <button

                className={styles.primary}

                disabled={busy}

                onClick={confirmAndConvert}

              >

                Confirm All & Convert

              </button>

            </div>

          </div>

        </div>

      )}

    </div>

  );

}

function EphysMetadataField({ rule, values, value, onChange }) {

  const label = `${rule.ui_prompt}${

    rule.required

      ? " *"

      : rule.required_if_field

        ? " * when applicable"

        : ""

  }`;

  if (rule.repeat_for_each_field) {

    const parentValue = values?.[rule.repeat_for_each_field];

    const selected = Array.isArray(parentValue)

      ? parentValue.map(String)

      : parentValue

        ? [String(parentValue)]

        : [];

    const excluded = new Set(rule.repeat_exclude_values ?? []);

    const applicable = selected.filter(item => !excluded.has(item));

    const current = value && typeof value === "object" && !Array.isArray(value)

      ? value

      : {};

    if (applicable.length === 0) {

      return null;

    }

    return (

      <fieldset className={styles.repeatField}>

        <legend>

          {label}

          {rule.help_text && <small title={rule.help_text}> ?</small>}

        </legend>

        <div className={styles.repeatRows}>

          {applicable.map(item => {

            const prompt = String(rule.repeat_prompt_template || `${rule.ui_prompt}: {value}`)

              .replaceAll("{value}", item)

              .replaceAll("{item}", item);

            return (

              <label key={item} className={styles.repeatRow}>

                <span>{prompt}</span>

                <input

                  value={current[item] ?? ""}

                  onChange={event =>

                    onChange({

                      ...current,

                      [item]: event.target.value,

                    })

                  }

                />

              </label>

            );

          })}

        </div>

      </fieldset>

    );

  }

  if (rule.input_type === "single_select") {

    return (

      <label className={styles.metadataField}>

        <span>

          {label}

          {rule.help_text && <small title={rule.help_text}> ?</small>}

        </span>

        <select value={value ?? ""} onChange={event => onChange(event.target.value)}>

          <option value="">Select…</option>

          {(rule.allowed_values ?? []).map(option => (

            <option key={option} value={option}>{option}</option>

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

    const exclusive = new Set(rule.exclusive_values ?? []);

    function setOption(option, checked) {

      let next;

      if (checked && exclusive.has(option)) {

        next = [option];

      } else if (checked) {

        next = [...selected.filter(item => !exclusive.has(item)), option];

      } else {

        next = selected.filter(item => item !== option);

      }

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

          <span className={styles.multiCount}>{selected.length} selected</span>

        </div>

        <div className={styles.multiToolbar}>

          <button

            type="button"

            className={styles.multiUtilityButton}

            onClick={() => onChange([...allowed.filter(option => !exclusive.has(option))])}

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

              className={selected.includes(option) ? styles.multiOptionSelected : ""}

            >

              <input

                type="checkbox"

                checked={selected.includes(option)}

                onChange={event => setOption(option, event.target.checked)}

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

      <input value={value ?? ""} onChange={event => onChange(event.target.value)} />

    </label>

  );

}
