"""R226: exercise actual isolated staged Child recursive engine, not a mock.

Runs after R225 source-stage and numpy installation. No invoices are uploaded.
"""
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'integration-build/InvoiceVisionChild/Engine'
HEADER='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'


def load(name):
    path=ENGINE/name
    if not path.is_file():
        raise AssertionError('Staged actual Child engine not found: '+str(path))
    spec=importlib.util.spec_from_file_location('_r226_test_'+name.split('.')[0],path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fixture():
    image=np.full((600,1200,3),255,dtype=np.uint8)
    data=[
       ('S.No',(46,94,88,108)), ('Products',(142,93,231,108)),
       ('HSNCode',(390,100,471,115)),('Rate',(687,109,730,123)),
       ('Amount',(835,114,910,131)),
       ('1',(50,130,66,144)),('COFFEE PREMIUM PACK',(140,129,333,144)),
       ('21011120',(392,135,465,148)),('248.57',(687,143,737,154)),
       ('6263.99',(842,148,906,162)),
       ('2',(50,160,66,173)),('BISCUITS SMALL PACK',(142,160,327,175)),
       ('19059020',(392,164,464,178)),('10.00',(687,172,728,186)),
       ('432.01',(842,179,906,192)),
       ('Total',(180,210,243,226)),('6966.00',(840,210,920,228)),
       ('31/00/2026',(8,250,100,270)),('03/09/202602:08PM',(8,277,172,298)),
    ]
    rows=[HEADER]
    for i,(txt,(x0,y0,x1,y1)) in enumerate(data,1):
        rows.append('5\t1\t%d\t1\t1\t1\t%d\t%d\t%d\t%d\t99\t%s'%
                    (i,x0,y0,x1-x0,y1-y0,txt))
    return image,'\n'.join(rows)+'\n'


class StagedChildReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=load('INVOICE_OCR_RECURSIVE_ZONES_R109.py')
        cls.review=load('INVOICE_OCR_SOURCE_REVIEW_R226.py')
        cls.rows=load('INVOICE_OCR_SOURCE_ROWS_R223.py')

    def test_real_staged_row_proposals_and_date_flags(self):
        image,tsv=fixture();before=image.copy()
        x=self.review.review(image,tsv)
        self.assertEqual(x['status'],'UNVERIFIED_SOURCE_GEOMETRY_REVIEW_ONLY')
        self.assertEqual(x['source_observations'],19)
        self.assertEqual(x['row_hypotheses']['proposed_row_count'],2)
        self.assertEqual(x['row_hypotheses']['proposed_table_count'],1)
        self.assertEqual(x['layout_recovery_review']['total_provisional_rows'],2)
        self.assertFalse(x['layout_recovery_review']['posting_eligible'])
        self.assertEqual(x['layout_recovery_review']['accepted_field_values'],0)
        self.assertEqual({k['reason'] for k in x['date_flags']},
                         {'invalid_calendar_date','date_time_glued'})
        self.assertEqual(x['decoded_frame_sha256'],hashlib.sha256(image.tobytes()).hexdigest())
        self.assertFalse(x['original_jpeg_sha256_verified'])
        self.assertTrue(np.array_equal(image,before))
        self.assertEqual(len(x['source_tsv_row_numbers']),19)
        self.assertFalse(x['posting_eligible'])
        self.assertFalse(x['release_approved'])

    def test_default_child_zone_behavior_unchanged_when_disabled(self):
        image,tsv=fixture()
        coarse=[{'id':'R001','xyxy':[0,0,1200,600],'category':'unknown'}]
        with patch.dict(os.environ,{'INVOICEVISION_SOURCE_REVIEW_R226':'0'}):
            leaves,meta,lines=self.engine.refine_regions(image,copy.deepcopy(coarse),tsv)
        self.assertNotIn('source_row_and_date_review',meta)
        self.assertTrue(leaves)
        self.assertTrue(lines)

    def test_opt_in_attaches_review_without_mutating_zones_tsv_pixels(self):
        image,tsv=fixture()
        coarse=[{'id':'R001','xyxy':[0,0,1200,600],'category':'unknown'}]
        original=image.tobytes();original_tsv=tsv
        with patch.dict(os.environ,{'INVOICEVISION_SOURCE_REVIEW_R226':'0'}):
            base,base_meta,base_lines=self.engine.refine_regions(image,copy.deepcopy(coarse),tsv)
        with patch.dict(os.environ,{'INVOICEVISION_SOURCE_REVIEW_R226':'1'}):
            leaves,meta,lines=self.engine.refine_regions(image,copy.deepcopy(coarse),tsv)
        self.assertEqual(leaves,base)
        self.assertEqual(lines,base_lines)
        self.assertEqual(tsv,original_tsv)
        self.assertEqual(image.tobytes(),original)
        self.assertNotIn('source_row_and_date_review',base_meta)
        proposal=meta['source_row_and_date_review']
        self.assertEqual(proposal['row_hypotheses']['proposed_row_count'],2)
        self.assertFalse(proposal['accounting_write_permitted'])
        self.assertFalse(proposal['release_approved'])

    def test_bad_source_box_fails_closed_without_new_approved_state(self):
        image,tsv=fixture();tsv=tsv.replace('8\t250\t92\t20','1150\t250\t92\t20')
        coarse=[{'id':'R001','xyxy':[0,0,1200,600],'category':'unknown'}]
        with patch.dict(os.environ,{'INVOICEVISION_SOURCE_REVIEW_R226':'1'}):
            leaves,meta,_=self.engine.refine_regions(image,coarse,tsv)
        review=meta['source_row_and_date_review']
        self.assertEqual(review['status'],'REVIEW_UNAVAILABLE')
        self.assertFalse(review['posting_eligible'])
        self.assertFalse(review['accounting_write_permitted'])
        self.assertTrue(leaves)

    def test_untrusted_tsv_requires_exact_header_and_shape(self):
        image,tsv=fixture()
        with self.assertRaises(ValueError):
            self.review.review(image,tsv.replace(HEADER,'unexpected-header'))
        with self.assertRaises(ValueError):
            self.review.review(image,tsv+'5\t1\tbad\n')

    def test_duplicate_data_never_becomes_certified_cell(self):
        image,tsv=fixture()
        review=self.review.review(image,tsv)
        values=[c for t in review['row_hypotheses']['tables']
                for row in t['rows'] for c in row['original_tokens']]
        self.assertTrue(values)
        self.assertTrue(all(not v['value_verified'] and not v['physical_cell_verified']
                            for v in values))
        self.assertEqual(review['row_hypotheses']['accepted_field_count'],0)


if __name__=='__main__':
    unittest.main(verbosity=2)
