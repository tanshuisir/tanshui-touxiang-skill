"""Shared eye drawing grammar for every avatar mode and generation stage."""

EYE_STYLE_ID = 'solid-upper-lid-v1'
EYE_INSTRUCTIONS = (
    '每只睁眼用短上眼睑，下接同主线色的实心下垂椭圆或圆底楔形，二者相接；'
    '眼形内不留白，不画封闭杏仁眼框、眼白、虹膜圈、独立瞳孔、反光点、挖空高光、睫毛或下眼睑线。'
    '用眼距、宽窄、上睑倾斜、眼形位置和眉眼关系表达视线与个体差异；'
    '照片确为闭眼或眯眼时用短弧线，不统一成困倦表情。'
)
EYE_PRECEDENCE = (
    '以下统一眼睛规则适用于全部画风和预览/高清，优先于上文特征处理、补充描述及图2/图3中的眼睛细节；'
    '旧brief或已确认预览中的眼白、瞳孔分层和高光须归并为实心眼形，高清不得补回。'
)
