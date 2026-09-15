import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Brain,
  FileText,
  Image as ImageIcon,
  Pencil,
  Plus,
  RefreshCw,
  Scissors,
  Search,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import DictionaryForm from "./DictionaryForm";
import PatientDataReview from "./PatientDataReview";
import BatchImportWorkflow from "./BatchImportWorkflow";
import styles from "./MetadataDashboard.module.css";

const api = () => window.pywebview?.api ?? null;

const SECTION_CONFIG = {
  Clinical: {
    title: "Clinical Metadata",
    icon: FileText,
    addLabel: "Add Clinical Assessment",
    uploadLabel: "Upload Clinical Assessments",
  },
  Surgical: {
    title: "Surgical Metadata",
    icon: Scissors,
    addLabel: "Add Surgical Record",
    uploadLabel: "Upload Surgical CSV/XLSX",
  },
  Imaging: {
    title: "Imaging Data",
    icon: ImageIcon,
    addLabel: "Add Imaging Data",
  },
  Electrophysiology: {
    title: "Electrophysiology Data",
    icon: Activity,
    addLabel: "Add Electrophysiology Recording",
  },
};

export default function MetadataDashboard({
  initialView = "home",
  onNavigate,
}) {
  const [view, setView] = useState(
    initialView === "patient_explorer"
      ? "patients"
      : initialView === "bulk"
        ? "bulk"
        : "home"
  );
  const [patients, setPatients] = useState([]);
  const [patientId, setPatientId] = useState("");
  const [loadedPatientId, setLoadedPatientId] = useState("");
  const [summary, setSummary] = useState(null);
  const [editor, setEditor] = useState(null);
  const [rules, setRules] = useState([]);
  const [draft, setDraft] = useState({});
  const [message, setMessage] = useState("");
  const [dataReview, setDataReview] = useState(null);
  const [batchImport, setBatchImport] = useState(null);
  const [selected, setSelected] = useState({
    Clinical: [],
    Surgical: [],
    Imaging: [],
    Electrophysiology: [],
  });

  useEffect(() => {
    if (view === "patients") {
      loadPatients();
    }
  }, [view]);

  async function currentSiteId() {
    return (await api()?.get_site_id?.()) ?? "";
  }

  async function loadPatients(preferred = "") {
    const siteId = await currentSiteId();
    const rows = await api()?.metadata_get_patients?.(siteId);
    const ids = (rows ?? []).map(row => row.patient_id);
    setPatients(ids);

    const next =
      preferred ||
      (ids.includes(patientId)
        ? patientId
        : ids[0] ?? "");

    if (!next) {
      setPatientId("");
      setLoadedPatientId("");
      setSummary(null);
      return;
    }

    setPatientId(next);
    await loadPatient(next);
  }

  async function loadPatient(id = patientId) {
    const clean = String(id ?? "").trim();
    if (!clean) return;

    const siteId = await currentSiteId();
    const result = await api()?.metadata_get_patient?.(
      siteId,
      clean
    );

    setPatientId(clean);
    setLoadedPatientId(clean);
    setSummary(result);
    clearSelections();
  }

  function clearSelections() {
    setSelected({
      Clinical: [],
      Surgical: [],
      Imaging: [],
      Electrophysiology: [],
    });
  }

  async function addPatient() {
    const id = window.prompt(
      "Enter the new CoCANoT Patient ID."
    );
    if (!id) return;

    const clean = id.trim();
    const siteId = await currentSiteId();

    await api()?.metadata_create_patient?.(
      siteId,
      clean
    );
    await loadPatients(clean);
  }

  async function openEditor(tableName, record = null) {
    const nextRules = await api()?.metadata_get_rules?.(
      tableName
    );

    const values = {
      ...(record?.metadata ?? {}),
    };

    if (
      loadedPatientId &&
      !values["CoCANoT Patient ID"]
    ) {
      values["CoCANoT Patient ID"] =
        loadedPatientId;
    }

    setRules(nextRules ?? []);
    setDraft(values);
    setEditor({
      tableName,
      record,
      context: record?.context ?? {},
    });
    setMessage("");
  }

  async function saveEditor() {
    try {
      if (editor.tableName === "Clinical") {
        await api()?.metadata_save_clinical?.(
          loadedPatientId,
          draft
        );
      } else {
        await api()?.metadata_save_record?.(
          editor.tableName,
          draft,
          editor.context ?? {}
        );
      }

      setEditor(null);
      setMessage(
        `${editor.tableName} metadata saved.`
      );
      await loadPatient(loadedPatientId);
    } catch (error) {
      setMessage(String(error));
    }
  }

  async function importRecords(tableName) {
    try {
      const result =
        await api()?.metadata_import_records?.(
          tableName
        );

      if (!result) return;

      const details =
        result.failed > 0
          ? ` ${result.failed} row(s) failed.`
          : "";

      setMessage(
        `Imported ${result.imported ?? 0} ${tableName} record(s).${details}`
      );
      await loadPatients(loadedPatientId);
    } catch (error) {
      setMessage(String(error));
    }
  }

  function toggleSelected(tableName, recordId) {
    setSelected(current => {
      const values = current[tableName] ?? [];
      return {
        ...current,
        [tableName]: values.includes(recordId)
          ? values.filter(id => id !== recordId)
          : [...values, recordId],
      };
    });
  }

  function selectedRows(tableName) {
    const ids = selected[tableName] ?? [];
    return recordsFor(tableName).filter(
      row => ids.includes(row.record_id)
    );
  }

  function recordsFor(tableName) {
    if (!summary) return [];
    if (tableName === "Clinical") {
      return summary.clinical ?? [];
    }
    if (tableName === "Surgical") {
      return summary.surgical ?? [];
    }
    if (tableName === "Imaging") {
      return summary.imaging ?? [];
    }
    return summary.electrophysiology ?? [];
  }

  async function reviewSelected(tableName) {
    const rows = selectedRows(tableName);

    if (rows.length !== 1) {
      setMessage(
        `Select exactly one ${tableName} record to review or edit.`
      );
      return;
    }

    if (
      tableName === "Imaging" ||
      tableName === "Electrophysiology"
    ) {
      setDataReview({
        tableName,
        record: rows[0],
      });
      setMessage("");
      return;
    }

    await openEditor(tableName, rows[0]);
  }

  async function deleteSelected(tableName) {
    const ids = selected[tableName] ?? [];

    if (!ids.length) {
      setMessage(
        `Select one or more ${tableName} records first.`
      );
      return;
    }

    const label =
      ids.length === 1
        ? `${tableName} record ${ids[0]}`
        : `${ids.length} ${tableName} records`;

    if (
      !window.confirm(
        `Delete ${label} from the local CoCANoT database?\n\nProcessed imaging/electrophysiology files on disk will not be deleted.`
      )
    ) {
      return;
    }

    try {
      const result =
        await api()?.metadata_delete_records?.(
          tableName,
          loadedPatientId,
          ids
        );

      const deleted = result?.deleted ?? [];
      const blocked = result?.blocked ?? [];

      let nextMessage =
        deleted.length > 0
          ? `Deleted ${deleted.length} ${tableName} record(s).`
          : `No ${tableName} records were deleted.`;

      if (blocked.length) {
        nextMessage +=
          " " +
          blocked
            .map(
              item =>
                `${item.record_id}: ${item.reason}`
            )
            .join(" | ");
      }

      setMessage(nextMessage);
      await loadPatient(loadedPatientId);
    } catch (error) {
      setMessage(String(error));
    }
  }

  function addFor(tableName) {
    if (tableName === "Imaging") {
      onNavigate("imaging-processing");
      return;
    }

    if (tableName === "Electrophysiology") {
      onNavigate("ephys-processing");
      return;
    }

    openEditor(tableName);
  }

  if (batchImport) {
    return (
      <BatchImportWorkflow
        tableName={batchImport}
        onBack={() => setBatchImport(null)}
        onFinished={result => {
          setMessage(
            `Imported ${result.imported ?? 0} ${batchImport} record(s).`
          );
        }}
      />
    );
  }

  if (dataReview) {
    return (
      <PatientDataReview
        tableName={dataReview.tableName}
        record={dataReview.record}
        onBack={() => setDataReview(null)}
        onEdit={async () => {
          const current = dataReview;
          setDataReview(null);
          await openEditor(
            current.tableName,
            current.record
          );
        }}
      />
    );
  }

  if (view === "home") {
    return (
      <div>
        <PageHeading
          eyebrow="METADATA MANAGEMENT"
          title="Manage CoCANoT metadata"
          text="Review one patient at a time or import Clinical and Surgical metadata in batches using the active machine-readable dictionary."
        />

        <div className={styles.homeCards}>
          <button onClick={() => setView("patients")}>
            <Users size={29} />
            <strong>Manage one patient</strong>
            <span>
              Review Clinical, Surgical, Imaging,
              and Electrophysiology records.
            </span>
          </button>

          <button onClick={() => setView("bulk")}>
            <Upload size={29} />
            <strong>Bulk upload</strong>
            <span>
              Import Clinical or Surgical metadata,
              or open the Imaging and
              Electrophysiology workflows.
            </span>
          </button>
        </div>
      </div>
    );
  }

  if (view === "bulk") {
    return (
      <div>
        <PageHeading
          eyebrow="BULK UPLOAD"
          title="Bulk metadata workflows"
          text="Clinical and Surgical files are imported into the local CoCANoT database. Imaging and Electrophysiology use their dedicated de-identification workflows."
        />

        <div className={styles.bulkGrid}>
          <ActionCard
            icon={FileText}
            title="Clinical metadata"
            text="Choose a file, review rows, validate metadata, and then import Clinical Assessments."
            onClick={() => setBatchImport("Clinical")}
          />
          <ActionCard
            icon={Scissors}
            title="Surgical metadata"
            text="Choose a file, review rows, validate metadata, and then import Surgical records."
            onClick={() => setBatchImport("Surgical")}
          />
          <ActionCard
            icon={Brain}
            title="Imaging"
            text="Open the Imaging processing workflow."
            onClick={() =>
              onNavigate("imaging-processing")
            }
          />
          <ActionCard
            icon={Activity}
            title="Electrophysiology"
            text="Open the Electrophysiology processing workflow."
            onClick={() =>
              onNavigate("ephys-processing")
            }
          />
        </div>

        {message && (
          <div className={styles.message}>
            {message}
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <div className={styles.breadcrumb}>
        <button
          onClick={() => onNavigate("metadata-home")}
        >
          <ArrowLeft size={14} />
          Metadata Management
        </button>
        <span>›</span>
        <strong>Manage One Patient</strong>
      </div>

      <PageHeading
        title="Manage One Patient"
        text="Review or update metadata for one patient."
      />

      <section className={styles.patientLookup}>
        <label>
          <span>CoCANoT Patient ID</span>

          <div className={styles.patientSelect}>
            <Search size={17} />
            <select
              value={patientId}
              onChange={event =>
                setPatientId(event.target.value)
              }
            >
              <option value="">
                Select a patient…
              </option>
              {patients.map(id => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </div>
        </label>

        <button
          className={styles.primary}
          disabled={!patientId}
          onClick={() => loadPatient(patientId)}
        >
          Load Patient
        </button>

        <button
          className={styles.outlinePrimary}
          onClick={addPatient}
        >
          <Plus size={17} />
          Add New Patient
        </button>

        <button
          className={styles.iconButton}
          title="Refresh patient list"
          onClick={() =>
            loadPatients(loadedPatientId)
          }
        >
          <RefreshCw size={17} />
        </button>
      </section>

      {summary ? (
        <div className={styles.recordSections}>
          {[
            "Clinical",
            "Surgical",
            "Imaging",
            "Electrophysiology",
          ].map(tableName => (
            <PatientRecordSection
              key={tableName}
              tableName={tableName}
              rows={recordsFor(tableName)}
              selected={
                selected[tableName] ?? []
              }
              onToggle={recordId =>
                toggleSelected(
                  tableName,
                  recordId
                )
              }
              onAdd={() => addFor(tableName)}
              onUpload={
                tableName === "Clinical" ||
                tableName === "Surgical"
                  ? () =>
                      importRecords(tableName)
                  : null
              }
              onDelete={() =>
                deleteSelected(tableName)
              }
              onReview={() =>
                reviewSelected(tableName)
              }
              reviewLabel={
                tableName === "Imaging" ||
                tableName === "Electrophysiology"
                  ? "Review Patient Data"
                  : "Review / Edit Selected"
              }
            />
          ))}
        </div>
      ) : (
        <div className={styles.emptyState}>
          Select a patient and choose Load Patient.
        </div>
      )}

      {message && (
        <div className={styles.message}>
          {message}
        </div>
      )}

      {editor && (
        <div className={styles.modalBackdrop}>
          <div className={styles.modal}>
            <div className={styles.modalHeader}>
              <div>
                <span>
                  {editor.tableName.toUpperCase()}
                </span>
                <h2>
                  {editor.record
                    ? "Review / Edit Metadata"
                    : `Add ${editor.tableName} Metadata`}
                </h2>
              </div>

              <button
                onClick={() => setEditor(null)}
              >
                Close
              </button>
            </div>

            <DictionaryForm
              rules={rules}
              values={draft}
              onChange={(field, value) =>
                setDraft(current => ({
                  ...current,
                  [field]: value,
                }))
              }
            />

            <div className={styles.modalActions}>
              <button
                onClick={() => setEditor(null)}
              >
                Cancel
              </button>

              <button
                className={styles.primary}
                onClick={saveEditor}
              >
                Save Metadata
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
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

function ActionCard({
  icon: Icon,
  title,
  text,
  onClick,
}) {
  return (
    <button
      className={styles.actionCard}
      onClick={onClick}
    >
      <Icon size={28} />
      <strong>{title}</strong>
      <span>{text}</span>
    </button>
  );
}

function PatientRecordSection({
  tableName,
  rows,
  selected,
  onToggle,
  onAdd,
  onUpload,
  onDelete,
  onReview,
  reviewLabel,
}) {
  const config = SECTION_CONFIG[tableName];
  const Icon = config.icon;

  return (
    <section className={styles.recordSection}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>
          <Icon size={21} />
          <h2>{config.title}</h2>
        </div>

        <div className={styles.sectionActions}>
          <button
            className={styles.primarySmall}
            onClick={onAdd}
          >
            <Plus size={14} />
            {config.addLabel}
          </button>

          {onUpload && (
            <button
              className={styles.outlineSmall}
              onClick={onUpload}
            >
              <Upload size={14} />
              {config.uploadLabel}
            </button>
          )}

          <button
            className={styles.dangerSmall}
            disabled={!selected.length}
            onClick={onDelete}
          >
            <Trash2 size={14} />
            Delete Selected
          </button>

          <button
            className={styles.outlineSmall}
            disabled={selected.length !== 1}
            onClick={onReview}
          >
            <Pencil size={14} />
            {reviewLabel}
          </button>
        </div>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.checkColumn}></th>
              <th>Record</th>
              <th>Summary</th>
              <th>Updated</th>
            </tr>
          </thead>

          <tbody>
            {!rows.length ? (
              <tr>
                <td
                  colSpan="4"
                  className={styles.emptyRow}
                >
                  No records found.
                </td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={row.record_id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.includes(
                        row.record_id
                      )}
                      onChange={() =>
                        onToggle(row.record_id)
                      }
                    />
                  </td>
                  <td>{row.record_id}</td>
                  <td>
                    {summarizeRecord(
                      tableName,
                      row,
                      index === 0
                    )}
                  </td>
                  <td>
                    {formatUpdated(
                      row.updated_at
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function displayValue(value) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return String(value ?? "");
}

function summarizeRecord(
  tableName,
  row,
  currentClinical
) {
  const metadata = row.metadata ?? {};

  if (tableName === "Clinical") {
    const parts = [
      currentClinical ? "Current" : "Previous",
      metadata["Visit Type"],
      metadata["Primary Diagnosis"],
    ].filter(Boolean);

    return parts.join(" | ");
  }

  if (tableName === "Surgical") {
    return [
      metadata["Surgery ID"] &&
        `Surgery ID: ${metadata["Surgery ID"]}`,
      metadata[
        "Intent of Surgery (multiselect)"
      ] &&
        `Intent: ${displayValue(
          metadata[
            "Intent of Surgery (multiselect)"
          ]
        )}`,
      metadata[
        "Type(s) of surgery (multiselect)"
      ] &&
        `Type: ${displayValue(
          metadata[
            "Type(s) of surgery (multiselect)"
          ]
        )}`,
    ]
      .filter(Boolean)
      .join(" | ");
  }

  if (tableName === "Imaging") {
    return [
      metadata["Image ID"] &&
        `Image ID: ${metadata["Image ID"]}`,
      metadata["Imaging Modality"] &&
        `Modality: ${metadata["Imaging Modality"]}`,
      metadata[
        "Purpose of Imaging (multiselect)"
      ] &&
        `Purpose: ${displayValue(
          metadata[
            "Purpose of Imaging (multiselect)"
          ]
        )}`,
    ]
      .filter(Boolean)
      .join(" | ");
  }

  return [
    metadata["Recording ID"] &&
      `Recording ID: ${metadata["Recording ID"]}`,
    metadata["Recording Modality"] &&
      `Modality: ${metadata["Recording Modality"]}`,
    metadata["Purpose of Recording"] &&
      `Purpose: ${displayValue(
        metadata["Purpose of Recording"]
      )}`,
  ]
    .filter(Boolean)
    .join(" | ");
}

function formatUpdated(value) {
  if (!value) return "";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
