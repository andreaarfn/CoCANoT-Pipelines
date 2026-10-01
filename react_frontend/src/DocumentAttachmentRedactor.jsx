import { useEffect, useMemo, useRef, useState } from "react";



import {



  ArrowLeft,



  Check,



  Eye,



  FileText,



  Pencil,



  Paperclip,



  RotateCcw,



  Trash2,



  Upload,



  X,



} from "lucide-react";



import styles from "./DocumentAttachmentRedactor.module.css";







const api = () => window.pywebview?.api ?? null;







const DOCUMENT_TYPES = {



  Clinical: [



    "Clinic Note",



    "Seizure Diary",



    "Medication List",



    "Neuropsychology Report",



    "EEG Report",



    "Imaging Report",



    "Discharge Summary",



    "Other",



  ],



  Surgical: [



    "Surgical Note",



    "Operative Report",



    "Implant / Device Record",



    "Pathology Report",



    "Discharge Summary",



    "EEG Report",



    "Imaging Report",



    "Other",



  ],



};







export default function DocumentAttachmentRedactor({



  patientId,



  tableName,



  recordId,



  onClose,



  onChanged,

  initialEditDocumentId = "",

  editOnly = false,

}) {



  const [documents, setDocuments] = useState([]);



  const [workingDocument, setWorkingDocument] = useState(null);



  const [pageIndex, setPageIndex] = useState(0);



  const [redactions, setRedactions] = useState({});



  const [drawing, setDrawing] = useState(null);



  const [busy, setBusy] = useState(false);



  const [message, setMessage] = useState("");



  const [documentTypes, setDocumentTypes] = useState([]);



  const [otherDocumentType, setOtherDocumentType] = useState("");



  const [stagedDocuments, setStagedDocuments] = useState([]);



  const [previewDocument, setPreviewDocument] = useState(null);



  const [previewPageIndex, setPreviewPageIndex] = useState(0);



  const stageRef = useRef(null);







  useEffect(() => {



    loadDocuments();



  }, [patientId, tableName, recordId]);







  useEffect(() => {

    if (!initialEditDocumentId) return;

    editDocument({ document_id: initialEditDocumentId });

  }, [patientId, tableName, recordId, initialEditDocumentId]);



  async function loadDocuments() {



    try {



      setMessage("");



      const rows = await api()?.metadata_document_list?.(



        patientId,



        tableName,



        recordId



      );



      setDocuments(rows ?? []);



    } catch (error) {



      setMessage(String(error));



    }



  }







  async function chooseDocument() {



    try {



      setBusy(true);



      setMessage("");



      const finalizedTypes = documentTypes.filter(type => type !== "Other");



      if (documentTypes.includes("Other")) {



        const customType = otherDocumentType.trim();



        if (!customType) {



          setMessage("Describe the Other document type before adding a document.");



          return;



        }



        finalizedTypes.push(customType);



      }



      if (!finalizedTypes.length) {



        setMessage("Select at least one associated document type before adding a document.");



        return;



      }



      const result = await api()?.metadata_document_choose?.(patientId, tableName, recordId, finalizedTypes);



      if (!result) return;



      setWorkingDocument(result);



      setPageIndex(0);



      setRedactions({});



    } catch (error) {



      setMessage(String(error));



    } finally {



      setBusy(false);



    }



  }







  function pageKey(index = pageIndex) {



    return String(index);



  }







  function pointFromEvent(event) {



    const bounds = stageRef.current?.getBoundingClientRect();



    if (!bounds?.width || !bounds?.height) return null;



    return {



      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),



      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),



    };



  }







  function beginRedaction(event) {



    if (event.button !== 0) return;



    const point = pointFromEvent(event);



    if (!point) return;



    event.currentTarget.setPointerCapture?.(event.pointerId);



    setDrawing({ start: point, end: point });



  }







  function updateRedaction(event) {



    if (!drawing) return;



    const point = pointFromEvent(event);



    if (!point) return;



    setDrawing(current => current ? { ...current, end: point } : null);



  }







  function finishRedaction(event) {



    if (!drawing) return;



    const point = pointFromEvent(event) ?? drawing.end;



    const x = Math.min(drawing.start.x, point.x);



    const y = Math.min(drawing.start.y, point.y);



    const width = Math.abs(point.x - drawing.start.x);



    const height = Math.abs(point.y - drawing.start.y);



    setDrawing(null);



    if (width < 0.005 || height < 0.005) return;



    const key = pageKey();



    setRedactions(current => ({



      ...current,



      [key]: [...(current[key] ?? []), { x, y, width, height }],



    }));



  }







  function undoLast() {



    const key = pageKey();



    setRedactions(current => ({



      ...current,



      [key]: (current[key] ?? []).slice(0, -1),



    }));



  }







  function clearPage() {



    const key = pageKey();



    setRedactions(current => ({ ...current, [key]: [] }));



  }







  async function saveRedactedDocument() {



    if (!workingDocument) return;



    try {



      setBusy(true);



      setMessage("");



      const editingExisting = Boolean(workingDocument.edit_existing);



      const saved = await api()?.metadata_document_save_redactions?.(workingDocument.document_id, redactions);



      setWorkingDocument(null);



      setPageIndex(0);



      setRedactions({});



      setDocumentTypes([]);



      setOtherDocumentType("");



      if (editingExisting) {

      await onChanged?.();

      if (editOnly) {

        onClose?.();

        return;

      }

      await loadDocuments();

      setMessage("Document redactions updated.");

    } else {



        setStagedDocuments(current => [...current.filter(item => item.document_id !== saved.document_id), saved]);



        setMessage("Redaction review saved. Confirm below to attach the document to this patient.");



      }



    } catch (error) {



      setMessage(String(error));



    } finally {



      setBusy(false);



    }



  }







  async function attachDocumentsToPatient() {



    if (!stagedDocuments.length) return;



    try {



      setBusy(true);



      setMessage("");



      const ids = stagedDocuments.map(document => document.document_id);



      await api()?.metadata_document_attach?.(patientId, tableName, recordId, ids);



      setStagedDocuments([]);



      await loadDocuments();



      await onChanged?.();



      setMessage(`${ids.length} document${ids.length === 1 ? "" : "s"} attached to patient ${patientId}.`);



    } catch (error) { setMessage(String(error)); } finally { setBusy(false); }



  }







  async function removeDocument(documentId) {



    if (!window.confirm("Remove this associated document?")) return;



    try {



      setBusy(true);



      setMessage("");



      await api()?.metadata_document_delete?.(documentId);



      await loadDocuments();



      await onChanged?.();



    } catch (error) {



      setMessage(String(error));



    } finally {



      setBusy(false);



    }



  }







  async function viewDocument(document) {



    try {



      setBusy(true);



      setMessage("");



      const result = await api()?.metadata_document_get_preview?.(



        patientId,



        tableName,



        recordId,



        document.document_id



      );



      setPreviewDocument({



        ...result,



        file_name: result?.file_name || document.file_name,



        document_types: result?.document_types ?? document.document_types ?? [],



      });



      setPreviewPageIndex(0);



    } catch (error) {



      setMessage(String(error));



    } finally {



      setBusy(false);



    }



  }







  async function editDocument(document) {



    try {



      setBusy(true);



      setMessage("");



      const result = await api()?.metadata_document_begin_edit?.(



        patientId,



        tableName,



        recordId,



        document.document_id



      );



      if (!result) return;



      setPreviewDocument(null);



      setPreviewPageIndex(0);



      setWorkingDocument(result);



      setPageIndex(0);



      setRedactions({});



      setDrawing(null);



    } catch (error) {



      setMessage(String(error));



    } finally {



      setBusy(false);



    }



  }





  const pages = workingDocument?.pages ?? [];



  const page = pages[pageIndex] ?? null;



  const previewPages = previewDocument?.pages ?? [];



  const previewPage = previewPages[previewPageIndex] ?? null;



  const currentRedactions = redactions[pageKey()] ?? [];



  const drawingBox = useMemo(() => drawing ? normalizeBox(drawing.start, drawing.end) : null, [drawing]);







  return (



    <div className={styles.backdrop}>



      <section className={styles.modal} role="dialog" aria-modal="true" aria-label="Associated documents">



        <header className={styles.header}>



          <div>



            <span>{tableName.toUpperCase()} SUPPORTING DOCUMENTS</span>



            <h2>Associated Documents</h2>



            <p>Record {recordId} · Patient {patientId}</p>



          </div>



          <button className={styles.closeButton} onClick={onClose} aria-label="Close">



            <X size={18} />



          </button>



        </header>







        {previewDocument ? (



          <>



            <div className={styles.previewHeader}>



              <button



                className={styles.previewBackButton}



                onClick={() => {



                  setPreviewDocument(null);



                  setPreviewPageIndex(0);



                }}



                disabled={busy}



              >



                <ArrowLeft size={14} /> Back to Associated Documents



              </button>



              <div>



                <span>ASSOCIATED DOCUMENT REVIEW</span>



                <strong>{previewDocument.file_name}</strong>



                <small>



                  {(previewDocument.document_types ?? []).join(", ") || "Supporting document"}



                </small>



              </div>



            </div>







            <div className={styles.previewToolbar}>



              <div>



                <strong>Sanitized associated document</strong>



                <span>



                  Page {previewPageIndex + 1} of {Math.max(1, previewPages.length)}



                </span>



              </div>



              <div className={styles.previewToolbarActions}>



                <button



                  className={styles.editDocumentButton}



                  onClick={() => editDocument(previewDocument)}



                  disabled={busy}



                >



                  <Pencil size={14} /> Edit Redactions



                </button>



                {previewPages.length > 1 && (



                <div className={styles.pageControls}>



                  <button



                    onClick={() => setPreviewPageIndex(value => Math.max(0, value - 1))}



                    disabled={previewPageIndex === 0}



                  >



                    Previous



                  </button>



                  <button



                    onClick={() =>



                      setPreviewPageIndex(value =>



                        Math.min(previewPages.length - 1, value + 1)



                      )



                    }



                    disabled={previewPageIndex >= previewPages.length - 1}



                  >



                    Next



                  </button>



                </div>



                )}



              </div>



            </div>







            {previewPage ? (



              <div className={styles.documentViewport}>



                <div className={styles.previewStage}>



                  <img



                    src={previewPage.image_data_url}



                    alt={`${previewDocument.file_name}, page ${previewPageIndex + 1}`}



                    draggable="false"



                  />



                </div>



              </div>



            ) : (



              <div className={styles.empty}>



                No preview pages were returned for this document.



              </div>



            )}







            <footer className={styles.footer}>



              <span>{previewDocument.file_name}</span>



              <button



                className={styles.primary}



                onClick={() => {



                  setPreviewDocument(null);



                  setPreviewPageIndex(0);



                }}



              >



                Back to Documents



              </button>



            </footer>



          </>



        ) : workingDocument ? (



          <>



            <div className={styles.reviewNotice}>



              <FileText size={18} />



              <div>



                <strong>{workingDocument.edit_existing ? "Edit document redactions" : "Review and redact before attaching"}</strong>



                <span>

                  {workingDocument.edit_existing

                    ? "Draw additional boxes over identifying information. Existing redactions remain permanently applied."

                    : "Draw boxes over identifying information. Redactions are permanently applied when the sanitized document is saved."}

                </span>



              </div>



            </div>







            <div className={styles.redactorToolbar}>



              <button
              onClick={() => {
                if (workingDocument.edit_existing && editOnly) {
                  onClose?.();
                  return;
                }
                setWorkingDocument(null);
              }}
              disabled={busy}
            >



                <ArrowLeft size={14} /> Back



              </button>



              <div className={styles.pageControls}>



                <button onClick={() => setPageIndex(value => Math.max(0, value - 1))} disabled={pageIndex === 0}>Previous</button>



                <span>Page {pageIndex + 1} of {Math.max(1, pages.length)}</span>



                <button onClick={() => setPageIndex(value => Math.min(pages.length - 1, value + 1))} disabled={pageIndex >= pages.length - 1}>Next</button>



              </div>



              <div className={styles.redactionActions}>



                <button onClick={undoLast} disabled={!currentRedactions.length}><RotateCcw size={14} /> Undo</button>



                <button onClick={clearPage} disabled={!currentRedactions.length}>Clear Page</button>



              </div>



            </div>







            {page ? (



              <div className={styles.documentViewport}>



                <div



                  ref={stageRef}



                  className={styles.redactionStage}



                  onPointerDown={beginRedaction}



                  onPointerMove={updateRedaction}



                  onPointerUp={finishRedaction}



                  onPointerCancel={() => setDrawing(null)}



                >



                  <img src={page.image_data_url} alt={`Document page ${pageIndex + 1}`} draggable="false" />



                  {currentRedactions.map((box, index) => <RedactionBox key={index} box={box} />)}



                  {drawingBox && <RedactionBox box={drawingBox} preview />}



                </div>



              </div>



            ) : (



              <div className={styles.empty}>No preview pages were returned for this document.</div>



            )}







            <footer className={styles.footer}>



              <span>{workingDocument.file_name}</span>



              <button className={styles.primary} onClick={saveRedactedDocument} disabled={busy || !page}>



                <Check size={15} /> {workingDocument.edit_existing ? "Save Updated Document" : "Save Sanitized Document"}



              </button>



            </footer>



          </>



        ) : (



          <>



            <div className={styles.uploadPanel}>



              <div className={styles.uploadIcon}><Paperclip size={24} /></div>



              <div className={styles.uploadCopy}>



                <strong>Add an associated document</strong>



                <p>Select one or more document types, then choose the local file. The file remains local until redaction review is complete.</p>



                <div className={styles.typePicker} aria-label="Associated document types">



                  {(DOCUMENT_TYPES[tableName] ?? DOCUMENT_TYPES.Clinical).map(type => {



                    const selected = documentTypes.includes(type);



                    return (



                      <label className={styles.typeCheckbox} key={type}>



                        <input type="checkbox" checked={selected} onChange={() => setDocumentTypes(current => selected ? current.filter(value => value !== type) : [...current, type])} disabled={busy} />



                        <span>{type}</span>



                      </label>



                    );



                  })}



                </div>



                {documentTypes.includes("Other") && (



                  <label className={styles.otherTypeField}>



                    <span>Other document type</span>



                    <input type="text" value={otherDocumentType} onChange={event => setOtherDocumentType(event.target.value)} placeholder="Enter document type" disabled={busy} />



                  </label>



                )}



              </div>



              <button



                className={styles.primary}



                onClick={chooseDocument}



                disabled={busy || !documentTypes.length || (documentTypes.includes("Other") && !otherDocumentType.trim())}



              >



                <Upload size={15} /> Add Associated Document



              </button>



            </div>







            {stagedDocuments.length > 0 && (



              <div className={styles.stagedPanel}>



                <div className={styles.stagedHeader}><div><strong>Ready to attach</strong><span>Redaction review is complete. Confirm the association before these documents become part of the patient record.</span></div><span>{stagedDocuments.length} ready</span></div>



                <div className={styles.stagedList}>{stagedDocuments.map(document => (<div className={styles.stagedDocument} key={document.document_id}><FileText size={16} /><div><strong>{document.file_name}</strong><span>{(document.document_types ?? []).join(", ")}</span></div></div>))}</div>



                <button className={styles.attachConfirmButton} onClick={attachDocumentsToPatient} disabled={busy}><Check size={16} />Attach {stagedDocuments.length === 1 ? "Document" : "Documents"} to Patient {patientId}</button>



                <p className={styles.attachConfirmationText}>This associates the sanitized document{stagedDocuments.length === 1 ? "" : "s"} with {tableName} record {recordId}.</p>



              </div>



            )}







            <div className={styles.documentList}>



              <div className={styles.listHeader}>



                <strong>Attached documents</strong>



                <span>{documents.length} {documents.length === 1 ? "document" : "documents"}</span>



              </div>



              {!documents.length ? (



                <div className={styles.empty}>No associated documents have been attached to this record.</div>



              ) : documents.map(document => (



                <div className={styles.documentRow} key={document.document_id}>



                  <FileText size={18} />



                  <div>



                    <strong>{document.file_name}</strong>



                    <span>



                      {(document.document_types ?? []).length



                        ? `${document.document_types.join(", ")} · `



                        : ""}



                      {document.status || "Redaction reviewed"}



                    </span>



                  </div>                  <div className={styles.documentRowActions}>

                    <button

                      className={styles.viewButton}

                      onClick={() => viewDocument(document)}

                      disabled={busy}

                    >

                      <Eye size={14} /> View Document

                    </button>

                    <button

                      className={styles.deleteButton}

                      onClick={() => removeDocument(document.document_id)}

                      disabled={busy}

                    >

                      <Trash2 size={14} /> Remove

                    </button>

                  </div>



                </div>



              ))}



            </div>



          </>



        )}







        {message && <div className={styles.message}>{message}</div>}



      </section>



    </div>



  );



}







function normalizeBox(start, end) {



  return {



    x: Math.min(start.x, end.x),



    y: Math.min(start.y, end.y),



    width: Math.abs(end.x - start.x),



    height: Math.abs(end.y - start.y),



  };



}







function RedactionBox({ box, preview = false }) {



  return (



    <div



      className={`${styles.redactionBox} ${preview ? styles.redactionPreview : ""}`}



      style={{



        left: `${box.x * 100}%`,



        top: `${box.y * 100}%`,



        width: `${box.width * 100}%`,



        height: `${box.height * 100}%`,



      }}



    />



  );



}
