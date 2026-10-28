import csv
import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from server.dashboard_server import app, _data_cache
from core.output import FIELDNAMES
from core.layer4 import layer4_trust


class DashboardReviewTests(TestCase):
    def test_api_export_identity_and_human_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'experiment.csv'
            rows=[]
            for fp, domain, governance, legacy in [('a/same.pdf','Unknown','Internal',''),('b/same.pdf','Architecture','Unknown',''),('c/old.pdf','Architecture','Internal','Manual review from old rule'),('d/done.pdf','Unknown','Internal','')]:
                row={k:'' for k in FIELDNAMES}
                row.update(filename=Path(fp).name,file_path=fp,domain=domain,governance=governance,asset_type='Document',certainty='High',confidentiality='Not Confidential',extraction_method='text',extraction_coverage='full content (100 chars)',action=legacy,short_summary='Keep original')
                rows.append(row)
            with path.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=FIELDNAMES);w.writeheader();w.writerows(rows)
            original=path.read_bytes()
            Path(str(path)+'.reviews.json').write_text(json.dumps({'reviewed':['d/done.pdf'],'edits':{'d/done.pdf':{'short_summary':'Human edited summary'}}}))
            client=app.test_client()
            data=client.get('/api/data',query_string={'csv':str(path)}).json
            self.assertEqual(data['count'],4)
            returned={r['file_path']:r for r in data['rows']}
            self.assertEqual(returned['d/done.pdf']['short_summary'],'Human edited summary')
            self.assertEqual(json.loads(returned['c/old.pdf']['review_audit'])['queue'],'none')
            for scope,expected in [('priority',{'a/same.pdf'}),('verification',{'b/same.pdf'}),('verify',{'a/same.pdf','b/same.pdf'})]:
                response=client.post('/api/download-filtered',json={'csv':str(path),'review_scope':scope})
                exported=list(csv.DictReader(io.StringIO(response.data.decode())))
                self.assertEqual({r['file_path'] for r in exported},expected)
                for r in exported:
                    self.assertEqual(len(r),46)
                    self.assertNotIn('review_audit',r)
                    self.assertEqual(r['review_reasons'],returned[r['file_path']]['review_reasons'])
            response=client.post('/api/download-filtered',json={'csv':str(path),'file_paths':['b/same.pdf']})
            self.assertEqual(len(list(csv.DictReader(io.StringIO(response.data.decode())))),1)
            response=client.post('/api/download-filtered',json={'csv':str(path),'file_paths':[]})
            self.assertEqual(list(csv.DictReader(io.StringIO(response.data.decode()))),[])
            self.assertEqual(path.read_bytes(),original)
            _data_cache.pop(str(path),None)
