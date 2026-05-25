from ass import Style, Document  # type: ignore[import-untyped]
from ass.data import Color  # type: ignore[import-untyped]
from copy import deepcopy
from typing import Any

# fmt: off
__all__ = [
    "gandhi_default", "GJM_GANDHI_PRESET",
    "cabin_default", "CABIN_PRESET",
    "cabinf_default", "CABINF_PRESET",
    "lato_default", "LATO_PRESET",
    "merriweather_default", "MERRIWEATHER_PRESET",
    "amazon_ember_default", "AMAZON_EMBER_PRESET",
    "ltf_default", "LTF_PRESET",
    "fira_default", "FIRA_PRESET",
    "edit_style", "resize_preset", "default_style_args", "get_complimenting_styles"
]
# fmt: on


def edit_style(style: Style, name: str, **kwargs) -> Style:
    """
    Copies a style to set a new name and other arguments via kwargs
    """
    style = deepcopy(style)
    style.name = name
    for key, val in kwargs.items():
        setattr(style, key, val)
    return style


def get_complimenting_styles(style: Style) -> list[Style]:
    """
    Generates colored Alt/Overlap and Flashback styles for a given style.
    """
    return [
        edit_style(style, "Overlap", outline_color=Color(r=0x15, g=0x3E, b=0x74, a=0x00)),
        edit_style(style, "Alt", outline_color=Color(r=0x15, g=0x3E, b=0x74, a=0x00)),
        edit_style(style, "Flashback", outline_color=Color(r=0x12, g=0x3E, b=0x01, a=0x00)),
    ]


default_style_args: dict[str, Any] = {
    "bold": True,
    "italic": False,
    "underline": False,
    "strike_out": False,
    "scale_x": 100.0,
    "scale_y": 100.0,
    "spacing": 0.0,
    "angle": 0.0,
    "encoding": 1,
    "alignment": 2,
    "border_style": 1,
    "primary_color": Color(r=0xFF, g=0xFF, b=0xFF, a=0x00),
    "secondary_color": Color(r=0xFF, g=0x00, b=0x00, a=0x00),
    "outline_color": Color(r=0x00, g=0x00, b=0x00, a=0x00),
    "back_color": Color(r=0x00, g=0x00, b=0x00, a=0xA0),
}

gandhi_default = Style(
    name="Default",
    fontname="Gandhi Sans",
    fontsize=75.0,
    outline=3.6,
    shadow=1.5,
    margin_l=180,
    margin_r=180,
    margin_v=55,
    **default_style_args,
)

GJM_GANDHI_PRESET = [gandhi_default, *get_complimenting_styles(gandhi_default)]
"""
A GandhiSans-Bold preset. The font is commonly used by GJM and MTBB and a few other groups.
[https://www.fontsquirrel.com/fonts/gandhi-sans](https://www.fontsquirrel.com/fonts/gandhi-sans)
"""

cabin_default = Style(
    name="Default",
    fontname="Cabin",
    fontsize=85.0,
    outline=3.2,
    shadow=1.5,
    margin_l=180,
    margin_r=180,
    margin_v=50,
    **default_style_args,
)

CABIN_PRESET = [cabin_default, *get_complimenting_styles(cabin_default)]
"""[https://fonts.google.com/specimen/Cabin](https://fonts.google.com/specimen/Cabin)"""

cabinf_default = edit_style(cabin_default, "Default", fontname="Cabin F", fontsize=75.0, margin_v=55)

CABINF_PRESET = [cabinf_default, *get_complimenting_styles(cabinf_default)]
"""
A custom Cabin variant with adjusted font size and margins and an em dash closer to Gandhi Sans.\n
Made by RaptoR.\n
From what I know there's no "official" page for this. You can download it [here](https://pomf2.lain.la/f/tgmlxa5k.7z).
"""

lato_default = Style(
    name="Default",
    fontname="Lato",
    fontsize=75.0,
    outline=3.2,
    shadow=1.5,
    margin_l=180,
    margin_r=180,
    margin_v=55,
    **default_style_args,
)

LATO_PRESET = [lato_default, *get_complimenting_styles(lato_default)]
"""[https://fonts.google.com/specimen/Lato](https://fonts.google.com/specimen/Lato)"""

merriweather_default = Style(
    name="Default",
    fontname="Merriweather",
    fontsize=78.0,
    outline=3.3,
    shadow=1.5,
    margin_l=180,
    margin_r=180,
    margin_v=55,
    **default_style_args,
)

MERRIWEATHER_PRESET = [merriweather_default, *get_complimenting_styles(merriweather_default)]
"""[https://fonts.google.com/specimen/Merriweather](https://fonts.google.com/specimen/Merriweather)"""

amazon_ember_default = Style(
    name="Default",
    fontname="Amazon Ember",
    fontsize=78.0,
    outline=3.5,
    shadow=1.3,
    margin_l=180,
    margin_r=180,
    margin_v=55,
    **default_style_args,
)

AMAZON_EMBER_PRESET = [amazon_ember_default, *get_complimenting_styles(amazon_ember_default)]
"""[https://developer.amazon.com/en-US/alexa/branding/echo-guidelines/identity-guidelines/typography](https://developer.amazon.com/en-US/alexa/branding/echo-guidelines/identity-guidelines/typography)"""

ltf_default = Style(
    name="Default",
    fontname="LTFinnegan Medium",
    fontsize=72.0,
    outline=3.6,
    shadow=1.5,
    margin_l=185,
    margin_r=185,
    margin_v=60,
    **(default_style_args | dict(bold=False)),
)

LTF_PRESET = [ltf_default, *get_complimenting_styles(ltf_default)]
"""
LinotypeFinnegan Medium preset. The font is commonly used by Commie and Kaleido.\n
It's, apparently, technically a [paid font](https://www.myfonts.com/de/collections/finnegan-font-linotype), 
but you can probably find it in a bunch of github repos or in the attachments of plenty of releases.
"""

fira_default = Style(
    name="Default",
    fontname="Fira Sans Medium",
    fontsize=70.0,
    outline=3.6,
    shadow=2.5,
    margin_l=185,
    margin_r=185,
    margin_v=56,
    **(default_style_args | dict(bold=False, scale_x=103.0)),
)

FIRA_PRESET = [fira_default, *get_complimenting_styles(fira_default)]
"""
Fira Sans Medium preset.
[https://fonts.google.com/specimen/Fira+Sans](https://fonts.google.com/specimen/Fira+Sans)
"""


def resize_preset(preset: list[Style], target_height: int | Document = 360) -> list[Style]:
    """
    Resize a list of styles to match a resolution.\n
    This assumes the passed styles are for a 1080p script.

    :param preset:          List of styles to resize
    :param target_height:   Either a height integer or an ass document to get the height from

    :return:                A list of deepcopied styles. This doesn't edit the input styles.
    """
    if isinstance(target_height, Document):
        target_height = int(target_height.info.get("PlayResY", 360))

    styles = list[Style]()
    multiplier = target_height / 1080
    for style in preset:
        style = deepcopy(style)
        setattr(style, "fontsize", int(getattr(style, "fontsize", 75.0) * multiplier))
        setattr(style, "margin_l", int(getattr(style, "margin_l", 180) * multiplier))
        setattr(style, "margin_r", int(getattr(style, "margin_r", 180) * multiplier))
        setattr(style, "margin_v", int(getattr(style, "margin_v", 55) * multiplier))
        setattr(style, "shadow", round(getattr(style, "shadow", 1.5) * multiplier, 1))
        setattr(style, "outline", round(getattr(style, "outline", 3.2) * multiplier, 1))
        styles.append(style)
    return styles
