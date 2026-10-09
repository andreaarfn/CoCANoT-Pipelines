import { useRef, useState } from "react";
import { Bug, Clipboard, LifeBuoy, Send } from "lucide-react";
import styles from "./HelpSupport.module.css";

export default function HelpSupport({ siteId }) {
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState("");
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const pendingReport = useRef(null);

  const reportText = [
    `Site: ${siteId || "Unknown"}`,
    `Summary: ${summary || "(not provided)"}`,
    "",
    "Description:",
    description || "(not provided)",
    "",
    "Steps to reproduce:",
    steps || "(not provided)",
  ].join("\n");

  async function copyReport() {
    try {
      await navigator.clipboard.writeText(reportText);
      setIsError(false);
      setMessage("Bug report copied to clipboard.");
    } catch {
      setIsError(true);
      setMessage("Could not copy the report to the clipboard.");
    }
  }

  async function submitReport(event) {
    event.preventDefault();
    if (submitting) return;
    setMessage("");
    setIsError(false);
    setSubmitting(true);
    try {
      const bridge = window.pywebview?.api;
      if (!bridge?.submit_bug_report) {
        throw new Error("Bug reporting is unavailable. Restart the updated desktop application.");
      }
      const fingerprint = JSON.stringify([siteId, summary.trim(), description.trim(), steps.trim()]);
      if (!pendingReport.current || pendingReport.current.fingerprint !== fingerprint) {
        pendingReport.current = { fingerprint, requestId: crypto.randomUUID() };
      }
      const result = await bridge.submit_bug_report({
        summary, description, steps, requestId: pendingReport.current.requestId,
      });
      if (!result?.ok) throw new Error(result?.message || "The report could not be submitted.");
      pendingReport.current = null;
      setMessage(`Bug report submitted successfully.`);
      setSummary("");
      setDescription("");
      setSteps("");
    } catch (error) {
      setIsError(true);
      setMessage(error?.message || "The report could not be submitted.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <header className={styles.heading}>
        <span>HELP & SUPPORT</span>
        <h1>Get help or report a problem</h1>
        <p>Submit a report directly to the CoCANoT development team. Do not include patient identifiers, PHI, or other sensitive information.</p>
      </header>
      <section className={styles.card}>
        <div className={styles.cardTitle}>
          <Bug size={21} />
          <div><strong>Report a bug</strong><span>Describe what happened and how to reproduce it.</span></div>
        </div>
        <form onSubmit={submitReport} style={{ display: "grid", gap: 15 }}>
          <label><span>Reporting site</span><input value={siteId || ""} readOnly /></label>
          <label><span>Short summary</span><input value={summary} maxLength={160} required onChange={event => setSummary(event.target.value)} placeholder="Example: Surgical record will not save" /></label>
          <label><span>What happened?</span><textarea value={description} maxLength={4000} required onChange={event => setDescription(event.target.value)} rows={5} placeholder="Describe the problem and any error message you saw." /></label>
          <label><span>Steps to reproduce</span><textarea value={steps} maxLength={3000} onChange={event => setSteps(event.target.value)} rows={5} placeholder={"1. Open Metadata\n2. Load a patient\n3. ..."} /></label>
          <div className={styles.actions}>
            <button type="button" className={styles.secondary} onClick={copyReport}><Clipboard size={16} />Copy bug report</button>
            <button type="submit" className={styles.primary} disabled={submitting || !summary.trim() || !description.trim()}><Send size={16} />{submitting ? "Submitting…" : "Submit Bug Report"}</button>
          </div>
          {message && <div className={styles.message} role={isError ? "alert" : "status"}>{message}</div>}
        </form>
      </section>
      <section className={styles.note}><LifeBuoy size={18} /><p>For data-governance, access, or consortium questions, use your normal CoCANoT support/contact process. Never include sensitive patient information in a bug report.</p></section>
    </div>
  );
}
