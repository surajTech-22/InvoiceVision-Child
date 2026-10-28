"""R231 immutable-source review queue tests: no private invoices, no posting."""
import copy
import hashlib
import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/'integration/Engine/INVOICE_OCR_REVIEW_QUEUE_R231.py'
spec=importlib.util.spec_from_file_location('r231_test_review_queue',FILE)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def case():
    return {'source_sha256':hashlib.sha256(b'REVIEW_QUEUE_SYNTHETIC_FRAME').hexdigest(),
            'source_width':400,'source_height':250,
            'raw_texts':['Products','HSN Code','Coffee Beans','09011110','31/00/2026'],
            'raw_boxes':[[10,10,90,25],[170,10,255,25],[10,60,142,77],
                         [180,60,240,77],[10,180,100,195]]}

def source():
    return ({'posting_eligible':False,'tables':[{'rows':[{'source_indices':[2,3]}]}]},
            {'posting_eligible':False,'baseline_merged_row_warnings':[],
             'total_provisional_rows':1,'orientation_tables':[],'hsn_anchor_rows':[]},
            [{'source_token_index':4}])

class SourceQueue(unittest.TestCase):
    def test_exact_source_items_and_no_approval(self):
        c=case();a,b,dates=source();before=copy.deepcopy((c,a,b,dates))
        result=module.build(c,a,b,dates)
        self.assertEqual(result['total_review_items'],2)
        self.assertEqual(result['item_proposals'],1)
        self.assertEqual(result['date_proposals'],1)
        self.assertEqual([x['source_token_indices'] for x in result['items']],[[2,3],[4]])
        self.assertEqual((c,a,b,dates),before)
        self.assertTrue(all(x['review_required'] and not x['posting_eligible']
                            and x['human_annotation'] is None for x in result['items']))
        self.assertFalse(result['accounting_write_permitted'])
        self.assertFalse(result['release_approved'])

    def test_deterministic_tamper_evident_identity(self):
        c=case();a,b,d=source()
        first=module.build(c,a,b,d)['items'][0]['review_id']
        self.assertEqual(first,module.build(c,a,b,d)['items'][0]['review_id'])
        c['raw_texts'][3]='09011111'
        self.assertNotEqual(first,module.build(c,a,b,d)['items'][0]['review_id'])

    def test_missing_source_token_rejected(self):
        c=case();a,b,d=source()
        a['tables'][0]['rows'][0]['source_indices']=[2,12]
        with self.assertRaises(ValueError):module.build(c,a,b,d)

    def test_outside_source_geometry_rejected(self):
        c=case();a,b,d=source();c['raw_boxes'][2]=[-1,0,8,8]
        with self.assertRaises(ValueError):module.build(c,a,b,d)

    def test_repeated_identical_group_rejected(self):
        c=case();a,b,d=source()
        a['tables'].append({'rows':[{'source_indices':[2,3]}]})
        b['total_provisional_rows']=2
        with self.assertRaises(ValueError):module.build(c,a,b,d)

    def test_mismatched_group_count_fail_closed(self):
        c=case();a,b,d=source();b['total_provisional_rows']=2
        with self.assertRaises(ValueError):module.build(c,a,b,d)

    def test_unsafe_marked_postable_input_rejected(self):
        c=case();a,b,d=source();a['posting_eligible']=True
        with self.assertRaises(ValueError):module.build(c,a,b,d)

    def test_date_token_missing_fails_closed(self):
        c=case();a,b,d=source();d=[{'source_token_index':9999}]
        with self.assertRaises(ValueError):module.build(c,a,b,d)

if __name__=='__main__':
    unittest.main(verbosity=2)
