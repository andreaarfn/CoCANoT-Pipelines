import {
  AlertCircle,
  ArrowLeft,
  Clock3,
  FileWarning,
  RefreshCw,
} from "lucide-react";
import styles from "./NeedsAttentionPage.module.css";

export default function NeedsAttentionPage({
  items = [],
  loading = false,
  error = "",
  onRefresh,
  onBack,
  onOpenPatient,
}) {
  return (
    <div>
      <div className={styles.breadcrumb}>
        <button onClick={onBack}>
          <ArrowLeft size={14} />
          Home
        </button>
        <span>›</span>
        <strong>Needs Attention</strong>
      </div>

      <header className={styles.heading}>
        <div>
          <span>DATA QUALITY & FOLLOW-UP</span>
          <h1>Needs Attention</h1>
          <p>
            Review records that no longer meet current metadata
            requirements, are missing local follow-up information,
            or have surgical outcomes due.
          </p>
        </div>

        <button
          className={styles.refresh}
          onClick={onRefresh}
        >
          <RefreshCw size={16} />
          Refresh
        </button>
      </header>

      <section className={styles.summary}>
        <strong
          className={
            items.length > 0
              ? styles.summaryAlert
              : ""
          }
        >
          {items.length}
        </strong>
        <span>
          {items.length === 1
            ? "item needs attention"
            : "items need attention"}
        </span>
      </section>

      {loading ? (
        <div className={styles.empty}>
          Checking current requirements…
        </div>
      ) : error ? (
        <div className={styles.error}>{error}</div>
      ) : !items.length ? (
        <div className={styles.empty}>
          Nothing currently needs attention.
        </div>
      ) : (
        <div className={styles.list}>
          {items.map(item => {
            const Icon =
              item.status === "overdue"
                ? AlertCircle
                : item.category === "followup"
                  ? Clock3
                  : FileWarning;

            return (
              <button
                key={item.attention_id}
                className={styles.row}
                onClick={() =>
                  onOpenPatient?.(
                    item.patient_id,
                    item
                  )
                }
              >
                <div className={styles.icon}>
                  <Icon size={19} />
                </div>

                <div className={styles.rowText}>
                  <div className={styles.rowTop}>
                    <strong>
                      Patient {item.patient_id}
                    </strong>

                    <span
                      className={`${styles.status} ${
                        item.status === "overdue"
                          ? styles.overdue
                          : item.status === "due"
                            ? styles.due
                            : item.status === "due_soon"
                              ? styles.dueSoon
                              : styles.needsReview
                      }`}
                    >
                      {String(
                        item.status ?? "needs_review"
                      )
                        .replaceAll("_", " ")
                        .toUpperCase()}
                    </span>
                  </div>

                  <p>{item.message}</p>

                  <div className={styles.meta}>
                    {item.table_name && (
                      <span>{item.table_name}</span>
                    )}
                    {item.record_id && (
                      <span>
                        Record {item.record_id}
                      </span>
                    )}
                    {item.surgery_id && (
                      <span>
                        Surgery {item.surgery_id}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
