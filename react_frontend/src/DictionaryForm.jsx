import styles from "./DictionaryForm.module.css";

export function conditionMatches(rule, values) {
  if (!rule?.required_if_field) return true;

  const current = values?.[rule.required_if_field];
  const expected = rule.required_if_value;
  const operator = String(
    rule.required_if_operator ?? ""
  ).toLowerCase();

  const currentValues = Array.isArray(current)
    ? current.map(String)
    : [String(current ?? "")];
  const expectedValues = Array.isArray(expected)
    ? expected.map(String)
    : [String(expected ?? "")];

  const matches = expectedValues.some(value =>
    currentValues.includes(value)
  );

  if (
    operator.includes("not") ||
    operator === "!=" ||
    operator === "not_equals"
  ) {
    return !matches;
  }

  return matches;
}

export function DictionaryField({
  rule,
  value,
  onChange,
  disabled = false,
}) {
  const label = `${rule.ui_prompt}${
    rule.required
      ? " *"
      : rule.required_if_field
        ? " * when applicable"
        : ""
  }`;

  if (rule.input_type === "multi_select") {
    const allowed = rule.allowed_values ?? [];
    const selected = Array.isArray(value)
      ? value.map(String)
      : value
        ? [String(value)]
        : [];

    return (
      <fieldset className={styles.multiField}>
        <div className={styles.multiHeader}>
          <legend>{label}</legend>
          <span>{selected.length} selected</span>
        </div>

        {rule.help_text && (
          <p className={styles.help}>{rule.help_text}</p>
        )}

        <div className={styles.multiToolbar}>
          <button
            type="button"
            onClick={() => onChange([...allowed])}
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
                  const next = event.target.checked
                    ? [...new Set([...selected, option])]
                    : selected.filter(item => item !== option);
                  onChange(
                    allowed.filter(item => next.includes(item))
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

  return (
    <label className={styles.field}>
      <span>
        {label}
        {rule.help_text && (
          <small title={rule.help_text}>?</small>
        )}
      </span>

      {rule.input_type === "single_select" ? (
        <select
          disabled={disabled}
          value={value ?? ""}
          onChange={event => onChange(event.target.value)}
        >
          <option value="">Select…</option>
          {(rule.allowed_values ?? []).map(option => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <input
          disabled={disabled}
          value={value ?? ""}
          onChange={event => onChange(event.target.value)}
        />
      )}
    </label>
  );
}

export default function DictionaryForm({
  rules,
  values,
  onChange,
  derivedFields = [],
}) {
  return (
    <div className={styles.form}>
      {(rules ?? [])
        .filter(rule => conditionMatches(rule, values))
        .map(rule => {
          const derived = derivedFields.includes(
            rule.field_name
          );

          return (
            <DictionaryField
              key={rule.field_name}
              rule={rule}
              value={values?.[rule.field_name]}
              disabled={derived}
              onChange={value =>
                onChange(rule.field_name, value)
              }
            />
          );
        })}
    </div>
  );
}
