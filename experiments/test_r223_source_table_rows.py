"""Synthetic source-only R223 safety cases. No private invoice assets."""
import copy
import hashlib
import unittest
from r223_source_table_rows import propose

PHOTO=b'fixture-only-r223-source-image-immutable'

def case():
    items=[
       ('S.No',[46,94,88,108]),('Products',[142,93,231,108]),
       ('HSNCode',[390,100,471,115]),('Rate',[687,109,730,123]),
       ('Amount',[835,114,910,131]),
       ('1',[50,130,66,144]),('COFFEE PREMIUM PACK',[140,129,333,144]),
       ('21011120',[392,135,465,148]),('248.57',[687,143,737,154]),
       ('6263.99',[842,148,906,162]),
       ('2',[50,160,66,173]),('BISCUITS SMALL PACK',[142,160,327,175]),
       ('19059020',[392,164,464,178]),('10.00',[687,172,728,186]),
       ('432.01',[842,179,906,192]),
       ('Total',[180,210,243,226]),('6966.00',[840,210,920,228]),
    ]
    return {'file':'synthetic.jpg','source_sha256':hashlib.sha256(PHOTO).hexdigest(),
            'source_width':1200,'source_height':600,
            'raw_texts':[t for t,_ in items],
            'raw_boxes':[b for _,b in items]}

class SourceTableProposals(unittest.TestCase):
    def test_two_sloped_rows_not_a_flat_band(self):
        r=propose(case(),PHOTO)
        self.assertEqual(r['proposed_table_count'],1)
        self.assertEqual(r['proposed_row_count'],2)
        self.assertEqual([x['description_anchor_source_index'] for x in r['tables'][0]['rows']],[6,11])
        self.assertGreater(r['tables'][0]['header_slope_hypothesis'],0)

    def test_source_bytes_and_boxes_remain_unchanged(self):
        c=case();before=copy.deepcopy(c)
        propose(c,PHOTO)
        self.assertEqual(c,before)

    def test_no_accounting_certifications_or_posts(self):
        r=propose(case(),PHOTO)
        self.assertFalse(r['release_approved']); self.assertFalse(r['posting_eligible'])
        self.assertEqual(r['accepted_field_count'],0)
        self.assertEqual(r['printed_cell_boundaries_verified'],0)
        for t in r['tables']:
            self.assertFalse(t['physical_column_dividers_verified'])
            for row in t['rows']:
                self.assertFalse(row['posting_eligible'])
                for tok in row['original_tokens']:
                    self.assertFalse(tok['physical_cell_verified'])
                    self.assertFalse(tok['value_verified'])

    def test_full_membership_and_single_assignment(self):
        c=case();r=propose(c,PHOTO)
        referenced=[]
        for t in r['tables']:
            referenced.extend(t['header_source_indices'])
            for row in t['rows']:referenced.extend(row['source_indices'])
        self.assertEqual(len(referenced),len(set(referenced)))
        self.assertEqual(sorted(set(referenced)|set(r['unassigned_source_indices'])),list(range(len(c['raw_texts']))))

    def test_hash_mismatch_refused(self):
        with self.assertRaises(ValueError):propose(case(),PHOTO+b'changed')

    def test_box_and_dimension_corruption_refused(self):
        for bad in (float('nan'),float('inf'),True,-1):
            c=case();c['raw_boxes'][6][0]=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):propose(c,PHOTO)
        c=case();c['source_height']=0
        with self.assertRaises(ValueError):propose(c,PHOTO)
        c=case();c['source_width']=float('nan')
        with self.assertRaises(ValueError):propose(c,PHOTO)
        c=case();c['raw_boxes'].pop()
        with self.assertRaises(ValueError):propose(c,PHOTO)

    def test_no_strong_table_header_fail_closed(self):
        c=case();c['raw_texts'][1]='Unknown Text'
        r=propose(c,PHOTO)
        self.assertEqual(r['proposed_row_count'],0)
        self.assertEqual(r['unassigned_source_indices'],list(range(len(c['raw_texts']))))

    def test_tax_summary_not_a_product_table(self):
        c=case();c['raw_texts'][1]='Taxable Value'
        r=propose(c,PHOTO)
        self.assertEqual(r['proposed_table_count'],0)

    def test_no_fabrication_on_merged_money_token(self):
        c=case();c['raw_texts'][9]='2.50%149.14'
        r=propose(c,PHOTO)
        row=r['tables'][0]['rows'][0]
        self.assertIn('2.50%149.14',[p['raw_text'] for p in row['original_tokens']])
        self.assertNotIn('149.14',[p['raw_text'] for p in row['original_tokens']])

    def test_missing_hsn_row_not_recast_as_item(self):
        c=case()
        c['raw_texts'][11]='Ional'  # could be OCR for a summary total
        c['raw_texts'][12]=''
        r=propose(c,PHOTO)
        self.assertEqual(r['proposed_row_count'],1)
        self.assertEqual(r['tables'][0]['rows'][0]['description_anchor_source_index'],6)

    def test_two_close_row_anchors_do_not_duplicate_token(self):
        c=case();c['raw_texts'].append('EXTRA PRODUCT')
        c['raw_boxes'].append([145,132,278,146])
        r=propose(c,PHOTO)
        all_indices=[i for t in r['tables'] for row in t['rows'] for i in row['source_indices']]
        self.assertEqual(len(all_indices),len(set(all_indices)))

if __name__=='__main__': unittest.main(verbosity=2)
