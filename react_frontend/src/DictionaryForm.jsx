import { useEffect, useMemo, useRef, useState } from "react";
import styles from "./DictionaryForm.module.css";

function nextMultiSelectValue(
  selected,
  option,
  checked,
  allowed,
  exclusiveValues
) {
  const current = Array.isArray(selected)
    ? selected.map(String)
    : [];

  const optionText = String(option);
  const exclusive = new Set(
    (exclusiveValues ?? []).map(String)
  );

  if (checked) {
    if (exclusive.has(optionText)) {
      return [optionText];
    }

    const next = [
      ...current.filter(
        item => !exclusive.has(item)
      ),
      optionText,
    ];

    return allowed.filter(item =>
      next.includes(item)
    );
  }

  return current.filter(item => item !== optionText);
}

export function conditionMatches(rule, values) {
  if (!rule?.required_if_field) return true;

  const current = values?.[rule.required_if_field];
  const operator = String(
    rule.required_if_operator ?? ""
  ).toLowerCase();

  if (operator === "is_blank") {
    return isEmptyValue(current);
  }

  if (operator === "is_not_blank") {
    return !isEmptyValue(current);
  }

  if (isEmptyValue(current)) {
    return false;
  }

  const expected = rule.required_if_value;

  function readExpectedList(value) {
    if (Array.isArray(value)) {
      return value.map(String);
    }

    if (typeof value === "string") {
      const text = value.trim();

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

    return [String(value ?? "")];
  }

  function contains(value, expectedValue) {
    if (Array.isArray(value)) {
      return value.map(String).includes(
        String(expectedValue)
      );
    }

    if (typeof value === "string") {
      return value.includes(
        String(expectedValue)
      );
    }

    return false;
  }

  if (operator === "equals" || operator === "==") {
    return String(current) === String(expected ?? "");
  }

  if (
    operator === "not_equals" ||
    operator === "!="
  ) {
    return String(current) !== String(expected ?? "");
  }

  if (operator === "contains") {
    return contains(current, expected);
  }

  if (
    operator === "does_not_contain" ||
    operator === "not_contains"
  ) {
    return !contains(current, expected);
  }

  if (operator === "contains_any") {
    return readExpectedList(expected).some(
      item => contains(current, item)
    );
  }

  if (operator === "in") {
    return readExpectedList(expected).includes(
      String(current)
    );
  }

  return false;
}

export function isEmptyValue(value) {
  if (Array.isArray(value)) {
    return value.length === 0;
  }

  return String(value ?? "").trim() === "";
}

export function fieldIsRequired(rule, values) {
  if (rule?.required) return true;

  return Boolean(
    rule?.required_if_field &&
    conditionMatches(rule, values)
  );
}

function completedCalendarMonths(dateText) {
  const text = String(dateText ?? "").trim();

  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return null;
  }

  const [year, month, day] = text
    .split("-")
    .map(Number);

  const today = new Date();
  let months =
    (today.getFullYear() - year) * 12 +
    (today.getMonth() + 1 - month);

  if (today.getDate() < day) {
    months -= 1;
  }

  return Math.max(months, 0);
}

function surgeryMilestoneIsAvailable(
  rule,
  context
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

  const months = completedCalendarMonths(
    context?.actual_surgery_date
  );

  if (months === null) {
    return false;
  }

  return months >= Number(threshold);
}

export function fieldIsVisible(
  rule,
  values,
  context = {}
) {
  return (
    conditionMatches(rule, values) &&
    surgeryMilestoneIsAvailable(
      rule,
      context
    )
  );
}

function repeatSelections(rule, values) {
  const parent = rule?.repeat_for_each_field;

  if (!parent) {
    return [];
  }

  const current = values?.[parent];
  const selected = Array.isArray(current)
    ? current.map(String)
    : current
      ? [String(current)]
      : [];

  const excluded = new Set(
    (rule.repeat_exclude_values ?? []).map(String)
  );

  return selected.filter(
    selection => !excluded.has(selection)
  );
}

function repeatedValueObject(value) {
  if (
    value &&
    typeof value === "object" &&
    !Array.isArray(value)
  ) {
    return value;
  }

  return {};
}

export function validateRecordAgainstRules(
  rules,
  values,
  contextOrOptions = {},
  options = {}
) {
  const hasSurgeryContext = Object.prototype.hasOwnProperty.call(
    contextOrOptions,
    "actual_surgery_date"
  );

  const context = hasSurgeryContext
    ? contextOrOptions
    : {};

  const includeUnknownFields = hasSurgeryContext
    ? Boolean(options?.includeUnknownFields)
    : Boolean(contextOrOptions?.includeUnknownFields);

  const errors = {};
  const activeNames = new Set(
    (rules ?? []).map(rule => rule.field_name)
  );

  for (const rule of rules ?? []) {
    if (
      !fieldIsVisible(
        rule,
        values,
        context
      )
    ) {
      continue;
    }

    if (rule?.repeat_for_each_field) {
      const selections = repeatSelections(rule, values);

      if (!selections.length) {
        continue;
      }

      const repeated = repeatedValueObject(
        values?.[rule.field_name]
      );

      if (fieldIsRequired(rule, values)) {
        const missing = selections.filter(
          selection =>
            isEmptyValue(repeated?.[selection])
        );

        if (missing.length) {
          errors[rule.field_name] =
            `A value is required for: ${missing.join(", ")}.`;
        }
      }

      continue;
    }

    if (
      fieldIsRequired(rule, values) &&
      isEmptyValue(values?.[rule.field_name])
    ) {
      errors[rule.field_name] =
        "A value is required for this field.";
    }
  }

  if (includeUnknownFields) {
    for (const fieldName of Object.keys(values ?? {})) {
      if (!activeNames.has(fieldName)) {
        errors[fieldName] =
          "This field is not defined in the active metadata dictionary.";
      }
    }
  }

  return errors;
}

// Shared, dictionary-driven detection. Never discard uploaded values here.
export function inapplicablePopulatedFields(rules, values, context = {}) {
  return (rules ?? []).filter(rule => {
    const name = rule?.field_name;
    if (!name || rule.system_generated) return false;
    const value = values?.[name];
    const hasValue = !isEmptyValue(value) &&
      !(value && typeof value === "object" && !Array.isArray(value) &&
        Object.keys(value).length === 0);
    if (!hasValue) return false;
    if (rule.repeat_for_each_field) {
      return repeatSelections(rule, values).length === 0;
    }
    return !fieldIsVisible(rule, values, context);
  }).map(rule => ({
    field_name: rule.field_name,
    label: rule.ui_prompt || rule.field_name,
    value: values[rule.field_name],
    parent: rule.required_if_field || rule.repeat_for_each_field || "",
  }));
}

function formatClearedValue(value) {
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

function HelpPopover({ text }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;

    function onPointerDown(event) {
      if (
        wrapRef.current &&
        !wrapRef.current.contains(event.target)
      ) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", onPointerDown);
    return () =>
      document.removeEventListener(
        "mousedown",
        onPointerDown
      );
  }, [open]);

  if (!text) return null;

  return (
    <span className={styles.helpWrap} ref={wrapRef}>
      <button
        type="button"
        className={styles.helpButton}
        aria-label="Show field help"
        aria-expanded={open}
        onClick={event => {
          event.preventDefault();
          event.stopPropagation();
          setOpen(value => !value);
        }}
      >
        ?
      </button>

      {open && (
        <span
          className={styles.helpPopover}
          role="tooltip"
        >
          {text}
        </span>
      )}
    </span>
  );
}

export function DictionaryField({
  rule,
  value,
  values,
  onChange,
  onBlur,
  error = "",
  disabled = false,
}) {
  const label = `${rule.ui_prompt}${
    rule.required
      ? " *"
      : rule.required_if_field
        ? " * when applicable"
        : ""
  }`;

  const invalid = Boolean(error);

  if (rule.repeat_for_each_field) {
    const selections = repeatSelections(
      rule,
      values
    );

    if (!selections.length) {
      return null;
    }

    const repeated = repeatedValueObject(
      value
    );
    const specialValues = (
      rule.repeat_special_values ?? []
    ).map(String);
    const template = String(
      rule.repeat_prompt_template ||
      "Enter value for {selection}"
    );

    return (
      <fieldset
        className={`${styles.repeatField} ${
          invalid ? styles.fieldInvalid : ""
        }`}
      >
        <legend>
          {label}
          <HelpPopover text={rule.help_text} />
        </legend>

        {selections.map(selection => {
          const prompt = template.replace(
            "{selection}",
            selection
          );
          const response = String(
            repeated?.[selection] ?? ""
          );
          const specialSelected =
            specialValues.includes(response);

          function updateResponse(nextValue) {
            const next = {
              ...repeated,
              [selection]: nextValue,
            };

            for (const key of Object.keys(next)) {
              if (!selections.includes(key)) {
                delete next[key];
              }
            }

            onChange(next);
          }

          return (
            <div
              className={styles.repeatRow}
              key={selection}
            >
              <span className={styles.repeatLabel}>
                {prompt}
              </span>

              <div className={styles.repeatControl}>
                <input
                  className={
                    invalid
                      ? styles.inputInvalid
                      : ""
                  }
                  disabled={disabled}
                  value={
                    specialSelected
                      ? ""
                      : response
                  }
                  onBlur={onBlur}
                  onChange={event =>
                    updateResponse(
                      event.target.value
                    )
                  }
                  aria-invalid={invalid}
                />

                {specialValues.length > 0 && (
                  <div
                    className={
                      styles.repeatSpecialValues
                    }
                  >
                    {specialValues.map(option => (
                      <button
                        type="button"
                        key={option}
                        disabled={disabled}
                        className={
                          response === option
                            ? styles.specialSelected
                            : ""
                        }
                        onClick={() =>
                          updateResponse(
                            response === option
                              ? ""
                              : option
                          )
                        }
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {invalid && (
          <span
            className={styles.repeatError}
            role="alert"
          >
            {error}
          </span>
        )}
      </fieldset>
    );
  }

  if (rule.input_type === "multi_select") {
    const allowed = (rule.allowed_values ?? []).map(String);
    const exclusiveValues = (
      rule.exclusive_values ?? []
    ).map(String);
    const selected = Array.isArray(value)
      ? value.map(String)
      : value
        ? [String(value)]
        : [];

    return (
      <fieldset
        className={`${styles.multiField} ${
          invalid ? styles.fieldInvalid : ""
        }`}
        onBlur={event => {
          if (
            !event.currentTarget.contains(
              event.relatedTarget
            )
          ) {
            onBlur?.();
          }
        }}
      >
        <div className={styles.multiHeader}>
          <legend>
            {label}
            <HelpPopover text={rule.help_text} />
          </legend>
          <span>{selected.length} selected</span>
        </div>

        {invalid && (
          <p className={styles.errorText} role="alert">
            {error}
          </p>
        )}

        <div className={styles.multiToolbar}>
          <button
            type="button"
            onClick={() =>
              onChange(
                allowed.filter(
                  option =>
                    !exclusiveValues.includes(
                      option
                    )
                )
              )
            }
            disabled={disabled}
          >
            Select all
          </button>
          <button
            type="button"
            onClick={() => onChange([])}
            disabled={disabled}
          >
            Clear
          </button>
        </div>

        <div className={styles.options}>
          {allowed.map(option => (
            <label
              key={option}
              className={
                selected.includes(option)
                  ? styles.optionSelected
                  : ""
              }
            >
              <input
                type="checkbox"
                disabled={disabled}
                checked={selected.includes(option)}
                onChange={event => {
                  onChange(
                    nextMultiSelectValue(
                      selected,
                      option,
                      event.target.checked,
                      allowed,
                      exclusiveValues
                    )
                  );
                }}
              />
              <span>{option}</span>
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  if (rule.input_type === "single_select") {
    const allowed = (rule.allowed_values ?? []).map(String);
    const selectedValue =
      value == null ? "" : String(value);

    return (
      <div
        className={`${styles.field} ${
          invalid ? styles.fieldInvalid : ""
        }`}
      >
        <span className={styles.fieldLabel}>
          {label}
          <HelpPopover text={rule.help_text} />
        </span>

        <select
          aria-label={rule.ui_prompt}
          className={invalid ? styles.inputInvalid : ""}
          disabled={disabled}
          value={selectedValue}
          onBlur={onBlur}
          onChange={event =>
            onChange(event.target.value)
          }
          aria-invalid={invalid}
        >
          <option value="">Select…</option>
          {allowed.map(option => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>

        {invalid && (
          <span className={styles.errorText} role="alert">
            {error}
          </span>
        )}
      </div>
    );
  }

  return (
    <div
      className={`${styles.field} ${
        invalid ? styles.fieldInvalid : ""
      }`}
    >
      <span className={styles.fieldLabel}>
        {label}
        <HelpPopover text={rule.help_text} />
      </span>

      <input
        aria-label={rule.ui_prompt}
        className={invalid ? styles.inputInvalid : ""}
        disabled={disabled}
        value={value ?? ""}
        onBlur={onBlur}
        onChange={event =>
          onChange(event.target.value)
        }
        aria-invalid={invalid}
      />

      {invalid && (
        <span className={styles.errorText} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export default function DictionaryForm({
  rules,
  values,
  onChange,
  derivedFields = [],
  errors = {},
  initiallyValidate = false,
  onFieldValid,
  context = {},
  prioritizeSurgeryMilestones = false,
}) {
  const [touched, setTouched] = useState({});
  // Only a review-session copy: original import files are never changed.
  const [clearedHistory, setClearedHistory] = useState([]);
  const inapplicable = inapplicablePopulatedFields(rules, values, context);

  function clearInapplicable(items, reason) {
    if (!items.length) return;
    // The action button is the user's explicit confirmation. No browser
    // dialogs or automatic loss of uploaded values.
    setClearedHistory(current => [
      ...current,
      ...items.map(item => ({ ...item, reason })),
    ]);
    items.forEach(item => onChange(item.field_name, null));
  }

  useEffect(() => {
    if (!initiallyValidate) {
      setTouched({});
      return;
    }

    const allTouched = {};

    for (const rule of rules ?? []) {
      allTouched[rule.field_name] = true;
    }

    setTouched(allTouched);
  }, [rules, initiallyValidate]);

  const visibleRules = useMemo(() => {
    const visible = (rules ?? []).filter(rule =>
      fieldIsVisible(rule, values, context)
    );
    if (!prioritizeSurgeryMilestones) return visible;
    // Surface all due postoperative assessment fields directly after the
    // date panel, while retaining the dictionary's order within each group.
    return [...visible].sort((left, right) => {
      const milestone = rule =>
        rule?.available_after_surgery_months === undefined ||
        rule?.available_after_surgery_months === null ||
        rule?.available_after_surgery_months === ""
          ? Number.POSITIVE_INFINITY
          : Number(rule.available_after_surgery_months);
      return milestone(left) - milestone(right);
    });
  }, [rules, values, context, prioritizeSurgeryMilestones]);

  function markTouched(fieldName) {
    setTouched(current => ({
      ...current,
      [fieldName]: true,
    }));
  }

  function errorFor(rule) {
    const backendError = errors?.[rule.field_name];

    if (backendError) {
      return backendError;
    }

    if (!touched[rule.field_name]) {
      return "";
    }

    const errorsNow = validateRecordAgainstRules(
      [rule],
      values,
      context
    );

    return errorsNow[rule.field_name] ?? "";
  }

  function handleChange(rule, nextValue) {
    const nextValues = {
      ...values,
      [rule.field_name]: nextValue,
    };
    // Parent changes can make child values inapplicable. Keep those values
    // available for review until the user explicitly clears them below.
    onChange(rule.field_name, nextValue);

    const nextErrors = validateRecordAgainstRules(
      [rule],
      nextValues,
      context
    );

    if (!nextErrors[rule.field_name]) {
      onFieldValid?.(rule.field_name);
    }
  }

  return (
    <div className={styles.form}>
      {inapplicable.length > 0 && (
        <section className={styles.conditionalPanel} aria-label="Conditional metadata review">
          <div className={styles.conditionalHeader}>
            <div>
              <span className={styles.conditionalEyebrow}>CONDITIONAL FIELD REVIEW</span>
              <h3>
                {inapplicable.length === 1
                  ? "1 value doesn't apply"
                  : `${inapplicable.length} values don't apply`}
              </h3>
              <p>
                These fields are inactive based on your current selections.
                Review their values before saving.
              </p>
            </div>
            <span className={styles.conditionalCount}>
              {inapplicable.length} to review
            </span>
          </div>
          <div className={styles.conditionalItems}>
            {inapplicable.map(item => (
              <div className={styles.conditionalItem} key={item.field_name}>
                <div className={styles.conditionalItemDetails}>
                  <strong>{item.label}</strong>
                  {item.parent && (
                    <span className={styles.conditionalDependency}>
                      Depends on {item.parent}
                    </span>
                  )}
                  <div className={styles.conditionalValue}>
                    <span>Current value</span>
                    <span className={styles.conditionalValueText}>
                      {formatClearedValue(item.value)}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  className={styles.conditionalClear}
                  onClick={() => clearInapplicable(
                    [item], "Cleared inapplicable value"
                  )}
                >
                  Clear value
                </button>
              </div>
            ))}
          </div>
          <div className={styles.conditionalFooter}>
            <span>The original upload is unchanged. Cleared values can be reviewed below.</span>
            {inapplicable.length > 1 && (
              <button
                type="button"
                className={styles.conditionalClearAll}
                onClick={() => clearInapplicable(
                  inapplicable, "Cleared inapplicable values"
                )}
              >
                Clear all {inapplicable.length} values
              </button>
            )}
          </div>
        </section>
      )}
      {clearedHistory.length > 0 && (
        <details className={styles.clearedHistory}>
          <summary>
            <span className={styles.clearedHistoryIcon}>✓</span>
            {clearedHistory.length} value(s) cleared
            <span className={styles.clearedHistoryHint}>View originals</span>
          </summary>
          <ul>
            {clearedHistory.map((item, index) => (
              <li key={index}>
                <strong>{item.label || item.field_name}</strong>
                <span>{formatClearedValue(item.value)}</span>
              </li>
            ))}
          </ul>
          <p>Original values are available for this editing session. The source file is unchanged.</p>
        </details>
      )}
      {visibleRules.map(rule => {
        const derived = derivedFields.includes(
          rule.field_name
        );

        return (
          <DictionaryField
            key={rule.field_name}
            rule={rule}
            value={values?.[rule.field_name]}
            values={values}
            disabled={derived}
            error={errorFor(rule)}
            onBlur={() =>
              markTouched(rule.field_name)
            }
            onChange={value =>
              handleChange(rule, value)
            }
          />
        );
      })}
    </div>
  );
}
