# TelOAVDiscovery - Telegraf OPCUA Discovery Service

TelOAVDiscovery is a Python-based utility designed to automatically discover OPC UA variables from one or more OPC UA servers and dynamically update Telegraf configuration files with the discovered nodes. It is particularly useful in dynamic industrial environments where the set of monitored sensors or variables frequently changes.

## Project Overview

- **Core Functionality**: Reads an input Telegraf configuration, identifies OPC UA input blocks (`opcua` or `opcua_listener`), connects to the specified endpoints, recursively browses for variables (skipping Namespace 0), and writes a new Telegraf configuration with an updated `nodes` list.
- **Technologies**:
    - **Language**: Python 3.12+
    - **OPC UA**: `asyncua` (Asynchronous OPC UA library)
    - **Terminal UI/Logging**: `rich` (for a modern TUI and structured logging)
    - **Configuration**: TOML based, using `tomllib` and `tomli_w`.
- **Architecture**:
    - `main.py`: Entry point, contains the discovery logic, TUI implementation, and main loop.
    - `src/Config.py`: A flexible configuration handler supporting CLI arguments, TOML/JSON files, and environment variable overrides via dataclasses.
    - `Dockerfile`: Multi-stage build for containerized deployment.

## Key Features

- **Interactive TUI**: When run in a TTY, it displays a real-time monitor of endpoints, discovered nodes, and logs.
- **Continuous Discovery**: Supports a polling mode (`POLLING_INTERVAL`) to keep Telegraf configs in sync with live OPC UA servers.
- **Tagging Strategies**: Supports different strategies for mapping OPC UA variable names to Telegraf field names (e.g., `suffix`, `enable`, `disable`).
- **Graceful Shutdown**: Handles SIGINT/SIGTERM for clean exits.

## Building and Running

### Development
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the application:
   ```bash
   python main.py --config debug.toml
   ```

### Docker
1. Build the image:
   ```bash
   docker build -t teloavdiscovery:latest .
   ```
2. Run the container:
   ```bash
   docker run -v ./telegraf.conf:/input/telegraf.conf:ro \
              -v ./output:/output:rw \
              -e POLLING_INTERVAL=60 \
              teloavdiscovery:latest
   ```

## Configuration

The application can be configured via a TOML file (using `--config`) or environment variables.

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `POLLING_INTERVAL` | `-1` | Seconds between discovery runs (-1 for single run). |
| `TELEGRAF_CONFIG_PATH_IN` | `./test/telegraf.conf` | Path to the template Telegraf config. |
| `TELEGRAF_CONFIG_PATH_OUT` | `./test/telegraf1.conf` | Path where the updated config will be written. |
| `NAMING_STRATEGY` | `suffix` | Options: `plain`, `prefix`, `suffix`, `path`. Controls node field naming. |
| `ENABLE_ID_TAG` | `False` | Whether to add an `id` tag with the variable's browse name to each node. |
| `INCLUDE_NS0` | `False` | Whether to include standard OPC UA nodes from Namespace 0. |
| `LOGLEVEL` | `INFO` | Standard Python log levels (DEBUG, INFO, etc.). |

## Development Conventions

- **Asynchronous IO**: The project strictly uses `asyncio` for network operations and file I/O to maintain responsiveness, especially for the TUI.
- **Type Hinting**: Extensive use of Python type hints for better maintainability and IDE support.
- **Configuration via Dataclasses**: New configuration options should be added to the `ServiceConfig` dataclass in `main.py`.
- **Styling**: Adheres to standard Python PEP 8 conventions. Uses `rich` for all terminal output.
