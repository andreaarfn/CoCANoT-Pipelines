"""Simple result helpers used by the metadata validator."""

VALID = "valid"
INVALID = "invalid"
MANUAL_REVIEW = "manual_review"
NOT_APPLICABLE = "not_applicable"
MISSING_REQUIRED = "missing_required"


def field_result(field_name, value, status, code, message, allowed_values=None):
    """Create one consistent field-level validation result."""
    result = {
        "field_name": field_name,
        "value": value,
        "status": status,
        "code": code,
        "message": message,
    }

    if allowed_values is not None:
        result["allowed_values"] = allowed_values

    return result
