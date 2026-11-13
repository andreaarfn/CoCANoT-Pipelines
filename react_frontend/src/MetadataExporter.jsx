import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, CheckCircle2, Download, FolderOpen, RefreshCw } from "lucide-react";
import styles from "./MetadataExporter.module.css";

const bridge = () => window.pywebview?.api ?? null;
const groups = [
  ["Clinical", "clinical", "Clinical Assessment ID"],
  ["Surgical", "surgical", "Surgery ID"],
  ["Imaging", "imaging", "Image ID"],
  ["Electrophysiology", "electrophysiology", "Recording ID"],
  ["Video", "video", "Video ID"],
];

const keyOf = record => `${record.table_name}:${record.record_id}`;

export default function MetadataExporter({ onBack }) {
  const [patients, setPatients] = useState([]);
  const [selectedPatients, setSelectedPatients] = useState({});
  const [inventories, setInventories] = useState({});
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [loadingRecords, setLoadingRecords] = useState({});
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function loadPatients() {
    setLoadingPatients(true);
    setError("");
    try {
      if (!bridge()?.metadata_get_patients) throw new Error("The desktop metadata service is unavailable.");
      const site = await bridge().get_site_id();
      const rows = await bridge().metadata_get_patients(site);
      setPatients((rows || []).map(item => item.patient_id).filter(Boolean));
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoadingPatients(false);
    }
  }

  useEffect(() => { loadPatients(); }, []);

  async function loadPatientRecords(patientId) {
    if (!bridge()?.metadata_get_patient) throw new Error("The patient metadata service is unavailable.");
    setLoadingRecords(old => ({ ...old, [patientId]: true }));
    try {
      const site = await bridge().get_site_id();
      const summary = await bridge().metadata_get_patient(site, patientId);
      const records = groups.flatMap(([table_name, key, idField]) =>
        (summary?.[key] || []).map(record => ({
          table_name,
          record_id: String(record.record_id),
          label: String(record.metadata?.[idField] || record.record_id),
        }))
      );
      setInventories(old => ({ ...old, [patientId]: records }));
      return records;
    } finally {
      setLoadingRecords(old => ({ ...old, [patientId]: false }));
    }
  }

  async function togglePatient(patientId, enabled) {
    setError("");
    setResult(null);
    if (!enabled) {
      setSelectedPatients(old => {
        const next = { ...old };
        delete next[patientId];
        return next;
      });
      return;
    }
    setSelectedPatients(old => ({ ...old, [patientId]: { mode: "all", records: [] } }));
    if (!inventories[patientId]) {
      try { await loadPatientRecords(patientId); }
      catch (err) { setError(String(err?.message || err)); }
    }
  }

  function toggleRecord(patientId, record, checked) {
    setSelectedPatients(old => {
      const previous = old[patientId];
      if (!previous) return old;
      const allKeys = (inventories[patientId] || []).map(keyOf);
      const selected = previous.mode === "all" ? allKeys : previous.records;
      const nextKeys = checked
        ? [...new Set([...selected, keyOf(record)])]
        : selected.filter(key => key !== keyOf(record));
      return { ...old, [patientId]: { mode: "custom", records: nextKeys } };
    });
    setResult(null);
  }

  const selection = useMemo(() => Object.entries(selectedPatients).flatMap(([patientId, options]) => {
    const records = inventories[patientId] || [];
    const chosen = options.mode === "all"
      ? records
      : records.filter(record => options.records.includes(keyOf(record)));
    return chosen.map(record => ({
      patient_id: patientId,
      table_name: record.table_name,
      record_id: record.record_id,
    }));
  }), [selectedPatients, inventories]);

  async function chooseFolder() {
    setError("");
    try {
      if (!bridge()?.metadata_choose_export_folder) throw new Error("Folder selection is unavailable.");
      const path = await bridge().metadata_choose_export_folder();
      if (path) { setFolder(path); setResult(null); }
    } catch (err) { setError(String(err?.message || err)); }
  }

  async function exportMetadata() {
    if (!selection.length || !folder) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      if (!bridge()?.metadata_export_records) throw new Error("Metadata export is unavailable.");
      const response = await bridge().metadata_export_records(selection, folder);
      if (!response || !Array.isArray(response.results)) throw new Error("Export did not return a verifiable result.");
      setResult(response);
    } catch (err) { setError(String(err?.message || err)); }
    finally { setBusy(false); }
  }

  const totals = (result?.results || []).reduce((counts, item) => {
    counts[item.status] = (counts[item.status] || 0) + 1;
    return counts;
  }, {});

  return <main className={styles.page}>
    <button type="button" className={styles.back} onClick={onBack}>
      <ArrowLeft size={16}/> Metadata
    </button>
    <header className={styles.heading}>
      <span>METADATA EXPORT</span>
      <h1>Export Metadata</h1>
      <p>Export selected patients and records across all five data types as de-identified JSON. Identical exports are skipped; changed records retain previous versions.</p>
    </header>
    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div><h2>Select patients and records</h2><p>Select a patient to export everything, or choose specific records.</p></div>
        <button type="button" className={styles.secondary} onClick={loadPatients} disabled={busy || loadingPatients}>
          <RefreshCw size={14}/> Refresh patients
        </button>
      </div>
      {loadingPatients && <p className={styles.muted}>Loading patients…</p>}
      {!loadingPatients && patients.length === 0 && <p className={styles.muted}>No locally stored patients were found.</p>}
      {patients.map(patient => {
        const enabled = Boolean(selectedPatients[patient]);
        const inventory = inventories[patient] || [];
        const isLoading = Boolean(loadingRecords[patient]);
        const mode = selectedPatients[patient]?.mode || "all";
        const currentKeys = new Set(mode === "all" ? inventory.map(keyOf) : selectedPatients[patient]?.records || []);
        return <div className={styles.patient} key={patient}>
          <label className={styles.patientHeader}>
            <input type="checkbox" checked={enabled} disabled={busy}
              onChange={event => togglePatient(patient, event.target.checked)}/>
            <strong>Patient {patient}</strong>
            <span>{enabled ? `${currentKeys.size} selected records` : "Not selected"}</span>
          </label>
          {enabled && <div className={styles.patientBody}>
            <div className={styles.mode}>
              <label><input type="radio" checked={mode === "all"} disabled={busy}
                onChange={() => setSelectedPatients(old => ({ ...old, [patient]: { mode: "all", records: [] } }))}/> Export all for this patient</label>
              <label><input type="radio" checked={mode === "custom"} disabled={busy}
                onChange={() => setSelectedPatients(old => ({
                  ...old, [patient]: { mode: "custom", records: inventory.map(keyOf) },
                }))}/> Select individual records</label>
            </div>
            {isLoading ? <p className={styles.muted}>Loading records…</p>
              : inventory.length === 0 ? <p className={styles.muted}>No metadata records found for this patient.</p>
              : mode === "custom" ? <div className={styles.records}>
                  {inventory.map(record => <label className={styles.record} key={keyOf(record)}>
                    <input type="checkbox" checked={currentKeys.has(keyOf(record))}
                      disabled={busy}
                      onChange={event => toggleRecord(patient, record, event.target.checked)}/>
                    <strong>{record.table_name}</strong>
                    <span>{record.label}</span>
                  </label>)}
                </div>
              : <p className={styles.muted}>All {inventory.length} available metadata records will be included.</p>}
          </div>}
        </div>;
      })}
    </section>
    <section className={styles.panel}>
      <h2>Export destination</h2>
      <p className={styles.muted}>Select an existing folder. Files will be grouped by patient and modality, with a manifest tracking duplicates and versions.</p>
      <div className={styles.folder}>
        <code>{folder || "No destination selected"}</code>
        <button className={styles.secondary} type="button" onClick={chooseFolder} disabled={busy}>
          <FolderOpen size={16}/> Browse
        </button>
      </div>
    </section>
    {error && <div className={styles.error} role="alert">{error}</div>}
    <div className={styles.actions}>
      <span>{selection.length} metadata record{selection.length === 1 ? "" : "s"} selected</span>
      <button className={styles.primary} disabled={busy || !folder || !selection.length || Object.values(loadingRecords).some(Boolean)}
        type="button" onClick={exportMetadata}>
        <Download size={16}/>{busy ? "Exporting…" : "Export Selected Metadata"}
      </button>
    </div>
    {result && <section className={styles.panel} aria-live="polite">
      <h2><CheckCircle2 size={17}/> Export results</h2>
      <p className={styles.muted}>
        {totals.exported || 0} new · {totals.skipped || 0} identical skipped · {totals.versioned || 0} versioned · {totals.failed || 0} failed
      </p>
      <div className={styles.results}>
        {result.results.map((item, index) => <div key={index} className={styles.result}>
          <strong>{item.patient_id} · {item.table_name} · {item.record_id}</strong>
          <span>{item.status}{item.message ? `: ${item.message}` : item.path ? ` · ${item.path}` : ""}</span>
        </div>)}
      </div>
    </section>}
  </main>;
}
