"""Freeze four complete reference palettes; never combine unrelated swatches."""
from copy import deepcopy

from source_colorways import (POLICY_ID, catalog, colorway, eligible_colorways,
                             plan_for, upgrade_gradient_plan, validate_plan)


def _default_references():
    """Replace an inadmissible default only by another complete colorway."""
    preferred = catalog()['default_reference_ids']
    if (not isinstance(preferred, list) or len(preferred) != 4 or
            any(type(value) is not int for value in preferred) or len(set(preferred)) != 4):
        raise ValueError('默认完整配色需要四个不同原作的整数编号')
    for reference in preferred:
        colorway(reference)
    candidates = eligible_colorways()
    available = {item['source_hd_id'] for item in candidates}
    references = [reference for reference in preferred if reference in available]
    references.extend(item['source_hd_id'] for item in candidates
                      if item['source_hd_id'] not in references)
    if len(references) < 4:
        raise ValueError('完整原作配色目录不足四套明亮非白方案；停止，不单换背景或跨图混色')
    return references[:4]


def _reuse_plans(plans):
    if not isinstance(plans, list) or len(plans) != 4:
        raise ValueError('variant_plans 必须恰好包含四个完整原作配色计划')
    result = [upgrade_gradient_plan(plan) for plan in plans]
    references = set()
    for index, plan in enumerate(result, 1):
        item = validate_plan(plan)
        current_background = plan_for(item['id'])['background_plan']
        if plan['background_plan'] != current_background:
            plan['background_policy_migration'] = {
                'from': plan['background_plan']['tone_policy']['id'],
                'to': current_background['tone_policy']['id'],
                'reason': '完整同源角色色均合规，仅刷新非白背景约束元数据；不替换任何角色颜色'}
            plan['background_plan'] = current_background
        if plan.get('variant_index') != index:
            raise ValueError('variant_index 必须依次为1至4')
        references.add(plan['source_hd_id'])
    if len(references) != 4:
        raise ValueError('四配色需要四张不同原作；肤色和背景不要求强行互异')
    return result


def make_variant_plans(brief, first_plan, record, reference_set, color_mode, plan_factory):
    """The old mixed-palette factory is retained in the signature but unused."""
    if color_mode != 'expressive':
        raise ValueError('四配色使用 expressive；保留自然发色请使用 --variants 1')
    frozen = brief.get('variant_plans')
    requested = brief.get('colorway_reference_ids')
    if frozen is not None and requested is None:
        if not isinstance(frozen, list) or len(frozen) != 4:
            raise ValueError('variant_plans 必须恰好包含四个完整配色计划')
        marked = [p.get('source_colorway', {}).get('policy_id') == POLICY_ID
                  for p in frozen if isinstance(p, dict)]
        if all(marked) and len(marked) == 4:
            return _reuse_plans(frozen)
        if any(marked):
            raise ValueError('完整原作方案与旧混搭方案不能混用')
        migration = {'from': 'legacy-mixed-colorways', 'to': POLICY_ID,
                     'reason': '旧方案跨原作混色，改用完整原作色板'}
    else:
        migration = None
    references = requested if requested is not None else _default_references()
    if (not isinstance(references, list) or len(references) != 4 or
            any(type(value) is not int for value in references) or len(set(references)) != 4):
        raise ValueError('colorway_reference_ids 需要四个不同原作的整数编号')
    result = []
    for index, reference in enumerate(references, 1):
        item = colorway(reference)
        plan = plan_for(item['id'], brief)
        plan['variant_index'] = index
        if migration:
            plan['migration'] = deepcopy(migration)
        result.append(plan)
    return _reuse_plans(result)


def select_variant_plan(brief, index):
    """Keep a selected original palette together for one new final render."""
    if type(index) is not int or not 1 <= index <= 4:
        raise ValueError('配色编号必须为1至4')
    plans = _reuse_plans(brief.get('variant_plans'))
    plan = plans[index - 1]
    result = deepcopy(brief)
    for key in ('variant_plans', 'gradient_adjustment', 'colorway_reference_ids'):
        result.pop(key, None)
    result.update(variants=1, selected_variant_index=index, source_colorway_id=plan['id'],
                  art_palette=plan['id'], color_mode='expressive',
                  color_roles=deepcopy(plan['roles']), gradient=deepcopy(plan['gradient']),
                  skin_template_id=plan['source_selection']['skin']['template_id'],
                  background_template_id=plan['source_selection']['background']['template_id'],
                  line_reference_id=plan['line_plan']['source_reference_id'],
                  line_family=plan['line_plan']['family_id'])
    if plan.get('background_policy_migration'):
        result['background_policy_migration'] = deepcopy(plan['background_policy_migration'])
    return result
