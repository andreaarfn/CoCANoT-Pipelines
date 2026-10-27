import { useEffect, useMemo, useState } from "react";
import { Download, FileText, History, UploadCloud } from "lucide-react";
import styles from "./TrialDocuments.module.css";

const DB_NAME = "atlas-trial-documents";
const STORE = "documents";
const AUDIT = "events";

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
      if (!db.objectStoreNames.contains(AUDIT)) db.createObjectStore(AUDIT, { keyPath: "id" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function database(operation, store, value) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(store, operation === "read" ? "readonly" : "readwrite");
    const request = operation === "read"
      ? transaction.objectStore(store).getAll()
      : transaction.objectStore(store).put(value);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => db.close();
    transaction.onerror = () => reject(transaction.error);
  });
}

export default function TrialDocuments({ section, siteId, experience = "research" }) {
  const regulatory = section === "regulatory";
  const canEdit = experience !== "research";
  const [records, setRecords] = useState([]);
  const [events, setEvents] = useState([]);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [showPrevious, setShowPrevious] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);

  async function refresh() {
    const [docs, history] = await Promise.all([
      database("read", STORE), database("read", AUDIT)
    ]);
    setRecords(docs.filter(item => item.siteId === siteId && item.section === section));
    setEvents(history.filter(item => item.siteId === siteId && item.section === section)
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp)));
  }
  useEffect(() => { refresh().catch(error => setError(error.message)); }, [siteId, section]);

  const grouped = useMemo(() => {
    const groups = new Map();
    for (const record of records) {
      const key = record.title.toLowerCase().trim();
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(record);
    }
    return [...groups.values()].map(items => items.sort((a, b) =>
      b.version - a.version || b.uploadedAt.localeCompare(a.uploadedAt)
    )).sort((a, b) => b[0].uploadedAt.localeCompare(a[0].uploadedAt));
  }, [records]);

  async function log(action, record) {
    await database("write", AUDIT, {
      id: crypto.randomUUID(), siteId, section,
      action, documentId: record.id, title: record.title,
      version: record.version, timestamp: new Date().toISOString()
    });
  }

  async function upload(file) {
    if (!canEdit || !file) return;
    const documentTitle = title.trim() || file.name;
    const previousVersions = records.filter(item =>
      item.title.trim().toLowerCase() === documentTitle.toLowerCase()
    );
    const version = Math.max(0, ...previousVersions.map(item => item.version)) + 1;
    const record = {
      id: crypto.randomUUID(), section, siteId, title: documentTitle,
      category: category.trim(), fileName: file.name, mimeType: file.type,
      size: file.size, version, uploadedAt: new Date().toISOString(),
      file
    };
    setBusy(true);
    setError("");
    try {
      await database("write", STORE, record);
      await log("UPLOAD", record);
      setTitle("");
      await refresh();
    } catch (e) {
      setError(e?.message || "Unable to save document.");
    } finally { setBusy(false); }
  }

  async function download(record) {
    const url = URL.createObjectURL(record.file);
    try {
      const link = document.createElement("a");
      link.href = url;
      link.download = record.fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      await log("DOWNLOAD", record);
      await refresh();
    } catch (e) {
      setError(e?.message || "Download could not be recorded.");
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }

  return (
    <section className={styles.page}>
      <div className={styles.heading}>
        <span className={styles.eyebrow}>CLINICAL TRIAL OPERATIONS / {siteId}</span>
        <h1>{regulatory ? "Regulatory" : "Contracts"}</h1>
        <p>{regulatory
          ? "All regulatory document versions remain visible. The current version is marked."
          : "Current contract versions appear first. Show previous versions when needed."}</p>
      </div>
      {canEdit && <div className={styles.card}>
        <h2>Upload document</h2>
        <div className={styles.form}>
          <label>Document title <input value={title} onChange={e => setTitle(e.target.value)}
            placeholder="e.g. Site agreement or IRB approval" /></label>
          <label>Category <input value={category} onChange={e => setCategory(e.target.value)}
            placeholder="e.g. CTA, Budget, IRB, Protocol" /></label>
          <label className={styles.upload}><UploadCloud size={18} />
            {busy ? "Saving..." : "Select document"}
            <input type="file" disabled={busy} onChange={e => { upload(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
        </div>
        <p className={styles.hint}>To add a new version, upload a document with the same title.</p>
      </div>}
      {!canEdit && <p>Document history is read-only for Research users.</p>}
      {error && <p className={styles.error} role="alert">{error}</p>}
      <div className={styles.sectionTitle}>
        <h2>Document library <span>({grouped.length})</span></h2>
        {!regulatory && <label className={styles.toggle}>
          <input type="checkbox" checked={showPrevious} onChange={e => setShowPrevious(e.target.checked)} />
          Show previous versions
        </label>}
      </div>
      {!grouped.length && <div className={styles.empty}>No documents have been uploaded for this site.</div>}
      {grouped.map(group => (
        <div className={styles.card} key={group[0].title.toLowerCase()}>
          <h3>{group[0].title}</h3>
          {(regulatory || showPrevious ? group : group.slice(0, 1)).map((record, i) => (
            <div className={styles.doc} key={record.id}>
              <FileText size={19} />
              <div className={styles.docInfo}>
                <strong>{record.fileName} {i === 0 && <span className={styles.current}>Current</span>}</strong>
                <small>Version {record.version} · {new Date(record.uploadedAt).toLocaleString()}
                  {record.category && ` · ${record.category}`}</small>
              </div>
              <button type="button" onClick={() => download(record)}>
                <Download size={16} /> Download
              </button>
            </div>
          ))}
        </div>
      ))}
      <div className={styles.sectionTitle}>
        <h2>Activity history</h2>
        {!regulatory && <button onClick={() => setShowHistory(value => !value)} className={styles.historyButton}>
          <History size={16} /> {showHistory ? "Hide activity" : "Show activity"} ({events.length})
        </button>}
      </div>
      {(regulatory || showHistory) && <div className={styles.card}>
        {!events.length ? <p>No activity recorded.</p> :
          events.map(item => <div className={styles.event} key={item.id}>
            <strong>{item.action}</strong> {item.title} · v{item.version}
            <small>{new Date(item.timestamp).toLocaleString()} · Site {item.siteId}</small>
          </div>)}
      </div>}
    </section>
  );
}
