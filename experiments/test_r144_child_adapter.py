"""Exercise the actual staged Child adapter, including generator-time failure."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch

PATH=Path(__file__).resolve().parents[1]/'integration/Engine/INVOICE_OCR_PADDLE_ADAPTER_R112.py'


def load():
    spec=importlib.util.spec_from_file_location('r144_child_adapter',PATH)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def payload(text):
    return {'res':{'rec_texts':[text], 'rec_scores':[.99],
                   'rec_polys':[[[10,10],[150,10],[150,30],[10,30]]]}}


class AdapterFallback(unittest.TestCase):
    def test_default_cpu_and_cpu_cache(self):
        m=load();devices=[]
        class Model:
            def __init__(self,**kwargs):devices.append(kwargs['device'])
            def predict(self,**kwargs):return [payload('CPU RAW')]
        with patch.dict('sys.modules',{'paddleocr':types.SimpleNamespace(PaddleOCR=Model),'paddle':types.SimpleNamespace(device=types.SimpleNamespace(is_compiled_with_cuda=lambda:True,cuda=types.SimpleNamespace(device_count=lambda:1)))}),patch.dict('os.environ',{'INVOICEVISION_OCR_DEVICE':'cpu'}):
            for _ in range(3):self.assertEqual(m._recognize_tile(None,300,200,{})[0]['text'],'CPU RAW')
        self.assertEqual(devices,['cpu'])

    def test_partial_gpu_generator_failure_never_leaks_partial_text(self):
        m=load();devices=[];events=[]
        class Model:
            def __init__(self,**kwargs):self.device=kwargs['device'];devices.append(self.device)
            def predict(self,**kwargs):
                if self.device=='gpu:0':
                    yield payload('GPU PARTIAL')
                    raise RuntimeError('device lost during iteration')
                yield payload('CPU COMPLETE')
        with patch.dict('sys.modules',{'paddleocr':types.SimpleNamespace(PaddleOCR=Model),'paddle':types.SimpleNamespace(device=types.SimpleNamespace(is_compiled_with_cuda=lambda:True,cuda=types.SimpleNamespace(device_count=lambda:1)))}),patch.dict('os.environ',{'INVOICEVISION_OCR_DEVICE':'auto'}):
            for _ in range(3):
                lines=m._recognize_tile(None,300,200,{},lambda event,**info:events.append((event,info)))
                self.assertEqual([x['text'] for x in lines],['CPU COMPLETE'])
        self.assertEqual(devices,['gpu:0','cpu'])
        self.assertEqual(len([e for e,_ in events if e=='OCR_BACKEND_FAILED']),1)

    def test_both_backends_fail_explicitly(self):
        m=load()
        class Model:
            def __init__(self,**kwargs):raise RuntimeError('local model unavailable')
        with patch.dict('sys.modules',{'paddleocr':types.SimpleNamespace(PaddleOCR=Model),'paddle':types.SimpleNamespace(device=types.SimpleNamespace(is_compiled_with_cuda=lambda:True,cuda=types.SimpleNamespace(device_count=lambda:1)))}),patch.dict('os.environ',{'INVOICEVISION_OCR_DEVICE':'gpu'}):
            with self.assertRaises(RuntimeError):m._recognize_tile(None,300,200,{})

    def test_invalid_preference_does_not_guess(self):
        with patch.dict('os.environ',{'INVOICEVISION_OCR_DEVICE':'invalid'}):
            with self.assertRaises(ValueError):load()._recognize_tile(None,300,200,{})

    def test_child_zones_protect_unknown_text_crossing_gutter(self):
        path=PATH.with_name('INVOICE_OCR_RECURSIVE_ZONES_R109.py')
        spec=importlib.util.spec_from_file_location('r144_zones',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        anchors=[{'xyxy':[10,10,60,25],'category':'supplier'},
                 {'xyxy':[10,70,60,85],'category':'tax'}]
        source=anchors+[{'xyxy':[10,20,60,75],'category':'unknown'}]
        self.assertIsNotNone(module._best_partition([0,0,100,100],anchors,'horizontal'))
        self.assertIsNone(module._best_partition([0,0,100,100],anchors,'horizontal',source))

if __name__=='__main__':unittest.main(verbosity=2)
