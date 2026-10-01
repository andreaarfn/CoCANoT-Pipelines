import { useMemo, useState } from "react";
import {
  Bug,
  Clipboard,
  ExternalLink,
  LifeBuoy,
} from "lucide-react";
import styles from "./HelpSupport.module.css";

const REPOSITORY_ISSUES_URL =
  "https://github.com/andreaarfn/CoCANoT-Pipelines/issues/new";

export default function HelpSupport({ siteId }) {
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState("");
  const [message, setMessage] = useState("");

  const reportText = useMemo(
    () => [
      `Site: ${siteId || "Unknown"}`,
      `Summary: ${summary || "(not provided)"}`,
      "",
      "Description:",
      description || "(not provided)",
      "",
      "Steps to reproduce:",
      steps || "(not provided)",
    ].join("\n"),
    [siteId, summary, description, steps]
  );

  async function copyReport() {
    try {
      await navigator.clipboard.writeText(reportText);
      setMessage("Bug report copied to clipboard.");
    } catch {
      setMessage(
        "Could not access the clipboard. You can still open a GitHub issue."
      );
    }
  }

  function openIssue() {
    const params = new URLSearchParams({
      title: summary
        ? `[Bug] ${summary}`
        : "[Bug] CoCANoT issue",
      body: reportText,
    });

    window.open(
      `${REPOSITORY_ISSUES_URL}?${params.toString()}`,
      "_blank",
      "noopener,noreferrer"
    );
  }

  return (
    <div>
      <header className={styles.heading}>
        <span>HELP & SUPPORT</span>
        <h1>Get help or report a problem</h1>
        <p>
          Use this page to prepare a reproducible bug report.
          Do not include patient identifiers, PHI, or other sensitive
          information.
        </p>
      </header>

      <section className={styles.card}>
        <div className={styles.cardTitle}>
          <Bug size={21} />
          <div>
            <strong>Report a bug</strong>
            <span>
              Describe what happened and how to reproduce it.
            </span>
          </div>
        </div>

        <label>
          <span>Short summary</span>
          <input
            value={summary}
            onChange={event =>
              setSummary(event.target.value)
            }
            placeholder="Example: Surgical record will not save"
          />
        </label>

        <label>
          <span>What happened?</span>
          <textarea
            value={description}
            onChange={event =>
              setDescription(event.target.value)
            }
            rows="5"
            placeholder="Describe the problem and any error message you saw."
          />
        </label>

        <label>
          <span>Steps to reproduce</span>
          <textarea
            value={steps}
            onChange={event =>
              setSteps(event.target.value)
            }
            rows="5"
            placeholder="1. Open Metadata&#10;2. Load a patient&#10;3. ..."
          />
        </label>

        <div className={styles.actions}>
          <button
            className={styles.secondary}
            onClick={copyReport}
          >
            <Clipboard size={16} />
            Copy bug report
          </button>

          <button
            className={styles.primary}
            onClick={openIssue}
          >
            <ExternalLink size={16} />
            Open GitHub bug report
          </button>
        </div>

        {message && (
          <div className={styles.message}>
            {message}
          </div>
        )}
      </section>

      <section className={styles.note}>
        <LifeBuoy size={18} />
        <p>
          For data-governance, access, or consortium questions,
          use your normal CoCANoT support/contact process rather
          than including sensitive information in a public issue.
        </p>
      </section>
    </div>
  );
}
