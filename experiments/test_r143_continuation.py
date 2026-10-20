import copy
import hashlib
import random
import unittest
from experiments.r138_field_evidence import reconstruct
from experiments.r141_inline_field_evidence import parse_inline
from experiments.r143_source_evidence import inspect, valid_date
from experiments.r143_recursive_zones import subdivide
from experiments.r143_runtime_fallback import Runtime, OcrUnavailable
from experiments.r143_orientation_evidence import point, rotate_case, hypotheses


def case(texts, boxes=None):
    return {'source_sha256': hashlib.sha256(b'original').hexdigest(),
            'source_width': 1000, 'source_height': 1000, 'raw_texts': texts,
            'raw_boxes': boxes if boxes is not None else
                [[10, i*40+10, 300, i*40+30] for i in range(len(texts))]}


class SourceEvidence(unittest.TestCase):
    def test_ship_to_is_not_buyer(self):
        self.assertEqual([x['field'] for x in parse_inline('Ship To: Delivery Warehouse')], ['consignee'])
        x = reconstruct(case(['Ship To', 'Delivery Warehouse']))
        self.assertFalse(x['fields']['buyer'])

    def test_customer_administrative_lines_are_not_buyer(self):
        for text in ['Customer Order ID', 'Customer Support: 1860',
                     'Customer Pin Code: 572103', 'Buyer (Bill to)',
                     'CUSTOMER ADDRESS Apmc Yard']:
            self.assertFalse([r for r in parse_inline(text) if r['field'] == 'buyer'])
        self.assertTrue(parse_inline('Customer Name: ABC Traders'))

    def test_credit_note_date_not_invoice_date(self):
        c = case(['CN Date:', '25/09/2026'], [[10,10,100,30],[110,10,220,30]])
        self.assertFalse([r for r in inspect(c,'cpu')['candidates'] if r['field'] == 'invoice_date'])

    def test_date_with_time_cannot_be_invoice_number(self):
        c = case(['Invoice No:', '03/09/2026 02:08 PM'], [[10,10,100,30],[110,10,320,30]])
        self.assertFalse([r for r in inspect(c,'cpu')['candidates'] if r['field'] == 'invoice_number'])

    def test_calendar_dates(self):
        for date in ['31/02/2026', '04/19/2026', '29/02/2025', '99/99/2026']:
            self.assertFalse(valid_date(date))
            self.assertFalse(inspect(case(['Invoice Date: '+date]), 'cpu')['candidates'])
        self.assertTrue(valid_date('29/02/2024'))
        self.assertTrue(valid_date('04/09/2026'))

    def test_original_byte_identity(self):
        with self.assertRaises(ValueError):
            inspect(case(['Bill No: E55409']), 'cpu', b'another invoice')

    def test_coordinates_and_raw_text_preserved(self):
        c = case(['Bill No: E55409', 'Date: 04/09/2026'])
        before = copy.deepcopy(c)
        result = inspect(c, 'cpu', b'original')
        self.assertEqual(c, before)
        for row in result['candidates']:
            self.assertEqual(row['source_regions'], [c['raw_boxes'][i] for i in row['source_tokens']])
            self.assertFalse(row['posting_eligible'])
        self.assertIn('E55409', [x['raw_value'] for x in result['candidates']])

    def test_missing_or_outside_box_never_links(self):
        for boxes in [[], [[900, 10, 1100, 30]], [[0, 0, float('nan'), 30]]]:
            result = inspect(case(['Bill No: ABC123'], boxes), 'cpu')
            self.assertFalse(result['candidates'])
            self.assertTrue(result['issues'])

    def test_invalid_coordinate_space(self):
        for value in [0, -1, float('inf'), True, None]:
            c = case([]); c['source_width'] = value
            with self.assertRaises(ValueError): inspect(c, 'cpu')


class RecursiveZones(unittest.TestCase):
    def token(self, id, y, role, group=None):
        return {'id': id, 'box': [10, y, 80, y+10], 'role': role, 'group': group}

    def test_recursive_groups(self):
        tokens = [self.token(1, 10, 'supplier'), self.token(2, 40, 'buyer'),
                  self.token(3, 70, 'items')]
        result = subdivide([0, 0, 100, 100], tokens)
        self.assertTrue(result['children'])
        self.assertTrue(any(n['children'] for n in result['children']))

    def test_header_value_group_cannot_split(self):
        tokens = [self.token(1, 10, 'label', 'bill'), self.token(2, 60, 'value', 'bill')]
        self.assertFalse(subdivide([0, 0, 100, 100], tokens)['children'])

    def test_unknown_evidence_keeps_parent(self):
        tokens = [self.token(1, 10, 'items'), self.token(2, 60, 'unknown')]
        self.assertFalse(subdivide([0, 0, 100, 100], tokens)['children'])

    def test_crossing_text_prevents_cut(self):
        tokens = [self.token(1, 10, 'items'), self.token(2, 60, 'tax'),
                  {'id': 3, 'box': [10, 15, 80, 70], 'role': 'items'}]
        self.assertFalse(subdivide([0, 0, 100, 100], tokens)['children'])

    def test_outside_and_duplicate_tokens_rejected(self):
        for tokens in [[self.token(1, 110, 'items')],
                       [self.token(1, 10, 'items'), self.token(1, 60, 'tax')]]:
            with self.assertRaises(ValueError): subdivide([0, 0, 100, 100], tokens)

    def test_randomized_no_loss_no_overlap_no_invented_border(self):
        rng = random.Random(143)
        for _ in range(300):
            tokens = [self.token(i, 10+i*30, rng.choice(['items','tax','buyer']))
                      for i in range(rng.randint(2, 20))]
            tree = subdivide([0, 0, 100, 700], tokens)
            leaves = []
            def visit(n):
                self.assertFalse(n['physical_border_verified'])
                self.assertFalse(n['posting_eligible'])
                if n['children']:
                    a, b = n['children']
                    self.assertEqual(set(n['source_tokens']), set(a['source_tokens']) | set(b['source_tokens']))
                    self.assertFalse(set(a['source_tokens']) & set(b['source_tokens']))
                    self.assertTrue(a['box'][2] <= b['box'][0] or a['box'][3] <= b['box'][1])
                    for child in n['children']: visit(child)
                else: leaves.extend(n['source_tokens'])
            visit(tree)
            self.assertEqual(sorted(leaves), list(range(len(tokens))))


class CpuFallback(unittest.TestCase):
    def test_gpu_error_then_reuse_cpu_without_retry_loop(self):
        events = []
        def factory(device):
            events.append(device)
            if device == 'gpu': raise MemoryError('device exhausted')
            return lambda source: ['recognized']
        runtime = Runtime(factory, bool, prefer_gpu=True)
        for _ in range(4): self.assertEqual(runtime.recognize(b'original')['device'], 'cpu')
        self.assertEqual(events, ['gpu', 'cpu'])

    def test_gpu_inference_failure_falls_back(self):
        def factory(device):
            def recognize(source):
                if device == 'gpu': raise RuntimeError('device lost')
                return ['recognized']
            return recognize
        runtime = Runtime(factory, bool, prefer_gpu=True)
        self.assertTrue(runtime.recognize(b'original')['fallback_used'])

    def test_no_gpu_when_cpu_selected(self):
        events = []
        def factory(device):
            events.append(device); return lambda source: ['recognized']
        Runtime(factory, bool).recognize(b'original')
        self.assertEqual(events, ['cpu'])

    def test_invalid_gpu_output_retried_on_cpu(self):
        runtime = Runtime(lambda d: lambda s: [] if d == 'gpu' else ['text'], bool, True)
        self.assertEqual(runtime.recognize(b'original')['device'], 'cpu')

    def test_cpu_failure_is_not_empty_success(self):
        runtime = Runtime(lambda d: lambda s: [], bool, True)
        with self.assertRaises(OcrUnavailable): runtime.recognize(b'original')
        self.assertEqual([x['device'] for x in runtime.diagnostics], ['gpu', 'cpu'])


class Orientation(unittest.TestCase):
    def test_round_trip_source_geometry(self):
        for turns in range(4):
            for x, y in [(0, 0), (900, 1600), (200, 300), (899, 1599)]:
                a, b = point(x, y, 900, 1600, turns)
                w, h = (1600, 900) if turns % 2 else (900, 1600)
                self.assertEqual(point(a, b, w, h, -turns), [x, y])

    def test_vertical_photo_total_retains_original_boxes(self):
        c = case(['Grand Total', '1140.00'], [[100, 100, 120, 220], [100, 300, 120, 380]])
        result = hypotheses(c, 'cpu', b'original')
        rows = [r for view in result for r in view['candidates'] if r['field'] == 'grand_total']
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['source_regions'], [c['raw_boxes'][i] for i in row['source_tokens']])
            self.assertFalse(row['orientation_verified'])
        self.assertEqual(c['raw_boxes'][0], [100, 100, 120, 220])

if __name__ == '__main__': unittest.main(verbosity=2)
