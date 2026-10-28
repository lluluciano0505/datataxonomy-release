"""Versioned evidence checks, not validation of summary facts or grade correctness."""
import json
import re
from pathlib import Path
from datetime import datetime
from .output import is_extraction_failed

VERSION = 1  # Review audit schema version.
LABELS = {
    'classification_failed': 'Classification failed',
    'unknown_domain': 'Unknown domain',
    'unsupported_grades': 'Ratings without readable content',
    'confidentiality_conflict': 'Confidentiality conflict',
    'low_certainty': 'Low classification confidence',
    'extraction_failed': 'Content extraction failed',
    'metadata_only': 'Metadata-only classification',
    'asset_conflict': 'Asset type conflict',
    'unknown_governance': 'Unknown source',
    'project_year': 'Project date mismatch',
}
GRADES = ('authority', 'scope', 'urgency', 'coverage', 'accessibility')


def decode_audit(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or '{}')
    except (ValueError, TypeError):
        return {}


def capture_evidence(meta, l2):
    from .layer4 import _SENSITIVE_TERMS
    blob = (str(meta.get('filename', '')) + '\n' + str(meta.get('content_sample', ''))[:3000]).lower()
    sources = []
    for field, text in [('filename', str(meta.get('filename',''))), ('content_sample', str(meta.get('content_sample',''))[:3000])]:
        for term in sorted(_SENSITIVE_TERMS):
            match = re.search(r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])', text.lower())
            if match:
                sources.append(dict(term=term, field=field, excerpt=text[max(0,match.start()-30):match.end()+30]))
    matches = sorted(t for t in _SENSITIVE_TERMS if re.search(r'(?<![a-z0-9])'+re.escape(t)+r'(?![a-z0-9])', blob))
    evidence = {
        'content_sample_length': len(str(meta.get('content_sample', '')).strip()),
        'sensitive_terms': matches,
        'sensitive_term_sources': sources,
        'visual_result': l2.get('_vlm') or {},
        'prescreen': l2.get('_prescreen') or {},
        'classification_certainty_raw': l2.get('_classification_certainty_raw'),
        'llm_status': str(l2.get('llm', '')),
    }
    if '_classification_certainty_raw' not in l2:
        evidence.pop('classification_certainty_raw')
    return evidence


def content_state(row, evidence):
    """Use final L1 result plus actual supplementary visual output; never confidence alone."""
    method = str(row.get('extraction_method', '')).strip().lower()
    coverage = str(row.get('extraction_coverage', '')).lower()
    visual = evidence.get('visual_result') or {}
    visual_ok = (bool(str(visual.get('visual_note', '')).strip())
                 and str(visual.get('visual_file_type', '')).lower() not in {'', 'unknown'}
                 and visual.get('visual_confidence') in {'Medium', 'High'})
    if visual_ok:
        return 'available'
    metadata = method == 'metadata' or any(t in coverage for t in ('filename +', 'binary header', 'signals only'))
    if metadata:
        return 'absent'
    # Positive final read evidence takes precedence over a failed earlier attempt.
    chars = re.findall(r'(\d+) chars', coverage)
    success = any(int(n) > 0 for n in chars) or bool(re.search(r'\+ OCR|\d+ (slides|of .*sheets)|all \d+ sheet|IFC header|ezdxf', coverage, re.I))
    if success:
        return 'available'
    if is_extraction_failed(coverage):
        return 'absent'
    length = evidence.get('content_sample_length')
    if length is not None:
        return 'available' if length > 0 else 'absent'
    # Historic CSV only: an explicitly successful final method/coverage is partial evidence.
    if method in {'text', 'text+ocr', 'ocr', 'vision', 'converted'} and coverage and not re.search(r'\b0 chars\b|blank|no content', coverage):
        return 'available'
    return 'unknown'


def evaluate_review(row, project=None, settings=None, evidence=None):
    from .layer4 import _age_warning, _apply_data_asset_guard, _is_drawing_like
    row = dict(row)
    stored = decode_audit(row.get('review_audit'))
    evidence = dict(evidence if evidence is not None else stored.get('evidence', {}))
    project = project or {}
    findings, unavailable = [], []
    def add(rule, queue, priority, fields, why, action):
        findings.append(dict(rule=rule, queue=queue, priority=priority, fields=fields, reason=why, action=action))
    def val(k):
        return str(row.get(k, '') or '').strip()
    path = Path(val('file_path') or val('filename'))
    state = content_state(row, evidence)
    if state == 'absent' and 'visual_result' not in evidence:
        state = 'unknown'  # Historical L2 visual fallback was not persisted.
    fields = {k: row.get(k, '') for k in ('extraction_method','extraction_coverage')}
    fields.update(content_state=state, content_sample_length=evidence.get('content_sample_length'), visual_result=evidence.get('visual_result'))
    if 'visual_result' not in evidence:
        unavailable.append('supplementary_visual_read: not persisted; absence cannot exclude a successful L2 visual read')
    if 'content_sample_length' not in evidence:
        unavailable.append('actual_content_sample: not persisted; content state uses final method/coverage only')
    status = evidence.get('llm_status', val('llm_status'))
    if str(status).lower().startswith('error'):
        # A high-confidence image hint is not a replacement classification.
        alternative = val('domain').lower() not in {'','unknown','none'} and val('asset_type').lower() not in {'','unknown','none'}
        if not alternative:
            add('classification_failed','priority','Critical',dict(llm_status=status,domain=val('domain'),asset_type=val('asset_type')), 'LLM classification failed and no usable final domain/asset classification is recorded.', 'Manual classification: open the source and assign domain and asset type.')
    if val('domain').lower() in {'','unknown','none'}:
        add('unknown_domain','priority','High',{'domain':val('domain')}, 'No usable primary domain is recorded.', 'Manual classification: inspect the source and select a primary domain.')
    populated = {k:row[k] for k in GRADES if val(k) and val(k).lower() not in {'unknown','none','nan','not rated','n/a'}}
    if state == 'absent' and populated:
        add('unsupported_grades','priority','High',dict(fields, **populated), 'No usable content is recorded, but Layer 3 grades are populated. The recorded grades therefore rely on indirect information such as filename, directory or generated classification/summary rather than a successful recorded content read.', 'Review the source before using these grades; verify the evidence for each populated grade.')
    conf = val('confidentiality')
    terms = evidence.get('sensitive_terms')
    # Even without content, filename matches can be checked retrospectively.
    from .layer4 import _SENSITIVE_TERMS
    filename_terms = sorted(t for t in _SENSITIVE_TERMS if re.search(r'(?<![a-z0-9])'+re.escape(t)+r'(?![a-z0-9])', path.name.lower()))
    terms = sorted(set((terms or []) + filename_terms))
    email = path.suffix.lower() in {'.eml','.msg','.mbox'}
    drawing = _is_drawing_like(path, row)
    conflict = (conf.lower() != 'confidential' and (email or terms)) or (conf.lower() == 'confidential' and drawing and not terms and 'sensitive_terms' in evidence)
    if conflict:
        add('confidentiality_conflict','priority','High',dict(confidentiality=conf,extension=path.suffix,email=email,sensitive_terms=terms,sensitive_term_sources=evidence.get('sensitive_term_sources', []),drawing_like=drawing), 'The original confidentiality label conflicts with the email/sensitive-term/drawing heuristic. This heuristic is a review signal, not proof of confidentiality.', 'Confirm confidentiality against the source and access policy; retain the original label until reviewed.')
    if 'sensitive_terms' not in evidence:
        unavailable.append('content_sensitive_terms: sample not persisted; content matches and drawing-without-sensitive-term conflict cannot be reconstructed')
    raw_cert = evidence.get('classification_certainty_raw')
    if str(raw_cert).lower() == 'low' or val('certainty').lower() == 'low':
        add('low_certainty','priority','Medium',dict(certainty=val('certainty'),classification_certainty_raw=raw_cert,certainty_reason=val('certainty_reason')), 'Classification certainty is Low; visual recognition confidence does not establish final classification certainty.', 'Check domain, asset type and classification rationale against the source.')
    if 'classification_certainty_raw' not in evidence:
        unavailable.append('raw_classification_certainty: not persisted; prior visual confidence promotions cannot be reversed')
    if state == 'absent' and is_extraction_failed(val('extraction_coverage')):
        add('extraction_failed','verification','Low',fields, 'Final reading reports extraction failure and no successful alternative reading is recorded.', 'Open the source; retry a suitable parser, OCR or visual reading, or record inaccessible content.')
    if val('extraction_method').lower() == 'metadata' and state == 'absent':
        add('metadata_only','verification','Low',fields, 'Classification relies on metadata/filename/directory rather than usable content, including unsupported CAD/BIM.', 'Inspect the original file with a compatible viewer and confirm classification.')
    if state == 'unknown':
        unavailable.append('content_dependent_rules: insufficient reading evidence to determine content availability')
    prescreen = evidence.get('prescreen', {})
    asset_row = dict(row, _prescreen=prescreen)
    guard = _apply_data_asset_guard(path, {}, asset_row, settings)
    from .layer4 import _DATA_FORMATS
    formats = (settings or {}).get('data_formats') or _DATA_FORMATS
    formats = {'.'+str(f).lower().lstrip('.') for f in formats}
    if path.suffix.lower() in formats and val('asset_type').lower() != 'data':
        guard['guard_signal'] = f"Format {path.suffix} suggests Data, but asset_type={val('asset_type')}."
    elif str(prescreen.get('data_likelihood','')).lower() == 'unlikely' and val('asset_type').lower() == 'data':
        guard['guard_signal'] = 'Prescreen data_likelihood=Unlikely conflicts with asset_type=Data.'
    if guard['guard_signal']:
        add('asset_conflict','verification','Low',dict(extension=path.suffix,asset_type=val('asset_type'),prescreen=prescreen), guard['guard_signal'], 'Inspect the file structure and confirm asset type; retain the model label until reviewed.')
    if 'prescreen' not in evidence:
        unavailable.append('prescreen_asset_conflict: prescreen not persisted; only format-based conflict is checked')
    if val('governance').lower() in {'','unknown','none'}:
        add('unknown_governance','verification','Low',{'governance':val('governance')}, 'Source/governance is not established.', 'Verify issuer, ownership or source context and set governance.')
    age = ''
    yr = project.get('year_range') or []
    if len(yr) >= 2:
        try:
            age = _age_warning(int(float(val('year').split()[0])),int(yr[0]),int(yr[1]),datetime.now().year,year_is_reliable=val('year_confidence').lower() in {'high','medium'},**{k:v for k,v in project.get('age_analysis',{}).items() if k in {'min_valid_year','warn_predates_years','warn_postproject_years'}})
        except (ValueError, IndexError, TypeError):
            unavailable.append('year_check: missing/unparseable year')
    else:
        unavailable.append('year_check: project time range unavailable')
    if age:
        add('project_year','verification','Low',dict(year=val('year'),year_confidence=val('year_confidence'),year_range=yr), age, 'Verify the date and relevance to the project timeline.')
    priorities = [f['priority'] for f in findings if f['queue']=='priority']
    priority = min(priorities,key=lambda x: {'Critical':0,'High':1,'Medium':2}[x]) if priorities else 'Low'
    queue = 'priority' if priorities else 'verification' if findings else 'none'
    reasons = '; '.join(LABELS[f['rule']] for f in findings)
    audit = dict(version=VERSION,queue=queue,findings=findings,unavailable=unavailable,evidence=evidence,content_state=state)
    return dict(review_priority=priority,review_reasons=reasons,action=' → '.join(dict.fromkeys(f['action'] for f in findings)) or 'Auto-process',age_warning=age,review_audit=json.dumps(audit,ensure_ascii=False))


def checkpoint_evidence(csv_path):
    """Read existing intermediates only. No source stat/read or model requests."""
    checkpoint = Path(str(csv_path) + '.resume.jsonl')
    records = {}
    if checkpoint.exists():
        with checkpoint.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                    records[item['file_path']] = item
                except (ValueError, KeyError):
                    continue
    sidecar = Path(str(csv_path) + '.audit.json')
    if sidecar.exists():
        try:
            for key, saved in json.loads(sidecar.read_text(encoding='utf-8')).items():
                records.setdefault(key, {})['_saved_audit'] = saved
        except (ValueError, OSError):
            pass
    return records


def matching_evidence(row, checkpoints):
    stored = decode_audit(row.get('review_audit'))
    # Recorded evidence remains usable across audit naming/schema revisions.
    if (isinstance(stored.get('evidence'), dict)
            and isinstance(stored.get('findings'), list)
            and stored.get('queue') in {'priority', 'verification', 'none'}):
        return stored['evidence']
    item = checkpoints.get(row.get('file_path'))
    saved = (item or {}).get('_saved_audit', {})
    if saved and all(str(row.get(k,'')) == str(v) for k,v in saved.get('match',{}).items()):
        return decode_audit(saved.get('review_audit')).get('evidence')
    if not item or not all(str(item.get('l2',{}).get(k,'')) == str(row.get(k,'')) for k in ('domain','asset_type','certainty')) or not all(str(item.get('l1',{}).get(k,'')) == str(row.get(k,'')) for k in ('extraction_method','extraction_coverage')):
        return None
    l1, l2 = item['l1'], item['l2']
    evidence = capture_evidence(l1,l2)
    if '_classification_certainty_raw' not in l2:
        evidence.pop('classification_certainty_raw', None)
    if '_vlm' not in l2:
        evidence.pop('visual_result', None)
    if '_prescreen' not in l2:
        evidence.pop('prescreen', None)
    evidence['source'] = 'matching L1/L2 checkpoint (path, domain, asset, certainty, final method/coverage)'
    return evidence
