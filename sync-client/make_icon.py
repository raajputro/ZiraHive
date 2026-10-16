"""Writes gharbox-sync.ico for the Windows build (the same little house as the tray icon)."""
from gharbox_sync.tray import _icon_image

_icon_image("ok").save("gharbox-sync.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
