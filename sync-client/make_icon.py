"""Writes zirahive-sync.ico for the Windows build (the honeycomb mark, as in the tray)."""
from zirahive_sync.tray import _icon_image

_icon_image("ok").save("zirahive-sync.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
