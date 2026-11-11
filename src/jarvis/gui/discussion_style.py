"""Unframed discussion surfaces using the desktop's existing design tokens."""
from PySide6.QtWidgets import QStyle
from .aurora import dialog_rules
from .voice_core import BASE_STYLE, glyph_icon


def discussion_icon(style, icon, color=None):
    names = {
        QStyle.StandardPixmap.SP_ComputerIcon: "monitor",
        QStyle.StandardPixmap.SP_DialogResetButton: "delete",
        QStyle.StandardPixmap.SP_BrowserReload: "refresh",
        QStyle.StandardPixmap.SP_MediaStop: "cancel",
        QStyle.StandardPixmap.SP_DirOpenIcon: "folder",
        QStyle.StandardPixmap.SP_DialogCloseButton: "close",
        QStyle.StandardPixmap.SP_TitleBarCloseButton: "close",
        QStyle.StandardPixmap.SP_FileDialogDetailedView: "history",
        QStyle.StandardPixmap.SP_FileDialogContentsView: "settings",
        QStyle.StandardPixmap.SP_ArrowForward: "send",
    }
    return glyph_icon(names.get(icon, ""), icon, style, **({"color": color} if color else {}))

# The Aurora dialog kit (gui/aurora.py, Claude) scoped to these dialogs.
DISCUSSION_STYLE = BASE_STYLE + dialog_rules("QDialog")
