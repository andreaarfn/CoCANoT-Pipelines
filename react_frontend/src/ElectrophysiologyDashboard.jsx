import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Database,
  FileAudio,
  FolderOpen,
  Info,
  Play,
  Save,
  Upload,
} from "lucide-react";
import DictionaryForm from "./DictionaryForm";
import styles from "./ElectrophysiologyDashboard.module.css";

const api = () => window.pywebview?.api ?? null;

export default function ElectrophysiologyDashboard({
  initialView = "home",
  onNavigate,
}) {
  const [view, setView] = useState(
    initialView === "processing" ? "processing" : "home"
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

  useEffect(() => {
    if (view === "processing") loadState();
    if (view === "review") loadReview();
    if (view === "bids") loadBids();
  }, [view]);

  async function loadState() {
    const next = await api()?.ephys_get_state?.();
    if (!next) return;
    setState(next);
    setRecords(next.records ?? []);
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

  async function browseOutput(key) {
    const selected = await api()?.choose_folder?.();
    if (!selected) return;

    setState(current => ({
      ...current,
      [key]: selected,
    }));
  }

  async function saveSettings() {
    const next = await api()?.ephys_save_settings?.({
      input_dirs: state.input_dirs,
      derivatives_dir: state.derivatives_dir,
      bids_output_dir: state.bids_output_dir,
    });

    if (next) setState(next);
  }

  async function run(operation) {
    const result = await api()?.ephys_run_operation?.({
      operation,
      records,
      derivatives_dir: state.derivatives_dir,
      bids_output_dir: state.bids_output_dir,
      overwrite,
    });

    if (operation === "review" && result?.ok) {
      setView("review");
      return;
    }

    if (operation === "bids" && result?.ok) {
      setView("bids");
      return;
    }

    await loadState();
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

  async function loadBids() {
    setBidsState(await api()?.ephys_bids_get_state?.());
  }

  const includedCount = useMemo(
    () => records.filter(record => record.include).length,
    [records]
  );

  if (view === "home") {
    return (
      <div>
        <PageHeading
          eyebrow="ELECTROPHYSIOLOGY PIPELINE"
          title="Prepare electrophysiology data for research use"
          text="Select EDF recordings, scrub identifying header information, review the results, and convert accepted recordings to BIDS."
        />

        <div className={styles.homeCards}>
          <button onClick={() => setView("processing")}>
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
        onBack={() => setView("processing")}
        onContinue={() => setView("bids")}
      />
    );
  }

  if (view === "bids") {
    return (
      <EphysBids
        state={bidsState}
        overwrite={overwrite}
        onBack={() => setView("processing")}
      />
    );
  }

  return (
    <div>
      <button
        className={styles.backLink}
        onClick={() => setView("home")}
      >
        <ArrowLeft size={16} />
        Back to Electrophysiology
      </button>

      <PageHeading
        title="Process Recordings"
        text="Add EDF files or folders, choose the recordings to process, scrub headers and metadata, review outputs, and export BIDS-formatted data."
      />

      <WorkflowStepper current={openSection} />

      <WorkflowSection
        number={1}
        title="Select recordings"
        subtitle="Add EDF files or folders below. Then choose which recordings to process in this session."
        open={openSection === 1}
        onOpen={() => setOpenSection(1)}
      >
        <div className={styles.uploadGrid}>
          <UploadCard
            icon={FileAudio}
            title="Add EDF files"
            text="Select one or more EDF files to add to your session."
            button="Choose Files…"
            onClick={() => choose("files")}
          />

          <UploadCard
            icon={FolderOpen}
            title="Add EDF folders"
            text="Select a folder containing EDF files. Subfolders are searched recursively."
            button="Choose Folder…"
            onClick={() => choose("folders")}
          />
        </div>

        <div className={styles.selectedBar}>
          <Database size={24} />
          <div>
            <strong>Selected data</strong>
            <span>
              {(state.input_dirs ?? []).length} source folder
              {(state.input_dirs ?? []).length === 1 ? "" : "s"}
              <em>|</em>
              {includedCount} EDF file
              {includedCount === 1 ? "" : "s"} selected
            </span>
          </div>

          <details className={styles.selectedDetails}>
            <summary>View Selected Files</summary>
            <div className={styles.selectedPopover}>
              <section>
                <div className={styles.popoverHeader}>
                  <strong>Source folders / files</strong>
                  <button
                    disabled={!selectedSources.length}
                    onClick={removeSources}
                  >
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
                            toggleRecord(
                              record.id,
                              event.target.checked
                            )
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
        title="Set output folders"
        subtitle="Choose where to save processed files. A derivatives folder and a BIDS output folder are required."
        open={openSection === 2}
        onOpen={() => setOpenSection(2)}
      >
        <div className={styles.folderStack}>
          <FolderField
            label="Derivatives output folder"
            value={state.derivatives_dir}
            onChange={value =>
              setState(current => ({
                ...current,
                derivatives_dir: value,
              }))
            }
            onBrowse={() => browseOutput("derivatives_dir")}
          />

          <FolderField
            label="BIDS output folder"
            value={state.bids_output_dir}
            onChange={value =>
              setState(current => ({
                ...current,
                bids_output_dir: value,
              }))
            }
            onBrowse={() => browseOutput("bids_output_dir")}
          />
        </div>

        <div className={styles.infoStrip}>
          <Info size={16} />
          Scrubbed EDFs, review files, logs, and final BIDS output remain in the configured local folders.
        </div>

        <div className={styles.sectionFooter}>
          <button className={styles.secondary} onClick={saveSettings}>
            <Save size={15} />
            Save Folder Settings
          </button>

          <button
            className={styles.primary}
            disabled={
              !state.derivatives_dir ||
              !state.bids_output_dir
            }
            onClick={() => setOpenSection(3)}
          >
            Continue to Process & Review
            <ArrowRight size={16} />
          </button>
        </div>
      </WorkflowSection>

      <WorkflowSection
        number={3}
        title="Process & review"
        subtitle="Run the de-identification pipeline, scrub headers and metadata, and review the outputs."
        open={openSection === 3}
        onOpen={() => setOpenSection(3)}
      >
        <div className={styles.processGrid}>
          <ProcessCard
            number="3A"
            title="Scrub Included EDFs"
            text="Create scrubbed EDF copies from the recordings currently included."
            onClick={() => run("scrub")}
          />
          <ProcessCard
            number="3B"
            title="Review Scrubbed EDFs"
            text="Compare complete raw and scrubbed EDF headers and annotations."
            onClick={() => run("review")}
          />
        </div>

        <label className={styles.overwrite}>
          <input
            type="checkbox"
            checked={overwrite}
            onChange={event =>
              setOverwrite(event.target.checked)
            }
          />
          Overwrite existing staged, scrubbed, or exact BIDS outputs
        </label>

        <div className={styles.statusPanel}>
          <div>
            <strong>Pipeline status</strong>
            <span>{state.status}</span>
          </div>
          <pre className={styles.log}>
            {(state.logs ?? []).join("\n") || "Dashboard ready."}
          </pre>
        </div>

        <div className={styles.sectionFooter}>
          <div />
          <button
            className={styles.primary}
            onClick={() => setOpenSection(4)}
          >
            Continue to Finalize & Export
            <ArrowRight size={16} />
          </button>
        </div>
      </WorkflowSection>

      <WorkflowSection
        number={4}
        title="Finalize & export"
        subtitle="Export BIDS-formatted output and complete the process."
        open={openSection === 4}
        onOpen={() => setOpenSection(4)}
      >
        <div className={styles.finalizeCard}>
          <CheckCircle2 size={30} />
          <div>
            <strong>Metadata & BIDS</strong>
            <p>
              Complete dictionary-driven Electrophysiology metadata,
              validate against the local Clinical Assessment database,
              and launch the BIDS conversion.
            </p>
          </div>
        </div>

        <div className={styles.sectionFooter}>
          <button
            className={styles.secondary}
            onClick={() => setOpenSection(3)}
          >
            Back to Process & Review
          </button>

          <button
            className={styles.primary}
            onClick={() => run("bids")}
          >
            Open Metadata & BIDS
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

function WorkflowStepper({ current }) {
  const steps = [
    [1, "Select Recordings"],
    [2, "Set Output Folders"],
    [3, "Process & Review"],
    [4, "Finalize & Export"],
  ];

  return (
    <div className={styles.stepper}>
      {steps.map(([number, label], index) => (
        <div className={styles.stepItem} key={label}>
          <div
            className={`${styles.stepCircle} ${
              number === current
                ? styles.stepActive
                : number < current
                  ? styles.stepDone
                  : ""
            }`}
          >
            {number}
          </div>
          <span>{label}</span>
          {index < steps.length - 1 && (
            <div className={styles.stepLine} />
          )}
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
  onOpen,
  children,
}) {
  return (
    <section
      className={`${styles.workflowSection} ${
        open ? styles.workflowOpen : ""
      }`}
    >
      <button className={styles.workflowHeader} onClick={onOpen}>
        <span className={styles.sectionNumber}>{number}</span>
        <span className={styles.workflowTitle}>
          <strong>{title}</strong>
          <small>{subtitle}</small>
        </span>

        {!open && <span className={styles.goButton}>Go to Section</span>}
        <ChevronDown
          size={18}
          className={open ? styles.chevronOpen : ""}
        />
      </button>

      {open && (
        <div className={styles.workflowBody}>
          {children}
        </div>
      )}
    </section>
  );
}

function UploadCard({
  icon: Icon,
  title,
  text,
  button,
  onClick,
}) {
  return (
    <div className={styles.uploadCard}>
      <div className={styles.uploadIcon}>
        <Icon size={29} />
      </div>
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
        <button onClick={onClick}>
          {button}
        </button>
      </div>
    </div>
  );
}

function ProcessCard({ number, title, text, onClick }) {
  return (
    <button className={styles.processCard} onClick={onClick}>
      <span>{number}</span>
      <strong>{title}</strong>
      <p>{text}</p>
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
  onBack,
  onContinue,
}) {
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

  return (
    <div>
      <button className={styles.backLink} onClick={onBack}>
        <ArrowLeft size={16} />
        Back to Electrophysiology
      </button>

      <PageHeading
        eyebrow="EDF REVIEW"
        title="EDF Header and Annotation Review"
        text="Raw EDF values are read-only. Edit supported scrubbed header fields or annotations, then save the scrubbed EDF."
      />

      <div className={styles.reviewLayout}>
        <aside className={styles.pairList}>
          <h3>EDF files</h3>
          {pairs.map(pair => (
            <button
              key={pair.id}
              onClick={() => onSelect(pair.id)}
              className={
                review?.id === pair.id
                  ? styles.activePair
                  : ""
              }
            >
              {pair.label}
            </button>
          ))}
        </aside>

        <div className={styles.reviewMain}>
          {!review ? (
            <div className={styles.empty}>
              No matching EDF pairs.
            </div>
          ) : (
            <>
              <section className={styles.card}>
                <h2>Complete EDF header</h2>
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
                        const editable =
                          review.editable_header_fields?.includes(field);

                        return (
                          <tr key={field}>
                            <td>{field}</td>
                            <td>
                              {String(
                                review.raw.header?.[field] ?? ""
                              )}
                            </td>
                            <td>
                              {editable ? (
                                <input
                                  value={String(
                                    review.scrubbed.header?.[field] ?? ""
                                  )}
                                  onChange={event =>
                                    setHeader(
                                      field,
                                      event.target.value
                                    )
                                  }
                                />
                              ) : (
                                String(
                                  review.scrubbed.header?.[field] ?? ""
                                )
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
                    {(review.raw.annotations ?? []).map(
                      (row, index) => (
                        <div
                          className={styles.annotationRow}
                          key={index}
                        >
                          <span>{row.onset}</span>
                          <span>{row.duration}</span>
                          <span>{row.description}</span>
                        </div>
                      )
                    )}
                  </div>

                  <div>
                    <div className={styles.annotationHeader}>
                      <h3>Scrubbed EDF annotations</h3>
                      <button onClick={addAnnotation}>
                        Add
                      </button>
                    </div>

                    {(review.scrubbed.annotations ?? []).map(
                      (row, index) => (
                        <div
                          className={styles.annotationEdit}
                          key={index}
                        >
                          <input
                            type="number"
                            value={row.onset}
                            onChange={event =>
                              updateAnnotation(
                                index,
                                "onset",
                                Number(event.target.value)
                              )
                            }
                          />
                          <input
                            type="number"
                            value={row.duration}
                            onChange={event =>
                              updateAnnotation(
                                index,
                                "duration",
                                Number(event.target.value)
                              )
                            }
                          />
                          <input
                            value={row.description}
                            onChange={event =>
                              updateAnnotation(
                                index,
                                "description",
                                event.target.value
                              )
                            }
                          />
                          <button
                            onClick={() =>
                              removeAnnotation(index)
                            }
                          >
                            Remove
                          </button>
                        </div>
                      )
                    )}
                  </div>
                </div>
              </section>

              <div className={styles.reviewActions}>
                <button onClick={onSave}>
                  <Save size={16} />
                  Save Scrubbed EDF
                </button>

                <button onClick={onContinue}>
                  Continue to Metadata & BIDS
                  <ArrowRight size={16} />
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function EphysBids({ state, overwrite, onBack }) {
  const [records, setRecords] = useState([]);
  const [rules, setRules] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [selectedIds, setSelectedIds] = useState([]);
  const [draft, setDraft] = useState({});
  const [project, setProject] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [problems, setProblems] = useState([]);

  useEffect(() => {
    setRecords(state?.records ?? []);
    setRules(state?.rules ?? []);

    if (state?.records?.length) {
      selectRecord(state.records[0]);
    }
  }, [state]);

  function selectRecord(record) {
    setActiveId(record.id);
    setSelectedIds([record.id]);
    setDraft({ ...(record.cocanot_metadata ?? {}) });
    setProject(record.project ?? "");
    setProjectDescription(record.project_description ?? "");
    setSessionId(record.session_id ?? "");
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
    setRecords(preparedRecords());
  }

  async function validateAndConvert() {
    const nextRecords = preparedRecords();
    setRecords(nextRecords);

    const validation = await api()?.ephys_bids_validate?.({
      records: nextRecords,
      overwrite,
    });

    if (!validation?.ok) {
      setProblems(
        validation?.problems ?? ["Validation failed."]
      );
      return;
    }

    if (
      !window.confirm(
        `${validation.records.length} recording(s) passed validation. Continue with BIDS conversion?`
      )
    ) {
      return;
    }

    const result = await api()?.ephys_bids_convert?.({
      records: validation.records,
      overwrite,
    });

    if (!result?.ok) {
      setProblems(
        result?.problems ?? [
          "Conversion could not start.",
        ]
      );
      return;
    }

    setProblems([]);
    window.alert(
      `BIDS conversion started for ${result.record_count} recording(s).`
    );
  }

  const active = records.find(
    record => record.id === activeId
  );

  return (
    <div>
      <button className={styles.backLink} onClick={onBack}>
        <ArrowLeft size={16} />
        Back to Electrophysiology
      </button>

      <PageHeading
        eyebrow="FINALIZE & EXPORT"
        title="Electrophysiology Metadata & BIDS Review"
        text="CoCANoT fields come from the active machine-readable Electrophysiology dictionary. Project and Session ID control dataset organization."
      />

      <section className={styles.card}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Select</th>
              <th>Include</th>
              <th>File</th>
              <th>Project</th>
              <th>Patient</th>
              <th>Recording</th>
              <th>Surgery</th>
              <th>Modality</th>
            </tr>
          </thead>
          <tbody>
            {records.map(record => (
              <tr
                key={record.id}
                className={
                  activeId === record.id
                    ? styles.activeRow
                    : ""
                }
                onClick={() => selectRecord(record)}
              >
                <td
                  onClick={event =>
                    event.stopPropagation()
                  }
                >
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(record.id)}
                    onChange={() =>
                      setSelectedIds(current =>
                        current.includes(record.id)
                          ? current.filter(
                              id => id !== record.id
                            )
                          : [...current, record.id]
                      )
                    }
                  />
                </td>
                <td
                  onClick={event =>
                    event.stopPropagation()
                  }
                >
                  <input
                    type="checkbox"
                    checked={record.include}
                    onChange={event =>
                      setRecords(current =>
                        current.map(item =>
                          item.id === record.id
                            ? {
                                ...item,
                                include:
                                  event.target.checked,
                              }
                            : item
                        )
                      )
                    }
                  />
                </td>
                <td>{record.source_label}</td>
                <td>{record.project}</td>
                <td>
                  {
                    record.cocanot_metadata?.[
                      "CoCANoT Patient ID"
                    ]
                  }
                </td>
                <td>
                  {
                    record.cocanot_metadata?.[
                      "Recording ID"
                    ]
                  }
                </td>
                <td>
                  {
                    record.cocanot_metadata?.[
                      "Surgery ID"
                    ]
                  }
                </td>
                <td>
                  {
                    record.cocanot_metadata?.[
                      "Recording Modality"
                    ]
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {active && (
        <>
          <section className={styles.card}>
            <h2>CoCANoT Electrophysiology Metadata</h2>
            <DictionaryForm
              rules={rules}
              values={draft}
              derivedFields={
                state?.derived_fields ?? []
              }
              onChange={(field, value) =>
                setDraft(current => ({
                  ...current,
                  [field]: value,
                }))
              }
            />
          </section>

          <section className={styles.card}>
            <h2>Dataset Organization</h2>

            <div className={styles.orgGrid}>
              <label>
                <span>Project *</span>
                <input
                  value={project}
                  onChange={event =>
                    setProject(event.target.value)
                  }
                />
              </label>

              <label>
                <span>Session ID *</span>
                <input
                  value={sessionId}
                  onChange={event =>
                    setSessionId(event.target.value)
                  }
                />
              </label>

              <label className={styles.full}>
                <span>Project Description</span>
                <input
                  value={projectDescription}
                  onChange={event =>
                    setProjectDescription(
                      event.target.value
                    )
                  }
                />
              </label>
            </div>
          </section>

          <div className={styles.reviewActions}>
            <button onClick={applySelected}>
              Apply to Selected
            </button>
            <button onClick={validateAndConvert}>
              Review Metadata & Convert
            </button>
          </div>
        </>
      )}

      {problems.length > 0 && (
        <section className={styles.errorBox}>
          <strong>Metadata needs attention</strong>
          <ul>
            {problems.map((problem, index) => (
              <li key={index}>{problem}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
