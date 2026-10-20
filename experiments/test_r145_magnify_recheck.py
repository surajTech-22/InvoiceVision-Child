import unittest
import cv2
import numpy as np
from experiments.r145_magnify_recheck import recheck


class MagnifyGeometry(unittest.TestCase):
    def test_all_quarter_turns_and_scales_map_back_to_original(self):
        image=np.full((180,300,3),255,dtype='uint8')
        raw=cv2.imencode('.png',image)[1].tobytes()
        for turns in range(4):
            for scale in (1,2,4,8):
                def reader(view):
                    h,w=view.shape[:2]
                    return ['RAW'],[[[0,0],[w,0],[w,h],[0,h]]]
                result=recheck(raw,[50,60,170,100],reader,turns,scale,margin=0)
                for view in result['views']:
                    points=np.array(view['source_polygons'][0])
                    self.assertTrue(np.array_equal(points.min(axis=0),[50,60]))
                    self.assertTrue(np.array_equal(points.max(axis=0),[170,100]))
                    self.assertFalse(view['posting_eligible'])

    def test_outside_crop_rejected(self):
        raw=cv2.imencode('.png',np.zeros((100,100,3),dtype='uint8'))[1].tobytes()
        with self.assertRaises(ValueError):recheck(raw,[0,0,110,40],lambda x:([],[]))

if __name__=='__main__':unittest.main(verbosity=2)
