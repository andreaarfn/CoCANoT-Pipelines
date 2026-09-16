import { useEffect, useState } from "react";
import AppShell from "./AppShell";
import HomeDashboard from "./HomeDashboard";
import ImagingDashboard from "./ImagingDashboard";
import ElectrophysiologyDashboard from "./ElectrophysiologyDashboard";
import MetadataDashboard from "./MetadataDashboard";
import styles from "./App.module.css";

const api = () => window.pywebview?.api ?? null;

export default function App() {
  const [siteId, setSiteId] = useState("");
  const [ready, setReady] = useState(false);
  const [page, setPage] = useState("home");

  useEffect(() => {
    let cancelled = false;

    async function initialize() {
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const bridge = api();
        if (bridge?.get_site_id) {
          const stored = await bridge.get_site_id();
          if (!cancelled) {
            setSiteId(stored ?? "");
            setReady(true);
          }
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 75));
      }
      if (!cancelled) setReady(true);
    }

    initialize();
    return () => {
      cancelled = true;
    };
  }, []);

  async function saveSite() {
    const value = siteId.trim().toUpperCase();
    if (!value) return;
    const saved = await api()?.set_site_id?.(value);
    setSiteId(saved || value);
    setPage("home");
  }

  if (!ready) {
    return <div className={styles.loading}>Loading CoCANoT…</div>;
  }

  if (!siteId) {
    return (
      <div className={styles.siteAccess}>
        <div className={styles.siteCard}>
          <div className={styles.mark}>C</div>
          <h1>CoCANoT</h1>
          <p>Enter the Site ID for this local installation.</p>
          <input
            value={siteId}
            onChange={event =>
              setSiteId(event.target.value.toUpperCase())
            }
            onKeyDown={event => {
              if (event.key === "Enter") saveSite();
            }}
            placeholder="Site ID"
          />
          <button onClick={saveSite}>Continue</button>
        </div>
      </div>
    );
  }

  let content;

  if (page === "home") {
    content = <HomeDashboard onNavigate={setPage} />;
  } else if (
    page === "imaging" ||
    page === "imaging-processing"
  ) {
    content = (
      <ImagingDashboard
        key={page}
        siteId={siteId}
        initialView={
          page === "imaging-processing" ? "processing" : "home"
        }
        onBack={() => setPage("home")}
        onHome={() => setPage("home")}
        onPatientReview={() => setPage("patient-review")}
        onRouteChange={setPage}
      />
    );
  } else if (
    page === "ephys" ||
    page === "ephys-processing"
  ) {
    content = (
      <ElectrophysiologyDashboard
        key={page}
        initialView={
          page === "ephys-processing" ? "processing" : "home"
        }
        onNavigate={setPage}
        onRouteChange={setPage}
      />
    );
  } else if (
    page === "metadata-home" ||
    page === "metadata-patients" ||
    page === "metadata-bulk" ||
    page === "patient-review"
  ) {
    content = (
      <MetadataDashboard
        key={page}
        initialView={
          page === "metadata-patients" ||
          page === "patient-review"
            ? "patient_explorer"
            : page === "metadata-bulk"
              ? "bulk"
              : "home"
        }
        patientReviewMode={page === "patient-review"}
        onNavigate={setPage}
      />
    );
  }

  return (
    <AppShell
      siteId={siteId}
      page={page}
      onNavigate={setPage}
      onSignOut={() => {
        setSiteId("");
        setPage("home");
      }}
    >
      {content}
    </AppShell>
  );
}
