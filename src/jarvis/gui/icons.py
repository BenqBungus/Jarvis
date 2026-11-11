from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QStyle


_GLYPHS = {
    QStyle.StandardPixmap.SP_FileDialogListView: "\ue765",
    QStyle.StandardPixmap.SP_FileDialogContentsView: "\ue81c",
    QStyle.StandardPixmap.SP_FileDialogDetailedView: "\ue713",
    QStyle.StandardPixmap.SP_ArrowBack: "\ue72b",
    QStyle.StandardPixmap.SP_ArrowForward: "\ue724",
    QStyle.StandardPixmap.SP_BrowserStop: "\ue711",
    QStyle.StandardPixmap.SP_TitleBarCloseButton: "\ue711",
    QStyle.StandardPixmap.SP_MediaPlay: "\ue768",
    QStyle.StandardPixmap.SP_MediaPause: "\ue769",
    QStyle.StandardPixmap.SP_MediaStop: "\ue71a",
}


def control_icon(style, kind, color: str = "#a9dce2") -> QIcon:
    if kind in _GLYPHS and "Segoe MDL2 Assets" in QFontDatabase.families():
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QColor(color))
        painter.setFont(QFont("Segoe MDL2 Assets", 18))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, _GLYPHS[kind])
        painter.end()
        return QIcon(pixmap)
    # Some native icons have opaque backgrounds; tinting erases their details.
    return style.standardIcon(kind)
