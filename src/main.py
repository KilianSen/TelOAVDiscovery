import asyncio
import sys
import tomllib
from dataclasses import dataclass
from typing import Literal
from datetime import datetime, timedelta
from collections import deque

import tomli_w
from asyncua import Client, ua
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.logging import RichHandler
import logging

from Config import config

INPUT_TYPES: set[Literal["opcua_listener", "opcua"]] = {"opcua_listener", "opcua"}

# Global state for TUI
endpoint_stats: dict = {}
last_update_time: datetime | None = None
next_update_time: datetime | None = None
polling_interval: int = 0
log_messages: deque = deque(maxlen=100)  # Store last 100 log messages

# Setup logger
logger = logging.getLogger("TelOAVDiscovery")


class TUILogHandler(logging.Handler):
    """Custom log handler that stores messages for TUI display"""
    def emit(self, record):
        log_entry = {
            "time": datetime.fromtimestamp(record.created),
            "level": record.levelname,
            "message": record.getMessage()
        }
        log_messages.append(log_entry)

@dataclass
class ServiceConfig:
    """
    Service configuration dataclass
    Configures how TelOAVDiscovery operates

    All values can be overridden via environment variables, or --config file.(toml/json)
    """
    POLLING_INTERVAL: int = -1 # Value in seconds, -1 means no polling (only run once)
    TELEGRAF_CONFIG_PATH_IN: str = "./input/telegraf.conf"
    TELEGRAF_CONFIG_PATH_OUT: str = "./output/telegraf.conf"

def endpoints_from_config(toml_config: dict) -> list[str]:
    inputs = toml_config.get("inputs", {})

    endpoints_to_monitor = []

    for input_type in INPUT_TYPES:
        if input_type not in inputs:
            continue

        list_type_fields = inputs.get(input_type, [])

        for type_fields in list_type_fields:

            endpoint = type_fields.get("endpoint", None)

            if endpoint is None:
                raise ValueError(f"Missing 'endpoint' for input type '{input_type}'")

            if endpoint not in endpoints_to_monitor:
                endpoints_to_monitor.append(endpoint)

    return endpoints_to_monitor


async def browse_recursive(node, nodes_to_add: list[dict]):
    try:
        children = await node.get_children()
    except Exception as e:
        logger.debug(f"Failed to get children for node: {e}")
        return

    for child in children:
        try:
            node_class = await child.read_node_class()
            if node_class == ua.NodeClass.Variable:
                # Skip Namespaces 0 and 1 as they are standard OPC UA nodes
                node_id = child.nodeid
                if node_id.NamespaceIndex in (0, 1):
                    continue

                browse_name = await child.read_browse_name()

                # Get data type information
                try:
                    data_type = await child.read_data_type()
                    data_type_name = data_type.to_string() if data_type else "Unknown"
                except Exception as e:
                    logger.debug(f"Failed to read data type for {browse_name.Name}: {e}")
                    data_type_name = "Unknown"

                nodes_to_add.append({
                    "name": browse_name.Name,
                    "namespace": str(node_id.NamespaceIndex),
                    "identifier_type": node_id.NodeIdType,
                    "identifier": str(node_id.Identifier),
                    "data_type": data_type_name
                })
                logger.debug(f"Discovered node: {browse_name.Name} (ns={node_id.NamespaceIndex})")

            await browse_recursive(child, nodes_to_add)
        except Exception as e:
            logger.debug(f"Error processing child node: {e}")
            continue


async def discover_nodes(endpoint: str, use_tui: bool = False) -> list[dict]:
    global endpoint_stats, last_update_time

    logger.info(f"🔍 Starting discovery on endpoint: {endpoint}")

    nodes_to_add = []

    try:
        logger.debug(f"Connecting to {endpoint}...")
        async with Client(url=endpoint) as client:
            logger.debug(f"Connected to {endpoint}")
            objects_node = client.get_objects_node()
            await browse_recursive(objects_node, nodes_to_add)

        logger.info(f"Discovered {len(nodes_to_add)} nodes on {endpoint}")

        # Update stats for TUI
        if use_tui:
            endpoint_stats[endpoint] = {
                "status": "Connected",
                "node_count": len(nodes_to_add),
                "nodes": nodes_to_add,
                "last_update": datetime.now()
            }
            last_update_time = datetime.now()

    except ConnectionError as e:
        logger.error(f"Connection failed to {endpoint}: {e}")

        if use_tui:
            endpoint_stats[endpoint] = {
                "status": "Connection Failed",
                "node_count": 0,
                "nodes": [],
                "last_update": datetime.now()
            }
            last_update_time = datetime.now()

        return []
    except Exception as e:
        logger.error(f"Unexpected error discovering nodes on {endpoint}: {e}")

        if use_tui:
            endpoint_stats[endpoint] = {
                "status": f"Error: {str(e)[:30]}",
                "node_count": 0,
                "nodes": [],
                "last_update": datetime.now()
            }
            last_update_time = datetime.now()

        return []

    return nodes_to_add


def generate_tui_layout() -> Layout:
    """Generate the Rich TUI layout"""
    layout = Layout()

    # Create header
    header = Panel(
        Text("TelOAV Discovery - OPC UA Node Monitor", justify="center", style="bold white"),
        style="bold white"
    )

    # Create status info
    if last_update_time is not None:
        last_update_str = last_update_time.strftime('%Y-%m-%d %H:%M:%S')
    else:
        last_update_str = 'Never'

    status_text = f"Last Update: {last_update_str}"
    status_text += f" | Endpoints: {len(endpoint_stats)}"
    status_text += f" | Logs: {len(log_messages)}"

    # Add countdown to next update if polling is enabled
    if next_update_time is not None and polling_interval > 0:
        time_remaining = (next_update_time - datetime.now()).total_seconds()
        if time_remaining > 0:
            minutes, seconds = divmod(int(time_remaining), 60)
            if minutes > 0:
                status_text += f" | Next update in: {minutes}m {seconds}s"
            else:
                status_text += f" | Next update in: {seconds}s"
        else:
            status_text += " | Updating..."
    elif polling_interval > 0:
        status_text += f" | Polling every {polling_interval}s"

    status_panel = Panel(Text(status_text, justify="center"), style="green")

    # Determine if we have enough space for logs (console height check)
    console = Console()
    console_height = console.size.height
    show_logs = console_height > 30  # Only show logs if terminal is tall enough

    # Split layout: header, status, main content, and optionally logs
    if show_logs:
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="status", size=3),
            Layout(name="main"),
            Layout(name="logs", size=12)
        )
    else:
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="status", size=3),
            Layout(name="main")
        )

    layout["header"].update(header)
    layout["status"].update(status_panel)

    # Split main area into endpoint panels
    if endpoint_stats:
        endpoint_layouts = []
        for endpoint, stats in endpoint_stats.items():
            endpoint_layouts.append(Layout(name=endpoint))

        # Split main area evenly among endpoints
        if len(endpoint_layouts) == 1:
            layout["main"].update(endpoint_layouts[0])
        else:
            layout["main"].split_row(*endpoint_layouts)

        # Update each endpoint panel
        for endpoint, stats in endpoint_stats.items():
            table = create_endpoint_table(endpoint, stats)
            layout[endpoint].update(table)
    else:
        layout["main"].update(Panel("No endpoints configured", style="yellow"))

    # Add log panel if we have enough space
    if show_logs:
        log_panel = create_log_panel()
        layout["logs"].update(log_panel)

    return layout


def create_endpoint_table(endpoint: str, stats: dict) -> Panel:
    """Create a table showing nodes for a specific endpoint"""

    # Create table
    table = Table(
        title=f"{endpoint}",
        show_header=True,
        header_style="bold magenta",
        expand=True,
        show_lines=True
    )

    table.add_column("Variable Name", style="cyan", no_wrap=False)
    table.add_column("Namespace", style="yellow", justify="center", width=10)
    table.add_column("Identifier", style="white", no_wrap=False)
    table.add_column("Data Type", style="green", no_wrap=False)

    # Add status row
    status_color = "green" if stats["status"] == "Connected" else "red"

    nodes = stats.get("nodes", [])

    if stats["status"] == "Connected" and nodes:
        # Add node rows (limit to reasonable number for display)
        display_limit = 50
        for i, node in enumerate(nodes[:display_limit]):
            table.add_row(
                node.get("name", "N/A"),
                node.get("namespace", "N/A"),
                str(node.get("identifier", "N/A")),
                node.get("data_type", "Unknown")
            )

        if len(nodes) > display_limit:
            table.add_row(
                f"... and {len(nodes) - display_limit} more nodes",
                "", "", "",
                style="dim italic"
            )
    elif stats["status"] != "Connected":
        table.add_row(
            f"{stats['status']}", "", "", "",
            style="bold red"
        )
    else:
        table.add_row(
            "No nodes discovered", "", "", "",
            style="dim italic"
        )

    # Create panel with node count in subtitle
    subtitle = f"Status: [{status_color}]{stats['status']}[/{status_color}] | Nodes: {stats['node_count']}"
    if stats.get('last_update'):
        subtitle += f" | Updated: {stats['last_update'].strftime('%H:%M:%S')}"

    return Panel(
        table,
        subtitle=subtitle,
        border_style=status_color,
        padding=(1, 2)
    )


def create_log_panel() -> Panel:
    """Create a panel showing recent log messages"""

    # Create log table
    log_table = Table(
        show_header=True,
        header_style="bold blue",
        expand=True,
        show_lines=False,
        box=None
    )

    log_table.add_column("Time", style="dim", width=8, no_wrap=True)
    log_table.add_column("Level", width=8, no_wrap=True)
    log_table.add_column("Message", no_wrap=False)

    # Add recent log messages (last 8)
    recent_logs = list(log_messages)[-8:]

    if recent_logs:
        for log_entry in recent_logs:
            level = log_entry["level"]

            # Color code by log level
            if level == "ERROR":
                level_style = "bold red"
            elif level == "WARNING":
                level_style = "bold yellow"
            elif level == "INFO":
                level_style = "bold green"
            elif level == "DEBUG":
                level_style = "dim cyan"
            else:
                level_style = "white"

            time_str = log_entry["time"].strftime("%H:%M:%S")
            message = log_entry["message"]

            # Truncate very long messages
            if len(message) > 120:
                message = message[:117] + "..."

            log_table.add_row(
                time_str,
                Text(level, style=level_style),
                message
            )
    else:
        log_table.add_row("--:--:--", "INFO", "No log messages yet", style="dim italic")

    return Panel(
        log_table,
        title="📋 Recent Logs",
        border_style="blue",
        padding=(0, 1)
    )



async def main_async():
    global polling_interval, next_update_time

    service_config: ServiceConfig = config(ServiceConfig)
    polling_interval = service_config.POLLING_INTERVAL

    # Detect if we're in an interactive TTY
    use_tui = sys.stdout.isatty() and sys.stdin.isatty()

    # Setup logging
    logger.setLevel(logging.DEBUG)

    if use_tui:
        # In TUI mode, use custom handler to capture logs
        tui_handler = TUILogHandler()
        tui_handler.setLevel(logging.DEBUG)
        logger.addHandler(tui_handler)
    else:
        # In non-TUI mode, use rich console handler
        console_handler = RichHandler(rich_tracebacks=True)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        logger.info("Configuration: %s", service_config)

    console = Console() if use_tui else None

    async def fetch_and_update():
        global next_update_time

        logger.info("Reading Telegraf configuration from %s", service_config.TELEGRAF_CONFIG_PATH_IN)

        try:
            with open(service_config.TELEGRAF_CONFIG_PATH_IN, "rb") as f:
                toml_config = tomllib.load(f)
        except FileNotFoundError:
            logger.error("Configuration file not found: %s", service_config.TELEGRAF_CONFIG_PATH_IN)
            return
        except Exception as e:
            logger.error("Failed to read configuration: %s", e)
            return

        endpoints_to_monitor = endpoints_from_config(toml_config)
        logger.info("Found %d endpoint(s) to monitor", len(endpoints_to_monitor))

        discovered_nodes_by_endpoint = {}
        for endpoint in endpoints_to_monitor:
            discovered_nodes_by_endpoint[endpoint] = await discover_nodes(endpoint, use_tui=use_tui)

        inputs = toml_config.get("inputs", {})
        nodes_updated_count = 0

        for input_type in INPUT_TYPES:
            if input_type not in inputs:
                continue

            for config_block in inputs.get(input_type, []):
                endpoint = config_block.get("endpoint")
                if endpoint and endpoint in discovered_nodes_by_endpoint:
                    nodes = discovered_nodes_by_endpoint[endpoint]
                    if nodes:
                        config_block["nodes"] = nodes
                        nodes_updated_count += 1
                        logger.debug("Updated configuration for endpoint: %s", endpoint)
                    else:
                        logger.warning("No nodes discovered for endpoint %s, skipping update", endpoint)

        try:
            with open(service_config.TELEGRAF_CONFIG_PATH_OUT, "wb") as f:
                tomli_w.dump(toml_config, f)
            logger.info("Updated Telegraf config written to %s (%d endpoint(s) updated)",
                       service_config.TELEGRAF_CONFIG_PATH_OUT, nodes_updated_count)
        except Exception as e:
            logger.error("Error writing config file: %s", e)

        # Set next update time if polling
        if service_config.POLLING_INTERVAL > 0:
            next_update_time = datetime.now() + timedelta(seconds=service_config.POLLING_INTERVAL)

    if use_tui and service_config.POLLING_INTERVAL > 0:
        # TUI mode with polling - use higher refresh rate for smooth countdown
        with Live(generate_tui_layout(), console=console, refresh_per_second=4, screen=True) as live:
            while True:
                await fetch_and_update()

                # Update UI every 0.25 seconds for smooth countdown
                for _ in range(service_config.POLLING_INTERVAL * 4):
                    live.update(generate_tui_layout())
                    await asyncio.sleep(0.25)
    elif use_tui:
        # TUI mode, single run
        await fetch_and_update()
        console.print(generate_tui_layout())
        console.print("\nDiscovery complete. Press any key to exit...")
        try:
            import msvcrt
            msvcrt.getch()
        except ImportError:
            input()
    elif service_config.POLLING_INTERVAL > 0:
        # Normal logging mode with polling
        while True:
            await fetch_and_update()
            logger.info("Waiting for %d seconds before next poll...", service_config.POLLING_INTERVAL)
            await asyncio.sleep(service_config.POLLING_INTERVAL)
    else:
        # Normal logging mode, single run
        await fetch_and_update()


if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting gracefully...")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
