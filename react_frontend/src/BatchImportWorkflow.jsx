import { useEffect, useMemo, useState } from "react";

import {

  ArrowLeft,

  ArrowRight,

  CheckCircle2,

  FileSpreadsheet,

  Stethoscope,

  Pencil,

  RefreshCw,

  Upload,

} from "lucide-react";

import DictionaryForm from "./DictionaryForm";

import styles from "./BatchImportWorkflow.module.css";



const api = () => window.pywebview?.api ?? null;



function normalizeText(value) {
  return String(value ?? "")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/[^a-z0-9]+/gi, " ")
    .trim()
    .toLowerCase();
}



function levenshtein(a, b) {

  const left = String(a ?? "");

  const right = String(b ?? "");

  const matrix = Array.from(

    { length: left.length + 1 },

    () => Array(right.length + 1).fill(0)

  );



  for (let i = 0; i <= left.length; i += 1) matrix[i][0] = i;

  for (let j = 0; j <= right.length; j += 1) matrix[0][j] = j;



  for (let i = 1; i <= left.length; i += 1) {

    for (let j = 1; j <= right.length; j += 1) {

      const cost = left[i - 1] === right[j - 1] ? 0 : 1;

      matrix[i][j] = Math.min(

        matrix[i - 1][j] + 1,

        matrix[i][j - 1] + 1,

        matrix[i - 1][j - 1] + cost

      );

    }

  }



  return matrix[left.length][right.length];

}



function similarityScore(source, target) {

  const a = normalizeText(source);

  const b = normalizeText(target);



  if (!a || !b) return 0;

  if (a === b) return 1;

  if (a.includes(b) || b.includes(a)) return 0.92;



  const aTokens = new Set(a.split(" ").filter(Boolean));

  const bTokens = new Set(b.split(" ").filter(Boolean));

  const shared = [...aTokens].filter(token => bTokens.has(token)).length;

  const tokenScore =

    shared / Math.max(aTokens.size, bTokens.size, 1);



  const distance = levenshtein(a, b);

  const editScore =

    1 - distance / Math.max(a.length, b.length, 1);



  return Math.max(tokenScore, editScore);

}



export default function BatchImportWorkflow({

  tableName,

  targetPatientId = "",

  onBack,

  onFinished,

  backLabel = "Back to Bulk Upload",

}) {

  const scopedPatientId = String(targetPatientId || "").trim();
  const normalizedPatientId = value => {
    const text = String(value ?? "").trim();
    return /^[0-9]+$/.test(text) ? String(Number(text)).padStart(3, "0") : text;
  };
  const rowPatientId = row => normalizedPatientId(
    row?.metadata?.["CoCANoT Patient ID"] ?? row?.patient_id ?? ""
  );
  const rowCanImport = row =>
    (row?.problems ?? []).length === 0 &&
    row?.import_allowed !== false &&
    row?.difference_status !== "Duplicate";

  const [step, setStep] = useState(1);

  const [batch, setBatch] = useState(null);

  const [rows, setRows] = useState([]);

  const [rules, setRules] = useState([]);

  const [editingIndex, setEditingIndex] = useState(null);

  const [editingValues, setEditingValues] = useState({});
  const [editingProblemField, setEditingProblemField] = useState("");

  const [validation, setValidation] = useState(null);

  const [result, setResult] = useState(null);

  const [busy, setBusy] = useState(false);

  const [error, setError] = useState("");

  const [columnTargets, setColumnTargets] = useState({});
  const [resolvedUploadedHeaders, setResolvedUploadedHeaders] = useState([]);

  const [clinicalAssistOpen, setClinicalAssistOpen] = useState(false);

  const [clinicalLinkMessage, setClinicalLinkMessage] = useState("");
  const [surgeryDateDrafts, setSurgeryDateDrafts] = useState({});
  const [surgeryDateMessage, setSurgeryDateMessage] = useState("");
  const [existingClinical, setExistingClinical] = useState(null);
  const [existingClinicalValues, setExistingClinicalValues] = useState({});
  const [existingClinicalPatientId, setExistingClinicalPatientId] = useState("");
  const [existingClinicalRecordId, setExistingClinicalRecordId] = useState("");
  const [existingClinicalRules, setExistingClinicalRules] = useState([]);



  const includedCount = useMemo(

    () => rows.filter(row => row.include).length,

    [rows]

  );



  const invalidIncludedCount = useMemo(

    () =>

      rows.filter(

        row =>

          row.include &&

          (row.problems ?? []).length > 0

      ).length,

    [rows]

  );



  const surgicalClinicalPatients = useMemo(() => {

    if (tableName !== "Surgical") return [];



    const byPatient = new Map();



    // Keep the scoped patient's missing Clinical Assessment warning visible
    // even when validation correctly deselects blocked rows.
    rows.filter(row => row.include || (
      scopedPatientId && rowPatientId(row) === normalizedPatientId(scopedPatientId)
    )).forEach(row => {

      const metadata = row?.metadata ?? {};

      const patientId = String(

        metadata["CoCANoT Patient ID"] ??

          row?.patient_id ??

          ""

      ).trim();



      if (!patientId) return;



      const assessmentId = String(

        metadata["Clinical Assessment ID"] ?? ""

      ).trim();



      const current = byPatient.get(patientId) ?? {

        patient_id: patientId,

        assessment_id: "",

      };



      if (assessmentId) {

        current.assessment_id = assessmentId;

      }



      byPatient.set(patientId, current);

    });



    return [...byPatient.values()];

  }, [rows, tableName, scopedPatientId]);



  const missingClinicalPatients = useMemo(

    () =>

      surgicalClinicalPatients.filter(

        item => !item.assessment_id

      ),

    [surgicalClinicalPatients]

  );



  const linkedClinicalCount =

    surgicalClinicalPatients.length -

    missingClinicalPatients.length;



  const missingSurgeryDates = useMemo(() => {
    if (tableName !== "Surgical") return [];

    const unique = new Map();

    rows.filter(row => row.include).forEach(row => {
      const metadata = row?.metadata ?? {};
      const patientId = String(
        metadata["CoCANoT Patient ID"] ??
          row?.patient_id ??
          ""
      ).trim();
      const surgeryId = String(
        metadata["Surgery ID"] ?? ""
      ).trim();

      if (
        patientId &&
        surgeryId &&
        row?.actual_surgery_date_missing
      ) {
        unique.set(
          `${patientId}::${surgeryId}`,
          {
            patient_id: patientId,
            surgery_id: surgeryId,
          }
        );
      }
    });

    return [...unique.values()];
  }, [rows, tableName]);


  const unmatchedHeaders = useMemo(() => {
    const known = new Set(
      (rules ?? []).map(rule => String(rule.field_name ?? "").trim()).filter(Boolean)
    );
    const resolved = new Set(resolvedUploadedHeaders);
    // Use ORIGINAL uploaded headers, never metadata enriched by CoCANoT.
    // In particular, the source Clinical Assessment ID stays visible here
    // even after the backend sets the authoritative assessment link.
    const uploaded = batch?.uploaded_headers ??
      [...new Set(rows.flatMap(row => Object.keys(row?.metadata ?? {})))];
    return uploaded.filter(header => !known.has(header) && !resolved.has(header));
  }, [batch, rules, rows, resolvedUploadedHeaders]);


  function suggestedHeaderTarget(sourceHeader) {

    return (rules ?? [])

      .filter(rule => !rule.system_generated)

      .map(rule => {

        const field = String(rule.field_name ?? "").trim();

        return {

          field,

          score: similarityScore(sourceHeader, field),

        };

      })

      .filter(item => item.field)

      .sort((a, b) => b.score - a.score)[0] ?? {

      field: "",

      score: 0,

    };

  }



  function refreshIncludeFlags(activeRows, previousRows = null) {
    return (activeRows ?? []).map((row, index) => ({
      ...row,
      include: rowCanImport(row) &&
        (!scopedPatientId || rowPatientId(row) === normalizedPatientId(scopedPatientId)) && (
        previousRows
          ? Boolean(previousRows[index]?.include)
          : !scopedPatientId || rowPatientId(row) === normalizedPatientId(scopedPatientId)
      ),
    }));
  }

  function surgeryDateKey(patientId, surgeryId) {
    return `${String(patientId ?? "").trim()}::${String(
      surgeryId ?? ""
    ).trim()}`;
  }

  async function attachActualSurgeryDates(activeRows) {
    if (tableName !== "Surgical") return activeRows;

    const siteId =
      (await api()?.get_site_id?.()) ?? "";

    const identities = new Map();

    (activeRows ?? []).filter(row => row.include).forEach(row => {
      const metadata = row?.metadata ?? {};
      const patientId = String(
        metadata["CoCANoT Patient ID"] ??
          row?.patient_id ??
          ""
      ).trim();
      const surgeryId = String(
        metadata["Surgery ID"] ?? ""
      ).trim();

      if (patientId && surgeryId) {
        identities.set(
          surgeryDateKey(patientId, surgeryId),
          { patientId, surgeryId }
        );
      }
    });

    const datesByKey = {};

    await Promise.all(
      [...identities.values()].map(
        async ({ patientId, surgeryId }) => {
          const key = surgeryDateKey(
            patientId,
            surgeryId
          );

          try {
            const result =
              await api()?.metadata_get_real_surgery_date?.(
                siteId,
                patientId,
                surgeryId
              );

            datesByKey[key] = String(
              result?.real_surgery_date ?? ""
            ).trim();
          } catch {
            datesByKey[key] = "";
          }
        }
      )
    );

    setSurgeryDateDrafts(current => {
      const next = { ...current };

      Object.entries(datesByKey).forEach(
        ([key, value]) => {
          if (!(key in next)) {
            next[key] = value;
          }
        }
      );

      return next;
    });

    return (activeRows ?? []).map(row => {
      const metadata = row?.metadata ?? {};
      const patientId = String(
        metadata["CoCANoT Patient ID"] ??
          row?.patient_id ??
          ""
      ).trim();
      const surgeryId = String(
        metadata["Surgery ID"] ?? ""
      ).trim();
      const key = surgeryDateKey(
        patientId,
        surgeryId
      );
      const date = datesByKey[key] ?? "";

      return {
        ...row,
        actual_surgery_date: date,
        actual_surgery_date_missing:
          Boolean(patientId && surgeryId) &&
          !date,
      };
    });
  }

  async function saveActualSurgeryDate(
    patientId,
    surgeryId
  ) {
    const key = surgeryDateKey(
      patientId,
      surgeryId
    );
    const requestedDate = String(
      surgeryDateDrafts[key] ?? ""
    ).trim();

    if (!requestedDate) {
      setSurgeryDateMessage(
        `Enter an Actual Surgery Date for patient ${patientId}, surgery ${surgeryId}.`
      );
      return;
    }

    try {
      setBusy(true);
      setError("");
      setSurgeryDateMessage("");

      const siteId =
        (await api()?.get_site_id?.()) ?? "";

      const saved =
        await api()?.metadata_save_real_surgery_date?.(
          siteId,
          patientId,
          surgeryId,
          requestedDate
        );

      const savedDate = String(
        saved?.real_surgery_date ?? ""
      ).trim();

      if (!savedDate) {
        throw new Error(
          "Actual Surgery Date was not saved."
        );
      }

      setSurgeryDateDrafts(current => ({
        ...current,
        [key]: savedDate,
      }));

      setRows(current =>
        current.map(row => {
          const metadata = row?.metadata ?? {};
          const rowPatient = String(
            metadata["CoCANoT Patient ID"] ??
              row?.patient_id ??
              ""
          ).trim();
          const rowSurgery = String(
            metadata["Surgery ID"] ?? ""
          ).trim();

          if (
            rowPatient !== String(patientId) ||
            rowSurgery !== String(surgeryId)
          ) {
            return row;
          }

          return {
            ...row,
            actual_surgery_date: savedDate,
            actual_surgery_date_missing: false,
          };
        })
      );

      setSurgeryDateMessage(
        `Saved Actual Surgery Date for patient ${patientId}, surgery ${surgeryId}.`
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }


  async function attachClinicalAssessmentIds(activeRows) {
    if (tableName !== "Surgical") return activeRows;

    const bridge = api();
    if (!bridge?.metadata_batch_clinical_link) {
      throw new Error("Clinical Assessment lookup is unavailable. No surgical rows were imported.");
    }
    // Look up every row belonging to the scoped patient, not merely rows that
    // happen to be selected during validation. The identifier must match
    // CoCANoT's numeric-equivalence rule (1 == 001).
    const patientIds = [...new Set(
      (activeRows ?? []).map(row => rowPatientId(row)).filter(Boolean)
    )];
    const clinicalByPatient = {};
    for (const patientId of patientIds) {
      let link;
      try {
        link = await bridge.metadata_batch_clinical_link(patientId);
      } catch (err) {
        throw new Error(
          `Could not check Clinical Assessments for patient ${patientId}: ${String(err)}. Existing records were not assumed missing.`
        );
      }
      if (!link || typeof link.found !== "boolean") {
        throw new Error(
          `Clinical Assessment lookup returned an invalid response for patient ${patientId}. Please retry without importing.`
        );
      }
      clinicalByPatient[patientId] = String(link.assessment_id ?? "").trim();
    }

    return (activeRows ?? []).map(row => {
      const metadata = { ...(row?.metadata ?? {}) };
      const patientId = rowPatientId(row);
      // Never take this linkage from a spreadsheet or another patient.
      delete metadata["Clinical Assessment ID"];
      const assessmentId = clinicalByPatient[patientId] ?? "";
      if (assessmentId) metadata["Clinical Assessment ID"] = assessmentId;
      return {
        ...row, metadata,
        clinical_assessment_id: assessmentId,
        clinical_assessment_missing: Boolean(patientId) && !assessmentId,
      };
    });
  }


  function stripSystemGeneratedUploadedFields(

    activeRows,

    activeRules

  ) {

    const generatedNames = new Set(

      (activeRules ?? [])

        .filter(rule => Boolean(rule?.system_generated))

        .map(rule =>

          String(rule?.field_name ?? "").trim()

        )

        .filter(Boolean)

    );



    // Surgical Clinical Assessment ID is always managed by

    // CoCANoT, even if an older rules payload omitted the flag.

    if (tableName === "Surgical") {

      generatedNames.add("Clinical Assessment ID");

    }



    const generatedNormalized = new Set(

      [...generatedNames].map(normalizeText)

    );



    return (activeRows ?? []).map(row => {

      const metadata = { ...(row?.metadata ?? {}) };



      Object.keys(metadata).forEach(key => {

        if (

          generatedNames.has(key) ||

          generatedNormalized.has(

            normalizeText(key)

          )

        ) {

          delete metadata[key];

        }

      });



      return {

        ...row,

        metadata,

      };

    });

  }



  async function refreshSurgicalClinicalLinks() {

    if (tableName !== "Surgical") return;



    try {

      setBusy(true);

      setError("");



      let refreshed =

        await attachClinicalAssessmentIds(rows);



      const checked =

        await api()?.metadata_batch_validate?.(

          tableName,

          refreshed

        );



      if (checked?.rows) {

        refreshed = refreshIncludeFlags(

          checked.rows, rows

        );

      } else {

        refreshed = refreshIncludeFlags(

          refreshed, rows

        );

      }



      setRows(refreshed);

      setValidation(null);



      const missing = new Set(

        refreshed

          .filter(row => row.include)
          .filter(

            row =>

              row?.clinical_assessment_missing ||

              !String(

                row?.metadata?.[

                  "Clinical Assessment ID"

                ] ?? ""

              ).trim()

          )

          .map(row =>

            String(

              row?.metadata?.[

                "CoCANoT Patient ID"

              ] ??

                row?.patient_id ??

                ""

            ).trim()

          )

          .filter(Boolean)

      );



      setClinicalLinkMessage(

        missing.size

          ? `${missing.size} patient(s) still need a Clinical Assessment. Your Surgical review progress has been preserved.`

          : "Clinical Assessments linked. Your Surgical review progress has been preserved."

      );

    } catch (err) {

      setError(String(err));

    } finally {

      setBusy(false);

    }

  }



  async function validateRowsAgainstBackend(activeRows) {

    const checked =

      await api()?.metadata_batch_validate?.(

        tableName,

        activeRows

      );



    if (!checked) {

      throw new Error(

        "The metadata validation API is unavailable."

      );

    }



    return {

      ...checked,

      rows: refreshIncludeFlags(

        checked.rows ?? activeRows, activeRows

      ),

    };

  }



  async function chooseFile() {

    try {

      setBusy(true);

      setError("");



      // Avoid concurrent pywebview bridge calls while macOS displays its
      // native file picker. A simultaneous rules request can race the dialog.
      const bridge = api();
      if (!bridge?.metadata_batch_choose_file || !bridge?.metadata_get_rules) {
        throw new Error("The metadata upload API is not available.");
      }

      const nextBatch = await bridge.metadata_batch_choose_file(tableName);
      if (!nextBatch || nextBatch.cancelled) return;
      if (nextBatch.ok === false) {
        throw new Error(nextBatch.message || "Could not read the selected file.");
      }
      const nextRules = await bridge.metadata_get_rules(tableName);



      if (

        !nextBatch ||

        nextBatch.cancelled

      ) {

        return;

      }



      const activeRules = nextRules ?? [];

      let stagedRows =

        stripSystemGeneratedUploadedFields(

          nextBatch.rows ?? [],

          activeRules

        );



      // Select only the patient whose Manage One Patient upload was opened.
      // All other file rows remain visible for optional, confirmed reassignment.
      stagedRows = refreshIncludeFlags(stagedRows);

      stagedRows =

        await attachClinicalAssessmentIds(

          stagedRows

        );



      stagedRows =

        await attachActualSurgeryDates(

          stagedRows

        );



      const stagedRowsBeforeValidation = stagedRows;



      const checked =

        await api()?.metadata_batch_validate?.(

          tableName,

          stagedRows

        );



      if (checked?.rows) {

        stagedRows = refreshIncludeFlags(

          checked.rows.map((row, index) => ({

            ...row,

            actual_surgery_date:

              stagedRowsBeforeValidation[index]

                ?.actual_surgery_date ?? "",

            actual_surgery_date_missing:

              Boolean(

                stagedRowsBeforeValidation[index]

                  ?.actual_surgery_date_missing

              ),

          }))

        );

      }



      const initialTargets = {};

      const known = new Set(

        activeRules

          .map(rule =>

            String(rule.field_name ?? "").trim()

          )

          .filter(Boolean)

      );

      // Match the actual file's columns, not linked/generated fields.
      const uploadedHeaders = new Set(nextBatch.uploaded_headers ?? [
        ...new Set((nextBatch.rows ?? []).flatMap(row => Object.keys(row?.metadata ?? {})))
      ]);


      [...uploadedHeaders].forEach(header => {

        const suggestion = activeRules

          .filter(rule => !rule.system_generated)

          .map(rule => ({

            field: String(

              rule.field_name ?? ""

            ).trim(),

            score: similarityScore(

              header,

              rule.field_name

            ),

          }))

          .filter(item => item.field)

          .sort((a, b) => b.score - a.score)[0];



        if (suggestion?.score >= 0.58) {

          initialTargets[header] =

            suggestion.field;

        }

      });



      setBatch({

        ...nextBatch,

        rows: stagedRows,

      });

      setRows(stagedRows);

      setRules(activeRules);

      setColumnTargets(initialTargets);
      setResolvedUploadedHeaders([]);

      setValidation(null);

      setResult(null);

      setStep(2);

    } catch (err) {

      setError(String(err));

    } finally {

      setBusy(false);

    }

  }



  async function toggleInclude(index) {
    const selected = rows[index];
    if (!selected) return;
    if (selected.include) {
      setRows(current => current.map((row, i) =>
        i === index ? { ...row, include: false } : row
      ));
      return;
    }
    if (!rowCanImport(selected) && (!scopedPatientId || rowPatientId(selected) === normalizedPatientId(scopedPatientId))) return;

    if (scopedPatientId && rowPatientId(selected) !== normalizedPatientId(scopedPatientId)) {
      const sourceId = rowPatientId(selected) || "(blank)";
      const confirmed = window.confirm(
        `This uploaded row belongs to patient ${sourceId}. Change its CoCANoT Patient ID to ${normalizedPatientId(scopedPatientId)} and include it in this patient's import? This changes the staged row, not the original file.`
      );
      if (!confirmed) return;
      const adjusted = rows.map((row, i) => i === index ? {
        ...row,
        metadata: {
          ...row.metadata,
          "CoCANoT Patient ID": normalizedPatientId(scopedPatientId),
        },
        patient_id: normalizedPatientId(scopedPatientId),
        include: true,
      } : row);
      try {
        setBusy(true);
        setError("");
        let prepared = await attachClinicalAssessmentIds(adjusted);
        prepared = await attachActualSurgeryDates(prepared);
        const refreshed = await validateRowsAgainstBackend(prepared);
        setRows(refreshed.rows);
        setValidation(null);
      } catch (err) {
        setError(String(err));
      } finally {
        setBusy(false);
      }
      return;
    }

    setRows(current => current.map((row, i) =>
      i === index ? { ...row, include: true } : row
    ));
  }



  function editRow(index, problemField = "") {
    setEditingIndex(index);
    setEditingProblemField(
      String(problemField ?? "").trim()
    );
    setEditingValues({
      ...(rows[index]?.metadata ?? {}),
    });
  }



  function jumpToEditingProblem(fieldName) {
    const field = String(fieldName ?? "").trim();
    if (!field) return;

    setEditingProblemField(field);

    window.setTimeout(() => {
      const modal = document.querySelector(
        '[data-batch-edit-modal="true"]'
      );
      if (!modal) return;

      const rule = (rules ?? []).find(
        item =>
          String(item?.field_name ?? "").trim() === field
      );

      const prompt = String(
        rule?.ui_prompt ??
          rule?.field_name ??
          field
      ).trim();

      const target = [
        ...modal.querySelectorAll("label, fieldset"),
      ].find(element => {
        const text = String(
          element?.textContent ?? ""
        )
          .replace(/\s+/g, " ")
          .trim();

        return (
          text.includes(prompt) ||
          text.includes(field)
        );
      });

      if (!target) return;

      target.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });

      target.classList.add(
        styles.problemFieldHighlight
      );

      window.setTimeout(() => {
        target.classList.remove(
          styles.problemFieldHighlight
        );
      }, 2500);

      target
        .querySelector("input, select, textarea")
        ?.focus?.({ preventScroll: true });
    }, 120);
  }

  useEffect(() => {
    if (
      editingIndex !== null &&
      editingProblemField
    ) {
      jumpToEditingProblem(
        editingProblemField
      );
    }
  }, [editingIndex]);

  async function saveRowEdit() {
    if (editingIndex === null) return;

    try {
      setBusy(true);
      setError("");

      const nextRows = rows.map((row, index) =>
        index === editingIndex
          ? {
              ...row,
              metadata: {
                ...editingValues,
              },
              reviewed: true,
            }
          : row
      );

      const checked =
        await validateRowsAgainstBackend(
          nextRows
        );

      setRows(
        checked.rows ?? nextRows
      );

      setEditingIndex(null);
      setEditingProblemField("");
      setEditingValues({});
      setValidation(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }



  async function applyColumnMapping(

    sourceHeader,

    targetHeader

  ) {

    if (!sourceHeader || !targetHeader) return;

    try {

      setBusy(true);

      setError("");



      const ignoreColumn =
        targetHeader === "__IGNORE__";



      const mapped = rows.map(row => {

        const metadata = {

          ...(row?.metadata ?? {}),

        };



        if (

          Object.prototype.hasOwnProperty.call(

            metadata,

            sourceHeader

          )

        ) {

          if (!ignoreColumn) {

            const sourceValue =

              metadata[sourceHeader];

            const currentTarget =

              metadata[targetHeader];



            if (

              currentTarget === undefined ||

              currentTarget === null ||

              String(currentTarget).trim() === ""

            ) {

              metadata[targetHeader] =

                sourceValue;

            }

          }



          // A source column named Clinical Assessment ID is different from
          // the authoritative Clinical Assessment ID that CoCANoT attached.
          // Its uploaded value was already stripped on initial staging.
          if (!(tableName === "Surgical" &&
                normalizeText(sourceHeader) === normalizeText("Clinical Assessment ID"))) {
            delete metadata[sourceHeader];
          }

        }



        return {

          ...row,

          metadata,

        };

      });



      const checked =

        await validateRowsAgainstBackend(

          mapped

        );



      setRows(checked.rows ?? mapped);
      setResolvedUploadedHeaders(current => [...new Set([...current, sourceHeader])]);
      setValidation(null);

    } catch (err) {

      setError(String(err));

    } finally {

      setBusy(false);

    }

  }



  function closestAllowedValue(

    rule,

    currentValue

  ) {

    const allowed = (

      rule?.allowed_values ?? []

    )

      .map(value => String(value))

      .filter(Boolean);



    if (!allowed.length) return "";



    const scalar = Array.isArray(

      currentValue

    )

      ? String(currentValue[0] ?? "")

      : String(currentValue ?? "");



    if (!scalar.trim()) return "";



    const ranked = allowed

      .map(value => ({

        value,

        score: similarityScore(

          scalar,

          value

        ),

      }))

      .sort((a, b) => b.score - a.score);



    return ranked[0]?.score >= 0.58

      ? ranked[0].value

      : "";

  }



  async function applyValueSuggestion(

    rowIndex,

    fieldName,

    value

  ) {

    try {

      setBusy(true);

      setError("");



      const nextRows = rows.map(

        (row, index) =>

          index === rowIndex

            ? {

                ...row,

                metadata: {

                  ...(row?.metadata ?? {}),

                  [fieldName]: value,

                },

              }

            : row

      );



      const checked =

        await validateRowsAgainstBackend(

          nextRows

        );



      setRows(

        checked.rows ?? nextRows

      );

      setValidation(null);

    } catch (err) {

      setError(String(err));

    } finally {

      setBusy(false);

    }

  }



  async function viewExistingClinical(row) {
    if (tableName !== "Clinical") return;

    const patientId = String(
      row?.metadata?.["CoCANoT Patient ID"] ??
        row?.patient_id ??
        ""
    ).trim();

    const recordId = String(
      row?.existing_record_id ?? ""
    ).trim();

    if (!patientId || !recordId) return;

    try {
      setBusy(true);
      setError("");

      const siteId =
        (await api()?.get_site_id?.()) ?? "";

      const snapshot =
        await api()?.metadata_get_patient?.(
          siteId,
          patientId
        );

      const clinicalRows = Array.isArray(snapshot?.clinical)
        ? snapshot.clinical
        : [];

      const current =
        clinicalRows.find(item => {
          const id = String(
            item?.record_id ??
              item?.assessment_id ??
              item?.metadata?.["Clinical Assessment ID"] ??
              ""
          ).trim();

          return id === recordId;
        }) ?? null;

      if (!current) {
        throw new Error(
          `Clinical Assessment ${recordId} was not found for patient ${patientId}.`
        );
      }

      const currentRules =
        await api()?.metadata_get_rules?.(
          "Clinical",
          current?.dictionary_version ?? ""
        );

      setExistingClinical(current);
      setExistingClinicalValues({
        ...(current?.metadata ?? {}),
      });
      setExistingClinicalPatientId(patientId);
      setExistingClinicalRecordId(recordId);
      setExistingClinicalRules(currentRules ?? rules);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveExistingClinical() {
    if (
      !existingClinicalPatientId ||
      !existingClinicalRecordId
    ) return;

    try {
      setBusy(true);
      setError("");

      await api()?.metadata_save_clinical?.(
        existingClinicalPatientId,
        existingClinicalValues,
        existingClinicalRecordId
      );

      setExistingClinical(null);
      setExistingClinicalValues({});
      setExistingClinicalPatientId("");
      setExistingClinicalRecordId("");
      setExistingClinicalRules([]);

      const checked =
        await validateRowsAgainstBackend(rows);

      setRows(checked.rows ?? rows);
      setValidation(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function useExistingClinical(rowIndex) {
    setRows(current =>
      current.map((row, index) =>
        index === rowIndex
          ? {
              ...row,
              include: false,
              reviewed: true,
              clinical_resolution: "existing",
            }
          : row
      )
    );

    setExistingClinical(null);
    setExistingClinicalValues({});
    setExistingClinicalPatientId("");
    setExistingClinicalRecordId("");
    setExistingClinicalRules([]);
    setValidation(null);
  }

  function useUploadedClinical(rowIndex) {
    setRows(current =>
      current.map((row, index) => {
        if (index !== rowIndex) return row;

        const unchanged =
          row?.difference_status === "Duplicate";

        return {
          ...row,
          metadata: {
            ...editingValues,
          },
          include:
            !unchanged &&
            row?.import_allowed !== false,
          reviewed: true,
          clinical_resolution:
            unchanged ? "existing" : "uploaded",
        };
      })
    );

    setEditingIndex(null);
    setEditingProblemField("");
    setEditingValues({});
    setValidation(null);
  }

  const clinicalReviewComplete = useMemo(() => {
    if (tableName !== "Clinical") return false;

    return (
      rows.length > 0 &&
      rows.every(row => {
        if (!row.include) return true;
        if (!row?.existing_record_id) {
          return Boolean(
            row?.clinical_resolution === "uploaded" ||
              row?.reviewed
          );
        }

        if (
          row?.difference_status === "Duplicate"
        ) {
          return true;
        }

        return Boolean(row?.clinical_resolution);
      })
    );
  }, [rows, tableName]);

  function finishClinicalReviewWithExisting() {
    onFinished?.({
      ok: true,
      imported: 0,
      created: 0,
      updated: 0,
      skipped_unchanged: rows.filter(
        row =>
          row?.difference_status === "Duplicate" ||
          row?.clinical_resolution === "existing"
      ).length,
      failed: 0,
      results: [],
    });
  }

  async function validateRows() {

    try {

      setBusy(true);

      setError("");



      const checked =

        await validateRowsAgainstBackend(

          rows

        );



      setValidation(checked);

      setRows(checked.rows ?? []);

      setStep(3);

    } catch (err) {

      setError(String(err));

    } finally {

      setBusy(false);

    }

  }



  async function commitRows() {

    try {
      if (scopedPatientId && rows.some(row =>
        row.include && rowPatientId(row) !== normalizedPatientId(scopedPatientId)
      )) {
        throw new Error("An included row belongs to another patient. Confirm reassignment before importing.");
      }

      setBusy(true);

      setError("");



      const imported =

        await api()?.metadata_batch_commit?.(

          tableName,

          rows

        );



      if (!imported) {

        throw new Error(

          "The metadata import API is unavailable."

        );

      }



      setResult(imported);



      if (imported.rows) {

        setRows(imported.rows);

      }



      if (!imported.ok) {
        // Some failures are caught during the final database save, rather than
        // pre-import validation. Always show each failed source row and reason.
        const details = [
          ...(imported.problems ?? []).map(value => String(value)),
          ...(imported.results ?? [])
            .filter(item => item.status === "Failed")
            .map(item => `Row ${item.row_number}: ${item.message || "Save failed (no details returned)"}`),
        ];
        setError([...new Set(details)].join("\n") ||
          "Import was not completed. Please review included rows and retry.");
        // Keep the review page visible and never imply complete success.
        return;
      }

      setStep(3);

      onFinished?.(imported);

    } catch (err) {

      setError(String(err));

    } finally {

      setBusy(false);

    }

  }



  return (

    <div>

      <button

        className={styles.backLink}

        onClick={onBack}

      >

        <ArrowLeft size={16} />

        {backLabel}

      </button>



      <header className={styles.heading}>

        <span>

          {tableName.toUpperCase()} BATCH IMPORT

        </span>

        <h1>

          Import {tableName} metadata

        </h1>

        <p>

          Choose a CSV/XLSX file, review column mappings

          and row-level validation, make corrections,

          then explicitly import accepted records.

        </p>
        {scopedPatientId && (
          <p>
            Importing for patient <strong>{normalizedPatientId(scopedPatientId)}</strong>.
            All uploaded rows are shown, but only this patient's eligible rows are selected.
            Selecting another patient's row requires confirming reassignment.
          </p>
        )}

      </header>



      <ImportStepper current={step} />



      {error && (

        <div className={styles.errorBox}>

          {error

            .split("\n")

            .map((line, index) => (

              <div key={index}>{line}</div>

            ))}

        </div>

      )}



      {step === 1 && (

        <section className={styles.chooseCard}>

          <div className={styles.fileIcon}>

            <FileSpreadsheet size={32} />

          </div>

          <div>

            <h2>

              Select {tableName} CSV/XLSX

            </h2>

            <p>

              Selecting a file does not import

              anything yet. Rows are staged for

              review first.

            </p>

            <button

              className={styles.primary}

              onClick={chooseFile}

              disabled={busy}

            >

              <Upload size={16} />

              Choose File…

            </button>

          </div>

        </section>

      )}



      {step === 2 && batch && (

        <>

          {tableName === "Surgical" && (

            <section className={styles.clinicalLinkCard}>

              <div className={styles.clinicalLinkHeader}>

                <div className={styles.clinicalLinkIcon}>

                  <Stethoscope size={20} />

                </div>

                <div>

                  <span>CLINICAL ASSESSMENT LINKING</span>

                  <h2>

                    Clinical Assessments for this Surgical upload

                  </h2>

                  <p>

                    CoCANoT links each Surgical row to the patient's current

                    Clinical Assessment. Clinical Assessment ID is

                    system-generated and is not mapped from the uploaded file.

                  </p>

                </div>

              </div>



              <div className={styles.clinicalLinkStats}>

                <div>

                  <strong>{linkedClinicalCount}</strong>

                  <span>patient(s) linked</span>

                </div>

                <div>

                  <strong>{missingClinicalPatients.length}</strong>

                  <span>patient(s) needing an assessment</span>

                </div>

                <button

                  className={styles.primary}

                  onClick={() => setClinicalAssistOpen(true)}

                  disabled={busy}

                >

                  <Upload size={15} />

                  Upload / Update Clinical Assessments

                </button>

              </div>



              {missingClinicalPatients.length > 0 && (

                <div className={styles.missingClinicalList}>

                  <strong>

                    Clinical Assessment needed before these Surgical rows

                    can be imported:

                  </strong>

                  <div>

                    {missingClinicalPatients.map(item => (

                      <span key={item.patient_id}>

                        {item.patient_id}

                      </span>

                    ))}

                  </div>

                </div>

              )}



              {clinicalLinkMessage && (

                <div className={styles.clinicalLinkMessage}>

                  {clinicalLinkMessage}

                </div>

              )}

            </section>

          )}



          {tableName === "Surgical" &&
            missingSurgeryDates.length > 0 && (
              <section className={styles.surgeryDateCard}>
                <div className={styles.surgeryDateHeader}>
                  <span>
                    LOCAL SURGERY FOLLOW-UP
                  </span>
                  <h2>
                    Add Actual Surgery Dates
                  </h2>
                  <p>
                    Enter the actual date for each surgery before importing.
                    These dates stay on this computer for local follow-up
                    tracking and are not included in consortium metadata.
                  </p>
                </div>

                <div className={styles.surgeryDateRows}>
                  {missingSurgeryDates.map(item => {
                    const key = surgeryDateKey(
                      item.patient_id,
                      item.surgery_id
                    );

                    return (
                      <div
                        key={key}
                        className={styles.surgeryDateRow}
                      >
                        <div>
                          <strong>
                            Patient {item.patient_id}
                          </strong>
                          <span>
                            Surgery {item.surgery_id}
                          </span>
                        </div>

                        <label>
                          <span>
                            Actual Surgery Date
                          </span>
                          <input
                            type="date"
                            value={
                              surgeryDateDrafts[key] ?? ""
                            }
                            onChange={event =>
                              setSurgeryDateDrafts(
                                current => ({
                                  ...current,
                                  [key]:
                                    event.target.value,
                                })
                              )
                            }
                          />
                        </label>

                        <button
                          className={styles.primary}
                          disabled={busy}
                          onClick={() =>
                            saveActualSurgeryDate(
                              item.patient_id,
                              item.surgery_id
                            )
                          }
                        >
                          Save Date
                        </button>
                      </div>
                    );
                  })}
                </div>

                {surgeryDateMessage && (
                  <div className={styles.surgeryDateMessage}>
                    {surgeryDateMessage}
                  </div>
                )}
              </section>
            )}


          <BatchSummary

            batch={batch}

            rows={rows}

            includedCount={includedCount}

          />



          {unmatchedHeaders.length > 0 && (

            <section className={styles.mappingCard}>

              <div className={styles.mappingHeader}>

                <span>COLUMN MATCHING</span>

                <h2>Review unmatched column names</h2>

                <p>

                  These uploaded columns do not exactly

                  match the active machine-readable

                  dictionary. CoCANoT suggests the closest

                  field when possible.

                </p>

              </div>



              <div className={styles.mappingGrid}>

                {unmatchedHeaders.map(sourceHeader => {

                  const suggestion =

                    suggestedHeaderTarget(

                      sourceHeader

                    );

                  const selectedTarget =

                    columnTargets[sourceHeader] ??

                    (suggestion.score >= 0.58

                      ? suggestion.field

                      : "");



                  return (

                    <div

                      className={styles.mappingRow}

                      key={sourceHeader}

                    >

                      <div>

                        <strong>

                          {sourceHeader}

                        </strong>

                        <span>

                          Uploaded column

                        </span>

                      </div>



                      <div

                        className={

                          styles.mappingArrow

                        }

                      >

                        <ArrowRight size={15} />

                      </div>



                      <label>

                        <select

                          value={

                            selectedTarget

                          }

                          onChange={event =>

                            setColumnTargets(

                              current => ({

                                ...current,

                                [sourceHeader]:

                                  event.target

                                    .value,

                              })

                            )

                          }

                        >

                          <option value="">

                            Choose a CoCANoT

                            field…

                          </option>

                          <option value="__IGNORE__">

                            Ignore this uploaded column

                          </option>

                          {(rules ?? [])

                            .filter(

                              rule =>

                                !rule.system_generated

                            )

                            .map(rule => (

                              <option

                                key={

                                  rule.field_name

                                }

                                value={

                                  rule.field_name

                                }

                              >

                                {

                                  rule.field_name

                                }

                              </option>

                            ))}

                        </select>

                        <span>

                          {selectedTarget === "__IGNORE__"

                            ? "This uploaded column will be removed from the staged import."

                            : suggestion.score >=

                                0.85

                              ? "Strong match"

                              : suggestion.score >=

                                  0.58

                                ? "Suggested match"

                                : "Manual selection needed"}

                        </span>

                      </label>



                      <button

                        className={

                          styles.applyMappingButton

                        }

                        disabled={

                          busy ||

                          !selectedTarget

                        }

                        onClick={() =>

                          applyColumnMapping(

                            sourceHeader,

                            selectedTarget

                          )

                        }

                      >

                        {selectedTarget === "__IGNORE__"

                          ? "Ignore Column"

                          : "Apply Mapping"}

                      </button>

                    </div>

                  );

                })}

              </div>

            </section>

          )}



          <section className={styles.tableCard}>

            <div className={styles.tableHeader}>

              <div>

                <h2>

                  Review imported rows

                </h2>

                <p>

                  Invalid rows are excluded by

                  default. Edit them before

                  validation if needed.

                </p>

              </div>

              <button

                className={styles.secondary}

                onClick={chooseFile}

                disabled={busy}

              >

                <RefreshCw size={15} />

                Choose Different File

              </button>

            </div>



            <BatchTable

              tableName={tableName}

              rows={rows}

              rules={rules}

              onToggle={toggleInclude}

              onEdit={editRow}

              onViewExisting={viewExistingClinical}

              onUseExisting={useExistingClinical}

              onApplySuggestion={

                applyValueSuggestion

              }

            />

          </section>



          <div className={styles.footerActions}>

            <button

              className={styles.secondary}

              onClick={onBack}

            >

              Cancel

            </button>



            {tableName === "Clinical" &&
            clinicalReviewComplete &&
            includedCount === 0 ? (
              <button
                className={styles.primary}
                disabled={busy}
                onClick={finishClinicalReviewWithExisting}
              >
                Continue with Existing Assessments
                <ArrowRight size={16} />
              </button>
            ) : (
              <button
                className={styles.primary}
                disabled={
                  busy ||
                  includedCount === 0 ||
                  invalidIncludedCount > 0 ||
                  (tableName === "Surgical" &&
                    (
                      missingClinicalPatients.length > 0 ||
                      missingSurgeryDates.length > 0
                    ))
                }
                onClick={commitRows}
              >
                Import {includedCount} Record
                {includedCount === 1 ? "" : "s"}
                <ArrowRight size={16} />
              </button>
            )}

          </div>

        </>

      )}



      {step === 3 && result && (

        <section className={styles.resultCard}>

          <CheckCircle2 size={34} />

          <h2>Batch import complete</h2>

          <p>

            Created {result.created ?? 0}, updated{" "}

            {result.updated ?? 0}, skipped duplicate{" "}

            {result.skipped_unchanged ?? 0}, failed{" "}

            {result.failed ?? 0}.

          </p>



          {(result.results ?? []).length > 0 && (

            <table className={styles.resultTable}>

              <thead>

                <tr>

                  <th>Source Row</th>

                  <th>Status</th>

                  <th>Record ID</th>

                  <th>Message</th>

                </tr>

              </thead>

              <tbody>

                {result.results.map(item => (

                  <tr key={item.row_number}>

                    <td>{item.row_number}</td>

                    <td>{item.status}</td>

                    <td>{item.record_id}</td>

                    <td>{item.message}</td>

                  </tr>

                ))}

              </tbody>

            </table>

          )}



          <div className={styles.footerActions}>

            <button

              className={styles.secondary}

              onClick={onBack}

            >

              {backLabel}

            </button>

            <button

              className={styles.primary}

              onClick={() => {

                setStep(1);

                setBatch(null);

                setRows([]);

                setValidation(null);

                setResult(null);

                setColumnTargets({});

              }}

            >

              Import Another File

            </button>

          </div>

        </section>

      )}



      {clinicalAssistOpen && tableName === "Surgical" && (

        <div className={styles.modalBackdrop}>

          <div className={styles.clinicalAssistModal}>

            <div className={styles.clinicalAssistBanner}>

              <div>

                <span>SURGICAL IMPORT PAUSED SAFELY</span>

                <h2>Upload or update Clinical Assessments</h2>

                <p>

                  Your staged Surgical rows, edits, include/exclude choices,

                  mappings, and validation progress remain in memory while

                  you complete this Clinical bulk import.

                </p>

              </div>

              <button

                className={styles.secondary}

                onClick={() => setClinicalAssistOpen(false)}

              >

                Return to Surgical Review

              </button>

            </div>



            <BatchImportWorkflow

              tableName="Clinical"
              targetPatientId={scopedPatientId}

              backLabel="Return to Surgical Review"

              onBack={async () => {
                setClinicalAssistOpen(false);
                await refreshSurgicalClinicalLinks();
              }}

              onFinished={async () => {

                setClinicalAssistOpen(false);

                await refreshSurgicalClinicalLinks();

              }}

            />

          </div>

        </div>

      )}



      {existingClinical && tableName === "Clinical" && (
      <div className={styles.modalBackdrop}>
        <div className={styles.modal}>
          <div className={styles.modalHeader}>
            <div>
              <span>PATIENT {existingClinicalPatientId}</span>
              <h2>
                Existing Clinical Assessment{" "}
                {existingClinicalRecordId}
              </h2>
            </div>
            <button
              onClick={() => {
                setExistingClinical(null);
                setExistingClinicalValues({});
                setExistingClinicalPatientId("");
                setExistingClinicalRecordId("");
                setExistingClinicalRules([]);
              }}
            >
              Close
            </button>
          </div>

          <p>
            Review the Clinical Assessment already stored for this patient.
            You can correct it here before continuing the bulk import.
          </p>

          <DictionaryForm
            rules={existingClinicalRules}
            values={existingClinicalValues}
            onChange={(field, value) =>
              setExistingClinicalValues(current => ({
                ...current,
                [field]: value,
              }))
            }
          />

          <div className={styles.footerActions}>
            <button
              className={styles.secondary}
              onClick={() => {
                setExistingClinical(null);
                setExistingClinicalValues({});
                setExistingClinicalPatientId("");
                setExistingClinicalRecordId("");
                setExistingClinicalRules([]);
              }}
            >
              Cancel
            </button>
            <button
              className={styles.primary}
              disabled={busy}
              onClick={() => {
                const rowIndex = rows.findIndex(
                  row =>
                    String(
                      row?.patient_id ?? ""
                    ) ===
                      String(
                        existingClinicalPatientId
                      ) &&
                    String(
                      row?.existing_record_id ?? ""
                    ) ===
                      String(
                        existingClinicalRecordId
                      )
                );

                if (rowIndex >= 0) {
                  useExistingClinical(rowIndex);
                }
              }}
            >
              Use Existing Assessment
            </button>
          </div>
        </div>
      </div>
    )}

    {editingIndex !== null && (

        <div className={styles.modalBackdrop}>

          <div
            className={styles.modal}
            data-batch-edit-modal="true"
          >

            <div className={styles.modalHeader}>

              <div>

                <span>

                  SOURCE ROW{" "}

                  {rows[editingIndex]?.row_number}

                </span>

                <h2>

                  Review / Edit {tableName} Row

                </h2>

              </div>

              <button

                onClick={() =>

                  setEditingIndex(null)

                }

              >

                Close

              </button>

            </div>



            {(rows[editingIndex]?.problems ?? []).length > 0 && (
              <section className={styles.editProblemBanner}>
                <div>
                  <strong>
                    {rows[editingIndex].problems.length === 1
                      ? "1 field needs attention"
                      : `${rows[editingIndex].problems.length} fields need attention`}
                  </strong>
                  <span>
                    Click a problem to jump directly to that field.
                  </span>
                </div>

                <div className={styles.editProblemList}>
                  {rows[editingIndex].problems.map(
                    (problem, problemIndex) => (
                      <button
                        type="button"
                        key={`${problem.field_name}-${problemIndex}`}
                        className={styles.editProblemJump}
                        onClick={() =>
                          jumpToEditingProblem(
                            problem.field_name
                          )
                        }
                      >
                        <strong>{problem.field_name}</strong>
                        <span>{problem.message}</span>
                      </button>
                    )
                  )}
                </div>
              </section>
            )}

            <DictionaryForm

              rules={rules}

              values={editingValues}

              onChange={(field, value) =>

                setEditingValues(current => ({

                  ...current,

                  [field]: value,

                }))

              }

            />



            <div className={styles.footerActions}>

              <button

                className={styles.secondary}

                onClick={() =>

                  setEditingIndex(null)

                }

              >

                Cancel

              </button>

              <button
                className={styles.primary}
                onClick={() => {
                  if (
                    tableName === "Clinical" &&
                    editingIndex !== null
                  ) {
                    useUploadedClinical(
                      editingIndex
                    );
                  } else {
                    saveRowEdit();
                  }
                }}
              >
                {tableName === "Clinical"
                  ? "Use Uploaded Assessment"
                  : "Apply Row Changes"}
              </button>

            </div>

          </div>

        </div>

      )}

    </div>

  );

}



function ImportStepper({ current }) {

  const steps = [

    [1, "Choose File"],

    [2, "Review & Fix"],

    [3, "Import Results"],

  ];



  return (

    <div className={styles.stepper}>

      {steps.map(([number, label], index) => (

        <div

          className={styles.stepItem}

          key={label}

        >

          <span

            className={`${styles.stepCircle} ${

              number === current

                ? styles.stepActive

                : number < current

                  ? styles.stepDone

                  : ""

            }`}

          >

            {number}

          </span>

          <strong>{label}</strong>

          {index < steps.length - 1 && (

            <i className={styles.stepLine} />

          )}

        </div>

      ))}

    </div>

  );

}



function BatchSummary({

  batch,

  rows,

  includedCount,

}) {

  return (

    <section className={styles.summaryBar}>

      <div>

        <strong>{batch.file_name}</strong>

        <span>{batch.path}</span>
        {batch.file_sha256 && (
          <span title={batch.file_sha256}>File SHA-256: {batch.file_sha256.slice(0, 16)}…</span>
        )}
        {batch.dictionary_file && (
          <span title={batch.dictionary_sha256 || ""}>
            Dictionary: {batch.dictionary_file}
            {batch.dictionary_sha256 ? ` (${batch.dictionary_sha256.slice(0, 12)}…)` : ""}
          </span>
        )}

      </div>

      <div>

        <strong>{rows.length}</strong>

        <span>Total rows</span>

      </div>

      <div>

        <strong>

          {rows.filter(

            row =>

              row.difference_status === "New" ||

              row.difference_status === "New assessment"

          ).length}

        </strong>

        <span>New</span>

      </div>

      <div>

        <strong>

          {rows.filter(

            row =>

              row.difference_status === "Changed" ||

              row.difference_status === "Correction"

          ).length}

        </strong>

        <span>Updates</span>

      </div>

      <div>

        <strong>

          {rows.filter(

            row =>

              row.difference_status === "Duplicate"

          ).length}

        </strong>

        <span>Duplicate</span>

      </div>

      <div>

        <strong>

          {rows.filter(

            row => (row.problems ?? []).length > 0

          ).length}

        </strong>

        <span>Needs attention</span>

      </div>

      <div>

        <strong>{includedCount}</strong>

        <span>Included</span>

      </div>

    </section>

  );

}



function BatchTable({
  tableName,
  rows,
  rules,
  onToggle,
  onEdit,
  onViewExisting,
  onUseExisting,
  onApplySuggestion,
}) {

  return (

    <div className={styles.tableWrap}>

      <table className={styles.table}>

        <thead>

          <tr>

            <th>Include</th>

            <th>Source Row</th>

            <th>Patient ID</th>

            <th>Status</th>

            <th>Proposed Action</th>

            <th>Validation</th>

            <th></th>

          </tr>

        </thead>

        <tbody>

          {rows.map((row, index) => (

            <tr key={row.row_number}>

              <td>

                <input

                  type="checkbox"

                  checked={Boolean(row.include)}

                  disabled={

                    row.import_allowed === false

                  }

                  onChange={() =>

                    onToggle(index)

                  }

                />

              </td>

              <td>{row.row_number}</td>

              <td>{row.patient_id}</td>

              <td>

                <span

                  className={

                    row.difference_status === "Duplicate"

                      ? styles.unchangedBadge

                      : row.requires_review

                        ? styles.reviewBadge

                        : row.difference_status ===

                              "Correction" ||

                            row.difference_status ===

                              "Changed"

                          ? styles.changedBadge

                          : styles.newBadge

                  }

                >

                  {row.difference_status ?? "New"}

                </span>

              </td>

              <td>

                <span className={styles.actionText}>

                  {row.proposed_action ?? ""}

                </span>

                {row.immutable && (

                  <small className={styles.immutableNote}>

                    Historical Clinical Assessments are read-only.

                  </small>

                )}

              </td>

              <td>

                {(row.problems ?? []).length ? (

                  <div className={styles.problemList}>

                    {row.problems.map(

                      (problem, problemIndex) => {

                        const rule = (rules ?? []).find(

                          item =>

                            item.field_name ===

                            problem.field_name

                        );

                        const currentValue =

                          row?.metadata?.[

                            problem.field_name

                          ];



                        let suggestion = "";

                        if (rule?.allowed_values?.length) {

                          const scalar =

                            Array.isArray(

                              currentValue

                            )

                              ? String(

                                  currentValue[0] ??

                                    ""

                                )

                              : String(

                                  currentValue ?? ""

                                );



                          if (scalar.trim()) {

                            const ranked =

                              rule.allowed_values

                                .map(value => ({

                                  value:

                                    String(value),

                                  score:

                                    similarityScore(

                                      scalar,

                                      value

                                    ),

                                }))

                                .sort(

                                  (a, b) =>

                                    b.score - a.score

                                );



                            if (

                              ranked[0]?.score >=

                              0.58

                            ) {

                              suggestion =

                                ranked[0].value;

                            }

                          }

                        }



                        return (

                          <div

                            className={

                              styles.problemItem

                            }

                            key={`${problem.field_name}-${problemIndex}`}

                          >

                            <strong>

                              {problem.field_name}

                            </strong>

                            <span>

                              {problem.message}

                            </span>

                            {suggestion && (

                              <button

                                type="button"

                                className={

                                  styles.suggestionButton

                                }

                                onClick={() =>

                                  onApplySuggestion?.(

                                    index,

                                    problem.field_name,

                                    suggestion

                                  )

                                }

                              >

                                Use “{suggestion}”

                              </button>

                            )}

                          </div>

                        );

                      }

                    )}

                  </div>

                ) : tableName === "Clinical" ? (
                  <div className={styles.clinicalCompareStatus}>
                    {row.existing_record_id ? (
                      row.difference_status === "Duplicate" ? (
                        <span className={styles.noProblems}>
                          Same as existing
                        </span>
                      ) : row.clinical_resolution ? (
                        <span className={styles.noProblems}>
                          {row.clinical_resolution === "existing"
                            ? "Using existing assessment"
                            : "Using uploaded assessment"}
                        </span>
                      ) : (
                        <span className={styles.reviewBadge}>
                          Different from existing
                        </span>
                      )
                    ) : row.clinical_resolution === "uploaded" ||
                      row.reviewed ? (
                      <span className={styles.noProblems}>
                        Uploaded assessment selected
                      </span>
                    ) : (
                      <span className={styles.reviewBadge}>
                        New assessment - review needed
                      </span>
                    )}

                    <div className={styles.actionText}>
                      {row.existing_record_id
                        ? `Existing assessment: ${row.existing_record_id}`
                        : "No existing Clinical Assessment"}
                    </div>
                  </div>
                ) : (
                  <span className={styles.noProblems}>
                    No validation problems
                  </span>
                )}

              </td>

              <td>
                {tableName === "Clinical" &&
                  row.existing_record_id && (
                    <>
                      <button
                        className={styles.secondary}
                        onClick={() =>
                          onViewExisting?.(row)
                        }
                      >
                        View Existing
                      </button>

                      <button
                        className={styles.secondary}
                        onClick={() =>
                          onUseExisting?.(index)
                        }
                      >
                        Use Existing Assessment
                      </button>
                    </>
                  )}

                <button
                  className={styles.editButton}
                  onClick={() =>
                    onEdit(
                      index,
                      row?.problems?.[0]?.field_name ?? ""
                    )
                  }
                >
                  <Pencil size={14} />
                  {tableName === "Clinical"
                    ? "Review Uploaded"
                    : "Edit"}
                </button>
              </td>

            </tr>

          ))}

        </tbody>

      </table>

    </div>

  );

}
