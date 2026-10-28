"""Offline audit of saved experiments. No LLM or source-file reads; originals unchanged."""
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml
from core.output import write_rows
from core.review_rules import evaluate_review, decode_audit, checkpoint_evidence, matching_evidence


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_project(path, destination):
    original_hash = digest(path)
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        raw = list(reader)
    unique = {r.get('file_path') or r['filename']: r for r in reversed(raw)}
    rows = list(reversed(list(unique.values())))
    snapshot = Path(str(path)+'.config.yaml')
    config = yaml.safe_load(snapshot.read_text()) if snapshot.exists() else {}
    project = dict(config.get('project') or {})
    project['age_analysis'] = config.get('age_analysis') or project.get('age_analysis', {})
    review_path = Path(str(path)+'.reviews.json')
    reviews = json.loads(review_path.read_text()) if review_path.exists() else {}
    reviewed = set(reviews.get('reviewed', []))
    old_priority = {r['file_path'] for r in rows if r.get('review_priority') in {'Critical','Urgent','High','Medium'}}
    old_expanded = old_priority | {r['file_path'] for r in rows if __import__('re').search(r'\b(manual|verify|review)\b', r.get('action',''), __import__('re').I)}
    old_reasons = Counter(reason.strip() for r in rows for reason in r.get('review_reasons','').split(',') if reason.strip())
    counts, limits, priority_set, verify_set, overlap, cases = Counter(), Counter(), set(), set(), set(), []
    result_rows = []
    checkpoints = checkpoint_evidence(path)
    matched = 0
    new_priority = Counter()
    example_rules = set()
    reason_overlaps = Counter()
    for r in rows:
        key = r['file_path']
        original = dict(r)
        evidence = matching_evidence(r, checkpoints)
        matched += int(evidence is not None)
        edits = reviews.get('edits',{}).get(key,{})
        r.update({k:v for k,v in edits.items() if k in r and k not in {'file_path','filename'}})
        result = evaluate_review(r, project, config.get('layer2_settings'), evidence)
        r.update(result)
        audit = decode_audit(result['review_audit'])
        findings = audit['findings']
        queues = {f['queue'] for f in findings}
        if 'priority' in queues: priority_set.add(key)
        if 'verification' in queues: verify_set.add(key)
        if len(queues) == 2: overlap.add(key)
        counts.update(f['rule'] for f in findings)
        from itertools import combinations
        reason_overlaps.update(' + '.join(pair) for pair in combinations(sorted(f['rule'] for f in findings),2))
        limits.update(audit['unavailable'])
        new_priority[result['review_priority']] += 1
        if findings and any(f['rule'] not in example_rules for f in findings):
            example_rules.update(f['rule'] for f in findings)
            cases.append(dict(filename=r['filename'],file_path=key,queue=audit['queue'],input={k:original.get(k,'') for k in ['extraction_method','extraction_coverage','certainty','llm_status','domain','asset_type','confidentiality','governance','year','year_confidence',*('authority','scope','urgency','coverage','accessibility')]},findings=findings,unavailable=audit['unavailable']))
        result_rows.append(r)
    report = dict(project=path.stem,matched_checkpoints=matched,checkpoint_sha256=digest(Path(str(path)+'.resume.jsonl')) if Path(str(path)+'.resume.jsonl').exists() else None,config_sha256=digest(snapshot) if snapshot.exists() else None,original_sha256=original_hash,rows=len(raw),unique_files=len(rows),reviewed=len(reviewed),
                  before=dict(priority=len(old_priority),legacy_action_expanded=len(old_expanded),priority_pending=len(old_priority-reviewed),legacy_reason_counts=dict(old_reasons)),
                  after=dict(priority=len(priority_set),verification_including_overlap=len(verify_set),overlap=len(overlap),verification_only=len(verify_set-priority_set),combined=len(priority_set|verify_set),
                             priority_pending=len(priority_set-reviewed),verification_only_pending=len((verify_set-priority_set)-reviewed),combined_pending=len((priority_set|verify_set)-reviewed),priority_distribution=dict(new_priority)),
                  reason_counts=dict(counts),reason_pair_overlaps=dict(reason_overlaps),unavailable_counts=dict(limits),cases=cases,
                  interpretation='Rule-trigger counts only. No source or human validation performed. Legacy actions are baseline only, never inputs to review rules.')
    destination.mkdir(parents=True, exist_ok=True)
    out = destination/(path.stem+'.review.csv')
    if out.resolve() == path.resolve(): raise ValueError('Refusing to overwrite source')
    write_rows(result_rows, out)
    (destination/(path.stem+'.report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    assert digest(path)==original_hash
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('outputs/review'))
    parser.add_argument('csv',nargs='+',type=Path,help='Saved experiment CSV files to audit locally')
    args=parser.parse_args()
    reports=[audit_project(p,args.output) for p in args.csv]
    (args.output/'summary.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    for r in reports:
        print(r['project'],json.dumps({'before':r['before']['priority'],'after':r['after'],'reasons':r['reason_counts']},ensure_ascii=False))


if __name__=='__main__':main()
