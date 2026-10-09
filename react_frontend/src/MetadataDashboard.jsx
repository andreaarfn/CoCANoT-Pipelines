import { useEffect, useMemo, useRef, useState } from "react";



import {



  Activity,



  ArrowLeft,



  Brain,



  CalendarDays,



  FileText,



  Paperclip,



  Image as ImageIcon,



  Pencil,



  Plus,



  RefreshCw,



  Scissors,



  Search,



  Trash2,



  Upload,



  Users,



} from "lucide-react";



import DictionaryForm, { validateRecordAgainstRules } from "./DictionaryForm";



import PatientDataReview from "./PatientDataReview";



import DocumentAttachmentRedactor from "./DocumentAttachmentRedactor";



import BatchImportWorkflow from "./BatchImportWorkflow";



import styles from "./MetadataDashboard.module.css";



const api = () => window.pywebview?.api ?? null;



const SECTION_CONFIG = {



  Clinical: {



    title: "Clinical Metadata",



    icon: FileText,



    addLabel: "Add Clinical Assessment",



    uploadLabel: "Upload Clinical Assessments",



  },



  Surgical: {



    title: "Surgical Metadata",



    icon: Scissors,



    addLabel: "Add Surgical Record",



    uploadLabel: "Upload Surgical Record",



  },



  Imaging: {



    title: "Imaging Data",



    icon: ImageIcon,



    addLabel: "Add Imaging Data",



  },



  Electrophysiology: {



    title: "Electrophysiology Data",



    icon: Activity,



    addLabel: "Add Electrophysiology Recording",



  },



};



export default function MetadataDashboard({



  initialView = "home",



  patientReviewMode = false,



  preferredPatientId = "",



  autoOpenClinical = false,



  returnPage = "",



  returnContext = {},



  attentionItems = [],



  onDataChanged,



  onNavigate,



}) {



  const [view, setView] = useState(



    initialView === "patient_explorer"



      ? "patients"



      : initialView === "bulk"



        ? "bulk"



        : "home"



  );



  const [patients, setPatients] = useState([]);



  const [patientId, setPatientId] = useState("");



  const [loadedPatientId, setLoadedPatientId] = useState("");



  const [summary, setSummary] = useState(null);



  const [editor, setEditor] = useState(null);

  const [pendingAddAfterClinical, setPendingAddAfterClinical] = useState(null);



  const [rules, setRules] = useState([]);



  const [draft, setDraft] = useState({});



  const [realSurgeryDate, setRealSurgeryDate] = useState("");



  const [message, setMessage] = useState("");



  const [deleteRequest, setDeleteRequest] = useState(null);



  const [editorError, setEditorError] = useState("");



  const [fieldErrors, setFieldErrors] = useState({});



  const [dataReview, setDataReview] = useState(null);



  const [batchImport, setBatchImport] = useState(null);



  const [documentManager, setDocumentManager] = useState(null);



  const autoOpenClinicalRef = useRef(false);



  const [selected, setSelected] = useState({



    Clinical: [],



    Surgical: [],



    Imaging: [],



    Electrophysiology: [],



  });



  useEffect(() => {



    if (view !== "patients") {



      return;



    }



    async function initializePatients() {



      await loadPatients();



      const preferred = String(



        preferredPatientId ?? ""



      ).trim();



      if (preferred) {



        await loadPatient(preferred);



        if (



          autoOpenClinical &&



          !autoOpenClinicalRef.current



        ) {



          autoOpenClinicalRef.current = true;



          await openEditor("Clinical", null, preferred);



        }



      }



    }



    initializePatients();



  }, [view, preferredPatientId, autoOpenClinical]);



  async function currentSiteId() {



    return (await api()?.get_site_id?.()) ?? "";



  }



  async function loadPatients() {



    const siteId = await currentSiteId();



    const rows = await api()?.metadata_get_patients?.(siteId);



    const ids = (rows ?? []).map(row => row.patient_id);



    setPatients(ids);



    if (



      loadedPatientId &&



      !ids.includes(loadedPatientId)



    ) {



      setPatientId("");



      setLoadedPatientId("");



      setSummary(null);



      clearSelections();



    }



  }



  async function loadPatient(id) {



    const clean = String(id ?? "").trim();



    setPatientId(clean);



    if (!clean) {



      setLoadedPatientId("");



      setSummary(null);



      clearSelections();



      return;



    }



    const siteId = await currentSiteId();



    const result = await api()?.metadata_get_patient?.(



      siteId,



      clean



    );



    setLoadedPatientId(clean);



    setSummary(result);



    clearSelections();



  }



  function clearSelections() {



    setSelected({



      Clinical: [],



      Surgical: [],



      Imaging: [],



      Electrophysiology: [],



    });



  }



  async function addPatient() {



    const id = window.prompt(



      "Enter the new CoCANoT Patient ID."



    );



    if (!id) return;



    const clean = id.trim();



    const siteId = await currentSiteId();



    await api()?.metadata_create_patient?.(



      siteId,



      clean



    );



    await loadPatients();



    await loadPatient(clean);



    await onDataChanged?.();



  }



  async function openEditor(



    tableName,



    record = null,



    patientIdOverride = ""



  ) {



    const effectivePatientId = String(



      patientIdOverride || loadedPatientId || ""



    ).trim();



    let patientSnapshot = summary;



    if (

      effectivePatientId &&

      (!patientSnapshot ||

        String(loadedPatientId || "").trim() !== effectivePatientId)

    ) {

      const siteId = await currentSiteId();



      patientSnapshot =

        await api()?.metadata_get_patient?.(

          siteId,

          effectivePatientId

        );

    }



    const currentClinicalId = String(



      patientSnapshot?.clinical?.[0]?.record_id ?? ""



    ).trim();



    const selectedRecordId = String(



      record?.record_id ?? ""



    );



    const historicalClinical =



      tableName === "Clinical" &&



      Boolean(record) &&



      Boolean(selectedRecordId) &&



      selectedRecordId !== currentClinicalId;



    const dictionaryVersion =



      historicalClinical



        ? String(record?.dictionary_version ?? "")



        : "";



    const nextRules =



      await api()?.metadata_get_rules?.(



        tableName,



        dictionaryVersion



      );



    const activeRules = nextRules ?? [];



    const values = {



      ...(record?.metadata ?? {}),



    };



    if (



      effectivePatientId &&



      !values["CoCANoT Patient ID"]



    ) {



      values["CoCANoT Patient ID"] =



        effectivePatientId;



    }



    if (

      tableName === "Surgical" &&

      currentClinicalId &&

      !values["Clinical Assessment ID"]

    ) {

      values["Clinical Assessment ID"] =

        currentClinicalId;

    }



    setRules(activeRules);



    setDraft(values);



    setRealSurgeryDate("");



    setFieldErrors({});



    setEditor({



      tableName,



      record,



      context: record?.context ?? {},



      historicalClinical,



      dictionaryVersion,



      patientId: effectivePatientId,



    });



    setEditorError("");



    setMessage("");



    let localDate = "";



    if (tableName === "Surgical" && record) {



      try {



        const siteId = await currentSiteId();



        const surgeryId =



          values["Surgery ID"] ||



          record?.record_id ||



          "";



        if (surgeryId) {



          const tracking =



            await api()?.metadata_get_real_surgery_date?.(



              siteId,



              effectivePatientId,



              surgeryId



            );



          localDate =



            typeof tracking === "string"



              ? tracking



              : tracking?.real_surgery_date ?? "";



        }



      } catch (error) {



        setEditorError(String(error));



      }



    }



    setRealSurgeryDate(localDate);



    if (record) {



      setFieldErrors(



        validateRecordAgainstRules(



          activeRules,



          values,



          {



            actual_surgery_date: localDate,



          }



        )



      );



    }



  }



  function normalizeFieldName(value) {



    return String(value ?? "")



      .replace(/<br\s*\/?>/gi, " ")



      .replace(/\s+/g, " ")



      .trim()



      .toLowerCase();



  }



  function parseValidationErrors(errorText) {



    const nextFieldErrors = {};



    const generalErrors = [];



    const activeRules = new Map(



      (rules ?? []).map(rule => [



        normalizeFieldName(rule.field_name),



        rule.field_name,



      ])



    );



    String(errorText ?? "")



      .split(/\r?\n/)



      .map(line => line.trim())



      .filter(Boolean)



      .forEach(line => {



        const separator = line.indexOf(":");



        if (separator <= 0) {



          generalErrors.push(line);



          return;



        }



        const rawField = line.slice(0, separator).trim();



        const message = line.slice(separator + 1).trim();



        const canonicalField =



          activeRules.get(normalizeFieldName(rawField));



        if (canonicalField) {



          nextFieldErrors[canonicalField] = message;



        } else {



          generalErrors.push(line);



        }



      });



    return {



      fieldErrors: nextFieldErrors,



      generalErrors,



    };



  }



  async function saveEditor() {



    const targetPatientId = String(



      editor?.patientId || loadedPatientId || ""



    ).trim();



    const savedTableName = editor?.tableName ?? "";



    try {



      setEditorError("");



      setFieldErrors({});



      if (

        editor.tableName === "Surgical" &&

        !String(

          draft["Clinical Assessment ID"] ?? ""

        ).trim()

      ) {

        const siteId = await currentSiteId();



        const patientSnapshot =

          await api()?.metadata_get_patient?.(

            siteId,

            targetPatientId

          );



        const latestClinicalId = String(

          patientSnapshot?.clinical?.[0]?.record_id ?? ""

        ).trim();



        if (!latestClinicalId) {

          setPendingAddAfterClinical({

            tableName: "Surgical",

            patientId: targetPatientId,

            draft: structuredClone(draft),

            realSurgeryDate: String(

              realSurgeryDate ?? ""

            ),

          });



          setMessage(

            "Add the patient's first Clinical Assessment before saving the Surgical record."

          );



          await openEditor(

            "Clinical",

            null,

            targetPatientId

          );

          return;

        }



        setDraft(current => ({

          ...current,

          "Clinical Assessment ID":

            latestClinicalId,

        }));



        draft["Clinical Assessment ID"] =

          latestClinicalId;

      }



      if (



        editor.tableName === "Surgical" &&



        !String(realSurgeryDate ?? "").trim()



      ) {



        setEditorError(



          "Enter the actual surgery date to enable local follow-up tracking. This date stays on this computer and is never included in consortium metadata."



        );



        return;



      }



      if (editor.tableName === "Clinical") {



        await api()?.metadata_save_clinical?.(



          targetPatientId,



          draft,



          editor.record?.record_id ?? ""



        );



      } else {



        await api()?.metadata_save_record?.(



          editor.tableName,



          draft,



          editor.context ?? {},



          editor.tableName === "Surgical"



            ? {



                actual_surgery_date:



                  realSurgeryDate,



              }



            : {}



        );



        if (editor.tableName === "Surgical") {



          const siteId = await currentSiteId();



          const surgeryId = String(



            draft["Surgery ID"] ?? ""



          ).trim();



          if (surgeryId) {



            const requestedDate = String(



              realSurgeryDate ?? ""



            ).trim();



            const savedTracking =



              await api()?.metadata_save_real_surgery_date?.(



                siteId,



                loadedPatientId,



                surgeryId,



                requestedDate



              );



            const savedDate =



              typeof savedTracking === "string"



                ? savedTracking



                : savedTracking?.real_surgery_date ?? "";



            if (savedDate !== requestedDate) {



              throw new Error(



                `Actual Surgery Date was not saved correctly. Expected ${requestedDate}, received ${savedDate || "blank"}.`



              );



            }



            setRealSurgeryDate(savedDate);



          }



        }



      }



      setEditor(null);



      setMessage(



        `${editor.tableName} metadata saved.`



      );



      await loadPatient(targetPatientId);



      await onDataChanged?.();



      if (

        savedTableName === "Clinical" &&

        pendingAddAfterClinical?.tableName === "Surgical"

      ) {

        const pending = pendingAddAfterClinical;



        setPendingAddAfterClinical(null);



        await loadPatient(targetPatientId);



        await openEditor(

          "Surgical",

          null,

          targetPatientId

        );



        if (pending?.draft) {

          const siteId = await currentSiteId();



          const patientSnapshot =

            await api()?.metadata_get_patient?.(

              siteId,

              targetPatientId

            );



          const latestClinicalId = String(

            patientSnapshot?.clinical?.[0]?.record_id ?? ""

          ).trim();



          setDraft(current => ({

            ...current,

            ...pending.draft,

            "CoCANoT Patient ID":

              targetPatientId,

            "Clinical Assessment ID":

              latestClinicalId,

          }));



          setRealSurgeryDate(

            pending.realSurgeryDate ?? ""

          );

        }



        setMessage(

          "Clinical Assessment saved. Continue the Surgical record."

        );

        return;

      }



      if (



        savedTableName === "Clinical" &&



        returnPage



      ) {



        onNavigate(returnPage, returnContext);



        return;



      }



    } catch (error) {



      const text = (



        error?.message ||



        String(error) ||



        "Unable to save metadata."



      ).replace(/^Error:\s\*/i, "");



      const parsed = parseValidationErrors(text);



      setFieldErrors(parsed.fieldErrors);



      setEditorError(parsed.generalErrors.join("\n"));



    }



  }



  async function importRecords(tableName) {



    try {



      const result =



        await api()?.metadata_import_records?.(



          tableName



        );



      if (!result) return;



      const details =



        result.failed > 0



          ? ` ${result.failed} row(s) failed.`



          : "";



      setMessage(



        `Imported ${result.imported ?? 0} ${tableName} record(s).${details}`



      );



      await loadPatient(loadedPatientId);



      await onDataChanged?.();



    } catch (error) {



      setMessage(String(error));



    }



  }



  function toggleSelected(tableName, recordId) {



    setSelected(current => {



      const values = current[tableName] ?? [];



      return {



        ...current,



        [tableName]: values.includes(recordId)



          ? values.filter(id => id !== recordId)



          : [...values, recordId],



      };



    });



  }



  function selectedRows(tableName) {



    const ids = selected[tableName] ?? [];



    return recordsFor(tableName).filter(



      row => ids.includes(row.record_id)



    );



  }



  function recordsFor(tableName) {



    if (!summary) return [];



    if (tableName === "Clinical") {



      return summary.clinical ?? [];



    }



    if (tableName === "Surgical") {



      return summary.surgical ?? [];



    }



    if (tableName === "Imaging") {



      return summary.imaging ?? [];



    }



    return summary.electrophysiology ?? [];



  }



  async function reviewSelected(tableName) {



    const rows = selectedRows(tableName);



    if (rows.length !== 1) {



      setMessage(



        `Select exactly one ${tableName} record to review or edit.`



      );



      return;



    }



    if (



      tableName === "Imaging" ||



      tableName === "Electrophysiology" ||



      (patientReviewMode &&



        (tableName === "Clinical" || tableName === "Surgical"))



    ) {



      setDataReview({



        tableName,



        record: rows[0],



      });



      setMessage("");



      return;



    }



    try {



      await openEditor(



        tableName,



        rows[0]



      );



    } catch (error) {



      setMessage(



        String(error)



      );



    }



  }



  function deleteSelected(tableName) {



    const ids = selected[tableName] ?? [];



    if (!ids.length) {



      setMessage(`Select one or more ${tableName} records first.`);



      return;



    }



    setDeleteRequest({



      tableName,



      ids: [...ids],



    });



    setMessage("");



  }



  async function confirmDelete(deleteProcessedFiles) {



    if (!deleteRequest) return;



    const { tableName, ids } = deleteRequest;



    setDeleteRequest(null);



    try {



      const result = await api()?.metadata_delete_records?.(



        tableName,



        loadedPatientId,



        ids,



        Boolean(deleteProcessedFiles)



      );



      const deleted = result?.deleted ?? [];



      const blocked = result?.blocked ?? [];



      const fileCleanup = result?.file_cleanup ?? {};



      let nextMessage =



        deleted.length > 0



          ? `Deleted ${deleted.length} ${tableName} record(s).`



          : `No ${tableName} records were deleted.`;



      if (deleteProcessedFiles && Number(fileCleanup.deleted_count ?? 0) > 0) {



        nextMessage += ` Deleted ${fileCleanup.deleted_count} linked processed file(s).`;



      }



      if (deleteProcessedFiles && Number(fileCleanup.skipped_shared_count ?? 0) > 0) {



        nextMessage += ` Kept ${fileCleanup.skipped_shared_count} shared file(s) that are still linked to other records.`;



      }



      if (blocked.length) {



        nextMessage +=



          " " +



          blocked



            .map(item => `${item.record_id}: ${item.reason}`)



            .join(" | ");



      }



      setMessage(nextMessage);



      await loadPatient(loadedPatientId);



      await onDataChanged?.();



    } catch (error) {



      setMessage(String(error));



    }



  }



  async function addFor(tableName) {



    if (tableName === "Imaging") {

      onNavigate("imaging-processing");

      return;

    }



    if (tableName === "Electrophysiology") {

      onNavigate("ephys-processing");

      return;

    }



    await openEditor(tableName);



  }





  if (batchImport) {



    return (



      <BatchImportWorkflow



        tableName={batchImport}



        onBack={() => setBatchImport(null)}



        onFinished={result => {



          setMessage(



            `Imported ${result.imported ?? 0} ${batchImport} record(s).`



          );



        }}



      />



    );



  }



  if (dataReview) {



    return (



      <PatientDataReview



        patientId={loadedPatientId}



        tableName={dataReview.tableName}



        record={dataReview.record}



        onBack={() => setDataReview(null)}



        onEdit={async () => {



          const current = dataReview;



          setDataReview(null);



          await openEditor(



            current.tableName,



            current.record



          );



        }}



      />



    );



  }



  if (view === "home") {



    return (



      <div>



        <PageHeading



          eyebrow="METADATA MANAGEMENT"



          title="Manage CoCANoT metadata"



          text="Review one patient at a time or import Clinical and Surgical metadata in batches using the active machine-readable dictionary."



        />



        <div className={styles.homeCards}>



          <button onClick={() => onNavigate("metadata-patients")}>



            <Users size={29} />



            <strong>Manage one patient</strong>



            <span>



              Review Clinical, Surgical, Imaging,



              and Electrophysiology records.



            </span>



          </button>



          <button onClick={() => onNavigate("metadata-bulk")}>



            <Upload size={29} />



            <strong>Bulk upload</strong>



            <span>



              Import Clinical or Surgical metadata,



              or open the Imaging and



              Electrophysiology workflows.



            </span>



          </button>



        </div>



      </div>



    );



  }



  if (view === "bulk") {



    return (



      <div>



        <div className={styles.breadcrumb}>
        <button
          onClick={() => onNavigate("metadata-home")}
        >
          <ArrowLeft size={14} />
          Metadata Management
        </button>
      </div>

      <PageHeading



          eyebrow="BULK UPLOAD"



          title="Bulk metadata workflows"



          text="Clinical and Surgical files are imported into the local CoCANoT database. Imaging and Electrophysiology use their dedicated de-identification workflows."



        />



        <div className={styles.bulkGrid}>



          <ActionCard



            icon={FileText}



            title="Clinical metadata"



            text="Choose a file, review rows, validate metadata, and then import Clinical Assessments."



            onClick={() => setBatchImport("Clinical")}



          />



          <ActionCard



            icon={Scissors}



            title="Surgical metadata"



            text="Choose a file, review rows, validate metadata, and then import Surgical records."



            onClick={() => setBatchImport("Surgical")}



          />



          <ActionCard



            icon={Brain}



            title="Imaging"



            text="Open the Imaging processing workflow."



            onClick={() =>
            onNavigate("imaging-processing", {
              returnPage: "metadata-bulk",
            })
          }



          />



          <ActionCard



            icon={Activity}



            title="Electrophysiology"



            text="Open the Electrophysiology processing workflow."



            onClick={() =>
            onNavigate("ephys-processing", {
              returnPage: "metadata-bulk",
            })
          }



          />



        </div>



        {message && (



          <div className={styles.message}>



            {message}



          </div>



        )}



      </div>



    );



  }



  const patientAttentionItems = (attentionItems ?? []).filter(



    item =>



      String(item?.patient_id ?? "") ===



      String(loadedPatientId ?? "")



  );



  return (



    <div>



      {!patientReviewMode && (



        <div className={styles.breadcrumb}>



          <button



            onClick={() => onNavigate("metadata-home")}



          >



            <ArrowLeft size={14} />



            Metadata Management



          </button>



          <span>›</span>



          <strong>Manage One Patient</strong>



        </div>



      )}



      {patientReviewMode && (



        <div className={styles.breadcrumb}>



          <button



            onClick={() => onNavigate("home")}



          >



            <ArrowLeft size={14} />



            Home



          </button>



          <span>›</span>



          <strong>Patient Data Review</strong>



        </div>



      )}



      <PageHeading



        title={



          patientReviewMode



            ? "Patient Data Review"



            : "Manage One Patient"



        }



        text={



          patientReviewMode



            ? "Review stored clinical, surgical, imaging, and electrophysiology data for a patient."



            : "Review or update metadata for one patient."



        }



      />



      <section className={styles.patientLookup}>



        <label>



          <span>CoCANoT Patient ID</span>



          <div className={styles.patientSelect}>



            <Search size={17} />



            <select



              value={patientId}



              onChange={event =>



                loadPatient(event.target.value)



              }



            >



              <option value="">



                Select a patient…



              </option>



              {patients.map(id => (



                <option key={id} value={id}>



                  {id}



                </option>



              ))}



            </select>



          </div>



        </label>



        <button



          className={styles.outlinePrimary}



          onClick={addPatient}



        >



          <Plus size={17} />



          Add New Patient



        </button>



        <button



          className={styles.iconButton}



          title="Refresh patient list"



          onClick={loadPatients}



        >



          <RefreshCw size={17} />



        </button>



      </section>



      {summary ? (



        <div className={styles.recordSections}>



          {[



            "Clinical",



            "Surgical",



            "Imaging",



            "Electrophysiology",



          ].map(tableName => (



            <PatientRecordSection



              key={tableName}



              tableName={tableName}



              rows={recordsFor(tableName)}



              selected={



                selected[tableName] ?? []



              }



              onToggle={recordId =>



                toggleSelected(



                  tableName,



                  recordId



                )



              }



              onAdd={() => addFor(tableName)}



              onUpload={



                tableName === "Clinical" ||



                tableName === "Surgical"



                  ? () =>



                      importRecords(tableName)



                  : null



              }



              onDelete={() =>



                deleteSelected(tableName)



              }



              onDocuments={



                tableName === "Clinical" ||



                tableName === "Surgical"



                  ? () => {



                      const rows = selectedRows(tableName);



                      if (rows.length !== 1) {



                        setMessage(`Select exactly one ${tableName} record to manage associated documents.`);



                        return;



                      }



                      setDocumentManager({ tableName, record: rows[0] });



                      setMessage("");



                    }



                  : null



              }



              onReview={() =>



                reviewSelected(tableName)



              }



              reviewLabel={



                tableName === "Imaging" ||



                tableName === "Electrophysiology"



                  ? "Review Patient Data"



                  : patientReviewMode



                    ? "Review Selected"



                    : "Review / Edit Selected"



              }



              reviewOnly={patientReviewMode}



              attentionItems={patientAttentionItems}



            />



          ))}



        </div>



      ) : (



        <div className={styles.emptyState}>



          Select a patient to review their stored data.



        </div>



      )}



      {message && (



        <div className={styles.message}>



          {message}



        </div>



      )}



      {documentManager && (



        <DocumentAttachmentRedactor



          patientId={loadedPatientId}



          tableName={documentManager.tableName}



          recordId={documentManager.record.record_id}



          onClose={() => setDocumentManager(null)}



          onChanged={async () => {



            await loadPatient(loadedPatientId);



            await onDataChanged?.();



          }}



        />



      )}



      {deleteRequest && (



        <div className={styles.modalBackdrop}>



          <div className={styles.modal}>



            <div className={styles.modalHeader}>



              <div>



                <span>DELETE RECORD</span>



                <h2>Delete selected {deleteRequest.tableName} record{deleteRequest.ids.length === 1 ? "" : "s"}?</h2>



              </div>



              <button onClick={() => setDeleteRequest(null)}>



                Cancel



              </button>



            </div>



            <div className={styles.localOnlyCard}>



              <div className={styles.localOnlyHeading}>



                <div>



                  <strong>Delete record only</strong>



                </div>



              </div>



              <p>



                {(deleteRequest.tableName === "Imaging" ||



                  deleteRequest.tableName === "Electrophysiology")



                  ? `Removes ${deleteRequest.ids.length === 1 ? "this record" : "these records"} from CoCANoT. Processed files will remain in the derivatives folder and final output folder selected when ${deleteRequest.ids.length === 1 ? "this record was" : "these records were"} processed.`



                  : `Removes ${deleteRequest.ids.length === 1 ? "this record" : "these records"} from CoCANoT.`}



              </p>



            </div>



            {(deleteRequest.tableName === "Imaging" ||



              deleteRequest.tableName === "Electrophysiology") && (



              <div className={styles.localOnlyCard}>



                <div className={styles.localOnlyHeading}>



                  <div>



                    <strong>Delete record and processed files</strong>



                  </div>



                </div>



                <p>



                  Removes {deleteRequest.ids.length === 1 ? "this record" : "these records"} from CoCANoT and deletes the linked processed files from the derivatives folder and final output folder used during processing. Raw source files are not deleted.



                </p>



              </div>



            )}



            <div className={styles.modalActions}>



              <button onClick={() => setDeleteRequest(null)}>



                Cancel



              </button>



              <button onClick={() => confirmDelete(false)}>



                Delete Record Only



              </button>



              {(deleteRequest.tableName === "Imaging" ||



                deleteRequest.tableName === "Electrophysiology") && (



                <button onClick={() => confirmDelete(true)}>



                  Delete Record + Processed Files



                </button>



              )}



            </div>



          </div>



        </div>



      )}



      {editor && (



        <div className={styles.modalBackdrop}>



          <div className={styles.modal}>



            <div className={styles.modalHeader}>



              <div>



                <span>



                  {editor.tableName.toUpperCase()}



                </span>



                <h2>



                  {editor.record



                    ? "Review / Edit Metadata"



                    : `Add ${editor.tableName} Metadata`}



                </h2>



              </div>



              <button



                onClick={() => {



                  setEditorError("");



                  setFieldErrors({});



                  setEditor(null);



                }}



              >



                Close



              </button>



            </div>



            {editor.tableName === "Surgical" && (



              <section className={styles.localOnlyCard}>



                <div className={styles.localOnlyHeading}>



                  <CalendarDays size={18} />



                  <div>



                    <strong>Actual Surgery Date</strong>



                    <span>LOCAL ONLY — NEVER UPLOADED</span>



                  </div>



                </div>



                <p>



                  Used only on this computer to calculate 12-, 24-, 36-,



                  48-, and 60-month follow-up reminders. This value is



                  stored separately from Surgical metadata.



                </p>



                <label>



                  <span>Actual surgery date \*</span>



                  <input



                    type="date"



                    value={realSurgeryDate || ""}



                    onChange={event =>



                      setRealSurgeryDate(



                        event.target.value || ""



                      )



                    }



                    autoComplete="off"



                  />



                </label>



              </section>



            )}



            <DictionaryForm



              rules={rules}



              values={draft}



              context={{



                actual_surgery_date:



                  editor.tableName === "Surgical"



                    ? realSurgeryDate



                    : "",



              }}



              errors={fieldErrors}



              initiallyValidate={Boolean(editor.record)}



              onFieldValid={field =>



                setFieldErrors(current => {



                  if (!current[field]) return current;



                  const next = { ...current };



                  delete next[field];



                  return next;



                })



              }



              onChange={(field, value) =>



                setDraft(current => ({



                  ...current,



                  [field]: value,



                }))



              }



            />



            {editorError && (



              <div



                className={styles.editorError}



                role="alert"



                aria-live="assertive"



              >



                <strong>Unable to save metadata</strong>



                <pre>{editorError}</pre>



              </div>



            )}



            <div className={styles.modalActions}>



              <button



                onClick={() => {



                  setEditorError("");



                  setFieldErrors({});



                  setEditor(null);



                }}



              >



                Cancel



              </button>



              <button



                className={styles.primary}



                onClick={saveEditor}



              >



                Save Metadata



              </button>



            </div>



          </div>



        </div>



      )}



    </div>



  );



}



function PageHeading({ eyebrow, title, text }) {



  return (



    <header className={styles.heading}>



      {eyebrow && <span>{eyebrow}</span>}



      <h1>{title}</h1>



      <p>{text}</p>



    </header>



  );



}



function ActionCard({



  icon: Icon,



  title,



  text,



  onClick,



}) {



  return (



    <button



      className={styles.actionCard}



      onClick={onClick}



    >



      <Icon size={28} />



      <strong>{title}</strong>



      <span>{text}</span>



    </button>



  );



}



function PatientRecordSection({



  tableName,



  rows,



  selected,



  onToggle,



  onAdd,



  onUpload,



  onDelete,



  onDocuments,



  onReview,



  reviewLabel,



  reviewOnly = false,



  attentionItems = [],



}) {



  const config = SECTION_CONFIG[tableName];



  const Icon = config.icon;



  function attentionForRecord(row) {



    const rowId = String(row?.record_id ?? "");



    return (attentionItems ?? []).filter(item => {



      const itemRecordId = String(



        item?.record_id ??



        item?.surgery_id ??



        ""



      );



      const sameTable =



        String(item?.table_name ?? "") ===



          tableName ||



        (



          tableName === "Surgical" &&



          (



            item?.category === "followup" ||



            item?.category === "local_surgery_date"



          )



        );



      return sameTable && itemRecordId === rowId;



    });



  }



  return (



    <section className={styles.recordSection}>



      <div className={styles.sectionHeader}>



        <div className={styles.sectionTitle} style={{ flexShrink: 0 }}>



          <Icon size={21} />



          <h2 style={{ whiteSpace: "nowrap" }}>{config.title}</h2>



        </div>



        <div className={styles.sectionActions}>



          {!reviewOnly && (



            <>



              <button



                className={styles.primarySmall}



                style={{ fontSize: "11px", whiteSpace: "nowrap" }}



                onClick={onAdd}



              >



                <Plus size={14} />



                {config.addLabel}



              </button>



              {onUpload && (



                <button



                  className={styles.outlineSmall}



                style={{ fontSize: "11px", whiteSpace: "nowrap" }}



                  onClick={onUpload}



                >



                  <Upload size={14} />



                  {config.uploadLabel}



                </button>



              )}



              <button



                className={styles.dangerSmall}



                style={{ fontSize: "11px", whiteSpace: "nowrap" }}



                disabled={!selected.length}



                onClick={onDelete}



              >



                <Trash2 size={14} />



                Delete Selected



              </button>



              {onDocuments && (



                <button



                  className={styles.outlineSmall}



                style={{ fontSize: "11px", whiteSpace: "nowrap" }}



                  disabled={selected.length !== 1}



                  onClick={onDocuments}



                >



                  <Paperclip size={14} />



                  Associated Documents



                </button>



              )}



            </>



          )}



          <button



            type="button"



            className={styles.outlineSmall}



                style={{ fontSize: "11px", whiteSpace: "nowrap" }}



            disabled={selected.length !== 1}



            onClick={event => {



              event.preventDefault();



              event.stopPropagation();



              onReview();



            }}



          >



            <Pencil size={14} />



            {reviewLabel}



          </button>



        </div>



      </div>



      <div className={styles.tableWrap}>



        <table className={styles.table}>



          <thead>



            <tr>



              <th className={styles.checkColumn}></th>



              <th>Record</th>



              <th>Summary</th>



              <th>Review Status</th>



              <th>Updated</th>



            </tr>



          </thead>



          <tbody>



            {!rows.length ? (



              <tr>



                <td



                  colSpan="5"



                  className={styles.emptyRow}



                >



                  No records found.



                </td>



              </tr>



            ) : (



              rows.map((row, index) => {



                const rowAttention =



                  attentionForRecord(row);



                const issueCount = rowAttention.reduce(



                  (total, item) => {



                    const fieldErrorCount = Object.keys(



                      item?.field_errors ?? {}



                    ).length;



                    return total + (



                      fieldErrorCount > 0



                        ? fieldErrorCount



                        : 1



                    );



                  },



                  0



                );



                const needsReview =



                  issueCount > 0;



                return (



                  <tr



                    key={row.record_id}



                    className={



                      needsReview



                        ? styles.needsReviewRow



                        : ""



                    }



                  >



                    <td>



                      <input



                        type="checkbox"



                        checked={selected.includes(



                          row.record_id



                        )}



                        onChange={() =>



                          onToggle(row.record_id)



                        }



                        onClick={event =>



                          event.stopPropagation()



                        }



                      />



                    </td>



                    <td>{row.record_id}</td>



                    <td>



                      {summarizeRecord(



                        tableName,



                        row,



                        index === 0



                      )}



                    </td>



                    <td>



                      {needsReview ? (



                        <div



                          className={



                            styles.reviewStatusWrap



                          }



                        >



                          <span



                            className={



                              styles.needsReviewBadge



                            }



                          >



                            Needs Review



                          </span>



                          <span



                            className={



                              styles.reviewIssueCount



                            }



                            title={rowAttention



                              .map(item => item.message)



                              .join("\n")}



                          >



                            {issueCount}{" "}



                            {issueCount === 1



                              ? "issue"



                              : "issues"}



                          </span>



                        </div>



                      ) : (



                        <span



                          className={



                            styles.reviewOkBadge



                          }



                        >



                          Up to date



                        </span>



                      )}



                    </td>



                    <td>



                      {formatUpdated(



                        row.updated_at



                      )}



                    </td>



                  </tr>



                );



              })



            )}



          </tbody>



        </table>



      </div>



    </section>



  );



}



function displayValue(value) {



  if (Array.isArray(value)) {



    return value.join(", ");



  }



  return String(value ?? "");



}



function summarizeRecord(



  tableName,



  row,



  currentClinical



) {



  const metadata = row.metadata ?? {};



  if (tableName === "Clinical") {



    const parts = [



      currentClinical ? "Current" : "Previous",



      metadata["Visit Type"],



      metadata["Primary Diagnosis"],



    ].filter(Boolean);



    return parts.join(" | ");



  }



  if (tableName === "Surgical") {



    return [



      metadata["Surgery ID"] &&



        `Surgery ID: ${metadata["Surgery ID"]}`,



      metadata[



        "Intent of Surgery (multiselect)"



      ] &&



        `Intent: ${displayValue(



          metadata[



            "Intent of Surgery (multiselect)"



          ]



        )}`,



      metadata[



        "Type(s) of surgery (multiselect)"



      ] &&



        `Type: ${displayValue(



          metadata[



            "Type(s) of surgery (multiselect)"



          ]



        )}`,



    ]



      .filter(Boolean)



      .join(" | ");



  }



  if (tableName === "Imaging") {



    return [



      metadata["Image ID"] &&



        `Image ID: ${metadata["Image ID"]}`,



      metadata["Imaging Modality"] &&



        `Modality: ${metadata["Imaging Modality"]}`,



      metadata[



        "Purpose of Imaging (multiselect)"



      ] &&



        `Purpose: ${displayValue(



          metadata[



            "Purpose of Imaging (multiselect)"



          ]



        )}`,



    ]



      .filter(Boolean)



      .join(" | ");



  }



  return [



    metadata["Recording ID"] &&



      `Recording ID: ${metadata["Recording ID"]}`,



    metadata["Recording Modality"] &&



      `Modality: ${metadata["Recording Modality"]}`,



    metadata["Purpose of Recording"] &&



      `Purpose: ${displayValue(



        metadata["Purpose of Recording"]



      )}`,



  ]



    .filter(Boolean)



    .join(" | ");



}



function formatUpdated(value) {



  if (!value) return "";



  const date = new Date(value);



  if (Number.isNaN(date.getTime())) {



    return value;



  }



  return date.toLocaleString([], {



    year: "numeric",



    month: "short",



    day: "2-digit",



    hour: "2-digit",



    minute: "2-digit",



  });



}
