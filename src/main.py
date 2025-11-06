import asyncio
import sys
import tomllib
from dataclasses import dataclass
from typing import Literal
from datetime import datetime

import tomli_w
from asyncua import Client, ua
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from Config import config

INPUT_TYPES: set[Literal["opcua_listener", "opcua"]] = {"opcua_listener", "opcua"}

# Global state for TUI
endpoint_stats = {}
last_update_time = None

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
    children = await node.get_children()
    for child in children:
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
            except:
                data_type_name = "Unknown"

            nodes_to_add.append({
                "name": browse_name.Name,
                "namespace": str(node_id.NamespaceIndex),
                "identifier_type": node_id.NodeIdType,
                "identifier": str(node_id.Identifier),
                "data_type": data_type_name
            })
        await browse_recursive(child, nodes_to_add)


async def discover_nodes(endpoint: str, use_tui: bool = False) -> list[dict]:
    global endpoint_stats, last_update_time

    if not use_tui:
        print(f"Discovering nodes on {endpoint}")

    nodes_to_add = []
    status = "Connected"

    try:
        async with Client(url=endpoint) as client:
            objects_node = client.get_objects_node()
            await browse_recursive(objects_node, nodes_to_add)

        if not use_tui:
            print(f"Discovered {len(nodes_to_add)} nodes on {endpoint}")

        # Update stats for TUI
        if use_tui:
            endpoint_stats[endpoint] = {
                "status": "Connected",
                "node_count": len(nodes_to_add),
                "nodes": nodes_to_add,
                "last_update": datetime.now()
            }
            last_update_time = datetime.now()

    except ConnectionError:
        if not use_tui:
            print(f"Could not connect to {endpoint}")

        if use_tui:
            endpoint_stats[endpoint] = {
                "status": "Connection Failed",
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
        Text("TelOAV Discovery - OPC UA Node Monitor", justify="center", style="bold cyan"),
        style="bold white on blue"
    )

    # Create status info
    status_text = f"Last Update: {last_update_time.strftime('%Y-%m-%d %H:%M:%S') if last_update_time else 'Never'}"
    status_text += f" | Endpoints: {len(endpoint_stats)}"
    status_panel = Panel(Text(status_text, justify="center"), style="green")

    # Split layout: header, status, and content area
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
            f"❌ {stats['status']}", "", "", "",
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



async def main_async():
    service_config: ServiceConfig = config(ServiceConfig)

    # Detect if we're in an interactive TTY
    use_tui = sys.stdout.isatty() and sys.stdin.isatty()

    if not use_tui:
        print("Configuration:", service_config)

    console = Console() if use_tui else None

    async def fetch_and_update():
        with open(service_config.TELEGRAF_CONFIG_PATH_IN, "rb") as f:
            toml_config = tomllib.load(f)

        endpoints_to_monitor = endpoints_from_config(toml_config)

        discovered_nodes_by_endpoint = {}
        for endpoint in endpoints_to_monitor:
            discovered_nodes_by_endpoint[endpoint] = await discover_nodes(endpoint, use_tui=use_tui)

        inputs = toml_config.get("inputs", {})
        for input_type in INPUT_TYPES:
            if input_type not in inputs:
                continue

            for config_block in inputs.get(input_type, []):
                endpoint = config_block.get("endpoint")
                if endpoint and endpoint in discovered_nodes_by_endpoint:
                    nodes = discovered_nodes_by_endpoint[endpoint]
                    if nodes:
                        config_block["nodes"] = nodes
                    else:
                        if not use_tui:
                            print(f"No nodes discovered for endpoint {endpoint}, skipping update.")

        try:
            with open(service_config.TELEGRAF_CONFIG_PATH_OUT, "wb") as f:
                tomli_w.dump(toml_config, f)
            if not use_tui:
                print(f"Updated telegraf config written to {service_config.TELEGRAF_CONFIG_PATH_OUT}")
        except Exception as e:
            if not use_tui:
                print(f"Error writing config file: {e}")

    if use_tui and service_config.POLLING_INTERVAL > 0:
        # TUI mode with polling
        with Live(generate_tui_layout(), console=console, refresh_per_second=2, screen=True) as live:
            while True:
                await fetch_and_update()
                live.update(generate_tui_layout())
                await asyncio.sleep(service_config.POLLING_INTERVAL)
    elif use_tui:
        # TUI mode, single run
        await fetch_and_update()
        console.print(generate_tui_layout())
        console.print("\n[green]✓[/green] Discovery complete. Press any key to exit...")
        try:
            import msvcrt
            msvcrt.getch()
        except ImportError:
            input()
    elif service_config.POLLING_INTERVAL > 0:
        # Normal logging mode with polling
        while True:
            await fetch_and_update()
            print(f"Waiting for {service_config.POLLING_INTERVAL} seconds before next poll...")
            await asyncio.sleep(service_config.POLLING_INTERVAL)
    else:
        # Normal logging mode, single run
        await fetch_and_update()


if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("Exiting...")
