import {
  AlertCircle,
  ArrowRight,
  Clock3,
  FileWarning,
  RefreshCw,
} from "lucide-react";
import styles from "./NeedsAttention.module.css";

export default function NeedsAttention({
  items = [],
  loading = false,
  error = "",
  onRefresh,
  onOpenAll,
  onOpenPatient,
}) {
  const visible = items.slice(0, 4);

  return (
    <aside className={styles.panel}>
      <div className={styles.header}>
        <div>
          <span>NEEDS ATTENTION</span>
          <strong
            className={
              items.length > 0
                ? styles.countAlert
                : ""
            }
          >
            {items.length}
          </strong>
        </div>

        <button
          type="button"
          title="Refresh attention items"
          onClick={onRefresh}
        >
          <RefreshCw size={15} />
        </button>
      </div>

      {loading ? (
        <p className={styles.empty}>
          Checking current requirements…
        </p>
      ) : error ? (
        <p className={styles.error}>{error}</p>
      ) : !items.length ? (
        <p className={styles.empty}>
          Nothing currently needs attention.
        </p>
      ) : (
        <>
          <div className={styles.list}>
            {visible.map(item => {
              const Icon =
                item.status === "overdue"
                  ? AlertCircle
                  : item.category === "followup"
                    ? Clock3
                    : FileWarning;

              return (
                <button
                  type="button"
                  key={item.attention_id}
                  className={styles.item}
                  onClick={() =>
                    onOpenPatient?.(
                      item.patient_id,
                      item
                    )
                  }
                >
                  <div className={styles.itemIcon}>
                    <Icon size={17} />
                  </div>

                  <div>
                    <strong>
                      Patient {item.patient_id}
                    </strong>
                    <span>{item.message}</span>
                  </div>
                </button>
              );
            })}
          </div>

          <button
            type="button"
            className={styles.viewAll}
            onClick={onOpenAll}
          >
            <span>View all attention items</span>
            <ArrowRight size={15} />
          </button>
        </>
      )}
    </aside>
  );
}
