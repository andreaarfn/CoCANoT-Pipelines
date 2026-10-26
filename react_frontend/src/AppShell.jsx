import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Brain,
  CircleHelp,
  FileText,
  Home,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Users,
  ClipboardCheck,
  FileSignature,
  ShieldCheck,
  GraduationCap,
  Database,
} from "lucide-react";
import styles from "./AppShell.module.css";

const LOGO_SRC = new URL(
  "./assets/logo-1024.png",
  import.meta.url
).href;

const NAV = [
  { key: "home", label: "Home", icon: Home },
  { key: "contracts", label: "Contracts", icon: FileSignature },
  { key: "regulatory", label: "Regulatory", icon: ShieldCheck },
  { key: "site-training", label: "Site Initiation & Training", icon: GraduationCap },
  { key: "data-capture", label: "Data Capture & Monitoring", icon: Database },
  { key: "needs-attention", label: "Needs Attention", icon: AlertTriangle },
];

export default function AppShell({
  siteId,
  page,
  attentionCount = 0,
  onNavigate,
  onSignOut,
  children,
}) {
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem("cocanot.sidebar.collapsed") === "true";
  });

  useEffect(() => {
    localStorage.setItem(
      "cocanot.sidebar.collapsed",
      String(collapsed)
    );
  }, [collapsed]);

  const dataPages = ["imaging", "ephys", "metadata", "patient-review"];
  const activeMain = page === "training-demo" || dataPages.some(item => page === item || page.startsWith(item + "-"))
    ? "data-capture"
    : page;

  function go(key) {
    onNavigate(key === "data-capture" ? "data-capture" : key);
  }

  return (
    <div
      className={`${styles.shell} ${
        collapsed ? styles.collapsed : ""
      }`}
    >
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandLogoWrap}>
            <img
              className={styles.brandLogo}
              src={LOGO_SRC}
              alt="CoCANoT"
            />
          </div>

          {!collapsed && (
            <div className={styles.brandText}>
              <strong>CoCANoT</strong>
              <span>Data. Discovery. Impact.</span>
            </div>
          )}
        </div>

        <button
          className={styles.collapseButton}
          onClick={() => setCollapsed(value => !value)}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <PanelLeftOpen size={18} />
          ) : (
            <PanelLeftClose size={18} />
          )}
          {!collapsed && <span>Collapse</span>}
        </button>

        <nav className={styles.nav}>
          {NAV.map(item => {
            const Icon = item.icon;
            const active = activeMain === item.key;

            return (
              <div key={item.key}>
                <button
                  className={`${styles.navItem} ${
                    active ? styles.navItemActive : ""
                  }`}
                  onClick={() => go(item.key)}
                  title={collapsed ? item.label : undefined}
                >
                  <Icon size={19} strokeWidth={1.9} />

                  {!collapsed && (
                    <>
                      <span>{item.label}</span>

                      {item.key === "needs-attention" &&
                        attentionCount > 0 && (
                          <span
                            style={{
                              marginLeft: "auto",
                              minWidth: 22,
                              height: 22,
                              padding: "0 6px",
                              display: "grid",
                              placeItems: "center",
                              borderRadius: 11,
                              background: "#c93643",
                              color: "#fff",
                              fontSize: 10,
                              fontWeight: 850,
                            }}
                          >
                            {attentionCount}
                          </span>
                        )}
                    </>
                  )}

                  {collapsed &&
                    item.key === "needs-attention" &&
                    attentionCount > 0 && (
                      <span
                        style={{
                          position: "absolute",
                          top: 5,
                          right: 5,
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: "#d6404d",
                        }}
                      />
                    )}
                </button>

                {!collapsed && item.key === "data-capture" && active && (
                  <>
                    {[
                      ["imaging", "Imaging"],
                      ["ephys", "Electrophysiology"],
                      ["metadata-home", "Metadata"],
                      ["patient-review", "Patient Data Review"],
                    ].map(([target, label]) => (
                      <button
                        key={target}
                        className={`${styles.subItem} ${
                          (target === "imaging" && page.startsWith("imaging")) ||
                          (target === "ephys" && page.startsWith("ephys")) ||
                          (target === "metadata-home" && page.startsWith("metadata")) ||
                          page === target
                            ? styles.subItemActive : ""
                        }`}
                        onClick={() => onNavigate(target)}
                      >{label}</button>
                    ))}
                  </>
                )}

              </div>
            );
          })}
        </nav>

        <div className={styles.sidebarFooter}>
          <div
            className={styles.help}
            role="button"
            tabIndex={0}
            onClick={() => onNavigate("help-support")}
            onKeyDown={event => {
              if (
                event.key === "Enter" ||
                event.key === " "
              ) {
                onNavigate("help-support");
              }
            }}
          >
            <CircleHelp size={18} />
            {!collapsed && <span>Help & Support</span>}
          </div>
        </div>
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <div className={styles.site}>
            <span>ACTIVE SITE</span>
            <strong>{siteId}</strong>
          </div>
          <button
            className={styles.signOut}
            onClick={onSignOut}
          >
            <LogOut size={17} />
            <span>Sign Out</span>
          </button>
        </header>

        <main className={styles.content}>
          {children}
        </main>
      </div>
    </div>
  );
}
