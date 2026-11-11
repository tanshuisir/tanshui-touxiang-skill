"""Source-backed garment layers; cached metadata only during generation."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

POLICY_ID='source-garment-layers-v1'
ENCODING_ID='semantic-garments-v2'
GARMENT_ROLES=('clothing','clothing_inner','clothing_shadow','clothing_trim','clothing_pattern')

@lru_cache(maxsize=1)
def catalog():
    data=json.loads((Path(__file__).resolve().parents[1]/'references/garment-library.json').read_text())
    if data.get('policy_id')!=POLICY_ID or data.get('source_count')!=70 or {x.get('source_hd_id') for x in data.get('garments',[])}!=set(range(1,71)):
        raise ValueError('70套服饰分层目录缺失，不能回退成单一衣色')
    return {x['source_hd_id']:x for x in data['garments']}

def plan_for(hd):
    item=deepcopy(catalog()[hd])
    item['policy_id']=POLICY_ID
    return item

def validate(plan,hd):
    if plan!=plan_for(hd):
        raise ValueError('服饰配色或来源被改动，必须使用同一模板的服饰取样')

def upgrade(plan):
    result=deepcopy(plan)
    hd=result['source_hd_id']
    if 'garment_plan' in result:validate(result['garment_plan'],hd)
    else:
        result['garment_plan']=plan_for(hd)
        result['garment_migration']={'to':POLICY_ID,'reason':'同一模板补齐外层、内层、衣褶、滚边及花纹色；不重新抽色'}
    return result
