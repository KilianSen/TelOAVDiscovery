import logging
from datetime import datetime
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.models import AppState

class TUILogHandler(logging.Handler):
    """Custom log handler that stores messages for AppState display"""
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state

    def emit(self, record):
        log_entry = {
            "time": datetime.fromtimestamp(record.created),
            "level": record.levelname,
            "message": record.getMessage()
        }
        self.state.log_messages.append(log_entry)

def generate_tui_layout(state: AppState) -> Layout:
    """Generate the Rich TUI layout based on AppState"""
    layout = Layout()

    # Create header
    header = Panel(
        Text("TelOAV Discovery - OPC UA Node Monitor", justify="center", style="bold white"),
        style="bold white"
    )

    # Create status info
    if state.last_update_time is not None:
        last_update_str = state.last_update_time.strftime('%Y-%m-%d %H:%M:%S')
    else:
        last_update_str = 'Never'

    status_text = f"Last Update: {last_update_str}"
    status_text += f" | Endpoints: {len(state.endpoint_stats)}"
    status_text += f" | Logs: {len(state.log_messages)}"

    # Add countdown to next update if polling is enabled
    if state.next_update_time is not None and state.polling_interval > 0:
        time_remaining = (state.next_update_time - datetime.now()).total_seconds()
        if time_remaining > 0:
            minutes, seconds = divmod(int(time_remaining), 60)
            if minutes > 0:
                status_text += f" | Next update in: {minutes}m {seconds}s"
            else:
                status_text += f" | Next update in: {seconds}s"
        else:
            status_text += " | Updating..."
    elif state.polling_interval > 0:
        status_text += f" | Polling every {state.polling_interval}s"

    status_panel = Panel(Text(status_text, justify="center"), style="green")

    # Determine if we have enough space for logs (console height check)
    console = Console()
    console_height = console.size.height
    show_logs = console_height > 30

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

    if state.endpoint_stats:
        endpoints = list(state.endpoint_stats.keys())
        count = len(endpoints)

        if count == 1:
            cols = 1
        elif count == 2:
            cols = 2
        elif count == 4:
            cols = 2
        else:
            cols = 3

        rows = (count + cols - 1) // cols

        row_layouts = []
        for i in range(rows):
            row_layouts.append(Layout(name=f"row_{i}"))

        layout["main"].split_column(*row_layouts)

        for i in range(rows):
            start_idx = i * cols
            end_idx = min(start_idx + cols, count)
            row_endpoints = endpoints[start_idx:end_idx]

            col_layouts = []
            for endpoint in row_endpoints:
                col_layouts.append(Layout(name=endpoint))

            if len(col_layouts) < cols:
                for j in range(cols - len(col_layouts)):
                    col_layouts.append(Layout(name=f"dummy_{i}_{j}"))

            layout[f"row_{i}"].split_row(*col_layouts)

            for endpoint in row_endpoints:
                table = create_endpoint_table(endpoint, state.endpoint_stats[endpoint])
                layout[endpoint].update(table)
    else:
        layout["main"].update(Panel("No endpoints configured", style="yellow"))

    if show_logs:
        log_panel = create_log_panel(state)
        layout["logs"].update(log_panel)

    return layout

def create_endpoint_table(endpoint: str, stats: dict) -> Panel:
    """Create a table showing nodes for a specific endpoint"""
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
    table.add_column("Identifier Type", style="green", no_wrap=False)

    status_color = "green" if stats["status"] == "Connected" else "red"
    nodes = stats.get("nodes", [])

    if stats["status"] == "Connected" and nodes:
        display_limit = 50
        for i, node in enumerate(nodes[:display_limit]):
            table.add_row(
                node.get("name", "N/A"),
                node.get("namespace", "N/A"),
                str(node.get("identifier", "N/A")),
                node.get("identifier_type", "Unknown")
            )

        if len(nodes) > display_limit:
            table.add_row(
                f"... and {len(nodes) - display_limit} more nodes",
                "", "", "",
                style="dim italic"
            )
    elif stats["status"] != "Connected":
        table.add_row(f"{stats['status']}", "", "", "", style="bold red")
    else:
        table.add_row("No nodes discovered", "", "", "", style="dim italic")

    subtitle = f"Status: [{status_color}]{stats['status']}[/{status_color}] | Nodes: {stats['node_count']}"
    if stats.get('last_update'):
        subtitle += f" | Updated: {stats['last_update'].strftime('%H:%M:%S')}"

    return Panel(table, subtitle=subtitle, border_style=status_color, padding=(1, 2))

def create_log_panel(state: AppState) -> Panel:
    """Create a panel showing recent log messages from AppState"""
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

    recent_logs = list(state.log_messages)[-8:]

    if recent_logs:
        for log_entry in recent_logs:
            level = log_entry["level"]
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
            if len(message) > 120:
                message = message[:117] + "..."

            log_table.add_row(time_str, Text(level, style=level_style), message)
    else:
        log_table.add_row("--:--:--", "INFO", "No log messages yet", style="dim italic")

    return Panel(log_table, title="📋 Recent Logs", border_style="blue", padding=(0, 1))
