"""ingest_intake_form handler — validate + normalize a submitted intake form.

Stateless. Takes the form's schema (provided by caller) and the raw
submission, returns either cleaned/normalized data ready to upsert or
validation errors keyed by field id.

Normalization done here (so callers don't repeat it):
  - email: lowercase, MX-check via email-validator
  - phone: parse to E.164 via phonenumbers; respects payload.default_region
  - text/textarea: trim leading/trailing whitespace, enforce max_length
  - select/multiselect: ensure value is in the schema's option set

Validation enforced:
  - required fields present
  - field types match (text/email/phone/textarea/select/multiselect/checkbox/date)
  - max_length on text/textarea
  - select value in options
  - email parses + has MX (skipped if context.skip_mx_check=true for offline tests)
  - phone parses to E.164 (against default_region, US if not supplied)
  - consent.required → submission.consent must be true

brief.payload:
  schema (dict, required)              — the intake_form.schema JSONB
  fields (dict, required)              — submitted answers keyed by field id
  consent (bool, optional)             — visitor consent acknowledgment
  default_region (str, default 'US')   — for phone parsing
brief.context:
  skip_mx_check (bool, optional)       — bypass DNS MX lookup (CI, tests)

returns SentinelFinding.payload:
  on ok: {
    "normalized": {field_id: value, ...},
    "lead_data": {name, email, phone, consent_marketing},
    "consent_timestamp_required": bool,  # caller stamps if True
  }
  on validation_failed: {"errors": {field_id: error_message, ...}}
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from email_validator import EmailNotValidError, validate_email
import phonenumbers

from .briefs import SentinelBrief, SentinelFinding


_TEXT_TYPES = {"text", "textarea", "email", "phone", "date"}
_CHOICE_TYPES = {"select", "multiselect"}
_KNOWN_TYPES = _TEXT_TYPES | _CHOICE_TYPES | {"checkbox"}


def ingest_intake_form(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    ctx = brief.context or {}

    schema = p.get("schema")
    fields = p.get("fields")
    if not isinstance(schema, dict) or not isinstance(fields, dict):
        return SentinelFinding(
            kind="ingest_intake_form", status="error",
            reason="payload.schema (dict) and payload.fields (dict) are required",
        )

    field_specs = schema.get("fields") or []
    if not isinstance(field_specs, list):
        return SentinelFinding(
            kind="ingest_intake_form", status="error",
            reason="schema.fields must be a list",
        )

    default_region = (p.get("default_region") or "US").upper()
    skip_mx = bool(ctx.get("skip_mx_check"))

    errors: dict[str, str] = {}
    normalized: dict[str, Any] = {}

    # Pre-compute visible field ids (respecting show_if conditional display).
    visible_ids = _compute_visible_ids(field_specs, fields)

    for spec in field_specs:
        fid = spec.get("id")
        if not fid:
            errors["_schema"] = "field spec missing 'id'"
            continue

        if fid not in visible_ids:
            # Field hidden by show_if — drop any submitted value. A hidden
            # field shouldn't carry data; if the client sent one, ignore it.
            continue

        ftype = spec.get("type", "text")
        if ftype not in _KNOWN_TYPES:
            errors[fid] = f"unknown field type {ftype!r}"
            continue

        required = bool(spec.get("required"))
        raw = fields.get(fid)

        # Required check
        if required and (raw is None or (isinstance(raw, str) and not raw.strip())):
            errors[fid] = "required"
            continue
        if raw is None or (isinstance(raw, str) and not raw.strip() and not required):
            continue  # blank optional field — skip

        # Per-type validation + normalization
        if ftype in _TEXT_TYPES:
            if not isinstance(raw, str):
                errors[fid] = "expected string"
                continue
            v = raw.strip()
            max_len = spec.get("max_length")
            if isinstance(max_len, int) and len(v) > max_len:
                errors[fid] = f"max_length is {max_len}"
                continue

            if ftype == "email":
                try:
                    info = validate_email(v, check_deliverability=not skip_mx)
                    v = info.normalized.lower()
                except EmailNotValidError as e:
                    errors[fid] = f"invalid email: {e!s}"
                    continue
            elif ftype == "phone":
                try:
                    parsed = phonenumbers.parse(v, default_region)
                    if not phonenumbers.is_valid_number(parsed):
                        errors[fid] = "invalid phone number"
                        continue
                    v = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                except phonenumbers.NumberParseException as e:
                    errors[fid] = f"invalid phone: {e!s}"
                    continue
            elif ftype == "date":
                try:
                    datetime.fromisoformat(v)
                except ValueError:
                    errors[fid] = "invalid ISO date"
                    continue

            normalized[fid] = v

        elif ftype == "select":
            options = {o.get("value") for o in (spec.get("options") or [])}
            if raw not in options:
                errors[fid] = f"value not in options"
                continue
            normalized[fid] = raw

        elif ftype == "multiselect":
            if not isinstance(raw, list):
                errors[fid] = "expected list"
                continue
            options = {o.get("value") for o in (spec.get("options") or [])}
            bad = [v for v in raw if v not in options]
            if bad:
                errors[fid] = f"values not in options: {bad}"
                continue
            normalized[fid] = raw

        elif ftype == "checkbox":
            normalized[fid] = bool(raw)

    # Consent rule
    consent_required = bool((schema.get("consent") or {}).get("required"))
    consent_given = bool(p.get("consent"))
    if consent_required and not consent_given:
        errors["_consent"] = "consent required and not given"

    if errors:
        return SentinelFinding(
            kind="ingest_intake_form", status="validation_failed",
            payload={"errors": errors},
            reason=f"{len(errors)} validation error(s)",
        )

    # Build the lead_data subset — fields conventionally named name/email/phone.
    lead_data = {
        "name": _first_match(normalized, ["name", "full_name", "first_name"]),
        "email": normalized.get("email"),
        "phone": normalized.get("phone"),
        # Marketing consent is a separate checkbox (default False); see design doc §11.
        "consent_marketing": bool(normalized.get("consent_marketing", False)),
    }

    return SentinelFinding(
        kind="ingest_intake_form", status="ok",
        payload={
            "normalized": normalized,
            "lead_data": lead_data,
            "consent_timestamp_required": consent_required and consent_given,
        },
        metadata={"n_fields_normalized": len(normalized)},
        reason=f"{len(normalized)} field(s) normalized",
    )


def _compute_visible_ids(field_specs: list[dict], fields: dict) -> set[str]:
    """Apply schema.fields[].show_if rules to determine which fields render.

    show_if is intentionally simple: {"field": "<id>", "equals": <value>}.
    No AND/OR/expressions. If the referenced field isn't present, hidden.
    """
    visible: set[str] = set()
    for spec in field_specs:
        fid = spec.get("id")
        if not fid:
            continue
        cond = spec.get("show_if")
        if cond is None:
            visible.add(fid)
            continue
        ref = cond.get("field")
        expected = cond.get("equals")
        if ref is None:
            visible.add(fid)
            continue
        if fields.get(ref) == expected:
            visible.add(fid)
    return visible


def _first_match(normalized: dict, keys: list[str]) -> Optional[str]:
    for k in keys:
        v = normalized.get(k)
        if v:
            return v
    return None
