from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Optional, Dict

@dataclass
class ServiceConfig:
    """
    Service configuration dataclass
    Configures how TelOAVDiscovery operates
    """
    POLLING_INTERVAL: int = -1 # Value in seconds, -1 means no polling (only run once)
    TELEGRAF_CONFIG_PATH_IN: str = "./test/telegraf.conf"
    TELEGRAF_CONFIG_PATH_OUT: str = "./test/telegraf1.conf"
    NAMING_STRATEGY: str = "suffix"  # Options: "plain", "prefix", "suffix", "path"
    ENABLE_ID_TAG: bool = False      # Whether to add the 'id' tag to nodes
    INCLUDE_NS0: bool = False        # Whether to include nodes from Namespace 0

@dataclass
class AppState:
    """
    Global application state for TUI and orchestration
    """
    endpoint_stats: Dict = field(default_factory=dict)
    last_update_time: Optional[datetime] = None
    next_update_time: Optional[datetime] = None
    last_config_in: Optional[bytes] = None
    polling_interval: int = 0
    log_messages: deque = field(default_factory=lambda: deque(maxlen=100))
