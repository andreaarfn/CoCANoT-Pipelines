import { useCallback, useEffect, useState } from "react";

import AppShell from "./AppShell";

import HomeDashboard from "./HomeDashboard";

import ImagingDashboard from "./ImagingDashboard";

import ElectrophysiologyDashboard from "./ElectrophysiologyDashboard";

import MetadataDashboard from "./MetadataDashboard";

import NeedsAttentionPage from "./NeedsAttentionPage";

import HelpSupport from "./HelpSupport";

import { loadNeedsAttention } from "./attentionService";

import styles from "./App.module.css";

const api = () => window.pywebview?.api ?? null;

export default function App() {

  const [siteId, setSiteId] = useState("");

  const [loginSiteId, setLoginSiteId] = useState("");

  const [accessCode, setAccessCode] = useState("");

  const [loginError, setLoginError] = useState("");

  const [authenticating, setAuthenticating] =

    useState(false);

  const [ready, setReady] = useState(false);

  const [page, setPage] = useState("home");

  const [navigationContext, setNavigationContext] =

    useState({});

  const [attentionItems, setAttentionItems] =

    useState([]);

  const [attentionLoading, setAttentionLoading] =

    useState(false);

  const [attentionError, setAttentionError] =

    useState("");

  useEffect(() => {

    let cancelled = false;

    async function initialize() {

      for (let attempt = 0; attempt < 80; attempt += 1) {

        const bridge = api();

        if (bridge?.authenticate_site) {

          if (!cancelled) {

            setReady(true);

          }

          return;

        }

        await new Promise(resolve =>

          setTimeout(resolve, 75)

        );

      }

      if (!cancelled) {

        setReady(true);

      }

    }

    initialize();

    return () => {

      cancelled = true;

    };

  }, []);

  const refreshAttention = useCallback(async () => {

    if (!siteId) {

      setAttentionItems([]);

      return;

    }

    try {

      setAttentionLoading(true);

      setAttentionError("");

      const rows = await loadNeedsAttention();

      setAttentionItems(rows);

    } catch (error) {

      setAttentionError(

        error?.message ||

          String(error) ||

          "Could not load attention items."

      );

    } finally {

      setAttentionLoading(false);

    }

  }, [siteId]);

  useEffect(() => {

    refreshAttention();

  }, [refreshAttention, page]);

  function navigate(nextPage, context = {}) {

    setNavigationContext(context ?? {});

    setPage(nextPage);

  }

  function openAttentionItem(patientId, item = {}) {

    if (

      item?.workflow === "imaging" ||

      item?.category === "imaging_step5"

    ) {

      navigate("imaging-processing", {

        imagingView: "metadata",

        attentionSourceKey: item?.source_key ?? "",

        attentionRecordId: item?.record_id ?? "",

      });

      return;

    }

    navigate("patient-review", {

      patientId,

    });

  }

  async function authenticateSite() {

    const value = loginSiteId.trim().toUpperCase();

    const code = accessCode.trim();

    if (!value || !code || authenticating) {

      return;

    }

    try {

      setAuthenticating(true);

      setLoginError("");

      const bridge = api();

      if (!bridge?.authenticate_site) {

        throw new Error(

          "Site authentication is not available."

        );

      }

      const result = await bridge.authenticate_site(

        value,

        code

      );

      if (!result?.ok) {

        setAccessCode("");

        setLoginError(

          result?.message ||

            "The Site ID and Access Code did not match."

        );

        return;

      }

      setSiteId(result.site_id || value);

      setLoginSiteId("");

      setAccessCode("");

      navigate("home");

    } catch (error) {

      setAccessCode("");

      setLoginError(

        error?.message ||

          String(error) ||

          "Site access could not be validated."

      );

    } finally {

      setAuthenticating(false);

    }

  }

  async function signOut() {

    try {

      await api()?.sign_out?.();

    } finally {

      setSiteId("");

      setLoginSiteId("");

      setAccessCode("");

      setLoginError("");

      setAttentionItems([]);

      navigate("home");

    }

  }

  if (!ready) {

    return (

      <div className={styles.loading}>

        Loading CoCANoT…

      </div>

    );

  }

  if (!siteId) {

    return (

      <main className={styles.siteAccess}>

        <form

          className={styles.siteCard}

          onSubmit={event => {

            event.preventDefault();

            authenticateSite();

          }}

          noValidate

        >

          <div className={styles.mark}>C</div>

          <h1>CoCANoT</h1>

          <p>Enter your Site ID and Access Code.</p>

          <label className={styles.loginField}>

            <span className={styles.srOnly}>

              Site ID

            </span>

            <input

              type="text"

              value={loginSiteId}

              onChange={event => {

                setLoginSiteId(

                  event.target.value.toUpperCase()

                );

                setLoginError("");

              }}

              placeholder="Site ID"

              aria-label="Site ID"

              autoComplete="off"

              autoFocus

              enterKeyHint="next"

            />

          </label>

          <label className={styles.loginField}>

            <span className={styles.srOnly}>

              Access Code

            </span>

            <input

              className={styles.passwordInput}

              type="password"

              value={accessCode}

              onChange={event => {

                setAccessCode(event.target.value);

                setLoginError("");

              }}

              onKeyDown={event => {

                if (event.key === "Enter") {

                  event.preventDefault();

                  authenticateSite();

                }

              }}

              placeholder="Access Code"

              aria-label="Access Code"

              autoComplete="off"

              autoCapitalize="none"

              autoCorrect="off"

              spellCheck={false}

              enterKeyHint="go"

            />

          </label>

          {loginError && (

            <p

              className={styles.loginError}

              role="alert"

            >

              {loginError}

            </p>

          )}

          <button

            type="submit"

            disabled={

              !loginSiteId.trim() ||

              !accessCode.trim() ||

              authenticating

            }

          >

            {authenticating

              ? "Checking…"

              : "Continue"}

          </button>

        </form>

      </main>

    );

  }

  let content;

  if (page === "home") {

    content = (

      <HomeDashboard

        onNavigate={navigate}

        attentionItems={attentionItems}

        attentionLoading={attentionLoading}

        attentionError={attentionError}

        onRefreshAttention={refreshAttention}

      />

    );

  } else if (page === "needs-attention") {

    content = (

      <NeedsAttentionPage

        items={attentionItems}

        loading={attentionLoading}

        error={attentionError}

        onRefresh={refreshAttention}

        onBack={() => navigate("home")}

        onOpenPatient={openAttentionItem}

      />

    );

  } else if (page === "help-support") {

    content = (

      <HelpSupport siteId={siteId} />

    );

  } else if (

    page === "imaging" ||

    page === "imaging-processing"

  ) {

    content = (

      <ImagingDashboard

        key={page}

        siteId={siteId}

        initialView={

          page === "imaging-processing"

            ? navigationContext.imagingView ?? "processing"

            : "home"

        }

        resumeBidsState={navigationContext.resumeBidsState ?? null}

        autoValidateBids={Boolean(navigationContext.autoValidateBids)}

        attentionSourceKey={navigationContext.attentionSourceKey ?? ""}

        attentionRecordId={navigationContext.attentionRecordId ?? ""}

        onCreateClinicalAssessment={(patientId, resumeBidsState) =>

          navigate("metadata-patients", {

            patientId,

            autoOpenClinical: true,

            returnPage: "imaging-processing",

            returnContext: {

              imagingView: "metadata",

              resumeBidsState,

              autoValidateBids: true,

            },

          })

        }

        onBack={() => navigate("home")}

        onHome={() => navigate("home")}

        onPatientReview={() =>

          navigate("patient-review")

        }

        onRouteChange={navigate}

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

          page === "ephys-processing"

            ? navigationContext.ephysView ?? "processing"

            : "home"

        }

        resumeBidsState={
          navigationContext.resumeEphysBidsState ?? null
        }

        autoValidateBids={Boolean(
          navigationContext.autoValidateEphysBids
        )}

        onCreateClinicalAssessment={(
          patientId,
          resumeEphysBidsState
        ) =>
          navigate("metadata-patients", {
            patientId,
            autoOpenClinical: true,
            returnPage: "ephys-processing",
            returnContext: {
              ephysView: "bids",
              resumeEphysBidsState,
              autoValidateEphysBids: true,
            },
          })
        }

        onNavigate={navigate}

        onRouteChange={navigate}

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

        key={`${page}:${navigationContext.patientId ?? ""}`}

        initialView={

          page === "metadata-patients" ||

          page === "patient-review"

            ? "patient_explorer"

            : page === "metadata-bulk"

              ? "bulk"

              : "home"

        }

        patientReviewMode={

          page === "patient-review"

        }

        preferredPatientId={

          navigationContext.patientId ?? ""

        }

        autoOpenClinical={Boolean(

          navigationContext.autoOpenClinical

        )}

        returnPage={navigationContext.returnPage ?? ""}

        returnContext={navigationContext.returnContext ?? {}}

        attentionItems={attentionItems}

        onDataChanged={refreshAttention}

        onNavigate={navigate}

      />

    );

  }

  return (

    <AppShell

      siteId={siteId}

      page={page}

      attentionCount={attentionItems.length}

      onNavigate={navigate}

      onSignOut={signOut}

    >

      {content}

    </AppShell>

  );

}
