import json
from pathlib import Path
from unittest import TestCase
from core.layer4 import layer4_trust
from core.review_rules import evaluate_review, capture_evidence, decode_audit, matching_evidence
from core.output import FIELDNAMES


class ReviewRulesTests(TestCase):
    def setUp(self):
        self.meta = dict(filename='brief.txt',file_path='brief.txt',extraction_method='text',extraction_coverage='full content (50 chars)',content_sample='Readable project source with actual content.',year_confidence='high')
        self.l2 = dict(domain='Architecture',asset_type='Document',governance='Internal',certainty='High',confidentiality='Not Confidential',llm='ok',year=2022,_prescreen={},_vlm={})
        self.project = dict(year_range=[2020,2030])

    def run_rule(self, meta=None, l2=None, l3=None, path='brief.txt'):
        return layer4_trust(Path(path),dict(self.meta,**(meta or {})),dict(self.l2,**(l2 or {})),self.project,layer3=l3)

    def rules(self, result):
        return {f['rule'] for f in decode_audit(result['review_audit'])['findings']}

    def test_failed_llm_high_vlm_hint_is_not_alternative_classification(self):
        r=self.run_rule(l2=dict(llm='error: timeout',domain='Unknown',asset_type='Unknown',vlm_confidence='High'))
        self.assertEqual(r['review_priority'],'Critical')
        self.assertIn('classification_failed',self.rules(r))

    def test_usable_alternative_final_classification(self):
        r=self.run_rule(l2=dict(llm='error: primary model',domain='Architecture',asset_type='Drawing'))
        self.assertNotIn('classification_failed',self.rules(r))

    def test_unknown_domain_high(self):
        self.assertEqual(self.run_rule(l2={'domain':'Unknown'})['review_priority'],'High')

    def test_metadata_grades_high_and_original_unchanged(self):
        l3=dict(authority='High',scope='Local',coverage='Partial')
        r=self.run_rule(meta=dict(extraction_method='metadata',extraction_coverage='filename + binary header',content_sample='[DWG filename placeholder]'),l3=l3,path='plan.dwg')
        self.assertEqual(r['review_priority'],'High')
        self.assertIn('unsupported_grades',self.rules(r))
        self.assertIn('metadata_only',self.rules(r))
        self.assertEqual(l3['authority'],'High')
        self.assertEqual(r['review_reasons'].split('; ')[0], 'Ratings without readable content')
        self.assertIn('indirect information',decode_audit(r['review_audit'])['findings'][0]['reason'])

    def test_no_l3_not_a_flag(self):
        r=self.run_rule()
        self.assertEqual(self.rules(r),set())
        self.assertEqual(r['action'],'Auto-process')

    def test_successful_visual_fallback_suppresses_read_failure(self):
        r=self.run_rule(meta=dict(extraction_method='metadata',extraction_coverage='extraction failed'),l2={'_vlm':dict(visual_note='A legible plan with plots',visual_file_type='Drawing',visual_confidence='High')},l3={'scope':'High'})
        self.assertFalse({'extraction_failed','metadata_only','unsupported_grades'} & self.rules(r))

    def test_successful_ocr_after_failure(self):
        r=self.run_rule(meta=dict(extraction_method='text+ocr',extraction_coverage='vision extraction failed + OCR (120 chars)'),l3={'scope':'High'})
        self.assertNotIn('unsupported_grades',self.rules(r))

    def test_visual_confidence_alone_cannot_exempt_low_classification(self):
        r=self.run_rule(l2=dict(certainty='Low',vlm_confidence='High'))
        self.assertEqual(r['review_priority'],'Medium')
        self.assertIn('low_certainty',self.rules(r))

    def test_email_sensitive_and_drawing_conflicts_preserve_label(self):
        for path, meta, conf in [('mail.eml',{},'Not Confidential'),('salary.txt',{'filename':'salary.txt'},'Not Confidential'),('plan.dwg',{},'Confidential')]:
            r=self.run_rule(meta=meta,l2={'confidentiality':conf},path=path)
            self.assertEqual(r['review_priority'],'High')
            self.assertEqual(r['confidentiality'],conf)
            self.assertIn('confidentiality_conflict',self.rules(r))

    def test_metadata_cad_not_exempt(self):
        r=self.run_rule(meta=dict(extraction_method='metadata',extraction_coverage='extraction failed',content_sample=''),path='model.rvt')
        self.assertTrue({'metadata_only','extraction_failed'} <= self.rules(r))
        self.assertEqual(decode_audit(r['review_audit'])['queue'],'verification')

    def test_asset_governance_year_and_queue_dedup(self):
        r=self.run_rule(l2=dict(asset_type='Document',governance='Unknown',domain='Unknown',year=2010),path='table.xlsx')
        self.assertTrue({'asset_conflict','unknown_governance','project_year','unknown_domain'} <= self.rules(r))
        self.assertEqual(decode_audit(r['review_audit'])['queue'],'priority')

    def test_legacy_action_ignored_missing_evidence_disclosed(self):
        r=evaluate_review(dict(self.l2,extraction_method='metadata',extraction_coverage='extraction failed',action='Manual review old rule',authority='High',file_path='old.dwg'),self.project)
        self.assertNotIn('unsupported_grades',self.rules(r))
        self.assertNotIn('metadata_only',self.rules(r))
        self.assertTrue(decode_audit(r['review_audit'])['unavailable'])

    def test_historical_float_year(self):
        row=dict(self.l2,file_path='brief.txt',year='2010.0',year_confidence='high')
        self.assertIn('project_year',self.rules(evaluate_review(row,self.project)))

    def test_checkpoint_mismatch_not_guessed(self):
        row=dict(self.meta,**self.l2)
        checkpoint={row['file_path']:dict(l1=self.meta,l2=dict(self.l2,domain='Different'))}
        self.assertIsNone(matching_evidence(row,checkpoint))

    def test_saved_evidence_survives_audit_label_changes(self):
        original = self.run_rule(l2={'certainty': 'Low'})
        stored = decode_audit(original['review_audit'])
        stored['version'] = 'legacy-label'
        row = {**self.meta, **self.l2, 'certainty': 'Low', 'review_audit': json.dumps(stored)}
        evidence = matching_evidence(row, {})
        self.assertEqual(evidence, stored['evidence'])
        updated = evaluate_review(row, self.project, evidence=evidence)
        self.assertEqual(decode_audit(updated['review_audit'])['version'], 1)
        for field in ('review_priority', 'review_reasons', 'action'):
            self.assertEqual(updated[field], original[field])
        self.assertEqual(decode_audit(updated['review_audit'])['findings'], stored['findings'])

    def test_schema_and_structured_evidence(self):
        self.assertEqual(len(FIELDNAMES),46)
        r=self.run_rule(l2={'certainty':'Low'})
        f=decode_audit(r['review_audit'])['findings'][0]
        self.assertTrue({'rule','queue','priority','fields','reason','action'} <= f.keys())

    def test_legacy_csv_append_migrates_header(self):
        import csv
        import tempfile
        from core.output import write_rows, read_rows
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'legacy.csv'
            with path.open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=FIELDNAMES+['review_audit']);writer.writeheader();writer.writerow({'filename':'old.pdf'})
            write_rows([{'filename':'new.pdf','review_audit':'{"version":1}'}],path,mode='a')
            rows=read_rows(path)
            self.assertEqual(len(rows),2)
            self.assertNotIn('review_audit',rows[0])
            self.assertEqual(len(rows[0]),46)
            self.assertNotIn(None,rows[1])
            self.assertNotIn('review_audit',rows[1])
            saved=json.loads(Path(str(path)+'.audit.json').read_text())
            self.assertEqual(json.loads(saved['new.pdf']['review_audit'])['version'],1)

    def test_layer2_does_not_promote_low_from_visual_confidence(self):
        from core.layer2 import _apply_post_guards
        result=_apply_post_guards(
            dict(self.l2,certainty='Low',certainty_score=20),
            dict(self.meta,format='TXT'),
            {},
            vlm_hint=dict(visual_confidence='High',visual_file_type='Drawing',visual_discipline='Architecture',visual_note='A clear drawing'),
        )
        self.assertEqual(result['certainty'],'Low')
        self.assertEqual(result['_classification_certainty_raw'],'Low')
