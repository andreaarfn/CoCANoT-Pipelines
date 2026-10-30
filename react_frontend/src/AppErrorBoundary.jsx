import React from "react";

/** Keep the desktop UI usable when a React subtree throws during upload. */
export default class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, detailsOpen: false };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("[CoCANoT] React render failure:", error, info?.componentStack);
  }

  render() {
    const { error, detailsOpen } = this.state;
    if (!error) return this.props.children;
    return (
      <main style={{
        minHeight: "100vh", display: "flex", alignItems: "center",
        justifyContent: "center", background: "#f5f7fa",
        color: "#1f2937", fontFamily: "system-ui, sans-serif", padding: 24,
      }}>
        <section role="alert" style={{
          width: "100%", maxWidth: 650, background: "#fff",
          border: "1px solid #dbe2e9", borderRadius: 14, padding: 28,
        }}>
          <h1 style={{ fontSize: 22, marginTop: 0 }}>CoCANoT encountered a display error</h1>
          <p>The interface could not display this screen. Your existing files
            have not been intentionally deleted by this error handler.</p>
          <p>Restart the display and retry the upload. If it happens again,
            copy the error details below and share them for diagnosis.</p>
          <button type="button" onClick={() => window.location.reload()}
            style={{ padding: "10px 18px", cursor: "pointer", marginRight: 12 }}>
            Reload interface
          </button>
          <button type="button" onClick={() => this.setState({detailsOpen: !detailsOpen})}
            style={{ padding: "10px 18px", cursor: "pointer" }}>
            {detailsOpen ? "Hide error details" : "Show error details"}
          </button>
          {detailsOpen && (
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere",
              background: "#f3f4f6", padding: 12, borderRadius: 6,
              fontSize: 12 }}>
              {String(error?.stack || error?.message || error)}
            </pre>
          )}
        </section>
      </main>
    );
  }
}
