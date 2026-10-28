"""R236 source-crop reread tests; no private photographs or OCR strings."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'integration/Engine/INVOICE_OCR_TARGETED_RECHECK_R236.py'
spec=importlib.util.spec_from_file_location('_r236_crop_reread',p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class TargetedReread(unittest.TestCase):
    def setUp(self):
        self.img=np.full((180,120,3),243,dtype=np.uint8)
        self.img[40:48,60:76]=0

    def test_tight_original_crop_returns_source_preserving_candidate(self):
        expected=self.img.copy()
        out=mod.reread(self.img,'2',[55,35,79,55],'90_CCW',
                       lambda _img,psm:'20')
        self.assertEqual(out['correlated_consensus_candidate'],'20')
        self.assertTrue(out['candidate_disagrees_with_original'])
        self.assertFalse(out['original_ocr_value_replaced'])
        self.assertFalse(out['posting_eligible'])
        self.assertTrue(np.array_equal(self.img,expected))
        self.assertEqual(out['rotation_used'],'90_CCW')
        self.assertTrue(len(out['reread_votes'])>=4)

    def test_source_crop_never_moves_past_frame(self):
        for box in ([0,0,7,9],[112,170,120,180]):
            result=mod.reread(self.img,'1',box,'0',lambda _img,psm:'1')
            x0,y0,x1,y1=result['source_crop_in_rotated_coordinates']
            self.assertGreaterEqual(x0,0)
            self.assertGreaterEqual(y0,0)
            self.assertLessEqual(x1,120)
            self.assertLessEqual(y1,180)

    def test_mixed_ocr_passes_do_not_become_consensus(self):
        out=mod.reread(self.img,'2',[55,35,79,55],'90_CCW',
                       lambda _img,psm:'20' if psm==7 else '30')
        self.assertIsNone(out['correlated_consensus_candidate'])
        self.assertFalse(out['candidate_disagrees_with_original'])
        self.assertFalse(out['field_accuracy_certified'])

    def test_spurious_non_digits_not_accepted(self):
        out=mod.reread(self.img,'2',[55,35,79,55],'90_CCW',
                       lambda _img,psm:'20 BUY')
        self.assertIsNone(out['correlated_consensus_candidate'])

    def test_bad_boundaries_or_rotation_fail_closed(self):
        for box,orientation in [([-1,0,10,10],'0'),([0,0,200,10],'0'),
                                ([20,20,20,30],'0'),([10,10,20,20],'180')]:
            with self.subTest(box=box,orientation=orientation):
                with self.assertRaises(ValueError):
                    mod.reread(self.img,'2',box,orientation,lambda v,p:'20')

    def test_no_quantity_header_means_no_proposal(self):
        self.assertEqual(mod.numeric_quantity_candidates(
            ['TOTAL','2'],[[1,1,40,12],[4,30,16,40]]),[])

    def test_sideways_qty_header_uses_source_geometry(self):
        hints=mod.numeric_quantity_candidates(['QTY FREE','2'],
            [[76,30,96,90],[45,33,60,49]])
        self.assertEqual(len(hints),1)
        self.assertEqual(hints[0]['suggested_rotation'],'90_CCW')
        self.assertEqual(hints[0]['source_token_index'],1)

    def test_upright_qty_header_requires_nearby_numeric(self):
        hints=mod.numeric_quantity_candidates(['QTY','20','5.1'],
            [[100,3,135,16],[99,60,130,76],[0,60,25,76]])
        self.assertEqual([h['source_token_index'] for h in hints],[1])

    def test_rotated_quantity_heading_does_not_capture_distant_price_column(self):
        t=['QTY FREE','2','65.00','54.29','1085.71']
        b=[[690,674,720,804],[669,680,686,703],
           [662,852,688,903],[662,941,688,992],[667,1263,686,1323]]
        got=mod.numeric_quantity_candidates(t,b)
        self.assertEqual([v['source_token_index'] for v in got],[1])
        self.assertEqual(got[0]['suggested_rotation'],'90_CCW')

    def test_ocr_backend_must_return_text(self):
        with self.assertRaises(ValueError):
            mod.reread(self.img,'2',[55,35,79,55],'90_CCW',lambda v,p:None)

    def test_max_candidates_bounded(self):
        t=['QTY']+['1']*70
        b=[[75,20,105,100]]+[[51,25,64,40] for _ in range(70)]
        self.assertEqual(len(mod.numeric_quantity_candidates(t,b,max_candidates=12)),12)

if __name__=='__main__':
    unittest.main(verbosity=2)
