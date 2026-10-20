"""Injected OCR backend lifecycle; runtime tests do not certify model accuracy."""
from __future__ import annotations


class OcrUnavailable(RuntimeError):
    pass


class Runtime:
    def __init__(self, factory, validate, prefer_gpu=False):
        self.factory, self.validate = factory, validate
        self.prefer_gpu = prefer_gpu
        self.backend = None
        self.device = None
        self.gpu_failed = False
        self.diagnostics = []

    def recognize(self, source):
        devices = ['gpu', 'cpu'] if self.prefer_gpu and not self.gpu_failed else ['cpu']
        for device in devices:
            try:
                if self.backend is None or self.device != device:
                    self.backend = self.factory(device)
                    self.device = device
                result = self.backend(source)
                if not self.validate(result):
                    raise ValueError('OCR result failed schema validation')
                return {'result': result, 'device': device,
                        'fallback_used': self.gpu_failed, 'posting_eligible': False}
            except Exception as exc:
                # Memory exhaustion, device errors and unavailable offline models
                # must be visible; a second failure must never become empty success.
                self.diagnostics.append({'device': device, 'error_type': type(exc).__name__,
                                         'message': str(exc)})
                self.backend, self.device = None, None
                if device == 'gpu':
                    self.gpu_failed = True
                else:
                    raise OcrUnavailable('CPU OCR unavailable; preserve input for retry') from exc
        raise OcrUnavailable('No OCR backend completed')
