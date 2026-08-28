from __future__ import annotations

from .mai_beeper_adapter.core import MaiBeeperAdapterPlugin


def create_plugin() -> MaiBeeperAdapterPlugin:
    """建立 Mai Beeper Adapter 插件。"""

    return MaiBeeperAdapterPlugin()
