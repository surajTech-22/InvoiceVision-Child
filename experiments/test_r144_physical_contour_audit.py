import unittest
import cv2
import numpy as np
from experiments.r144_physical_contour_audit import audit,closed_regions,closed_ink_contours


class ContourAudit(unittest.TestCase):
    def test_tilted_source_box_without_synthetic_gap_repair(self):
        ink=np.zeros((400,500),dtype='uint8')
        p=cv2.boxPoints(((250.,200.),(420.,300.),-2.)).astype(int)
        cv2.polylines(ink,[p],True,255,2)
        before=ink.copy()
        self.assertTrue(closed_ink_contours({'ink':ink}))
        self.assertTrue(np.array_equal(ink,before))
        # Cut a genuine opening in one complete side; no contour may close it.
        ink[180:220,30:60]=0
        self.assertFalse(closed_ink_contours({'ink':ink}))

    def test_full_width_source_frame_is_not_excluded(self):
        ink=np.zeros((600,400),dtype='uint8')
        cv2.rectangle(ink,(10,10),(390,590),255,2)
        rows=closed_regions({'raw':ink,'h35':ink,'v35':ink})
        self.assertTrue(rows)
        self.assertGreater(rows[0]['xyxy'][2]-rows[0]['xyxy'][0],400*.75)
        ink[250:270,8:13]=0
        self.assertFalse(closed_regions({'raw':ink,'h35':ink,'v35':ink}))

    def test_closed_source_mask_and_missing_side(self):
        ink=np.zeros((160,200),dtype='uint8')
        cv2.rectangle(ink,(20,30),(150,100),255,2)
        candidate={'xyxy':[22,32,149,99]}
        before=ink.copy()
        row=audit({'raw':ink},[candidate])[0]
        self.assertTrue(row['closed_source_component'])
        self.assertFalse(row['physical_border_verified'])
        self.assertTrue(np.array_equal(before,ink))
        ink[50:70,18:23]=0
        self.assertFalse(audit({'raw':ink},[candidate])[0]['closed_source_component'])

    def test_small_glyph_loop_cannot_certify_large_rectangle(self):
        ink=np.zeros((160,200),dtype='uint8')
        cv2.rectangle(ink,(70,60),(90,80),255,2)
        row=audit({'raw':ink},[{'xyxy':[20,30,150,100]}])[0]
        self.assertFalse(row['closed_source_component'])

if __name__=='__main__': unittest.main(verbosity=2)
