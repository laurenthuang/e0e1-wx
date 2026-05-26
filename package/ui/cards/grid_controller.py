"""管理当前页卡片实例的增量挂载与卸载。"""

from __future__ import annotations

from collections.abc import Callable


class MonitorCardGridController:
    """负责把当前页记录映射为可复用的卡片控件。"""

    def __init__(self, layout, card_factory: Callable[[dict], object]) -> None:
        """保存布局对象和卡片工厂。"""
        self.layout = layout
        self.card_factory = card_factory
        self.cards_by_id: dict[int, object] = {}

    def clear(self) -> None:
        """清空当前页持有的卡片实例。"""
        for card in list(self.cards_by_id.values()):
            self.layout.removeWidget(card)
            card.deleteLater()
        self.cards_by_id.clear()

    def apply_page_records(self, records: list[dict], card_width: int, columns: int = 2) -> list[object]:
        """按当前页记录增量复用或创建卡片，并返回新建卡片列表。"""
        created_cards: list[object] = []
        next_ids = {int(record.get("id") or 0) for record in records if int(record.get("id") or 0) > 0}

        for record_id in list(self.cards_by_id):
            if record_id not in next_ids:
                card = self.cards_by_id.pop(record_id)
                self.layout.removeWidget(card)
                card.deleteLater()

        for index, record in enumerate(records):
            record_id = int(record.get("id") or 0)
            if record_id <= 0:
                continue
            if record_id in self.cards_by_id:
                card = self.cards_by_id[record_id]
                card.update_record(record)
            else:
                card = self.card_factory(record)
                self.cards_by_id[record_id] = card
                created_cards.append(card)
            card.set_equal_width(card_width)
            row = index // columns
            column = index % columns
            self.layout.addWidget(card, row, column)
        return created_cards
