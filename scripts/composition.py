"""Shared square canvas and upper-body composition defaults."""

DEFAULT_SIZE = '1024x1024'
FRAMING_ID = 'complete-limbs-continuous-garments-v3'
FRAMING_PLAN = {
    'id': FRAMING_ID,
    'canvas_aspect': '1:1',
    'crown_to_chin_height_ratio': [0.40, 0.48],
    'top_margin_ratio': [0.12, 0.16],
    'chin_y_ratio': [0.55, 0.64],
    'shoulder_width_ratio': [0.65, 0.80],
    'bottom_anchor': 'continuous torso/garment reaches the last pixel row; no floating bust or background strip',
    'crop': 'mid-chest; shoulders and upper torso visible',
    'limb_completion': 'complete source-cropped shoulders and elbows in the existing pose; preserve real occlusion',
    'occlusion_continuity': 'organize existing garments behind foreground occluders; reconnect only their reappearing portions with consistent direction, width and role colors',
    'raised_arm_exception': 'pull the whole figure back enough to fit both elbows; head target may be smaller',
    'repair_prohibition': 'no pasted bottom strip, copied rows, stretched limbs or unverified geometric extensions',
    'basis': 'User-selected reference compositions; design targets, not measured library statistics',
}
FRAMING_INSTRUCTIONS = (
    '1:1正方形留白胸像，镜头拉远至胸部中段，整体人物缩小而非只缩头。'
    '发顶至下巴占画高40%–48%，顶空12%–16%，下巴位于55%–64%，'
    '下方36%–45%留给颈、两肩与上胸，肩宽65%–80%，两侧留白。'
    '保持自然头身比例和原照姿态，长发顺身体垂落，不拉长脖子；近景自拍也重构胸像。'
    '衣服和上胸必须向下延续到画布最后一行，由底边自然截断；底部不留背景带，不画悬浮半身像或衣服封底横线。'
    '只在顶部和左右留白，底部不留白。仅延伸已见衣片，不加西装领、手势道具。'
)

STRUCTURE_POLICY_ID = 'complete-limbs-continuous-garments-v2'
STRUCTURE_INSTRUCTIONS = (
    '原照画框裁掉的肩、肘或手臂须沿已见姿势保守补全；不要继承照片截边。真实被头发、衣物或另一肢体遮住的部分仍保留遮挡，不凭空画到前面。'
    '双臂抬起时从肩—肘—腕逐段组织外轮廓，上臂与前臂粗细随透视、袖料自然过渡，肘腕收束；不可画膨胀弯管、圆弧补丁或左右无依据的粗细突变。'
    '完整肘部优先于固定肩宽和头部下限，必要时整体拉远，使两侧肘部与画框之间留出可见背景，不单独缩头、拉长手臂或更改手势。'
    '裸臂与胸部须在腋下和上臂内侧有清楚自然的边界，轮廓随姿态向下延续；不可只画短刻痕就将手臂与躯干并成大块。'
    '衣服、袖子与躯干必须在整张底稿中连贯画到下边缘，侧缝、袖身分界、领口、褶线和原有渐变连续；不出现腰部水平贴片、突然变宽、断线或矩形封底。'
    '先组织完整衣着结构，再处理前景遮挡。手臂横过胸前时，遮挡后重新露出的内搭、衣襟、领带或配饰仍须沿既有方向、宽度和部位色接续，不能全部涂成外套色或在遮挡处终止。'
    '只延续照片已确认或用户明确要求的部件；不凭空加领带或领结，不让后方线条画穿手臂，也不强行露出完全隐藏或仍在画外的部分。'
    '补画按肩臂或整件衣服的结构区域重画并实看连接处；禁止复制底行、拉伸身体或用未经视觉核对的几何外推凑贴底。无法合理补全时明确说明，不将残缺预览标为合格。'
)
STRUCTURE_REVIEW = {
    'policy_id': STRUCTURE_POLICY_ID,
    'required': True,
    'verification': 'visual comparison of final portrait with photo after all local transforms',
    'checks': [
        'source-cropped shoulders/elbows completed; actual occlusions preserved',
        'continuous shoulder-elbow-wrist chain with plausible taper and perspective',
        'raised elbows fully inside frame, no cut or patched contour',
        'visible arm has a continuous axilla/inner-arm boundary distinct from torso',
        'sleeve, torso, seams, folds and gradient continue to bottom without a pasted band',
        'visible garment parts reconnect before and after occlusion with consistent direction, width and colors; hidden portions stay behind the foreground',
        'collar patterns subordinate to face; no skin/cheek/detail colors borrowed for motifs',
    ],
    'scope': 'manual visual gate; palette and pixel checks cannot prove anatomy',
}
FRAMING_INSTRUCTIONS += STRUCTURE_INSTRUCTIONS
