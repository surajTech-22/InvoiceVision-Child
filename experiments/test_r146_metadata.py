"""No silently truncated or invented text-to-source association at Child boundary."""
import copy
import types
import unittest
from unittest.mock import patch
import numpy as np
from .test_r144_child_adapter import load, payload


class MetadataContract(unittest.TestCase):
    def test_real_numpy_arrays_and_fractional_enclosure(self):
        m=load();p=payload(' raw text ')
        p['res']['rec_scores']=np.array([.99])
        p['res']['rec_polys']=np.array([[[10.1,10.2],[150.8,10.2],[150.8,30.9],[10.1,30.9]]])
        line=m.normalized_lines(p,300,200)[0]
        self.assertEqual(line['box'],(10,10,141,21))
        self.assertEqual(line['raw_text'],' raw text ')
        self.assertEqual(line['source_polygon'],p['res']['rec_polys'][0].tolist())

    def test_incomplete_metadata_never_returns_partial_success(self):
        mutations=[lambda r:r.update(rec_texts=['first','second']),
                   lambda r:r.update(rec_scores=[]),
                   lambda r:r.pop('rec_texts'),
                   lambda r:r.update(rec_texts=[123]),
                   lambda r:r.update(rec_scores=[float('nan')]),
                   lambda r:r.update(rec_scores=[1.2]),
                   lambda r:r.update(rec_polys=[[[0,0],[10,0],[float('inf'),10],[0,10]]]),
                   lambda r:r.update(rec_polys=[[-1,0,10,20]]),
                   lambda r:r.update(rec_polys=[[20,0,10,20]]),
                   lambda r:r.update(rec_polys=[[[0,0],[10,10],[20,20],[30,30]]]),
                   lambda r:r.update(dt_polys=r.pop('rec_polys'))]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                p=payload('source');mutate(p['res'])
                with self.assertRaises(ValueError):load().normalized_lines(p,300,200)

    def test_valid_blank_page_distinct_from_missing_result(self):
        self.assertEqual(load().normalized_lines({'rec_texts':[], 'rec_scores':[], 'rec_polys':[]},300,200),[])
        for results in ([],[payload('one'),payload('two')]):
            m=load()
            with patch.object(m,'_pipeline',return_value=types.SimpleNamespace(predict=lambda **kw:iter(results))),patch.dict('os.environ',{'INVOICEVISION_OCR_DEVICE':'cpu'}):
                with self.assertRaises(ValueError):m._recognize_tile(None,300,200,{})

    def test_malformed_gpu_is_retried_and_no_partial_mapping_escapes(self):
        m=load();calls=[]
        class Model:
            def __init__(self,device):self.device=device
            def predict(self,**kw):
                p=payload('GPU wrong' if self.device=='gpu:0' else 'CPU complete')
                if self.device=='gpu:0':p['res']['rec_texts'].append('missing position')
                return [p]
        def factory(device):calls.append(device);return Model(device)
        with patch.object(m,'_pipeline',side_effect=factory),patch.dict('os.environ',{'INVOICEVISION_OCR_DEVICE':'auto'}):
            self.assertEqual(m._recognize_tile(None,300,200,{})[0]['text'],'CPU complete')
        self.assertEqual(calls,['gpu:0','cpu'])

    def test_cpu_only_runtime_cannot_be_reported_as_gpu_success(self):
        m=load();devices=[];events=[]
        class Model:
            def __init__(self,**kw):devices.append(kw['device'])
            def predict(self,**kw):return [payload('actual CPU')]
        fake=types.SimpleNamespace(device=types.SimpleNamespace(is_compiled_with_cuda=lambda:False))
        with patch.dict('sys.modules',{'paddle':fake,'paddleocr':types.SimpleNamespace(PaddleOCR=Model)}),patch.dict('os.environ',{'INVOICEVISION_OCR_DEVICE':'auto'}):
            for _ in range(2):m._recognize_tile(None,300,200,{},lambda event,**kw:events.append((event,kw)))
        self.assertEqual(devices,['cpu'])
        self.assertEqual([kw['device'] for event,kw in events if event=='OCR_BACKEND_COMPLETE'],['cpu','cpu'])
        self.assertEqual(len([e for e,k in events if e=='OCR_BACKEND_FAILED']),1)

    def test_validation_does_not_mutate_metadata(self):
        p=payload('source');before=copy.deepcopy(p)
        load().normalized_lines(p,300,200)
        self.assertEqual(p,before)

if __name__=='__main__':unittest.main()
