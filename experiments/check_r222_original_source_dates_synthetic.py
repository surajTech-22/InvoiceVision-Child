"""Synthetic CI coverage for R222. Actual invoice photos must NOT be committed."""
import copy
import hashlib
import unittest
import cv2
from r222_original_source_date_review import review, parse_dates


def fixture(text):
    ok, encoded = cv2.imencode('.jpg', __import__('numpy').full((120,320,3),255,dtype='uint8'))
    assert ok
    photo=encoded.tobytes()
    case={'file':'synthetic-test-only.jpg','source_sha256':hashlib.sha256(photo).hexdigest(),
          'source_width':320,'source_height':120,'raw_texts':[text],
          'raw_boxes':[[20,20,220,42]]}
    return case,photo


class R222SyntheticDateSafety(unittest.TestCase):
    def test_invalid_date_requires_two_views(self):
        case,photo=fixture('E-Inv Dt:31/00/2026')
        old=copy.deepcopy(case)
        result=review(case,photo,ocr=lambda _: 'E-Inv Dt:31/08/2026')
        r=result['proposals'][0]
        self.assertEqual(r['status'],'correlated_ocr_review_proposal')
        self.assertEqual(r['suggested_date'],'31/08/2026')
        self.assertFalse(result['posting_eligible'])
        self.assertEqual(case,old)

    def test_sideways_valid_year_discrepancy(self):
        case,photo=fixture(':04/09/202514:37:09')
        case['raw_boxes']=[[20,20,45,110]]
        out=review(case,photo,ocr=lambda _: '04/09/2026 14:37:09')
        self.assertEqual(out['proposals'][0]['status'],'correlated_ocr_date_conflict_review')
        self.assertEqual(out['proposals'][0]['suggested_date'],'04/09/2026')

    def test_conflicting_ocr_variants_do_not_vote(self):
        case,photo=fixture('31/00/2026')
        responses=iter(['31/08/2026','31/07/2026'])
        out=review(case,photo,ocr=lambda _:next(responses))
        self.assertEqual(out['proposals'][0]['status'],'conflicting_second_pass_dates')
        self.assertIsNone(out['proposals'][0]['suggested_date'])

    def test_missing_engine_does_not_invent_date(self):
        case,photo=fixture('31/00/2026')
        out=review(case,photo,ocr=lambda _: (_ for _ in ()).throw(OSError('unavailable')))
        self.assertIsNone(out['proposals'][0]['suggested_date'])

    def test_glued_datetime_preserves_exact_source(self):
        case,photo=fixture('03/09/202602:08PM')
        out=review(case,photo,ocr=lambda _: '')
        self.assertEqual(out['proposals'][0]['suggested_date'],'03/09/2026')
        self.assertEqual(out['proposals'][0]['status'],'original_date_span_only')
        self.assertEqual(case['raw_texts'][0],'03/09/202602:08PM')

    def test_source_hash_refuses_changed_bytes(self):
        case,photo=fixture('31/00/2026')
        with self.assertRaises(ValueError):review(case,photo+b'bad')

    def test_dimensions_and_geometry_fail_closed(self):
        case,photo=fixture('31/00/2026')
        case['source_width']=321
        with self.assertRaises(ValueError):review(case,photo)
        case['source_width']=320
        case['raw_boxes'][0][0]=float('nan')
        with self.assertRaises(ValueError):review(case,photo)

    def test_regular_valid_date_is_not_rewritten(self):
        case,photo=fixture('31/08/2026')
        out=review(case,photo,ocr=lambda _: (_ for _ in ()).throw(AssertionError('unexpected OCR')))
        self.assertFalse(out['proposals'])
        self.assertFalse(out['release_approved'])

    def test_no_date_fabricated(self):
        self.assertEqual(parse_dates('unrelated receipt number 20260904'),[])


if __name__=='__main__':
    unittest.main(verbosity=2)
