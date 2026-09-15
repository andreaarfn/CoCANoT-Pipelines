import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Brain,
  ChevronLeft,
  ChevronRight,
  Pencil,
  RefreshCw,
} from "lucide-react";
import styles from "./PatientDataReview.module.css";

const api = () => window.pywebview?.api ?? null;

export default function PatientDataReview({
  tableName,
  record,
  onBack,
  onEdit,
}) {
  if (tableName === "Imaging") {
    return (
      <ImagingPatientReview
        record={record}
        onBack={onBack}
        onEdit={onEdit}
      />
    );
  }

  if (tableName === "Electrophysiology") {
    return (
      <EphysPatientReview
        record={record}
        onBack={onBack}
        onEdit={onEdit}
      />
    );
  }

  return null;
}

function ReviewHeader({
  icon: Icon,
  eyebrow,
  title,
  text,
  onBack,
  onEdit,
}) {
  return (
    <>
      <div className={styles.topActions}>
        <button className={styles.backButton} onClick={onBack}>
          <ArrowLeft size={16} />
          Back to Patient
        </button>

        <button className={styles.editButton} onClick={onEdit}>
          <Pencil size={15} />
          Edit Metadata
        </button>
      </div>

      <header className={styles.heading}>
        <div className={styles.headingIcon}>
          <Icon size={26} />
        </div>
        <div>
          <span>{eyebrow}</span>
          <h1>{title}</h1>
          <p>{text}</p>
        </div>
      </header>
    </>
  );
}

function ImagingPatientReview({
  record,
  onBack,
  onEdit,
}) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    loadPreview();
  }, [record]);

  async function loadPreview(coords = {}) {
    try {
      setError("");

      const result =
        await api()?.metadata_get_imaging_preview?.(
          record,
          coords.x ?? preview?.x ?? null,
          coords.y ?? preview?.y ?? null,
          coords.z ?? preview?.z ?? null,
          coords.volume ?? preview?.volume ?? null
        );

      setPreview(result);
    } catch (err) {
      setError(String(err));
    }
  }

  function move(axis, value) {
    loadPreview({
      [axis]: Number(value),
    });
  }

  return (
    <div>
      <ReviewHeader
        icon={Brain}
        eyebrow="IMAGING DATA REVIEW"
        title="Review linked image"
        text="View the NIfTI associated with this Imaging metadata record. Slice controls remain linked across axial, coronal, and sagittal views."
        onBack={onBack}
        onEdit={onEdit}
      />

      <MetadataSummary record={record} />

      {error && (
        <div className={styles.errorBox}>{error}</div>
      )}

      {!preview && !error && (
        <div className={styles.loading}>
          Loading linked NIfTI…
        </div>
      )}

      {preview && (
        <section className={styles.viewerCard}>
          <div className={styles.viewerHeader}>
            <div>
              <strong>{preview.file_name}</strong>
              <span>
                Shape: {preview.shape.join(" × ")}
              </span>
            </div>
            <button
              className={styles.refreshButton}
              onClick={() => loadPreview()}
            >
              <RefreshCw size={15} />
              Refresh
            </button>
          </div>

          <div className={styles.imageGrid}>
            <ImagePanel
              label="Axial"
              src={preview.views.axial}
            />
            <ImagePanel
              label="Coronal"
              src={preview.views.coronal}
            />
            <ImagePanel
              label="Sagittal"
              src={preview.views.sagittal}
            />
          </div>

          <div className={styles.sliderStack}>
            <ReviewSlider
              label="Sagittal X"
              value={preview.x}
              max={preview.limits.x_max}
              onChange={value => move("x", value)}
            />
            <ReviewSlider
              label="Coronal Y"
              value={preview.y}
              max={preview.limits.y_max}
              onChange={value => move("y", value)}
            />
            <ReviewSlider
              label="Axial Z"
              value={preview.z}
              max={preview.limits.z_max}
              onChange={value => move("z", value)}
            />

            {preview.is_4d && (
              <ReviewSlider
                label="4D Volume"
                value={preview.volume}
                max={preview.limits.volume_max}
                onChange={value =>
                  move("volume", value)
                }
              />
            )}
          </div>

          {preview.is_4d && (
            <p className={styles.viewerNote}>
              This is a 4D NIfTI. Use the volume control to move
              through the fourth dimension.
            </p>
          )}
        </section>
      )}
    </div>
  );
}

function ImagePanel({ label, src }) {
  return (
    <div className={styles.imagePanel}>
      <span>{label}</span>
      <div>
        <img src={src} alt={`${label} NIfTI slice`} />
      </div>
    </div>
  );
}

function ReviewSlider({
  label,
  value,
  max,
  onChange,
}) {
  return (
    <label className={styles.sliderRow}>
      <span>{label}</span>
      <input
        type="range"
        min="0"
        max={Math.max(0, max)}
        value={value}
        onChange={event =>
          onChange(event.target.value)
        }
      />
      <strong>
        {value} / {max}
      </strong>
    </label>
  );
}

function EphysPatientReview({
  record,
  onBack,
  onEdit,
}) {
  const [signal, setSignal] = useState(null);
  const [selectedChannels, setSelectedChannels] =
    useState([]);
  const [startSeconds, setStartSeconds] =
    useState(0);
  const [windowSeconds, setWindowSeconds] =
    useState(10);
  const [displayMode, setDisplayMode] =
    useState("stacked");
  const [error, setError] = useState("");

  useEffect(() => {
    loadSignal({
      start: 0,
      window: 10,
      channels: [],
    });
  }, [record]);

  async function loadSignal({
    start = startSeconds,
    window = windowSeconds,
    channels = selectedChannels,
  } = {}) {
    try {
      setError("");

      const result =
        await api()?.metadata_get_ephys_signal_preview?.(
          record,
          Number(start),
          Number(window),
          channels
        );

      setSignal(result);
      setStartSeconds(
        Number(result?.start_seconds ?? start)
      );
      setWindowSeconds(
        Number(result?.window_seconds ?? window)
      );

      if (!selectedChannels.length) {
        setSelectedChannels(
          result?.selected_channels ?? []
        );
      }
    } catch (err) {
      setError(String(err));
    }
  }

  function toggleChannel(label) {
    setSelectedChannels(current => {
      if (current.includes(label)) {
        return current.filter(
          item => item !== label
        );
      }

      const limit =
        displayMode === "overlay" ? 4 : 12;

      if (current.length >= limit) {
        return current;
      }

      return [...current, label];
    });
  }

  function changeDisplayMode(mode) {
    setDisplayMode(mode);

    if (
      mode === "overlay" &&
      selectedChannels.length > 4
    ) {
      const next = selectedChannels.slice(0, 4);
      setSelectedChannels(next);
      loadSignal({
        channels: next,
      });
    }
  }

  const maxStart = Math.max(
    0,
    Number(signal?.duration_seconds ?? 0) -
      Number(windowSeconds)
  );

  function shift(direction) {
    const next = Math.max(
      0,
      Math.min(
        maxStart,
        startSeconds +
          direction * windowSeconds
      )
    );
    setStartSeconds(next);
    loadSignal({ start: next });
  }

  return (
    <div>
      <ReviewHeader
        icon={Activity}
        eyebrow="ELECTROPHYSIOLOGY DATA REVIEW"
        title="Review linked recording"
        text="View the EDF signals associated with this Electrophysiology metadata record. Choose channels and move through the recording by time window."
        onBack={onBack}
        onEdit={onEdit}
      />

      <MetadataSummary record={record} />

      {error && (
        <div className={styles.errorBox}>{error}</div>
      )}

      {!signal && !error && (
        <div className={styles.loading}>
          Loading linked EDF signals…
        </div>
      )}

      {signal && (
        <>
          <section className={styles.controlsCard}>
            <div className={styles.recordingInfo}>
              <strong>{signal.file_name}</strong>
              <span>
                Duration:{" "}
                {formatDuration(
                  signal.duration_seconds
                )}
              </span>
              <span>
                {signal.channel_labels.length} channels
              </span>
            </div>

            <div className={styles.timeControls}>
              <button
                onClick={() => shift(-1)}
                disabled={startSeconds <= 0}
              >
                <ChevronLeft size={16} />
                Previous
              </button>

              <label>
                <span>Window</span>
                <select
                  value={windowSeconds}
                  onChange={event => {
                    const value = Number(
                      event.target.value
                    );
                    setWindowSeconds(value);
                    loadSignal({
                      window: value,
                    });
                  }}
                >
                  <option value="5">5 sec</option>
                  <option value="10">10 sec</option>
                  <option value="30">30 sec</option>
                  <option value="60">60 sec</option>
                </select>
              </label>

              <button
                onClick={() => shift(1)}
                disabled={
                  startSeconds >= maxStart
                }
              >
                Next
                <ChevronRight size={16} />
              </button>
            </div>

            <label className={styles.timeSlider}>
              <span>
                Start: {startSeconds.toFixed(1)} sec
              </span>
              <input
                type="range"
                min="0"
                max={Math.max(0, maxStart)}
                step="0.5"
                value={Math.min(
                  startSeconds,
                  maxStart
                )}
                onChange={event =>
                  setStartSeconds(
                    Number(event.target.value)
                  )
                }
                onMouseUp={() =>
                  loadSignal({
                    start: startSeconds,
                  })
                }
                onKeyUp={() =>
                  loadSignal({
                    start: startSeconds,
                  })
                }
              />
            </label>
          </section>

          <section className={styles.channelCard}>
            <div className={styles.channelHeader}>
              <div>
                <strong>Channels</strong>
                <span>
                  {displayMode === "overlay"
                    ? "Select up to 4 channels for normalized overlay comparison."
                    : "Select up to 12 channels for stacked review."}
                </span>
              </div>

              <div className={styles.channelActions}>
                <div
                  className={styles.modeToggle}
                  role="group"
                  aria-label="Signal display mode"
                >
                  <button
                    className={
                      displayMode === "stacked"
                        ? styles.modeActive
                        : ""
                    }
                    onClick={() =>
                      changeDisplayMode("stacked")
                    }
                  >
                    Stacked
                  </button>
                  <button
                    className={
                      displayMode === "overlay"
                        ? styles.modeActive
                        : ""
                    }
                    onClick={() =>
                      changeDisplayMode("overlay")
                    }
                  >
                    Overlay
                  </button>
                </div>

                <button
                  onClick={() =>
                    loadSignal({
                      channels: selectedChannels,
                    })
                  }
                >
                  Apply Channel Selection
                </button>
              </div>
            </div>

            <div className={styles.channelGrid}>
              {signal.channel_labels.map(label => (
                <label key={label}>
                  <input
                    type="checkbox"
                    checked={selectedChannels.includes(
                      label
                    )}
                    onChange={() =>
                      toggleChannel(label)
                    }
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </section>

          <section className={styles.signalCard}>
            {displayMode === "overlay" ? (
              <OverlaySignals
                channels={signal.signals ?? []}
                startSeconds={signal.start_seconds}
                windowSeconds={signal.window_seconds}
              />
            ) : (
              <>
                {(signal.signals ?? []).map(channel => (
                  <SignalStrip
                    key={channel.label}
                    channel={channel}
                  />
                ))}
                <TimeAxis
                  startSeconds={signal.start_seconds}
                  windowSeconds={signal.window_seconds}
                />
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function SignalStrip({ channel }) {
  const width = 1000;
  const height = 110;
  const padding = 10;

  const points = useMemo(() => {
    const values = channel.values ?? [];

    if (!values.length) {
      return "";
    }

    let min = Number(channel.min ?? 0);
    let max = Number(channel.max ?? 0);

    if (max === min) {
      max = min + 1;
    }

    return values
      .map((value, index) => {
        const x =
          padding +
          (index /
            Math.max(
              1,
              values.length - 1
            )) *
            (width - padding * 2);
        const y =
          padding +
          (1 -
            (Number(value) - min) /
              (max - min)) *
            (height - padding * 2);

        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  }, [channel]);

  const unit = channel.unit || "native units";

  return (
    <div className={styles.signalStrip}>
      <div className={styles.signalLabel}>
        <strong>{channel.label}</strong>
        <span>
          {Number(
            channel.sample_frequency
          ).toFixed(1)}{" "}
          Hz
        </span>
        <span>Amplitude ({unit})</span>
        <small>
          {formatAmplitude(channel.max)} /{" "}
          {formatAmplitude(channel.min)}
        </small>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${channel.label} signal amplitude in ${unit}`}
      >
        <line
          x1="0"
          x2={width}
          y1={height / 2}
          y2={height / 2}
          className={styles.zeroLine}
        />
        <polyline
          points={points}
          className={styles.signalLine}
        />
      </svg>
    </div>
  );
}

function OverlaySignals({
  channels,
  startSeconds,
  windowSeconds,
}) {
  const width = 1000;
  const height = 360;
  const padding = 18;

  const rendered = useMemo(
    () =>
      (channels ?? []).slice(0, 4).map(
        (channel, channelIndex) => {
          const values = channel.values ?? [];

          if (!values.length) {
            return {
              ...channel,
              points: "",
              className: styles.overlayLine1,
            };
          }

          const finite = values
            .map(Number)
            .filter(Number.isFinite);
          const center =
            finite.reduce(
              (sum, value) => sum + value,
              0
            ) /
            Math.max(1, finite.length);
          const maxDeviation = Math.max(
            1e-12,
            ...finite.map(value =>
              Math.abs(value - center)
            )
          );

          const points = values
            .map((value, index) => {
              const x =
                padding +
                (index /
                  Math.max(
                    1,
                    values.length - 1
                  )) *
                  (width - padding * 2);
              const normalized =
                (Number(value) - center) /
                maxDeviation;
              const y =
                height / 2 -
                normalized *
                  (height / 2 - padding);

              return `${x.toFixed(2)},${y.toFixed(2)}`;
            })
            .join(" ");

          return {
            ...channel,
            points,
            className:
              styles[
                `overlayLine${channelIndex + 1}`
              ],
          };
        }
      ),
    [channels]
  );

  return (
    <div className={styles.overlayWrap}>
      <div className={styles.overlayHeader}>
        <div>
          <strong>Normalized overlay</strong>
          <span>
            Waveforms are independently normalized so timing
            and morphology can be compared. Do not compare
            absolute amplitudes in this view.
          </span>
        </div>

        <div className={styles.overlayLegend}>
          {rendered.map(channel => (
            <span key={channel.label}>
              <i className={channel.className} />
              {channel.label}
              {channel.unit
                ? ` (${channel.unit})`
                : ""}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.overlayChart}>
        <span className={styles.overlayYAxis}>
          Normalized amplitude
        </span>

        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
        >
          {[0.25, 0.5, 0.75].map(ratio => (
            <line
              key={ratio}
              x1="0"
              x2={width}
              y1={height * ratio}
              y2={height * ratio}
              className={styles.gridLine}
            />
          ))}

          {rendered.map(channel => (
            <polyline
              key={channel.label}
              points={channel.points}
              className={`${styles.overlayLine} ${channel.className}`}
            />
          ))}
        </svg>
      </div>

      <TimeAxis
        startSeconds={startSeconds}
        windowSeconds={windowSeconds}
      />
    </div>
  );
}

function TimeAxis({
  startSeconds,
  windowSeconds,
}) {
  const start = Number(startSeconds ?? 0);
  const window = Number(windowSeconds ?? 0);
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className={styles.timeAxis}>
      <span className={styles.timeAxisLabel}>
        Time (s)
      </span>
      <div className={styles.timeTicks}>
        {ticks.map(ratio => (
          <span key={ratio}>
            {(start + window * ratio).toFixed(1)}
          </span>
        ))}
      </div>
    </div>
  );
}

function formatAmplitude(value) {
  const numeric = Number(value);

  if (!Number.isFinite(numeric)) {
    return "";
  }

  if (Math.abs(numeric) >= 100) {
    return numeric.toFixed(0);
  }

  if (Math.abs(numeric) >= 10) {
    return numeric.toFixed(1);
  }

  return numeric.toFixed(2);
}


function MetadataSummary({ record }) {
  const metadata = record?.metadata ?? {};

  const preferredKeys = [
    "CoCANoT Patient ID",
    "Image ID",
    "Recording ID",
    "Surgery ID",
    "Imaging Modality",
    "Recording Modality",
    "Clinical Assessment ID",
  ];

  const rows = preferredKeys
    .filter(key => metadata[key] != null && metadata[key] !== "")
    .map(key => [
      key,
      Array.isArray(metadata[key])
        ? metadata[key].join(", ")
        : String(metadata[key]),
    ]);

  return (
    <section className={styles.metadataCard}>
      <div>
        <strong>Linked metadata</strong>
        <span>Record {record?.record_id}</span>
      </div>

      <dl>
        {rows.map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function formatDuration(seconds) {
  const value = Number(seconds ?? 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = Math.floor(value % 60);

  if (hours) {
    return `${hours}h ${minutes}m ${secs}s`;
  }

  return `${minutes}m ${secs}s`;
}
