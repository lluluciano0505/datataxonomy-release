"""Layer 4 evidence-based review. Guards flag conflicts without rewriting judgments."""
from datetime import datetime
from pathlib import Path
import logging
import re
from .output import is_extraction_failed

logger = logging.getLogger(__name__)

# Formats that are definitively data/tabular regardless of LLM label.
_DATA_FORMATS = {".csv", ".xlsx", ".xls", ".json", ".shp", ".geojson", ".kml", ".gpkg"}

# Drawing/CAD formats for a review heuristic; confidentiality is not inferred as fact.
_DRAWING_FORMATS = {".dwg", ".dxf", ".dwf", ".ifc", ".rvt", ".nwd"}

# Sensitive terms used to flag conflicts; never override model labels.
_SENSITIVE_TERMS = {
    # Financial — personal or firm-level only (not generic project cost docs)
    "payroll", "salary", "bank account", "account number",
    "balance sheet", "income statement", "profit and loss",
    "financial statement", "financial record",
    # Legal
    "legal advice", "legal counsel", "without prejudice", "privileged",
    "litigation", "settlement", "non-disclosure", "nda",
    # Personnel / HR
    "personnel record", "staff record", "disciplinary", "performance review",
    "termination", "employment record", "hr record", "grievance",
    "medical record", "health insurance",
    # Security / access
    "security clearance", "classified", "clearance level",
    "evacuation plan", "emergency protocol",
    # Explicit markers
    "strictly confidential", "private and confidential",
    "internal only", "not for distribution", "for internal use",
    "eyes only", "secret", "top secret",
}

# Word-boundary-anchored patterns for the terms above. A plain `term in text`
# substring check false-positives badly on ordinary AEC vocabulary — "nda"
# (meant to catch the "NDA" acronym) matches inside "age NDA", "seco NDA ry",
# "bou NDA ry" — so every filename containing "agenda", "secondary", or
# "boundary" was silently tripping the confidentiality guard. Matching is
# anchored on non-alphanumeric boundaries (not just \b) so separators like
# "_" and "-" — common in filenames — still count as word breaks.
_SENSITIVE_TERM_PATTERNS = [
    re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")
    for term in _SENSITIVE_TERMS
]


# ── Guard helpers ─────────────────────────────────────────────────────────────

def _normalize_confidentiality(value: str) -> str:
    v = str(value or "").strip().lower()
    if v == "confidential":
        return "Confidential"
    return "Not Confidential"


def _is_drawing_like(file_path: Path, layer2: dict) -> bool:
    ext       = file_path.suffix.lower()
    info_type = str(layer2.get("information_type", "")).lower()
    asset     = str(layer2.get("asset_type", "")).strip().lower()
    if ext in _DRAWING_FORMATS:
        return True
    if asset == "drawing":
        return True
    return info_type in {"technical", "bim"}


def _apply_confidentiality_guard(
    file_path: Path,
    meta: dict,
    layer2: dict,
) -> dict:
    """Detect guard signals for confidentiality review (no modifications).

    Returns dict with:
      confidentiality: LLM's judgment (unchanged)
      confidentiality_reason: LLM's reason + guard signal
      guard_signal: human-readable description of what the guard detected
    """
    conf   = _normalize_confidentiality(layer2.get("confidentiality", "Not Confidential"))
    reason = str(layer2.get("confidentiality_reason", "")).strip()
    signal = ""

    # Email files always need review if LLM missed it
    if file_path.suffix.lower() in {".eml", ".msg", ".mbox"}:
        if conf != "Confidential":
            signal = "Email file should always be Confidential — review needed"

    # Detect sensitive terms — important for review if LLM disagreed
    filename    = str(meta.get("filename", "")).lower()
    content     = str(meta.get("content_sample", "")).lower()
    signal_blob = f"{filename}\n{content[:3000]}"
    has_sensitive_term = any(p.search(signal_blob) for p in _SENSITIVE_TERM_PATTERNS)
    if has_sensitive_term and conf != "Confidential":
        signal = "Sensitive term detected — LLM judgment conflicts with content signal"

    # Detect drawing-like files — important for review if LLM said Confidential
    is_drawing_like = _is_drawing_like(file_path, layer2)
    if is_drawing_like and conf == "Confidential" and not has_sensitive_term:
        signal = "Drawing-like file marked Confidential without sensitive term — review needed"

    return {
        "confidentiality": conf,
        "confidentiality_reason": reason,
        "guard_signal": signal,
    }


def _apply_data_asset_guard(
    file_path: Path,
    meta: dict,
    layer2: dict,
    settings: dict | None = None,
) -> dict:
    """Detect guard signals for asset type review (no modifications).

    Returns dict with:
      asset_type: LLM's judgment (unchanged)
      is_data_asset: based on LLM's asset_type
      guard_signal: human-readable description of what the guard detected
    """
    asset = str(layer2.get("asset_type", "Unknown")).strip()

    data_formats = _DATA_FORMATS
    if settings:
        raw = settings.get("data_formats")
        if raw:
            data_formats = {str(f).lower() if f.startswith(".") else f".{f.lower()}" for f in raw}

    ext = file_path.suffix.lower()
    prescreen = layer2.get("_prescreen") or {}
    pre_likelihood = str(prescreen.get("data_likelihood", "")).strip().lower()

    is_data_format = ext in data_formats or pre_likelihood in {"likely", "possible"}

    signal = ""
    # Detect conflict: format suggests data but LLM said generic label
    if is_data_format and asset.lower() in {"", "unknown", "document", "other"}:
        signal = f"Format {ext} suggests data, but LLM classified as {asset} — review recommended"

    is_data = "Yes" if asset.lower() == "data" else "No"
    return {
        "asset_type": asset,
        "is_data_asset": is_data,
        "guard_signal": signal,
    }




def _age_warning(
    file_year: int,
    project_start: int,
    project_end: int,
    current_year: int,
    min_valid_year: int = 2000,
    warn_predates_years: int = 10,
    warn_postproject_years: int = 3,
    year_is_reliable: bool = True,
) -> str:
    """Return an age warning string, or '' if no warning is needed.

    Severity:
      ''         — no anomaly
      'NOTICE: ' — informational
      'WARNING:' — significant anomaly
    """
    if file_year < min_valid_year or file_year > current_year:
        return ""

    if file_year < project_start:
        years_before = project_start - file_year
        if years_before > warn_predates_years:
            msg = (f"dated {file_year} — {years_before} years before "
                   f"project start ({project_start}), verify relevance")
            if year_is_reliable:
                return f"WARNING: {msg}"
            return f"NOTICE: {msg} (year from OS mtime — low confidence)"
        if not year_is_reliable:
            return ""
        return f"NOTICE: dated {file_year} — predates project start ({project_start})"

    if file_year <= project_end:
        return ""

    years_after = file_year - project_end
    if years_after > warn_postproject_years and year_is_reliable:
        return f"NOTICE: dated {file_year} — {years_after} years after project end ({project_end})"
    return ""


def layer4_trust(
    file_path: Path,
    meta: dict,
    layer2: dict,
    project: dict,
    settings: dict | None = None,
    layer3: dict | None = None,
) -> dict:
    """Capture actual L1/L2 evidence and evaluate shared rules against L3 outputs.

    Original model labels and grades are retained. Findings include rule IDs,
    checked fields, reasons and suggested human checks in review_audit.
    """
    from .review_rules import capture_evidence, evaluate_review
    row = dict(meta)
    row.update(layer2)
    row.update(layer3 or {})
    row['file_path'] = str(file_path)
    row['year'] = layer2.get('year') or meta.get('year')
    row['year_confidence'] = layer2.get('year_confidence') or meta.get('year_confidence', '')
    result = evaluate_review(row, project, settings, capture_evidence(meta, layer2))
    asset = layer2.get('asset_type', 'Unknown')
    result.update(asset_type=asset, is_data_asset='Yes' if str(asset).lower() == 'data' else 'No',
                  governance=layer2.get('governance', 'Unknown'),
                  confidentiality=layer2.get('confidentiality', 'Not Confidential'),
                  confidentiality_reason=layer2.get('confidentiality_reason', ''))
    return result
