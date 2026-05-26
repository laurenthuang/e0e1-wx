"""把监控记录转换为卡片展示字段。"""

from __future__ import annotations

from dataclasses import dataclass

from package.ui.record_text import mini_program_display_name


@dataclass(slots=True)
class CardViewModel:
    """卡片展示所需的最小字段集合。"""

    name_text: str
    wxid_text: str
    active: bool


def build_card_view_model(record: dict) -> CardViewModel:
    """从监控记录生成卡片展示模型。"""
    display_name = mini_program_display_name(record)
    wxid_text = str(record.get("wxids_display") or record.get("wxid") or "-")
    return CardViewModel(
        name_text=display_name,
        wxid_text=f"wxid: {wxid_text}",
        active=bool(record.get("status") == 1),
    )
