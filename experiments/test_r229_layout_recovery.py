"""R229 synthetic safety checks: never commit user invoice images to GitHub."""
import copy
import hashlib
import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=b'SYNTHETIC_R229_SOURCE_BYTES'
def load(path):
    spec=importlib.util.spec_from_file_location('r229_test_'+path.stem,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

R223=load(ROOT/'experiments/r223_source_table_rows.py')
R229=load(ROOT/'integration/Engine/INVOICE_OCR_LAYOUT_RECOVERY_R229.py')

def case(items,w=1200,h=600):
    return {'file':'SYNTHETIC_ONLY','source_sha256':hashlib.sha256(SOURCE).hexdigest(),
            'source_width':w,'source_height':h,
            'raw_texts':[t for t,b in items],'raw_boxes':[b for t,b in items]}

def basic():
    return case([
        ('S.No',[46,94,88,108]),('Products',[142,93,231,108]),
        ('HSNCode',[390,100,471,115]),('Rate',[687,109,730,123]),
        ('Amount',[835,114,910,131]),('1',[50,130,66,144]),
        ('COFFEE PREMIUM PACK',[140,129,333,144]),('21011120',[392,135,465,148]),
        ('248.57',[687,143,737,154]),('6263.99',[842,148,906,162]),
        ('2',[50,160,66,173]),('BISCUITS SMALL PACK',[142,160,327,175]),
        ('19059020',[392,164,464,178]),('10.00',[687,172,728,186]),
        ('432.01',[842,179,906,192]),('Total',[180,210,243,226])])

class SourceLockedRecovery(unittest.TestCase):
    def test_no_source_edits_and_no_accounting(self):
        c=basic();orig=copy.deepcopy(c)
        out=R229.propose(c,SOURCE,R223)
        self.assertEqual(c,orig)
        self.assertFalse(out['original_ocr_text_changed'])
        self.assertFalse(out['original_source_boxes_changed'])
        self.assertFalse(out['posting_eligible'])
        self.assertFalse(out['release_approved'])
        self.assertEqual(out['accepted_field_values'],0)
        self.assertEqual(out['physical_cells_verified'],0)

    def test_sha_mismatch(self):
        with self.assertRaises(ValueError):R229.propose(basic(),SOURCE+b'altered',R223)

    def test_horizontal_rows_unchanged(self):
        out=R229.propose(basic(),SOURCE,R223)
        self.assertEqual(out['total_provisional_rows'],2)
        self.assertEqual(out['sideways_additional_rows'],0)
        self.assertEqual(out['hsn_additional_rows'],0)

    def test_sideways_original_boxes_are_restored(self):
        c=basic();h=c['source_height']
        c['raw_boxes']=[[h-b[3],b[0],h-b[1],b[2]] for b in c['raw_boxes']]
        c['source_width'],c['source_height']=600,1200
        res=R229.propose(c,SOURCE,R223)
        self.assertEqual(res['sideways_additional_rows'],2)
        self.assertEqual(res['orientation'],'ROTATED_90_CCW_LOGICAL_VIEW_ONLY')
        for t in res['orientation_tables']:
            for header in t['headers']:
                self.assertEqual(header['source_box'],c['raw_boxes'][header['source_index']])
            for row in t['rows']:
                for token in row['original_tokens']:
                    self.assertEqual(token['original_box'],c['raw_boxes'][token['source_token_index']])
                    self.assertFalse(token['value_verified'])

    def test_one_vertical_word_does_not_rotate(self):
        c=basic();c['raw_boxes'][1]=[145,93,158,231]
        self.assertEqual(R229.propose(c,SOURCE,R223)['sideways_additional_rows'],0)

    def test_ocr_damaged_header_preserves_original_text(self):
        c=basic();c['raw_texts'][1]='Produci Name'
        self.assertEqual(R229.propose(c,SOURCE,R223)['total_provisional_rows'],2)
        self.assertEqual(c['raw_texts'][1],'Produci Name')

    def test_tax_summary_never_product_row(self):
        c=case([('CGST',[100,100,160,120]),('SGST',[200,100,250,120]),
                ('HSNCode',[390,100,470,120]),('Taxable',[700,100,780,120]),
                ('21011120',[392,150,465,170]),('48.13',[700,150,740,170])])
        self.assertEqual(R229.propose(c,SOURCE,R223)['total_provisional_rows'],0)

    def test_one_row_with_multiple_numeric_product_codes_not_false_merge(self):
        c=basic()
        c['raw_texts'].insert(8,'83914733')
        c['raw_boxes'].insert(8,[380,135,391,148])
        self.assertEqual(R229.propose(c,SOURCE,R223)['baseline_merged_row_warnings'],[])

    def test_bad_geometry_refused(self):
        c=basic();c['raw_boxes'][0]=[-10,2,5,10]
        with self.assertRaises(ValueError):R229.propose(c,SOURCE,R223)

if __name__=='__main__':unittest.main(verbosity=2)
