"""Source-native morphology/closure audit of pinned 36 synthetic + 15 real inputs."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import zipfile
import cv2
import numpy as np
from .r144_physical_contour_audit import audit, closed_regions, closed_ink_contours


def run(baseline,out):
    engine=baseline/'InvoiceVisionChild/Engine'
    sys.path.insert(0,str(engine))
    native=importlib.import_module('INVOICEVISION_RAW_MULTISCALE_R56')
    border=importlib.import_module('INVOICE_OCR_PRINTED_BORDER_R104')
    cases=[(p.name,p.read_bytes(),'synthetic') for p in sorted((engine/'InvoiceFormatExamples_R2').glob('*.png'))]
    with zipfile.ZipFile(engine/'VISUAL_BENCHMARK_15_PHOTOS.zip') as z:
        cases += [(Path(n).name,z.read(n),'real') for n in sorted(z.namelist())
                  if n.startswith('images/') and n.lower().endswith(('.png','.jpg','.jpeg'))]
    assert len(cases)==51
    assert len({hashlib.sha256(raw).hexdigest() for _,raw,_ in cases})==51
    out.mkdir(parents=True,exist_ok=True)
    report={'source_count':51,'real_count':15,'synthetic_count':36,'cases':[],
            'release_verified':False,'physical_boxes_verified':False}
    for name,raw,kind in cases:
        source=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        before=hashlib.sha256(source.tobytes()).hexdigest()
        layers=native.raw_multiscale(cv2.cvtColor(source,cv2.COLOR_BGR2GRAY))
        proposals=native.r70_provisional_cells(layers)
        reviewed=audit(layers,proposals)
        closed=closed_regions(layers)
        ink_contours=closed_ink_contours(layers)
        info,overlay,blank=border.analyze_borders(layers,source.shape)
        mask=overlay[:,:,3]>0
        assert not np.any(mask & (layers['h13']==0) & (layers['v13']==0)), name
        assert before==hashlib.sha256(source.tobytes()).hexdigest(), name
        # Visualize only source-supported pixels; candidate rectangles are not
        # drawn as if they were detected printed borders.
        marked=source.copy();marked[mask]=(marked[mask]*.35+overlay[:,:,:3][mask]*.65).astype('uint8')
        panel=np.concatenate([source,marked,blank],axis=1)
        cv2.imwrite(str(out/(Path(name).stem+'_native_comparison.jpg')),panel)
        cv2.imwrite(str(out/(Path(name).stem+'_source_rule_mask.png')),mask.astype('uint8')*255)
        result={'file':name,'kind':kind,'source_sha256':hashlib.sha256(raw).hexdigest(),
                'raw_rule_pixels':int(np.count_nonzero(layers['raw'])),
                'printed_rule_candidate_pixels':int(mask.sum()),'counts':info['counts'],
                'cell_candidates':len(proposals),
                'closed_region_candidates':closed,
                'closed_region_count':len(closed),
                'source_ink_contours':ink_contours,
                'source_ink_contour_count':len(ink_contours),
                'closed_source_components':sum(r['closed_source_component'] for r in reviewed),
                'cell_audit':reviewed,'physical_boxes_verified':False}
        report['cases'].append(result)
        (out/'REPORT.json').write_text(json.dumps(report,indent=2))
        print(name,result['cell_candidates'],result['closed_source_components'],flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.baseline,a.out)
