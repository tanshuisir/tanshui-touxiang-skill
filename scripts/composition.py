"""Shared square canvas and upper-body composition defaults."""

DEFAULT_SIZE = '1024x1024'
FRAMING_ID = 'upper-body-v1'
FRAMING_PLAN = {
    'id': FRAMING_ID,
    'canvas_aspect': '1:1',
    'crown_to_chin_height_ratio': [0.40, 0.48],
    'top_margin_ratio': [0.12, 0.16],
    'chin_y_ratio': [0.55, 0.64],
    'shoulder_width_ratio': [0.65, 0.80],
    'crop': 'mid-chest; shoulders and upper torso visible',
    'basis': 'User-selected reference compositions; design targets, not measured library statistics',
}
FRAMING_INSTRUCTIONS = (
    '1:1正方形留白胸像，镜头拉远至胸部中段，整体人物缩小而非只缩头。'
    '发顶至下巴占画高40%–48%，顶空12%–16%，下巴位于55%–64%，'
    '下方36%–45%留给颈、两肩与上胸，肩宽65%–80%，两侧留白。'
    '保持自然头身比例和原照姿态，长发顺身体垂落，不拉长脖子；近景自拍也重构胸像。'
    '仅延伸已见衣片，不加西装领、手势道具。'
)
