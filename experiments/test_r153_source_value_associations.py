import unittest
from r153_source_value_associations import associate

def c(pairs,width=1000,height=1500):
    return {'file':'test.png','source_sha256':'test-source',
     'source_width':width,'source_height':height,
     'raw_texts':[a for a,b in pairs],'raw_boxes':[b for a,b in pairs]}

class EvidenceTests(unittest.TestCase):
    def test_horizontal_total(self):
        r=associate(c([('Grand Total',[500,400,630,425]),('1431',[705,401,756,426])]))
        self.assertEqual(r['proposals'][0]['candidates'][0]['raw_value'],'1431')
    def test_vertical_total(self):
        r=associate(c([('GRAND TOTAL',[153,965,186,1127]),('1140.00',[166,1326,193,1396])],width=900,height=1600))
        self.assertEqual(r['proposals'][0]['candidates'][0]['reading_direction'],'vertical_downstream')
    def test_buyer_from_below(self):
        r=associate(c([('Buyer:',[50,120,100,140]),('BALAJI TRADING CO',[50,146,265,171])]))
        self.assertEqual(r['proposals'][0]['candidates'][0]['source_token_index'],1)
    def test_supplier_from_below(self):
        r=associate(c([('Supplier:',[45,250,130,270]),('SRI RAMA ENTERPRISES',[45,278,255,301])]))
        self.assertEqual(r['proposals'][0]['candidates'][0]['raw_value'],'SRI RAMA ENTERPRISES')
    def test_invoice_number(self):
        r=associate(c([('Bill No',[220,100,310,123]),(':E55409',[332,101,402,123])]))
        self.assertEqual(r['proposals'][0]['candidate_field'],'invoice_number')
    def test_2025_raw_not_rewritten_to_2026(self):
        r=associate(c([('Bill Date',[681,839,714,925]),(':04/09/202514:37:09',[672,1003,695,1162])],width=900,height=1600))
        q=r['proposals'][0]['candidates'][0]['raw_value']
        self.assertIn('2025',q)
        self.assertNotIn('2026',q)
    def test_reject_pure_alpha_as_invoice_number(self):
        r=associate(c([("Invoice No",[100,100,200,120]),("DELIVERY NOTE",[230,100,360,120])]))
        self.assertEqual(r["candidate_mentions"],0)
    def test_reject_false_contact_phone_as_buyer(self):
        r=associate(c([("Buyer:",[100,100,150,120]),("PHNO",[190,100,250,120])]))
        self.assertEqual(r["candidate_mentions"],0)
    def test_discount_total_excluded(self):
        r=associate(c([('Grand Total',[100,350,250,370]),('Discount: 100',[260,351,410,371])]))
        self.assertEqual(r['candidate_mentions'],0)
    def test_gst_product_not_buyer(self):
        r=associate(c([('Bill To',[100,100,160,120]),('GSTIN: 29AAxxx',[180,102,330,121])]))
        self.assertEqual(r['candidate_mentions'],0)
    def test_unrelated_far_amount_rejected(self):
        r=associate(c([('Grand Total',[10,100,150,120]),('800.00',[700,700,780,720])]))
        self.assertEqual(r['candidate_mentions'],0)
    def test_table_total_not_auto_approved(self):
        r=associate(c([('Grand Total',[100,100,240,125]),('8840.00',[300,100,380,125])]))
        self.assertFalse(r['posting_eligible']);self.assertFalse(r['proposals'][0]['field_value_verified'])
    def test_shared_token_conflict(self):
        r=associate(c([('Grand Total',[100,100,220,120]),('Net Payable',[100,130,220,150]),('800.00',[270,115,335,138])]))
        self.assertEqual(r['approved_field_count'],0)
        self.assertEqual(len(r['shared_candidate_conflicts']),0 if r['candidate_mentions']<2 else 1)
    def test_no_source_membership_loss(self):
        r=associate(c([('Grand Total',[10,100,150,120]),('800.00',[180,100,255,120]),('unrelated',[500,300,600,320])]))
        self.assertEqual(r['source_token_count'],3)
        self.assertTrue(r['source_token_membership_preserved'])
    def test_missing_valid_region_rejected(self):
        r=associate(c([('Grand Total',[10,100,150,120]),('900.00',[220,110,220,130])]))
        self.assertEqual(r['candidate_mentions'],0)
    def test_crossing_product_table_not_grouped(self):
        r=associate(c([('Net Payable',[100,100,220,120]),('Product Item 100.00',[250,100,440,125])]))
        self.assertEqual(r['candidate_mentions'],0)
    def test_string_raw_preserved(self):
        inp=c([('Grand Total',[10,100,150,120]),(':5181.00',[180,100,270,120])]);before=list(inp['raw_texts']);r=associate(inp)
        self.assertEqual(inp['raw_texts'],before)
        self.assertEqual(r['proposals'][0]['candidates'][0]['raw_value'],':5181.00')

if __name__=='__main__':unittest.main(verbosity=2)