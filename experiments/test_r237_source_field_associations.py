"""R237 synthetic source-field proposals (no real invoices in public tests)."""
import importlib.util
from pathlib import Path
import unittest

PATH=Path(__file__).resolve().parents[1]/'integration/Engine/INVOICE_OCR_SOURCE_FIELD_ASSOCIATIONS_R237.py'
spec=importlib.util.spec_from_file_location('_r237_synthetic_source_fields',PATH)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def fixture():
    texts=['ACME','Tools and Supplies India Ltd.','HSN No',
           'CGST 2.5 + SGST 2.5','433051090 SAMPLE SHAMPOO 5ML',
           '210.49210.49','TOTAL']
    boxes=[[15,50,175,102],[15,118,255,146],[120,200,180,220],
           [70,580,230,605],[125,258,320,278],[120,654,250,675],
           [50,700,150,725]]
    return texts,boxes

class SourceFieldAssociations(unittest.TestCase):
    def test_all_three_types_keep_exact_original_source(self):
        t,b=fixture();before=[list(x) for x in b]
        result=m.propose(t,b,900,1600)
        self.assertEqual(result['proposal_count'],3)
        types={x['type']:x for x in result['proposals']}
        self.assertEqual(types['HSN_WITH_ATTACHED_ROW_SERIAL']['candidate_text'],'33051090')
        self.assertEqual(types['HSN_WITH_ATTACHED_ROW_SERIAL']['separable_serial_prefix'],'4')
        self.assertEqual(types['TWO_SOURCE_AMOUNTS_JOINED_BY_OCR']['candidate_text'],
                         ['210.49','210.49'])
        self.assertFalse(types['TWO_SOURCE_AMOUNTS_JOINED_BY_OCR']['field_column_assignment_verified'])
        self.assertEqual(types['HEADER_SUPPLIER_NAME_FRAGMENTS']['candidate_text'],
                         'ACME Tools and Supplies India Ltd.')
        self.assertEqual(types['HEADER_SUPPLIER_NAME_FRAGMENTS']['source_token_indices'],[0,1])
        self.assertEqual(b,before)
        self.assertFalse(result['accounting_write_permitted'])
        self.assertTrue(all(not x['posting_eligible'] for x in result['proposals']))

    def test_evidence_cannot_invent_hsn_without_actual_header(self):
        t,b=fixture();t[2]='HSI'
        z=m.propose(t,b,900,1600)
        self.assertNotIn('HSN_WITH_ATTACHED_ROW_SERIAL',[p['type'] for p in z['proposals']])

    def test_ordinary_nine_digit_id_not_automatically_hsn(self):
        t,b=fixture();t[4]='433051090'
        z=m.propose(t,b,900,1600)
        self.assertNotIn('HSN_WITH_ATTACHED_ROW_SERIAL',[p['type'] for p in z['proposals']])

    def test_nonadjacent_amounts_not_silently_split(self):
        t,b=fixture();t[5]='210.49  210.49'
        z=m.propose(t,b,900,1600)
        self.assertNotIn('TWO_SOURCE_AMOUNTS_JOINED_BY_OCR',[p['type'] for p in z['proposals']])

    def test_missing_tax_context_blocks_cgst_sgst_labels(self):
        t,b=fixture();t[3]='GST'
        z=m.propose(t,b,900,1600)
        self.assertNotIn('TWO_SOURCE_AMOUNTS_JOINED_BY_OCR',[p['type'] for p in z['proposals']])

    def test_header_supplier_must_be_nearby_and_spatially_related(self):
        t,b=fixture();b[1]=[380,600,600,632]
        z=m.propose(t,b,900,1600)
        self.assertNotIn('HEADER_SUPPLIER_NAME_FRAGMENTS',[p['type'] for p in z['proposals']])

    def test_city_postcode_cannot_prefix_supplier(self):
        t,b=fixture()
        t[0]='DISTRICT-572103'
        z=m.propose(t,b,900,1600)
        self.assertNotIn('HEADER_SUPPLIER_NAME_FRAGMENTS',
                         [p['type'] for p in z['proposals']])

    def test_malformed_boxes_fail_closed(self):
        t,b=fixture();b[2]=[-1,0,70,20]
        with self.assertRaises(ValueError):m.propose(t,b,900,1600)

    def test_nonpostable_even_if_valid_numeric_strings(self):
        t,b=fixture()
        z=m.propose(t,b,900,1600)
        self.assertEqual(z['accepted_field_values'],0)
        self.assertFalse(z['release_approved'])
        self.assertTrue(all(p['field_value_verified'] is False for p in z['proposals']))

if __name__=='__main__':
    unittest.main(verbosity=2)
