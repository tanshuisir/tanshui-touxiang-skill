"""Decode source-independent clothing roles with PIL; no extra dependencies."""
import hashlib
from pathlib import Path
from PIL import Image, ImageChops, ImageFilter, ImageMath, ImageOps

ENCODING_ID='semantic-garments-v2'
ENCODING={
 'line':'#000000','background':'#FFFFFF','skin_base':'#FF0000',
 'skin_shadow':'#00FF00','hair':'#FFFF00','clothing':'#00FFFF',
 'accent':'#FF00FF','detail':'#0000FF',
 'clothing_inner':'#FF8000','clothing_shadow':'#8000FF',
 'clothing_trim':'#80FF00','clothing_pattern':'#FF0080',
 'accessory':'#0080FF','headwear':'#00FF80',
}
IDS={'line':0,'background':7,'skin_base':4,'skin_shadow':2,'hair':6,
     'clothing':3,'accent':5,'detail':1,'clothing_inner':8,'clothing_shadow':9,
     'clothing_trim':10,'clothing_pattern':11,'accessory':12,'headwear':13}
PROP_ENCODING_ID='semantic-props-v3'
PROP_ENCODING=dict(ENCODING, object_primary='#80FFFF', object_secondary='#FFFF80', tongue='#FF8080')
PROP_IDS=dict(IDS, object_primary=14, object_secondary=15, tongue=16)

def _count(mask):return sum(v*n for v,n in enumerate(mask.histogram()))/255
def _mask(ids,role):return ids.point([255 if v==IDS[role] else 0 for v in range(256)])

def decode(path, *, encoding=ENCODING_ID):
    if encoding not in (ENCODING_ID, PROP_ENCODING_ID):raise ValueError('未知区域编码版本')
    encoding_codes=PROP_ENCODING if encoding==PROP_ENCODING_ID else ENCODING
    role_ids=PROP_IDS if encoding==PROP_ENCODING_ID else IDS
    path=Path(path)
    with Image.open(path) as original:
        if getattr(original,'n_frames',1)!=1:raise ValueError('技术底稿必须为单帧')
        if ('A' in original.getbands() or 'transparency' in original.info) and original.convert('RGBA').getchannel('A').getextrema()!=(255,255):
            raise ValueError('技术底稿必须是不透明编码图')
        image=original.convert('RGB')
    channels=image.split()
    maximum=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
    normalized=Image.merge('RGB',tuple(ImageMath.lambda_eval(
        lambda d:d['c']*255/(d['m']+(d['m']==0)),c=c.convert('I'),m=maximum.convert('I')).convert('L') for c in channels))
    palette=[0]*768
    for role,code in encoding_codes.items():palette[role_ids[role]*3:role_ids[role]*3+3]=bytes.fromhex(code[1:])
    palette_image=Image.new('P',(1,1));palette_image.putpalette(palette)
    quantized=normalized.quantize(palette=palette_image,dither=Image.Dither.NONE)
    ids=Image.frombytes('L',image.size,quantized.tobytes()).point([i if i in role_ids.values() else 0 for i in range(256)])
    quantized.putpalette(palette)
    residual=ImageChops.difference(normalized,quantized.convert('RGB'))
    r,g,b=residual.split();error=ImageChops.lighter(ImageChops.lighter(r,g),b)
    actual_ink=maximum.point([255 if v<=96 else 0 for v in range(256)])
    invalid=ImageChops.multiply(error.point([255 if v>35 else 0 for v in range(256)]),
                               maximum.point([255 if v>96 else 0 for v in range(256)]))
    fraction=_count(invalid)/(image.width*image.height)
    if fraction>.03:raise ValueError(f'技术底稿编码不可靠：{fraction:.1%}像素偏离服饰角色编码')
    alpha=ImageOps.invert(maximum).point([0 if v<=8 else 255 if v>=247 else v for v in range(256)])
    alpha=ImageChops.multiply(alpha,actual_ink.filter(ImageFilter.MaxFilter(7)))
    # Correct ambiguous AA labels only in a 3px neighborhood of stable fills.
    stable=ImageChops.multiply(maximum.point([255 if v>=224 else 0 for v in range(256)]),
                               error.point([255 if v<=18 else 0 for v in range(256)]))
    neighbors={role_ids[role]:ImageChops.multiply(ids.point([255 if v==role_ids[role] else 0 for v in range(256)]),stable).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(7)).tobytes()
               for role in role_ids if role!='line'}
    labels=bytearray(ids.tobytes());rgb=normalized.tobytes();stable_bytes=stable.tobytes()
    codes={role_ids[role]:bytes.fromhex(code[1:]) for role,code in encoding_codes.items() if role!='line'}
    for n,label in enumerate(labels):
        if label==0 or stable_bytes[n] or neighbors[label][n]:continue
        options=[role for role,mask in neighbors.items() if mask[n]]
        if options:labels[n]=min(options,key=lambda role:sum((v-w)**2 for v,w in zip(rgb[n*3:n*3+3],codes[role])))
    ids=Image.frombytes('L',image.size,bytes(labels))
    return image,ids,alpha,{
        'schema_version':3 if encoding==PROP_ENCODING_ID else 2,'encoding_id':encoding,'encoding':encoding_codes,'role_ids':role_ids,
        'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'role_map_sha256':hashlib.sha256(ids.tobytes()).hexdigest(),
        'line_alpha_sha256':hashlib.sha256(alpha.tobytes()).hexdigest(),
        'role_pixel_counts':{role:ids.histogram()[role_id] for role,role_id in role_ids.items()},
        'unknown_fraction':round(fraction,6),
        'line_core_fraction':round(_count(alpha.point([255 if v>=160 else 0 for v in range(256)]))/(image.width*image.height),6),
        'validation_scope':'可解码性、分区与共用几何；不证明照片相似度或服饰语义'}
