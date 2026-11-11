"""Small, deterministic rejection checks for known style failures; no retouching."""
from collections import Counter, deque
from PIL import ImageChops, ImageFilter

POLICY_ID = 'confirmed-avatar-corrections-v6'
INSTRUCTIONS = (
    '衣领花纹必须服从脸部主次：只概括原照已有纹样，缩小面积、减少数量与细碎细节，不把胸针式大花或高对比锯齿搬到领口。花纹仅用同一套garment_plan中的服饰角色色，不借腮红、肤色、detail白色或头发色来画醒目图案。若本套花纹色与衣领底色相同，如实合并，或用同套已有服饰辅色做少量细线提示；不为展示花纹新增颜色。'
    '皮肤结构影与衣服褶皱必须分开：可见下颌下方的颈部必须保留下颌投影，按头颈转向形成简洁硬边暗面，编码#00FF00；脸侧结构暗面按照片角度保留，不画写实渐变、浓妆轮廓或额外阴影描边。禁用衣褶投影不等于删除皮肤暗面。原作有腮红且面颊可见时，不分男女均保留#FF00FF腮红区域，侧脸保留可见一侧，不因男性、简化或白底省略。衣服保留照片衣型，主布料之外保留同源内搭、领袖滚边和装饰辅色。用户要求增强服饰时，可用本套garment_plan已有辅色添加少量滚边或简洁几何小装饰；默认不移植模板整套衣型、人物首饰或标志。白底不是把衣服简化成单一填色的理由，不借头发/背景/肤色凑衣色，也不用粗阴影充当装饰。'

    '面颊腮红是独立浅色圆面，只用纯正#FF00FF编码，不与唇、衣服花纹混用；'
    '不画黑色/深色腮红、腮红描边或腮红渐变。最终程序使用本版原作cheek采样，'
    '保持原作轻淡程度，不拿主线色、衣服色或浓肤影替代。'
    '腮红内区平涂，边界连续平顺；禁止点状颗粒、零散墨点、杂色、锯齿或描边式断点，保留正常边缘抗锯齿。'
    '项链等配饰用连续轮廓和少量干净色面概括，不堆砌针尖碎点、密集链节网纹或内部杂质；保留照片形状与遮挡。'
    '用户明确银色时，只改变指定配饰为干净银白/浅灰面并保留必要主线；编码底稿仍用指定配饰区域编码，不把银色涂到皮肤或衣服，不将所有首饰默认银色。'
    '嘴形先按本次明确要求，再按原照片判断：默认 `mouth_style: auto` 区分闭嘴、微张与露齿；闭嘴且没有辨识性唇形时用符号口线，双唇清楚可见且确为人物特征时可保留简化双唇，微张与露齿保留相应开口和嘴角。不能把所有嘴都缩成短线或复制模板的厚唇。明确的 `line` 只用口线，`upper-lip` 用简化上唇配独立短下唇线，`full-lips` 允许简化双唇；明确“不露牙”时不画牙齿。所有模式均为平面概括，无写实唇纹、高光或唇部体积；不按性别决定唇形，腮红编码不作唇色。'
    '露齿表情先保留原照嘴角方向、开口与笑容，再概括唇形：牙齿用一块干净连续的浅色面，不逐颗分割、不画牙龈；上唇以细轮廓概括，下唇仅用短弧或省略，不用一圈浓色厚唇包住牙齿。嘴宽、开口高度和唇厚按原照相对面部的比例，不得沿用模板的夸大厚唇，也不能因简化而把露齿笑画成闭嘴。牙齿只用同套色板中已有的白或近白浅色；detail角色可能是粉色或深色，不能未经判断就当作牙色。编码底稿仍将牙区独立画为detail；若同套detail不适合作牙色，成品需按已观察的明确牙齿局部蒙版，复用同套已有白/近白色重填并记录，仅修改牙区，不改全局detail映射；不能可靠分出牙区时停止说明。不借腮红、发色或服饰色涂牙。007的男性露齿笑按此处理；性别不替代对原照结构的判断，原有明确双唇与闭嘴要求继续按本次指令执行。'
    '衣服褶皱只用少量细、疏、均匀圆端的黑色结构曲线，'
    '线宽约外轮廓的0.35–0.6，随肩袖和布料受力走向；'
    '禁止用#8000FF衣褶暗片、粗楔形/镰刀形/闪电形填充、大片衣服投影代替细线。'
    '即使暗片与主线同色、或连着外轮廓，也属于禁用填充衣褶；逐段检查线条是否仍是细线，不能仅凭没有clothing_shadow编码判通过。肩带逐侧核对数量、宽度、扣件与衣片的连接：照片可见或本次明确要求的第二条不能遗漏；真实遮挡保留，不强行穿过头发或手臂。用服饰底色加细轮廓/缝线表达，不能把整条肩带和扣件合成粗实心墨块。背包、背包肩带、胸带和内搭按实际部件区分，明暗分配服从照片或本次明确要求，不把背包与内搭的色位颠倒；不将某次“深背包、浅内搭”推广到所有照片。'
    '外套/内搭、真实领袖滚边、花纹和原作衣料渐变仍各自保留，'
    '不能为满足分色强加阴影块。新底稿保留#8000FF编码供旧文件兼容，但本次不绘制该角色。'
)


# The same concise rules feed the generation prompt and manual review plan.
CONFIRMED_CORRECTION_CHECKS = [{'id': 'mouth_proportion_stroke',
  'expected': '嘴宽、开口和唇厚按照片相对脸宽与五官的位置关系概括；符号化不等于缩成针尖，128像素头像中仍可读。口线平顺圆端，重量与本次五官主线协调，不用发丝般的细线或厚重唇环；明确双唇或不露牙的要求分别保留，不把057的口宽、065的唇形套给所有人。'},
 {'id': 'face_contour_age_detail',
  'expected': '可见脸侧至下颌轮廓连续、闭合关系合理，只在真实遮挡或本次明确的留白画法处断线。照片没有的眼角短褶皱不凭空添加；照片确有的年龄和表情纹理按简化程度保留，不统一去皱或幼态化。'},
 {'id': 'necklace_topology',
  'expected': '照片有项链时，链条按颈部悬垂走向形成可辨认连续路径，吊坠实际挂接链条；真实遮挡处隐藏、重新露出处接续。不把两条锁骨线加孤立圆圈当作项链，也不为所有人补项链；链条、皮肤结构线和衣领各自可辨。'},
 {'id': 'mesh_arm_readability',
  'expected': '照片有针织、网格或蕾丝时，保留衣型、领口和内搭，减为稀疏大网眼与少量纹样线；纹样轻于手臂与袖口轮廓，不以粗斜带或横向闭环分割手臂。先读出真实肩肘腕和袖口，再读出花纹；直前臂不凭空添加肘线，纹样与肢体轮廓相接不能造成假关节。'},
 {'id': 'arm_taper_and_separation',
  'expected': '沿照片肩—肘—腕组织上臂、前臂和袖料，宽度平缓变化、腕部自然收束，内臂与躯干有清楚边界；不画骤细锥形、等粗弯管或无依据的鼓起肌肉。粗细、透视和肌肉感服从该人物，不用性别刻板规则统一瘦身。'},
 {'id': 'inner_shirt_not_skin',
  'expected': '外套内的T恤、衬衫及领口下方可见布料属于衣服，分别编码并按冻结服饰计划填色，不能误涂成裸露皮肤。需要局部改色时仅改已观察衣片并记录用户授权与色值来源；044的蓝紫色是该例局部确认，不是未来内搭的默认色。'},
 {'id': 'chin_shadow_shape',
  'expected': '下颌投影贴合下巴与颈部的承接位置，随头部转向概括为简洁有方向的硬边暗面；脸侧暗面也为干净连续色面。不能将任意颈部横块、多块脏影或颗粒当作下巴投影；真实衣领/头发遮挡仍保留，衣褶禁暗片不代表删除皮肤结构影。'}]
INSTRUCTIONS += '\n已确认修订规则：' + ''.join(item['expected'] for item in CONFIRMED_CORRECTION_CHECKS)


def validate_cheek_edge_specks(ids, line_alpha, role_ids):
    """Reject isolated ink fragments in a narrow blush-edge band only.

    Connected facial/necklace strokes remain intact. This is detection, not a
    global denoiser, and it never modifies either shared geometry map.
    """
    width, height = ids.size
    scale = min(width, height) / 1024
    radius = max(1, round(4 * scale))
    blush = ids.point([255 if value == role_ids['accent'] else 0 for value in range(256)])
    if blush.getbbox() is None:
        return {'policy_id': 'cheek-edge-isolated-ink-v1', 'isolated_ink_regions': [], 'scope': 'no visible blush role'}
    # Remove subpixel role flecks from the detection mask only; artwork is unchanged.
    blush = blush.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    band = ImageChops.subtract(blush.filter(ImageFilter.MaxFilter(radius * 2 + 1)),
                               blush.filter(ImageFilter.MinFilter(radius * 2 + 1)))
    ink = line_alpha.tobytes()
    band_bytes = band.tobytes()
    seeds = ImageChops.multiply(band, line_alpha.point([255 if value >= 64 else 0 for value in range(256)]))
    box = seeds.getbbox()
    max_area = max(2, round(16 * scale * scale))
    visited = set()
    suspects = []
    if box:
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                seed = y * width + x
                if not band_bytes[seed] or ink[seed] < 64 or seed in visited:
                    continue
                component = []
                todo = [seed]
                visited.add(seed)
                while todo:
                    pos = todo.pop()
                    component.append(pos)
                    cy, cx = divmod(pos, width)
                    for ny in range(max(0, cy - 1), min(height, cy + 2)):
                        for nx in range(max(0, cx - 1), min(width, cx + 2)):
                            nxt = ny * width + nx
                            if ink[nxt] >= 32 and nxt not in visited:
                                visited.add(nxt)
                                todo.append(nxt)
                if len(component) <= max_area and all(band_bytes[pos] for pos in component):
                    xs = [pos % width for pos in component]
                    ys = [pos // width for pos in component]
                    suspects.append({'pixels': len(component), 'bbox': [min(xs), min(ys), max(xs)+1, max(ys)+1]})
    # Magenta/red edge blends can decode to clothing_pattern instead of ink.
    # The existing skin-island guard ignores tiny AA fragments; on the cheek
    # rim these fragments become a visible dotted outline after palette fill.
    labels = ids.tobytes()
    foreign_roles = {role_ids[role] for role in ('clothing', 'clothing_inner', 'clothing_shadow', 'clothing_trim', 'clothing_pattern') if role in role_ids}
    visited_roles = set()
    edge_box = band.getbbox()
    if edge_box:
        for y in range(edge_box[1], edge_box[3]):
            for x in range(edge_box[0], edge_box[2]):
                seed = y * width + x
                if not band_bytes[seed] or labels[seed] not in foreign_roles or seed in visited_roles:
                    continue
                label = labels[seed]
                component = []
                todo = [seed]
                visited_roles.add(seed)
                while todo:
                    pos = todo.pop()
                    component.append(pos)
                    cy, cx = divmod(pos, width)
                    for ny in range(max(0, cy - 1), min(height, cy + 2)):
                        for nx in range(max(0, cx - 1), min(width, cx + 2)):
                            nxt = ny * width + nx
                            if labels[nxt] == label and nxt not in visited_roles:
                                visited_roles.add(nxt)
                                todo.append(nxt)
                if len(component) <= max_area and all(band_bytes[pos] for pos in component):
                    xs = [pos % width for pos in component]
                    ys = [pos // width for pos in component]
                    suspects.append({'role_id': label, 'pixels': len(component), 'bbox': [min(xs), min(ys), max(xs)+1, max(ys)+1]})
    if suspects:
        raise ValueError('腮红边缘存在点状墨粒：停止交付，仅按实际腮红局部蒙版清理；不全图降噪。证据：' + str(suspects))
    return {'policy_id': 'cheek-edge-isolated-ink-v1', 'isolated_ink_regions': [],
            'edge_band_radius': radius, 'max_speck_pixels': max_area,
            'scope': '仅拒绝腮红边缘孤立小墨点与服饰误码碎点；不证明所有颗粒、描边或配饰洁净度'}


def _significant_component_pixels(ids, role_id, min_area=24):
    """Count role pixels in meaningful connected regions only.

    Semantic masters are generated from hard role colors. Anti-aliased edges
    around black linework can decode a few scattered pixels as the legacy
    clothing-shadow role. Those one-to-seventeen-pixel fragments are noise,
    not filled fold patches, and must not reject an otherwise valid master.
    """
    width, height = ids.size
    labels = ids.tobytes()
    visited = bytearray(len(labels))
    significant = 0
    for seed, label in enumerate(labels):
        if label != role_id or visited[seed]:
            continue
        visited[seed] = 1
        todo = deque([seed])
        area = 0
        while todo:
            pos = todo.popleft()
            area += 1
            y, x = divmod(pos, width)
            for nxt in ((pos - 1 if x else -1),
                        (pos + 1 if x + 1 < width else -1),
                        (pos - width if y else -1),
                        (pos + width if y + 1 < height else -1)):
                if nxt < 0:
                    continue
                if labels[nxt] == role_id and not visited[nxt]:
                    visited[nxt] = 1
                    todo.append(nxt)
        if area >= min_area:
            significant += area
    return significant


def validate_role_map(ids, line_alpha, role_ids, *, require_blush=False, require_skin_shadow=False):
    """Reject garment labels enclosed by skin and filled fold patches.

    This deliberately does not guess face landmarks, redraw lips, or repair
    roles. A detected mismatch must be fixed against the actual artwork.
    """
    width, height = ids.size
    labels = ids.tobytes()
    hist = ids.histogram()
    raw_shadow_pixels = hist[role_ids['clothing_shadow']]
    shadow_pixels = _significant_component_pixels(ids, role_ids['clothing_shadow'])
    if shadow_pixels > max(16, width * height * .0002):
        raise ValueError('衣褶仍为填充暗片：须改为细结构线；保留真实衣层、花纹和衣料渐变，不增加投影块')
    garment_ids = {role_ids[r] for r in (
        'clothing', 'clothing_inner', 'clothing_shadow',
        'clothing_trim', 'clothing_pattern')}
    skin_ids = {role_ids['skin_base'], role_ids['skin_shadow']}
    visited = bytearray(len(labels))
    suspects = []
    for seed, label in enumerate(labels):
        if label not in garment_ids or visited[seed]:
            continue
        visited[seed] = 1
        todo = deque([seed])
        area = 0
        contacts = Counter()
        min_x = max_x = seed % width
        min_y = max_y = seed // width
        while todo:
            pos = todo.popleft()
            area += 1
            y, x = divmod(pos, width)
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            for nxt in ((pos - 1 if x else -1),
                        (pos + 1 if x + 1 < width else -1),
                        (pos - width if y else -1),
                        (pos + width if y + 1 < height else -1)):
                if nxt < 0:
                    continue
                if labels[nxt] == label:
                    if not visited[nxt]:
                        visited[nxt] = 1
                        todo.append(nxt)
                else:
                    contacts[labels[nxt]] += 1
        # Exclude ink/AA boundary labels; require actual surrounding skin.
        skin_contact = sum(contacts[k] for k in skin_ids)
        other_contact = sum(n for k, n in contacts.items() if k not in skin_ids | {0})
        # A narrow garment strap may be between two exposed arms and continue
        # to the canvas edge; that is not a skin-enclosed face island.
        # Ignore tiny anti-aliased fragments and small garment-pattern pieces
        # touching a neckline; a real garment island enclosed by skin is
        # materially larger than these edge fragments.
        if max_y < height - 1 and area >= 200 and skin_contact >= 12 and skin_contact / max(1, skin_contact + other_contact) >= .80:
            suspects.append({'role_id': label, 'pixels': area,
                             'bbox': [min_x, min_y, max_x + 1, max_y + 1]})
    if suspects:
        raise ValueError('皮肤内出现服饰编码，疑似腮红/嘴部被误解成花纹；停止填色，不猜色、不交付深色腮红。证据：' + str(suspects))
    # Count visible interiors rather than stray pixels or labels hidden by ink.
    ink = line_alpha.tobytes()
    visible_counts = Counter(label for label, alpha in zip(labels, ink) if alpha < 64)
    skin_area = sum(visible_counts[role_ids[r]] for r in ('skin_base', 'skin_shadow'))
    minimum = max(16, round(skin_area * .002))
    if skin_area >= width * height * .01:
        missing = []
        for role, required in (('accent', require_blush), ('skin_shadow', require_skin_shadow)):
            if required and visible_counts[role_ids[role]] < minimum:
                missing.append(role)
        if missing:
            raise ValueError('皮肤细节缺失：' + ', '.join(missing) + '；停止交付，按照片可见部位核对腮红与下颌颈影，不能靠孤立编码点通过')
    return {'policy_id': POLICY_ID, 'filled_fold_pixels': shadow_pixels,
            'raw_clothing_shadow_pixels': raw_shadow_pixels,
            'ignored_antialias_shadow_pixels': raw_shadow_pixels - shadow_pixels,
            'skin_enclosed_garment_regions': [],
            'visible_blush_pixels': visible_counts[role_ids['accent']],
            'visible_skin_shadow_pixels': visible_counts[role_ids['skin_shadow']],
            'detail_checks': {'require_blush': require_blush, 'require_skin_shadow': require_skin_shadow},
            'scope': '拒绝已知衣褶暗片与皮肤内服饰误码；嘴形、线宽和语义仍须实际看图核对'}
