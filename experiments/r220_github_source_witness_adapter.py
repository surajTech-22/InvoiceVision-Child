"""R220 review-only source witness adapter. No OCR modification or posting."""
import hashlib
import re
from decimal import Decimal

NUM = re.compile(r'^(?:\d{1,11}[.,]\d{2}|\d{1,3}(?:,\d{3})+\.\d{2})$')
UNITS = {'ONE':1,'TWO':2,'THREE':3,'FOUR':4,'FIVE':5,'SIX':6,'SEVEN':7,'EIGHT':8,'NINE':9,
 'TEN':10,'ELEVEN':11,'TWELVE':12,'THIRTEEN':13,'FOURTEEN':14,'FIFTEEN':15,
 'SIXTEEN':16,'SEVENTEEN':17,'EIGHTEEN':18,'NINETEEN':19,
 'TWENTY':20,'THIRTY':30,'FORTY':40,'FIFTY':50,'SIXTY':60,
 'SEVENTY':70,'EIGHTY':80,'NINETY':90}
SCALES={'THOUSAND':1000,'LAKH':100000,'CRORE':10000000}

def money(raw):
 text=str(raw).strip()
 if not NUM.fullmatch(text):return None
 return Decimal(text.replace(',','.') if re.fullmatch(r'\d{1,11},\d{2}',text) else text.replace(',',''))

def words_value(raw):
 words=re.sub(r'\s+',' ',str(raw).upper().strip()).split()
 if not words or words[0]!='RUPEES':return None
 words=words[1:]
 if words and words[-1]=='ONLY':words.pop()
 if not words:return None
 total=group=0;last_scale=float('inf');prev=''
 for word in words:
  if word in UNITS:
   n=UNITS[word]
   if prev in UNITS and (UNITS[prev]>=20 or n>=20):
    if not (UNITS[prev] in range(20,100,10) and 0<n<10):return None
   group+=n
  elif word=='HUNDRED':
   if group<1 or group>9:return None
   group*=100
  elif word in SCALES:
   scale=SCALES[word]
   if scale>=last_scale or not group:return None
   total+=scale*group;last_scale=scale;group=0
  else:return None
  prev=word
 return total+group if total+group>0 else None

def propose(case,photo_bytes):
 """Return only a source-linked candidate for review, never financial truth."""
 if hashlib.sha256(photo_bytes).hexdigest()!=case['source_sha256']:
  raise ValueError('Original image SHA mismatch')
 texts=case['raw_texts'];boxes=case['raw_boxes'];w=case['source_width'];h=case['source_height']
 if len(texts)!=len(boxes) or w<=0 or h<=0:raise ValueError('Invalid OCR observation')
 for box in boxes:
  if len(box)!=4 or not (0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h):
   raise ValueError('Original bbox invalid')
 result={'status':'insufficient_witnesses','candidate_for_human_review':None,
  'certified_characters':0,'approved_training_labels':0,
  'accounting_write_permitted':False,'posting_eligible':False,
  'source_photo_sha256':case['source_sha256'],'raw_observation_count':len(texts),
  'witness_indices':[]}
 norm=lambda t:re.sub(r'[^A-Z]','',t.upper())
 a=[i for i,t in enumerate(texts) if norm(t)=='NETAMOUNTAFTERTAX']
 b=[i for i,t in enumerate(texts) if norm(t)=='AMOUNTINWORDS']
 if len(a)!=1 or len(b)!=1:return result
 ni,wi=a[0],b[0];na=boxes[ni];wa=boxes[wi]
 cy=lambda box:(box[1]+box[3])/2
 matches=[i for i,t in enumerate(texts) if i not in (ni,wi) and money(t) is not None
  and -.01*w<=boxes[i][0]-na[2]<=.36*w
  and -.02*h<=boxes[i][1]-na[1]<=.075*h
  and -.35*(na[3]-na[1])<=cy(boxes[i])-cy(na)<=max(1.6*(na[3]-na[1]),.015*h)]
 word_matches=[i for i,t in enumerate(texts) if i not in (ni,wi)
  and t.upper().startswith('RUPEES ') and -.025*w<=boxes[i][0]-wa[2]<=.16*w
  and -.04*h<=cy(boxes[i])-cy(wa)<=.11*h]
 if len(matches)!=1 or len(word_matches)!=1:return result
 mi,vi=matches[0],word_matches[0]
 overlap=lambda x,y:min(x[2],y[2])>max(x[0],y[0]) and min(x[3],y[3])>max(x[1],y[1])
 if overlap(boxes[mi],boxes[vi]) or overlap(boxes[mi],na) or overlap(boxes[vi],wa):
  return result
 result['witness_indices']=[ni,mi,wi,vi]
 integer=words_value(texts[vi]);value=money(texts[mi])
 if integer is None:result['status']='unparseable_words'
 elif value!=Decimal(integer).quantize(Decimal('0.00')):
  result['status']='conflicting_printed_witnesses'
 else:
  result['status']='matching_unverified_printed_witnesses'
  result['candidate_for_human_review']=str(value)
 return result
