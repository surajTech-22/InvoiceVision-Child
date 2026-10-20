"""Regression cases for observed logical groups in the actual Child engine."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np


def load():
    p=Path(__file__).resolve().parents[1]/'integration/Engine/INVOICE_OCR_RECURSIVE_ZONES_R109.py'
    s=importlib.util.spec_from_file_location('child_zones',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def line(text,x,y,w=100,h=20):
    m=load();scores=m.category_scores(text)
    return dict(text=text,xyxy=[x,y,x+w,y+h],category=max(scores,key=scores.get) if scores else 'unknown',scores=scores,confidence=90)


class LogicalGroups(unittest.TestCase):
    def test_item_description_cannot_reclassify_table_as_buyer(self):
        m=load();ls=[line('Description',20,100),line('Qty',240,100,40),
                    line('buyer supplied packaging',20,140,200),line('3',240,140,40),
                    line('Net payable',180,200),line('120.00',300,200)]
        groups=m.content_groups(ls);tables=[g for g in groups if g['category']=='item_table']
        self.assertEqual(len(tables),1)
        self.assertEqual(len(tables[0]['members']),4)
        anchors=m.grouped_anchors(ls,groups)
        self.assertEqual({a['category'] for a in anchors},{'item_table','totals'})
        self.assertEqual(ls[2]['category'],'buyer') # original hypothesis is retained

    def test_single_hsn_mention_is_not_table(self):
        self.assertFalse(load().content_groups([line('HSN',10,10),line('12345',10,50)]))

    def test_header_and_following_value_block_split(self):
        m=load();ls=[line('Supplier',10,20),line('Example Company',10,45),line('Grand Total',10,100),line('25.00',10,125)]
        groups=m.content_groups(ls)
        self.assertTrue(any(len(g['members'])==2 and g['category']=='supplier' for g in groups))
        part=m._best_partition([0,0,400,200],m.grouped_anchors(ls,groups),'horizontal',ls+groups)
        self.assertIsNotNone(part)
        self.assertGreater(part[1],65)
        self.assertLess(part[1],100)

    def test_coherent_table_not_sliced_into_description_and_amount_columns(self):
        m=load();ls=[line('Description',20,100),line('Qty',240,100,40),line('one',20,140),line('1',240,140,40)]
        groups=m.content_groups(ls)
        self.assertIsNone(m._best_partition([0,0,400,300],m.grouped_anchors(ls,groups),'vertical',ls+groups))

    def test_groups_remain_review_only_in_child_output(self):
        m=load();ls=[line('Description',20,100),line('Qty',240,100,40),line('one',20,140),line('1',240,140,40),line('Net payable',20,220),line('10.00',180,220)]
        rows=['header']
        for i,l in enumerate(ls):
            a,b,c,d=l['xyxy'];rows.append(f'5\t1\t{i}\t1\t1\t1\t{a}\t{b}\t{c-a}\t{d-b}\t90\t{l["text"]}')
        leaves,meta,_=m.refine_regions(np.zeros((400,400,3),np.uint8),[dict(id='R001',xyxy=[0,0,400,400],category='unknown')],'\n'.join(rows))
        self.assertEqual(len(leaves),2)
        for leaf in leaves:
            self.assertFalse(leaf['ocr_authorized']);self.assertFalse(leaf['proposed_approved'])
            for group in leaf['content_evidence']['logical_groups']:
                self.assertFalse(group['physical_border_verified'])

if __name__=='__main__':unittest.main()
