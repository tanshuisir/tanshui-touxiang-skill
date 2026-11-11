"""Freeze four complete reference palettes; never combine unrelated swatches."""
from copy import deepcopy

from source_colorways import (POLICY_ID, colorway, eligible_colorways,
                             plan_for, upgrade_gradient_plan, validate_plan)
from colorway_selection import draw_colorway_ids


def _random_references():
    """Draw across the entire eligible library, never a fixed preferred four."""
    candidates = eligible_colorways()
    if len(candidates) < 4:
        raise ValueError('完整模板配色目录不足四套已核对方案；停止，不单换背景或跨图混色')
    return draw_colorway_ids([item['source_hd_id'] for item in candidates], 4)


def _reuse_plans(plans):
    if not isinstance(plans, list) or len(plans) != 4:
        raise ValueError('variant_plans 必须恰好包含四个完整模板配色计划')
    result = [upgrade_gradient_plan(plan) for plan in plans]
    references = set()
    for index, plan in enumerate(result, 1):
        item = validate_plan(plan)
        current_background = plan_for(item['id'])['background_plan']
        if plan['background_plan'] != current_background:
            plan['background_policy_migration'] = {
                'from': plan['background_plan']['tone_policy']['id'],
                'to': current_background['tone_policy']['id'],
                'reason': '完整同源角色色均合规，仅刷新全库背景规则元数据；不替换任何角色颜色'}
            plan['background_plan'] = current_background
        if plan.get('variant_index') != index:
            raise ValueError('variant_index 必须依次为1至4')
        references.add(plan['source_hd_id'])
    if len(references) != 4:
        raise ValueError('四配色需要四张不同模板；肤色和背景不要求强行互异')
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
            raise ValueError('完整模板方案与旧混搭方案不能混用')
        raise ValueError('旧素材或混搭配色计划已停用；请明确重新选择TS模板')
    migration = None
    if requested is None:
        references, selection = _random_references()
    else:
        references, selection = requested, None
    if (not isinstance(references, list) or len(references) != 4 or
            any(type(value) is not int for value in references) or len(set(references)) != 4):
        raise ValueError('colorway_reference_ids 需要四个不同模板的整数编号')
    result = []
    for index, reference in enumerate(references, 1):
        item = colorway(reference)
        plan = plan_for(item['id'], brief)
        plan['variant_index'] = index
        if selection:
            plan['palette_selection'] = deepcopy(selection)
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
    for key in ('variant_plans', 'gradient_adjustment', 'colorway_reference_ids', 'object_plan'):
        result.pop(key, None)
    result.update(variants=1, selected_variant_index=index, source_colorway_id=plan['id'],
                  art_palette=plan['id'], color_mode='expressive',
                  color_roles=deepcopy(plan['roles']), gradient=deepcopy(plan['gradient']),
                  garment_plan=deepcopy(plan['garment_plan']),
                  skin_template_id=plan['source_selection']['skin']['template_id'],
                  background_template_id=plan['source_selection']['background']['template_id'],
                  line_reference_id=plan['line_plan']['source_reference_id'],
                  line_family=plan['line_plan']['family_id'])
    if plan.get('background_policy_migration'):
        result['background_policy_migration'] = deepcopy(plan['background_policy_migration'])
    if plan.get('object_plan'):
        result['object_plan'] = deepcopy(plan['object_plan'])
    return result
