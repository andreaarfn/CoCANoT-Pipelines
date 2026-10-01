const api = () => window.pywebview?.api ?? null;

const TABLES = [
  {
    tableName: "Clinical",
    summaryKeys: ["clinical", "Clinical"],
  },
  {
    tableName: "Surgical",
    summaryKeys: ["surgical", "Surgical"],
  },
  {
    tableName: "Imaging",
    summaryKeys: ["imaging", "Imaging"],
  },
  {
    tableName: "Electrophysiology",
    summaryKeys: [
      "electrophysiology",
      "Electrophysiology",
    ],
  },
];

function normalizeString(value) {
  return String(value ?? "").trim();
}

function isEmptyValue(value) {
  if (Array.isArray(value)) {
    return value.length === 0;
  }

  if (
    value &&
    typeof value === "object"
  ) {
    return Object.keys(value).length === 0;
  }

  return normalizeString(value) === "";
}

function readExpectedList(value) {
  if (Array.isArray(value)) {
    return value.map(String);
  }

  if (
    value === null ||
    value === undefined
  ) {
    return [];
  }

  if (typeof value === "string") {
    const text = value.trim();

    if (!text) {
      return [];
    }

    if (
      text.startsWith("[") &&
      text.endsWith("]")
    ) {
      try {
        const parsed = JSON.parse(text);

        if (Array.isArray(parsed)) {
          return parsed.map(String);
        }
      } catch {
        return [];
      }
    }

    return [text];
  }

  return [String(value)];
}

function contains(value, expected) {
  if (Array.isArray(value)) {
    return value
      .map(String)
      .includes(String(expected));
  }

  if (typeof value === "string") {
    return value.includes(
      String(expected)
    );
  }

  return false;
}

function conditionMatches(rule, values) {
  if (!rule?.required_if_field) {
    return true;
  }

  const current =
    values?.[rule.required_if_field];

  const operator = normalizeString(
    rule.required_if_operator
  ).toLowerCase();

  const expected =
    rule.required_if_value;

  if (operator === "is_blank") {
    return isEmptyValue(current);
  }

  if (operator === "is_not_blank") {
    return !isEmptyValue(current);
  }

  if (isEmptyValue(current)) {
    return false;
  }

  if (
    operator === "equals" ||
    operator === "=="
  ) {
    return (
      String(current) ===
      String(expected ?? "")
    );
  }

  if (
    operator === "not_equals" ||
    operator === "!="
  ) {
    return (
      String(current) !==
      String(expected ?? "")
    );
  }

  if (operator === "contains") {
    return contains(
      current,
      expected
    );
  }

  if (
    operator === "does_not_contain" ||
    operator === "not_contains"
  ) {
    return !contains(
      current,
      expected
    );
  }

  if (operator === "contains_any") {
    return readExpectedList(
      expected
    ).some(choice =>
      contains(
        current,
        choice
      )
    );
  }

  if (operator === "in") {
    return readExpectedList(
      expected
    ).includes(
      String(current)
    );
  }

  return false;
}

function fieldIsRequired(
  rule,
  values
) {
  if (Boolean(rule?.required)) {
    return true;
  }

  if (!rule?.required_if_field) {
    return false;
  }

  return conditionMatches(
    rule,
    values
  );
}

function completedCalendarMonths(
  dateText
) {
  const text =
    normalizeString(dateText);

  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(
      text
    )
  ) {
    return null;
  }

  const [
    year,
    month,
    day,
  ] = text
    .split("-")
    .map(Number);

  const today = new Date();

  let months =
    (
      today.getFullYear() -
      year
    ) * 12 +
    (
      today.getMonth() +
      1 -
      month
    );

  if (
    today.getDate() <
    day
  ) {
    months -= 1;
  }

  return Math.max(
    months,
    0
  );
}

function ruleIsAvailable(
  rule,
  actualSurgeryDate
) {
  const threshold =
    rule?.available_after_surgery_months;

  if (
    threshold === null ||
    threshold === undefined ||
    threshold === ""
  ) {
    return true;
  }

  const completed =
    completedCalendarMonths(
      actualSurgeryDate
    );

  if (completed === null) {
    return false;
  }

  return (
    completed >=
    Number(threshold)
  );
}

function repeatSelections(
  rule,
  metadata
) {
  const parent =
    rule?.repeat_for_each_field;

  if (!parent) {
    return [];
  }

  const current =
    metadata?.[parent];

  const selected =
    Array.isArray(current)
      ? current.map(String)
      : isEmptyValue(current)
        ? []
        : [String(current)];

  const excluded =
    new Set(
      (
        rule
          ?.repeat_exclude_values ??
        []
      ).map(String)
    );

  return selected.filter(
    selection =>
      !excluded.has(selection)
  );
}

function validateRequiredFields(
  rules,
  metadata,
  actualSurgeryDate = ""
) {
  const errors = {};

  for (
    const rule
    of rules ?? []
  ) {
    const fieldName =
      normalizeString(
        rule?.field_name
      );

    if (!fieldName) {
      continue;
    }

    if (
      !ruleIsAvailable(
        rule,
        actualSurgeryDate
      )
    ) {
      continue;
    }

    if (
      !conditionMatches(
        rule,
        metadata
      )
    ) {
      continue;
    }

    const required =
      fieldIsRequired(
        rule,
        metadata
      );

    if (!required) {
      continue;
    }

    if (
      rule?.repeat_for_each_field
    ) {
      const selections =
        repeatSelections(
          rule,
          metadata
        );

      if (!selections.length) {
        continue;
      }

      const currentValue =
        metadata?.[fieldName];

      const repeated =
        currentValue &&
        typeof currentValue ===
          "object" &&
        !Array.isArray(
          currentValue
        )
          ? currentValue
          : {};

      const missing =
        selections.filter(
          selection =>
            isEmptyValue(
              repeated?.[
                selection
              ]
            )
        );

      if (missing.length) {
        errors[fieldName] =
          `A value is required for: ${missing.join(", ")}.`;
      }

      continue;
    }

    if (
      isEmptyValue(
        metadata?.[fieldName]
      )
    ) {
      errors[fieldName] =
        "A value is required for this field.";
    }
  }

  return errors;
}

function getSummaryRecords(
  summary,
  keys
) {
  for (const key of keys) {
    const rows =
      summary?.[key];

    if (
      Array.isArray(rows)
    ) {
      return rows;
    }
  }

  return [];
}

function patientIdFromRow(row) {
  if (
    typeof row === "string"
  ) {
    return normalizeString(row);
  }

  return normalizeString(
    row?.patient_id ??
    row?.[
      "CoCANoT Patient ID"
    ]
  );
}

function recordId(record) {
  return normalizeString(
    record?.record_id ??
    record?.assessment_id ??
    record?.metadata?.[
      "Clinical Assessment ID"
    ] ??
    record?.metadata?.[
      "Surgery ID"
    ] ??
    record?.metadata?.[
      "Image ID"
    ] ??
    record?.metadata?.[
      "Recording ID"
    ]
  );
}

function clinicalAssessmentNumber(
  record
) {
  const match =
    /^CA-(\d+)$/i.exec(
      recordId(record)
    );

  return match
    ? Number(match[1])
    : -1;
}

function latestClinicalRecord(
  records
) {
  return [
    ...(records ?? []),
  ].sort(
    (a, b) =>
      clinicalAssessmentNumber(
        b
      ) -
      clinicalAssessmentNumber(
        a
      )
  )[0] ?? null;
}

function summarizeErrors(
  errors
) {
  const fields =
    Object.keys(
      errors ?? {}
    );

  if (!fields.length) {
    return "";
  }

  if (
    fields.length === 1
  ) {
    return (
      `${fields[0]} needs review.`
    );
  }

  return (
    `${fields[0]} and ` +
    `${fields.length - 1} other field(s) need review.`
  );
}

function priorityFor(status) {
  const priorities = {
    overdue: 0,
    due: 1,
    due_soon: 2,
    needs_review: 3,
  };

  return (
    priorities[
      status
    ] ?? 9
  );
}

async function getActualSurgeryDate(
  bridge,
  siteId,
  patientId,
  surgeryId
) {
  if (
    !bridge
      .metadata_get_real_surgery_date ||
    !surgeryId
  ) {
    return "";
  }

  const result =
    await bridge
      .metadata_get_real_surgery_date(
        siteId,
        patientId,
        surgeryId
      );

  if (
    typeof result === "string"
  ) {
    return normalizeString(
      result
    );
  }

  return normalizeString(
    result
      ?.real_surgery_date
  );
}

async function loadImagingStep5Attention(
  bridge
) {
  if (
    !bridge?.imaging_get_state ||
    !bridge?.imaging_bids_get_state
  ) {
    return [];
  }

  let workflowState;

  try {
    workflowState =
      await bridge.imaging_get_state();
  } catch {
    return [];
  }

  if (
    workflowState
      ?.process_stages
      ?.metadata_bids !== "failed"
  ) {
    return [];
  }

  let bidsState;

  try {
    bidsState =
      await bridge
        .imaging_bids_get_state();
  } catch {
    return [];
  }

  const rules =
    Array.isArray(bidsState?.rules)
      ? bidsState.rules
      : [];

  const records =
    Array.isArray(bidsState?.records)
      ? bidsState.records
      : [];

  const pending =
    records.filter(
      record =>
        record?.record_state !==
        "completed_recorded"
    );

  const attention = [];

  for (const record of pending) {
    const metadata =
      record?.cocanot_metadata ?? {};

    let fieldErrors = {};

    if (
      bridge.metadata_validate_record
    ) {
      try {
        const validation =
          await bridge
            .metadata_validate_record(
              "Imaging",
              metadata
            );

        fieldErrors =
          validation?.field_errors ?? {};
      } catch (error) {
        console.error(
          "Needs Attention could not validate an Imaging Step 5 draft with the backend validator:",
          error
        );

        fieldErrors =
          validateRequiredFields(
            rules,
            metadata
          );
      }
    } else {
      fieldErrors =
        validateRequiredFields(
          rules,
          metadata
        );
    }

    if (
      isEmptyValue(record?.project)
    ) {
      fieldErrors.Project =
        "Project is required.";
    }

    const hasDraft =
      Boolean(record?.include) ||
      !isEmptyValue(record?.project) ||
      !isEmptyValue(
        record?.session_id
      ) ||
      Object.values(
        metadata
      ).some(
        value =>
          !isEmptyValue(value)
      );

    if (!hasDraft) {
      continue;
    }

    if (
      Object.keys(
        fieldErrors
      ).length === 0
    ) {
      continue;
    }

    const patientId =
      normalizeString(
        metadata?.[
          "CoCANoT Patient ID"
        ]
      );

    const imageId =
      normalizeString(
        metadata?.["Image ID"]
      );

    const label =
      imageId ||
      normalizeString(
        record?.source_label
      ) ||
      normalizeString(
        record?.source_key
      ) ||
      "Pending image";

    const errorSummary =
      summarizeErrors(
        fieldErrors
      );

    attention.push({
      attention_id:
        `imaging-step5:${
          normalizeString(
            record?.source_key
          ) || label
        }`,
      patient_id:
        patientId || "Imaging",
      record_id:
        imageId || label,
      table_name:
        "Imaging",
      category:
        "imaging_step5",
      status:
        "needs_review",
      field_errors:
        fieldErrors,
      message:
        `Imaging ${label}: ${errorSummary}`,
      workflow:
        "imaging",
      target_view:
        "metadata",
      source_key:
        normalizeString(
          record?.source_key
        ),
    });
  }

  return attention;
}

export async function loadNeedsAttention() {
  const bridge = api();

  if (!bridge) {
    throw new Error(
      "The CoCANoT desktop bridge is not available."
    );
  }

  const siteId =
    normalizeString(
      await bridge
        .get_site_id?.()
    );

  if (!siteId) {
    return [];
  }

  if (
    !bridge.metadata_get_patients
  ) {
    throw new Error(
      "metadata_get_patients is not available in the desktop API."
    );
  }

  if (
    !bridge.metadata_get_patient
  ) {
    throw new Error(
      "metadata_get_patient is not available in the desktop API."
    );
  }

  if (
    !bridge.metadata_get_rules
  ) {
    throw new Error(
      "metadata_get_rules is not available in the desktop API."
    );
  }

  const rulePairs =
    await Promise.all(
      TABLES.map(
        async table => {
          const rules =
            await bridge
              .metadata_get_rules(
                table.tableName
              );

          return [
            table.tableName,
            Array.isArray(rules)
              ? rules
              : [],
          ];
        }
      )
    );

  const rulesByTable =
    Object.fromEntries(
      rulePairs
    );

  const patientRows =
    await bridge
      .metadata_get_patients(
        siteId
      );

  const patientIds =
    (patientRows ?? [])
      .map(
        patientIdFromRow
      )
      .filter(Boolean);

  const items = [];

  try {
    items.push(
      ...await loadImagingStep5Attention(
        bridge
      )
    );
  } catch (error) {
    console.error(
      "Needs Attention could not load Imaging Step 5 issues:",
      error
    );
  }

  for (
    const patientId
    of patientIds
  ) {
    let summary;

    try {
      summary =
        await bridge
          .metadata_get_patient(
            siteId,
            patientId
          );
    } catch (error) {
      console.error(
        `Needs Attention could not load patient ${patientId}:`,
        error
      );

      items.push({
        attention_id:
          `load-error:${patientId}`,
        patient_id:
          patientId,
        category:
          "metadata_review",
        status:
          "needs_review",
        message:
          "Patient data could not be checked against the current metadata requirements.",
      });

      continue;
    }

    for (
      const table
      of TABLES
    ) {
      const records =
        getSummaryRecords(
          summary,
          table.summaryKeys
        );

      const rules =
        rulesByTable[
          table.tableName
        ] ?? [];

      if (
        table.tableName ===
        "Clinical"
      ) {
        const current =
          latestClinicalRecord(
            records
          );

        if (!current) {
          continue;
        }

        const id =
          recordId(current) ||
          "Unknown";

        const storedVersion =
          normalizeString(
            current
              ?.dictionary_version
          );

        const activeVersion =
          normalizeString(
            rules?.[0]
              ?.dictionary_version
          );

        if (
          activeVersion &&
          storedVersion !==
            activeVersion
        ) {
          items.push({
            attention_id:
              `dictionary-version:Clinical:${patientId}:${id}`,
            patient_id:
              patientId,
            record_id:
              id,
            table_name:
              "Clinical",
            category:
              "dictionary_version_review",
            status:
              "needs_review",
            dictionary_version:
              storedVersion,
            current_dictionary_version:
              activeVersion,
            message:
              `Clinical ${id}: review for ${activeVersion}.`,
          });

          continue;
        }

        const errors =
          validateRequiredFields(
            rules,
            current?.metadata ??
              {}
          );

        if (
          Object.keys(
            errors
          ).length
        ) {
          items.push({
            attention_id:
              `validation:Clinical:${patientId}:${id}`,
            patient_id:
              patientId,
            record_id:
              id,
            table_name:
              "Clinical",
            category:
              "metadata_review",
            status:
              "needs_review",
            field_errors:
              errors,
            message:
              `Clinical ${id}: ` +
              summarizeErrors(
                errors
              ),
          });
        }

        continue;
      }

      for (
        const record
        of records
      ) {
        const metadata =
          record?.metadata ??
          {};

        const id =
          recordId(record) ||
          "Unknown";

        let actualSurgeryDate =
          "";

        if (
          table.tableName ===
          "Surgical"
        ) {
          const surgeryId =
            normalizeString(
              metadata?.[
                "Surgery ID"
              ]
            ) || id;

          try {
            actualSurgeryDate =
              await getActualSurgeryDate(
                bridge,
                siteId,
                patientId,
                surgeryId
              );
          } catch (error) {
            console.error(
              `Needs Attention could not check local surgery date for ${surgeryId}:`,
              error
            );

            actualSurgeryDate =
              "";
          }

          if (
            bridge
              .metadata_get_real_surgery_date &&
            !actualSurgeryDate
          ) {
            items.push({
              attention_id:
                `surgery-date:${patientId}:${surgeryId}`,
              patient_id:
                patientId,
              record_id:
                surgeryId,
              surgery_id:
                surgeryId,
              table_name:
                "Surgical",
              category:
                "local_surgery_date",
              status:
                "needs_review",
              message:
                `Surgical ${surgeryId}: actual surgery date is missing.`,
            });
          }
        }

        let errors;

        if (
          table.tableName ===
            "Imaging" &&
          bridge.metadata_validate_record
        ) {
          try {
            const validation =
              await bridge
                .metadata_validate_record(
                  "Imaging",
                  metadata
                );

            errors =
              validation?.field_errors ??
              {};
          } catch (error) {
            console.error(
              `Needs Attention could not validate Imaging ${id} with the backend validator:`,
              error
            );

            errors =
              validateRequiredFields(
                rules,
                metadata,
                actualSurgeryDate
              );
          }
        } else {
          errors =
            validateRequiredFields(
              rules,
              metadata,
              actualSurgeryDate
            );
        }

        if (
          Object.keys(
            errors
          ).length
        ) {
          items.push({
            attention_id:
              `validation:${table.tableName}:${patientId}:${id}`,
            patient_id:
              patientId,
            record_id:
              id,
            table_name:
              table.tableName,
            category:
              "metadata_review",
            status:
              "needs_review",
            field_errors:
              errors,
            message:
              `${table.tableName} ${id}: ` +
              summarizeErrors(
                errors
              ),
          });
        }
      }
    }
  }

  if (
    bridge
      .metadata_get_needs_attention
  ) {
    try {
      const followupItems =
        await bridge
          .metadata_get_needs_attention(
            siteId
          );

      for (
        const item
        of followupItems ?? []
      ) {
        if (
          item?.status ===
            "missing" &&
          item?.category ===
            "Surgical"
        ) {
          continue;
        }

        items.push({
          ...item,
          attention_id:
            item?.attention_id ??
            (
              `followup:` +
              `${item?.patient_id ?? ""}:` +
              `${item?.surgery_id ?? ""}:` +
              `${item?.milestone_months ?? ""}`
            ),
          category:
            "followup",
        });
      }
    } catch (error) {
      console.error(
        "Needs Attention could not load surgical follow-up reminders:",
        error
      );
    }
  }

  const deduped =
    Array.from(
      new Map(
        items.map(
          item => [
            item.attention_id,
            item,
          ]
        )
      ).values()
    );

  deduped.sort(
    (a, b) => {
      const priorityDifference =
        priorityFor(
          a.status
        ) -
        priorityFor(
          b.status
        );

      if (
        priorityDifference !==
        0
      ) {
        return (
          priorityDifference
        );
      }

      const patientDifference =
        String(
          a.patient_id ??
          ""
        ).localeCompare(
          String(
            b.patient_id ??
            ""
          )
        );

      if (
        patientDifference !==
        0
      ) {
        return (
          patientDifference
        );
      }

      return String(
        a.record_id ??
        a.surgery_id ??
        ""
      ).localeCompare(
        String(
          b.record_id ??
          b.surgery_id ??
          ""
        )
      );
    }
  );

  return deduped;
}

export default loadNeedsAttention;