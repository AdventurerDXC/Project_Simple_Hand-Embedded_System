from __future__ import annotations

from collections import deque
from datetime import datetime

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from protocol import ADC_POINT_COUNT, TactileFrame


# 用户界面以4096作为12位ADC满量程端点。
# 实际12位ADC通常输出0～4095；4095映射后也会显示为纯红色。
ADC_MAX = 4096

# 在模型中保存每个单元格背景色的自定义数据角色。
CELL_BACKGROUND_ROLE = Qt.UserRole + 1


def adc_value_to_color(adc_value: int) -> QColor:
    """将0～4096线性映射为白色～红色。"""

    clipped = max(0, min(ADC_MAX, int(adc_value)))
    ratio = clipped / ADC_MAX

    # ADC=0       -> RGB(255, 255, 255)
    # ADC=2048    -> RGB(255, 128, 128)
    # ADC=4095/96 -> RGB(255,   0,   0)
    green_blue = round(255 * (1.0 - ratio))
    return QColor(255, green_blue, green_blue)


class HeatmapCellDelegate(QStyledItemDelegate):
    """
    直接绘制单元格背景和文字。

    应用级QSS可能覆盖QTableWidgetItem.setBackground()产生的
    BackgroundRole。使用自定义delegate后，背景色由paint()直接绘制，
    不再受QSS优先级影响。
    """

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        painter.save()

        background = index.data(CELL_BACKGROUND_ROLE)
        if not isinstance(background, QColor):
            background = QColor(255, 255, 255)

        painter.fillRect(option.rect, background)

        painter.setPen(QColor(0, 0, 0))
        text = str(index.data(Qt.DisplayRole) or "0")
        painter.drawText(option.rect, Qt.AlignCenter, text)

        painter.restore()


class HeatmapGrid(QTableWidget):
    """紧凑型6×6 ADC数值热力表。"""

    ROWS = 6
    COLUMNS = 6

    def __init__(self, parent=None) -> None:
        super().__init__(self.ROWS, self.COLUMNS, parent)
        self.setObjectName("tactileTable")
        self._items: list[QTableWidgetItem] = []
        self._last_values: list[int | None] = [None] * ADC_POINT_COUNT

        # 使用自定义绘制，保证白色～红色映射不会被全局样式表覆盖。
        self.setItemDelegate(HeatmapCellDelegate(self))

        labels = [str(index) for index in range(1, 7)]
        self.setHorizontalHeaderLabels(labels)
        self.setVerticalHeaderLabels(labels)

        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setMinimumSectionSize(24)
        self.verticalHeader().setMinimumSectionSize(20)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.verticalHeader().setDefaultAlignment(Qt.AlignCenter)

        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(190)
        self.setMaximumHeight(230)
        self.setMinimumWidth(270)

        for row in range(self.ROWS):
            for column in range(self.COLUMNS):
                item = QTableWidgetItem("0")
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(CELL_BACKGROUND_ROLE, QColor(255, 255, 255))
                self.setItem(row, column, item)
                self._items.append(item)

        self.update_values([0] * ADC_POINT_COUNT)

    def update_values(self, values: list[int] | tuple[int, ...]) -> None:
        if len(values) != ADC_POINT_COUNT:
            raise ValueError(f"需要{ADC_POINT_COUNT}个ADC值")

        changed = False

        for index, raw_value in enumerate(values):
            value = max(0, min(ADC_MAX, int(raw_value)))
            if self._last_values[index] == value:
                continue

            self._last_values[index] = value
            item = self._items[index]
            item.setText(str(value))
            item.setData(CELL_BACKGROUND_ROLE, adc_value_to_color(value))
            changed = True

        # 主动触发viewport重绘，避免高频数据更新时出现延迟刷新。
        if changed:
            self.viewport().update()


class BoardPanel(QFrame):
    """单块传感板的紧凑状态卡片与6×6触觉矩阵。"""

    def __init__(self, board_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("boardCard")
        self.setMinimumSize(300, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.board_id = board_id
        self._offset = 0
        self._latest_raw = [0] * ADC_POINT_COUNT
        self._frame_times: deque[float] = deque(maxlen=80)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(5)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)

        title_label = QLabel(f"传感板 {board_id}")
        title_label.setObjectName("boardTitleLabel")

        self.status_label = QLabel("等待数据")
        self.status_label.setProperty("class", "statusBadge")
        self.status_label.setProperty("waiting", True)

        title_row.addWidget(title_label)
        title_row.addStretch(1)
        title_row.addWidget(self.status_label)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)

        self.counter_label = QLabel("帧：--")
        self.fps_label = QLabel("0.0 FPS")
        self.last_time_label = QLabel("更新：--:--:--")

        for label in (
            self.counter_label,
            self.fps_label,
            self.last_time_label,
        ):
            label.setObjectName("boardMetaLabel")

        meta_row.addWidget(self.counter_label)
        meta_row.addWidget(self.fps_label)
        meta_row.addStretch(1)
        meta_row.addWidget(self.last_time_label)

        self.grid = HeatmapGrid()

        root.addLayout(title_row)
        root.addLayout(meta_row)
        root.addWidget(self.grid, 1)

    def update_frame(self, frame: TactileFrame, offset: int) -> None:
        self._offset = offset
        self._latest_raw = list(frame.adc)
        self._frame_times.append(frame.received_at)

        calibrated = [
            max(0, min(ADC_MAX, value - self._offset))
            for value in self._latest_raw
        ]
        self.grid.update_values(calibrated)

        fps = 0.0
        if len(self._frame_times) >= 2:
            elapsed = self._frame_times[-1] - self._frame_times[0]
            if elapsed > 0:
                fps = (len(self._frame_times) - 1) / elapsed

        self._set_status("在线", online=True, waiting=False)
        self.counter_label.setText(f"帧：{frame.counter}")
        self.fps_label.setText(f"{fps:.1f} FPS")
        self.last_time_label.setText(
            "更新：" + datetime.now().strftime("%H:%M:%S")
        )

    def set_offset(self, offset: int) -> None:
        self._offset = max(0, min(ADC_MAX, int(offset)))
        calibrated = [
            max(0, min(ADC_MAX, value - self._offset))
            for value in self._latest_raw
        ]
        self.grid.update_values(calibrated)

    def mark_waiting(self) -> None:
        self._set_status("等待数据", online=False, waiting=True)

    def mark_disconnected(self) -> None:
        self._set_status("已断开", online=False, waiting=False)

    def _set_status(self, text: str, *, online: bool, waiting: bool) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("online", online)
        self.status_label.setProperty("waiting", waiting)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
