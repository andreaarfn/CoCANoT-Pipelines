import { useEffect, useMemo, useRef, useState } from "react";



import {



  Activity,



  ArrowLeft,



  Brain,



  CheckCircle2,



  ChevronLeft,



  ChevronRight,



  FileText,



  Pencil,



  RefreshCw,



  Scissors,



} from "lucide-react";



import DocumentAttachmentRedactor from "./DocumentAttachmentRedactor";
import styles from "./PatientDataReview.module.css";







const api = () => window.pywebview?.api ?? null;







export default function PatientDataReview({



  patientId,



  tableName,



  record,



  onBack,



  onEdit,



}) {



  if (tableName === "Clinical" || tableName === "Surgical") {

    return (

      <MetadataDocumentPatientReview

        patientId={patientId}

        tableName={tableName}

        record={record}

        onBack={onBack}

        onEdit={onEdit}

      />

    );

  }







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







function MetadataDocumentPatientReview({

  patientId,

  tableName,

  record,

  onBack,

  onEdit,

}) {

  const [documents, setDocuments] = useState([]);

  const [activeDocument, setActiveDocument] = useState(null);

  const [pageIndex, setPageIndex] = useState(0);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState("");
  const [redactionDocumentId, setRedactionDocumentId] = useState("");



  const Icon = tableName === "Surgical" ? Scissors : FileText;

  const recordId = String(record?.record_id ?? "");



  useEffect(() => {

    loadDocuments();

  }, [patientId, tableName, recordId]);



  async function loadDocuments() {

    try {

      setLoading(true);

      setError("");

      const rows = await api()?.metadata_document_list?.(

        patientId,

        tableName,

        recordId

      );

      const attached = rows ?? [];



      const withPreviews = await Promise.all(

        attached.map(async document => {

          try {

            const preview = await api()?.metadata_document_get_preview?.(

              patientId,

              tableName,

              recordId,

              document.document_id

            );

            return {

              ...document,

              previewPages: preview?.pages ?? [],

              previewError: "",

            };

          } catch (previewError) {

            return {

              ...document,

              previewPages: [],

              previewError: String(previewError),

            };

          }

        })

      );



      setDocuments(withPreviews);

    } catch (err) {

      setError(String(err));

    } finally {

      setLoading(false);

    }

  }



  async function openDocument(document) {

    try {

      setError("");

      const result = await api()?.metadata_document_get_preview?.(

        patientId,

        tableName,

        recordId,

        document.document_id

      );

      setActiveDocument(result);

      setPageIndex(0);

    } catch (err) {

      setError(String(err));

    }

  }



  if (activeDocument) {

    const pages = activeDocument.pages ?? [];

    const page = pages[pageIndex];



    return (

      <div>

        <ReviewHeader

          icon={FileText}

          eyebrow="ASSOCIATED DOCUMENT REVIEW"

          title={activeDocument.file_name}

          text={`${(activeDocument.document_types ?? []).join(", ") || "Supporting document"} · ${tableName} record ${recordId} · Patient ${patientId}`}

          onBack={() => {

            setActiveDocument(null);

            setPageIndex(0);

          }}


        />



        <section className={styles.documentReviewCard}>

          <div className={styles.documentReviewToolbar}>

            <div>

              <strong>Sanitized associated document</strong>

              <span>

                Page {pageIndex + 1} of {pages.length}

              </span>

            </div>



            <div className={styles.documentPageControls}>
              <button
                className={styles.editButton}
                onClick={() => setRedactionDocumentId(activeDocument.document_id)}
              >
                <Pencil size={15} />
                Edit Redactions
              </button>

              {pages.length > 1 && (
                <>
                  <button
                    onClick={() => setPageIndex(index => Math.max(0, index - 1))}
                    disabled={pageIndex === 0}
                  >
                    <ChevronLeft size={15} />
                    Previous
                  </button>
                  <button
                    onClick={() =>
                      setPageIndex(index => Math.min(pages.length - 1, index + 1))
                    }
                    disabled={pageIndex >= pages.length - 1}
                  >
                    Next
                    <ChevronRight size={15} />
                  </button>
                </>
              )}
            </div>

          </div>



          {page ? (

            <div className={styles.documentPage}>

              <img

                src={page.image_data_url}

                alt={`${activeDocument.file_name}, page ${pageIndex + 1}`}

              />

            </div>

          ) : (

            <div className={styles.documentEmpty}>

              No preview page is available.

            </div>

          )}

        </section>

        {redactionDocumentId && (
          <DocumentAttachmentRedactor
            patientId={patientId}
            tableName={tableName}
            recordId={recordId}
            initialEditDocumentId={redactionDocumentId}
            editOnly
            onClose={() => setRedactionDocumentId("")}
            onChanged={async () => {
              await loadDocuments();
              const refreshed = await api()?.metadata_document_get_preview?.(
                patientId,
                tableName,
                recordId,
                redactionDocumentId
              );
              setActiveDocument(refreshed);
              setPageIndex(0);
            }}
          />
        )}

      </div>

    );

  }



  return (

    <div>

      <ReviewHeader

        icon={Icon}

        eyebrow={`${tableName.toUpperCase()} DATA REVIEW`}

        title={`Review ${tableName.toLowerCase()} record`}

        text={`Review the stored metadata and sanitized documents associated with ${tableName} record ${recordId}.`}

        onBack={onBack}

        onEdit={onEdit}

      />



      <MetadataSummary record={record} />



      <section className={styles.associatedDocumentsCard}>

        <div className={styles.associatedDocumentsHeader}>

          <div>

            <strong>Associated documents</strong>

            <span>

              Sanitized documents explicitly attached to this patient record.

            </span>

          </div>

          <span className={styles.documentCount}>

            {documents.length} document{documents.length === 1 ? "" : "s"}

          </span>

        </div>



        {error && (

          <div className={styles.errorBox}>

            {error}

          </div>

        )}



        {loading ? (

          <div className={styles.documentEmpty}>

            Loading associated documents…

          </div>

        ) : documents.length ? (

          <div className={styles.documentPreviewGrid}>

            {documents.map(document => {

              const firstPage = document.previewPages?.[0];



              return (

                <article

                  key={document.document_id}

                  className={styles.documentPreviewCard}

                >

                  <div className={styles.documentPreviewHeading}>

                    <div className={styles.documentPreviewTitle}>

                      <FileText size={18} />

                      <div>

                        <strong>{document.file_name}</strong>

                        <span>

                          {(document.document_types ?? []).join(", ") || "Supporting document"}

                        </span>

                      </div>

                    </div>

                    <div className={styles.reviewDocumentStatus}>

                      <CheckCircle2 size={14} />

                      {document.status || "Attached"}

                    </div>

                  </div>



                  {firstPage ? (

                    <button

                      className={styles.inlineDocumentPreview}

                      onClick={() => openDocument(document)}

                      title={`Review ${document.file_name}`}

                    >

                      <img

                        src={firstPage.image_data_url}

                        alt={`Preview of ${document.file_name}`}

                      />

                      <span>

                        Review document

                        {document.previewPages.length > 1

                          ? ` · ${document.previewPages.length} pages`

                          : ""}

                        <ChevronRight size={15} />

                      </span>

                    </button>

                  ) : (

                    <div className={styles.previewUnavailable}>

                      <strong>Preview unavailable</strong>

                      <span>

                        {document.previewError ||

                          "The sanitized document could not be rendered."}

                      </span>

                    </div>

                  )}

                </article>

              );

            })}

          </div>

        ) : (

          <div className={styles.documentEmpty}>

            No associated documents are attached to this record.

          </div>

        )}

      </section>

    </div>

  );

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







        {onEdit && (
          <button className={styles.editButton} onClick={onEdit}>
            <Pencil size={15} />
            Edit Metadata
          </button>
        )}



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
  const [showDirectionLabels, setShowDirectionLabels] = useState(true);
  const [showLinkedJson, setShowLinkedJson] = useState(false);



  const [error, setError] = useState("");



  const [sliderCoords, setSliderCoords] = useState(null);



  const previewRef = useRef(null);



  const pendingSliderCoordsRef = useRef(null);



  const sliderTimerRef = useRef(null);



  const previewRequestRef = useRef(0);







  useEffect(() => {



    setPreview(null);



    setError("");



    setSliderCoords(null);



    previewRef.current = null;



    pendingSliderCoordsRef.current = null;







    if (sliderTimerRef.current) {



      window.clearTimeout(sliderTimerRef.current);



      sliderTimerRef.current = null;



    }







    previewRequestRef.current += 1;



    loadPreview({}, { showLoading: true });



    return () => {



      if (sliderTimerRef.current) {



        window.clearTimeout(sliderTimerRef.current);



        sliderTimerRef.current = null;



      }



      previewRequestRef.current += 1;



    };



  }, [record]);







  async function loadPreview(



    coords = {},



    {



      showLoading = false,



      requestId = null,



    } = {}



  ) {



    const currentRequestId = requestId ?? ++previewRequestRef.current;



    const currentPreview = previewRef.current ?? preview;







    try {



      setError("");







      if (showLoading && !currentPreview) {



        setPreview(null);



      }







      const result =



        await api()?.metadata_get_imaging_preview?.(



          record,



          coords.x ?? currentPreview?.x ?? null,



          coords.y ?? currentPreview?.y ?? null,



          coords.z ?? currentPreview?.z ?? null,



          coords.volume ?? currentPreview?.volume ?? null



        );







      if (currentRequestId !== previewRequestRef.current) {



        return;



      }







      previewRef.current = result;



      setPreview(result);



      setSliderCoords({



        x: Number(result.x ?? 0),



        y: Number(result.y ?? 0),



        z: Number(result.z ?? 0),



        volume: Number(result.volume ?? 0),



      });



    } catch (err) {



      if (currentRequestId === previewRequestRef.current) {



        setError(String(err));



      }



    }



  }







  function move(axis, value) {



    const currentPreview = previewRef.current ?? preview;



    if (!currentPreview) return;







    const numericValue = Number(value);



    const currentCoords = sliderCoords ?? {



      x: Number(currentPreview.x ?? 0),



      y: Number(currentPreview.y ?? 0),



      z: Number(currentPreview.z ?? 0),



      volume: Number(currentPreview.volume ?? 0),



    };







    const nextCoords = {



      ...currentCoords,



      [axis]: numericValue,



    };







    setSliderCoords(nextCoords);



    pendingSliderCoordsRef.current = nextCoords;







    if (sliderTimerRef.current) {



      window.clearTimeout(sliderTimerRef.current);



    }







    sliderTimerRef.current = window.setTimeout(async () => {



      sliderTimerRef.current = null;



      const requestId = ++previewRequestRef.current;



      const coords = pendingSliderCoordsRef.current ?? nextCoords;



      await loadPreview(coords, { requestId });



    }, 100);



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



              onClick={() => {



                if (sliderTimerRef.current) {



                  window.clearTimeout(sliderTimerRef.current);



                  sliderTimerRef.current = null;



                }



                pendingSliderCoordsRef.current = null;



                loadPreview(sliderCoords ?? {}, { showLoading: true });



              }}



            >



              <RefreshCw size={15} />



              Refresh



            </button>



          </div>







          <div className={styles.imageReviewToolbar}>
            <label className={styles.directionToggle}>
              <input type="checkbox" checked={showDirectionLabels} onChange={event => setShowDirectionLabels(event.target.checked)} />
              <span>Anatomical direction annotations</span>
              <span className={styles.directionToggleStatus}>{showDirectionLabels ? "Visible" : "Hidden"}</span>
            </label>
          </div>
          <div className={styles.imageGrid}>



            <ImagePanel



              label="Axial"



              src={preview.views.axial}
              showDirectionLabels={showDirectionLabels}
              automaticLabels={preview.orientation_labels?.axial}
              annotations={preview.direction_annotations?.defaced_axial ?? preview.direction_annotations?.raw_axial}



            />



            <ImagePanel



              label="Coronal"



              src={preview.views.coronal}
              showDirectionLabels={showDirectionLabels}
              automaticLabels={preview.orientation_labels?.coronal}
              annotations={preview.direction_annotations?.defaced_coronal ?? preview.direction_annotations?.raw_coronal}



            />



            <ImagePanel



              label="Sagittal"



              src={preview.views.sagittal}
              showDirectionLabels={showDirectionLabels}
              automaticLabels={preview.orientation_labels?.sagittal}
              annotations={preview.direction_annotations?.defaced_sagittal ?? preview.direction_annotations?.raw_sagittal}



            />



          </div>







          <div className={styles.sliderStack}>



            <ReviewSlider



              label="Sagittal X"



              value={sliderCoords?.x ?? preview.x}



              max={preview.limits.x_max}



              onChange={value => move("x", value)}



            />



            <ReviewSlider



              label="Coronal Y"



              value={sliderCoords?.y ?? preview.y}



              max={preview.limits.y_max}



              onChange={value => move("y", value)}



            />



            <ReviewSlider



              label="Axial Z"



              value={sliderCoords?.z ?? preview.z}



              max={preview.limits.z_max}



              onChange={value => move("z", value)}



            />







            {preview.is_4d && (



              <ReviewSlider



                label="4D Volume"



                value={sliderCoords?.volume ?? preview.volume}



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



              through the fourth dimension. Slider updates apply



              after a brief pause while dragging.



            </p>



          )}



        </section>



      )}



    
      {preview && (
        <section className={styles.linkedJsonCard}>
          <div className={styles.linkedJsonHeader}>
            <div className={styles.linkedJsonHeading}>
              <strong>NIfTI header</strong>
              <span>Header values read from the linked imaging file</span>
            </div>
          </div>
          <div className={styles.linkedJsonContent}>
            <pre className={styles.linkedJsonPreview}>{JSON.stringify(preview.linked_header ?? {}, null, 2)}</pre>
          </div>
        </section>
      )}

      {preview && (
        <section className={styles.linkedJsonCard}>
          <div className={styles.linkedJsonHeader}>
            <div className={styles.linkedJsonHeading}>
              <strong>Linked JSON file</strong>
              <span>{preview.linked_json_path ? preview.linked_json_path.split(/[\\/]/).pop() : "No matching JSON sidecar found"}</span>
            </div>
            <button type="button" className={styles.refreshButton} onClick={() => setShowLinkedJson(current => !current)} aria-expanded={showLinkedJson}>
              {showLinkedJson ? "Hide JSON" : "View JSON"}
            </button>
          </div>
          {(!preview.linked_is_bids_export || !preview.linked_json_has_cocanot_metadata) && (
            <p className={styles.linkedJsonEmpty} style={{ padding: "9px 14px", margin: 0 }}>
              {!preview.linked_is_bids_export
                ? "This viewer opened the earlier processed NIfTI and its processing JSON, not a verified Step 5 BIDS export. This does not mean Step 5 was never completed. The saved BIDS link may be missing, outdated, or pointing to a different output folder."
                : "This existing BIDS JSON predates the complete CoCANoT metadata export. Re-export from Step 5 to update the actual JSON file."}
            </p>
          )}
          {!preview.linked_json_has_cocanot_metadata && Object.keys(preview.record_cocanot_metadata ?? {}).length > 0 && (
            <div className={styles.linkedJsonContent}>
              <strong>CoCANoT metadata saved in patient record (not yet embedded in this JSON file)</strong>
              <p>The linked file shown above is missing CoCANoTMetadata. The values below are from the local patient database, not from the linked JSON. Complete a successful Step 5 export to create the combined final sidecar.</p>
              <pre className={styles.linkedJsonPreview}>{JSON.stringify(preview.record_cocanot_metadata, null, 2)}</pre>
            </div>
          )}
          {showLinkedJson && (
            <div className={styles.linkedJsonContent}>
              {preview.linked_json_error ? (
                <p role="alert" className={styles.errorBox}>Could not load linked JSON: {preview.linked_json_error}</p>
              ) : preview.linked_json != null ? (
                <pre className={styles.linkedJsonPreview}>{JSON.stringify(preview.linked_json, null, 2)}</pre>
              ) : (
                <p className={styles.linkedJsonEmpty}>No matching JSON sidecar was found beside the linked NIfTI image.</p>
              )}
            </div>
          )}
        </section>
      )}
      </div>



  );



}







function ImagePanel({ label, src, showDirectionLabels, automaticLabels, annotations }) {
  const overlay = annotations?.manualLabels ?? automaticLabels ?? {};
  const rotation = annotations?.rotation ?? 0;
  const flipHorizontal = annotations?.flipHorizontal ?? false;
  const flipVertical = annotations?.flipVertical ?? false;
  const displayed = { ...overlay };
  for (let turn = 0; turn < rotation / 90; turn += 1) {
    const old = { ...displayed };
    displayed.top = old.left;
    displayed.right = old.top;
    displayed.bottom = old.right;
    displayed.left = old.bottom;
  }
  if (flipHorizontal) [displayed.left, displayed.right] = [displayed.right, displayed.left];
  if (flipVertical) [displayed.top, displayed.bottom] = [displayed.bottom, displayed.top];
  const positions = {
    top: { top: 6, left: "50%", transform: "translateX(-50%)" },
    bottom: { bottom: 6, left: "50%", transform: "translateX(-50%)" },
    left: { left: 6, top: "50%", transform: "translateY(-50%)" },
    right: { right: 6, top: "50%", transform: "translateY(-50%)" },
  };
  return (
    <div className={styles.imagePanel}>
      <span>{label}</span>
      <div style={{ position: "relative", overflow: "hidden" }}>
        <img src={src} alt={`${label} NIfTI slice`} style={{ transform: `scaleX(${flipHorizontal ? -1 : 1}) scaleY(${flipVertical ? -1 : 1}) rotate(${rotation}deg)`, objectFit: "contain", maxWidth: "100%" }} />
        {showDirectionLabels && Object.entries(positions).map(([edge, position]) =>
          displayed[edge] ? <span key={edge} style={{ position: "absolute", ...position, padding: "2px 5px", borderRadius: 4, background: "rgba(0,0,0,0.8)", color: "white", fontWeight: 700, pointerEvents: "none" }}>{displayed[edge]}</span> : null
        )}
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
  const [showLinkedJson, setShowLinkedJson] = useState(false);







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

    const current = selectedChannels;
    const selected = current.includes(label);

    const next = selected
      ? current.filter(item => item !== label)
      : [...current, label];

    setSelectedChannels(next);
    loadSignal({ channels: next });

  }



  function changeDisplayMode(mode) {

    setDisplayMode(mode);

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



                    ? "Select any available channels for normalized overlay comparison."



                    : "Select any available channels for stacked review."}



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




          <section className={styles.linkedJsonCard}>
            <div className={styles.linkedJsonHeader}>
              <div className={styles.linkedJsonHeading}>
                <strong>EDF header</strong>
                <span>Header values read directly from the linked recording</span>
              </div>
            </div>
            <div className={styles.linkedJsonContent}>
              <pre className={styles.linkedJsonPreview}>{JSON.stringify(signal.header ?? {}, null, 2)}</pre>
            </div>
          </section>
          <section className={styles.linkedJsonCard}>
            <div className={styles.linkedJsonHeader}>
              <div className={styles.linkedJsonHeading}>
                <strong>Linked JSON file</strong>
                <span>Recording metadata followed by CoCANoT metadata</span>
              </div>
              <button type="button" className={styles.refreshButton} onClick={() => setShowLinkedJson(open => !open)} aria-expanded={showLinkedJson}>
                {showLinkedJson ? "Hide JSON" : "View JSON"}
              </button>
            </div>
            {!signal.linked_metadata?.CoCANoTMetadata && (
              <p className={styles.linkedJsonEmpty}>
                This recording's JSON does not contain embedded CoCANoT metadata. Complete Step 5 to create the combined final sidecar.
              </p>
            )}
            {showLinkedJson && (
              <div className={styles.linkedJsonContent}>
                <pre className={styles.linkedJsonPreview}>{JSON.stringify(signal.linked_metadata ?? {}, null, 2)}</pre>
              </div>
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



      (channels ?? []).map(



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



                `overlayLine${(channelIndex % 4) + 1}`



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
