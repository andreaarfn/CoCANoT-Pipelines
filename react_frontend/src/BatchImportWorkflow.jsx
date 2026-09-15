import { useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  FileSpreadsheet,
  Pencil,
  RefreshCw,
  Upload,
} from "lucide-react";
import DictionaryForm from "./DictionaryForm";
import styles from "./BatchImportWorkflow.module.css";

const api = () => window.pywebview?.api ?? null;

export default function BatchImportWorkflow({
  tableName,
  onBack,
  onFinished,
}) {
  const [step, setStep] = useState(1);
  const [batch, setBatch] = useState(null);
  const [rows, setRows] = useState([]);
  const [rules, setRules] = useState([]);
  const [editingIndex, setEditingIndex] = useState(null);
  const [editingValues, setEditingValues] = useState({});
  const [validation, setValidation] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const includedCount = useMemo(
    () =>
      rows.filter(row => row.include).length,
    [rows]
  );

  const invalidIncludedCount = useMemo(
    () =>
      rows.filter(
        row =>
          row.include &&
          (row.problems ?? []).length > 0
      ).length,
    [rows]
  );

  async function chooseFile() {
    try {
      setBusy(true);
      setError("");

      const [nextBatch, nextRules] =
        await Promise.all([
          api()?.metadata_batch_choose_file?.(
            tableName
          ),
          api()?.metadata_get_rules?.(
            tableName
          ),
        ]);

      if (
        !nextBatch ||
        nextBatch.cancelled
      ) {
        return;
      }

      setBatch(nextBatch);
      setRows(nextBatch.rows ?? []);
      setRules(nextRules ?? []);
      setValidation(null);
      setResult(null);
      setStep(2);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function toggleInclude(index) {
    setRows(current =>
      current.map((row, rowIndex) =>
        rowIndex === index
          ? {
              ...row,
              include: !row.include,
            }
          : row
      )
    );
  }

  function editRow(index) {
    setEditingIndex(index);
    setEditingValues({
      ...(rows[index]?.metadata ?? {}),
    });
  }

  function saveRowEdit() {
    setRows(current =>
      current.map((row, index) =>
        index === editingIndex
          ? {
              ...row,
              metadata: {
                ...editingValues,
              },
            }
          : row
      )
    );
    setEditingIndex(null);
    setEditingValues({});
    setValidation(null);
  }

  async function validateRows() {
    try {
      setBusy(true);
      setError("");

      const checked =
        await api()?.metadata_batch_validate?.(
          tableName,
          rows
        );

      if (!checked) {
        throw new Error(
          "The metadata validation API is unavailable."
        );
      }

      setValidation(checked);
      setRows(checked.rows ?? []);
      setStep(3);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function commitRows() {
    try {
      setBusy(true);
      setError("");

      const imported =
        await api()?.metadata_batch_commit?.(
          tableName,
          rows
        );

      if (!imported) {
        throw new Error(
          "The metadata import API is unavailable."
        );
      }

      setResult(imported);

      if (imported.rows) {
        setRows(imported.rows);
      }

      if (!imported.ok) {
        setError(
          (imported.problems ?? []).join(
            "\n"
          ) ||
            "One or more included rows still need attention."
        );
        return;
      }

      setStep(4);
      onFinished?.(imported);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button
        className={styles.backLink}
        onClick={onBack}
      >
        <ArrowLeft size={16} />
        Back to Bulk Upload
      </button>

      <header className={styles.heading}>
        <span>
          {tableName.toUpperCase()} BATCH IMPORT
        </span>
        <h1>
          Import {tableName} metadata
        </h1>
        <p>
          Choose a CSV/XLSX file, review and
          validate its rows, then explicitly
          import the accepted records into the
          local CoCANoT database.
        </p>
      </header>

      <ImportStepper current={step} />

      {error && (
        <div className={styles.errorBox}>
          {error
            .split("\n")
            .map((line, index) => (
              <div key={index}>{line}</div>
            ))}
        </div>
      )}

      {step === 1 && (
        <section className={styles.chooseCard}>
          <div className={styles.fileIcon}>
            <FileSpreadsheet size={32} />
          </div>
          <div>
            <h2>
              Select {tableName} CSV/XLSX
            </h2>
            <p>
              Selecting a file does not import
              anything yet. Rows are staged for
              review first.
            </p>
            <button
              className={styles.primary}
              onClick={chooseFile}
              disabled={busy}
            >
              <Upload size={16} />
              Choose File…
            </button>
          </div>
        </section>
      )}

      {step === 2 && batch && (
        <>
          <BatchSummary
            batch={batch}
            includedCount={includedCount}
          />

          <section className={styles.tableCard}>
            <div className={styles.tableHeader}>
              <div>
                <h2>
                  Review imported rows
                </h2>
                <p>
                  Invalid rows are excluded by
                  default. Edit them before
                  validation if needed.
                </p>
              </div>
              <button
                className={styles.secondary}
                onClick={chooseFile}
                disabled={busy}
              >
                <RefreshCw size={15} />
                Choose Different File
              </button>
            </div>

            <BatchTable
              rows={rows}
              onToggle={toggleInclude}
              onEdit={editRow}
            />
          </section>

          <div className={styles.footerActions}>
            <button
              className={styles.secondary}
              onClick={onBack}
            >
              Cancel
            </button>

            <button
              className={styles.primary}
              disabled={
                busy ||
                includedCount === 0
              }
              onClick={validateRows}
            >
              Validate Included Rows
              <ArrowRight size={16} />
            </button>
          </div>
        </>
      )}

      {step === 3 && validation && (
        <>
          <section
            className={`${styles.validationCard} ${
              invalidIncludedCount
                ? styles.validationProblem
                : styles.validationGood
            }`}
          >
            <CheckCircle2 size={24} />
            <div>
              <h2>
                {invalidIncludedCount
                  ? "Some included rows need attention"
                  : "Included rows passed validation"}
              </h2>
              <p>
                {validation.valid_count} valid
                row(s),{" "}
                {validation.invalid_count} row(s)
                with validation problems,{" "}
                {includedCount} row(s) selected for
                import.
              </p>
            </div>
          </section>

          <section className={styles.tableCard}>
            <BatchTable
              rows={rows}
              onToggle={toggleInclude}
              onEdit={editRow}
            />
          </section>

          <div className={styles.footerActions}>
            <button
              className={styles.secondary}
              onClick={() => setStep(2)}
            >
              <ArrowLeft size={16} />
              Back to Review
            </button>

            <button
              className={styles.primary}
              disabled={
                busy ||
                includedCount === 0 ||
                invalidIncludedCount > 0
              }
              onClick={commitRows}
            >
              Import {includedCount} Record
              {includedCount === 1 ? "" : "s"}
              <ArrowRight size={16} />
            </button>
          </div>
        </>
      )}

      {step === 4 && result && (
        <section className={styles.resultCard}>
          <CheckCircle2 size={34} />
          <h2>Batch import complete</h2>
          <p>
            Imported {result.imported ?? 0}{" "}
            {tableName} record
            {(result.imported ?? 0) === 1
              ? ""
              : "s"}
            .
          </p>

          {(result.results ?? []).length > 0 && (
            <table className={styles.resultTable}>
              <thead>
                <tr>
                  <th>Source Row</th>
                  <th>Status</th>
                  <th>Record ID</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map(item => (
                  <tr key={item.row_number}>
                    <td>{item.row_number}</td>
                    <td>{item.status}</td>
                    <td>{item.record_id}</td>
                    <td>{item.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className={styles.footerActions}>
            <button
              className={styles.secondary}
              onClick={onBack}
            >
              Back to Bulk Upload
            </button>
            <button
              className={styles.primary}
              onClick={() => {
                setStep(1);
                setBatch(null);
                setRows([]);
                setValidation(null);
                setResult(null);
              }}
            >
              Import Another File
            </button>
          </div>
        </section>
      )}

      {editingIndex !== null && (
        <div className={styles.modalBackdrop}>
          <div className={styles.modal}>
            <div className={styles.modalHeader}>
              <div>
                <span>
                  SOURCE ROW{" "}
                  {rows[editingIndex]?.row_number}
                </span>
                <h2>
                  Review / Edit {tableName} Row
                </h2>
              </div>
              <button
                onClick={() =>
                  setEditingIndex(null)
                }
              >
                Close
              </button>
            </div>

            <DictionaryForm
              rules={rules}
              values={editingValues}
              onChange={(field, value) =>
                setEditingValues(current => ({
                  ...current,
                  [field]: value,
                }))
              }
            />

            <div className={styles.footerActions}>
              <button
                className={styles.secondary}
                onClick={() =>
                  setEditingIndex(null)
                }
              >
                Cancel
              </button>
              <button
                className={styles.primary}
                onClick={saveRowEdit}
              >
                Apply Row Changes
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ImportStepper({ current }) {
  const steps = [
    [1, "Choose File"],
    [2, "Review Rows"],
    [3, "Validate & Confirm"],
    [4, "Import Results"],
  ];

  return (
    <div className={styles.stepper}>
      {steps.map(([number, label], index) => (
        <div
          className={styles.stepItem}
          key={label}
        >
          <span
            className={`${styles.stepCircle} ${
              number === current
                ? styles.stepActive
                : number < current
                  ? styles.stepDone
                  : ""
            }`}
          >
            {number}
          </span>
          <strong>{label}</strong>
          {index < steps.length - 1 && (
            <i className={styles.stepLine} />
          )}
        </div>
      ))}
    </div>
  );
}

function BatchSummary({
  batch,
  includedCount,
}) {
  return (
    <section className={styles.summaryBar}>
      <div>
        <strong>{batch.file_name}</strong>
        <span>{batch.path}</span>
      </div>
      <div>
        <strong>{batch.row_count}</strong>
        <span>Total rows</span>
      </div>
      <div>
        <strong>{batch.valid_count}</strong>
        <span>Initially valid</span>
      </div>
      <div>
        <strong>{includedCount}</strong>
        <span>Included</span>
      </div>
    </section>
  );
}

function BatchTable({
  rows,
  onToggle,
  onEdit,
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Include</th>
            <th>Source Row</th>
            <th>Patient ID</th>
            <th>Status</th>
            <th>Validation</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.row_number}>
              <td>
                <input
                  type="checkbox"
                  checked={Boolean(row.include)}
                  onChange={() =>
                    onToggle(index)
                  }
                />
              </td>
              <td>{row.row_number}</td>
              <td>{row.patient_id}</td>
              <td>
                <span
                  className={
                    (row.problems ?? []).length
                      ? styles.problemBadge
                      : styles.validBadge
                  }
                >
                  {row.status}
                </span>
              </td>
              <td>
                {(row.problems ?? []).length
                  ? row.problems
                      .map(
                        problem =>
                          `${problem.field_name}: ${problem.message}`
                      )
                      .join(" | ")
                  : "No validation problems"}
              </td>
              <td>
                <button
                  className={styles.editButton}
                  onClick={() =>
                    onEdit(index)
                  }
                >
                  <Pencil size={14} />
                  Edit
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
