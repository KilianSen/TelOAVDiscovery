# Telegraf OPCUA Discovery Service

This repository contains a docker container, that automatically discovers OPCUA Variables from a given OPCUA Server
and creates/updates a Telegraf configuration file with the discovered variables.

### TUI Mode (Interactive Terminal)

When run in an interactive terminal, the application displays a rich TUI with:
- Split-screen view of all monitored endpoints
- Live variable tracking with type information
- Log window at the bottom (on terminals > 30 lines)
- Color-coded status indicators
- Real-time updates

### Logging Mode (Non-Interactive)

When run in Docker or with output redirection:
- Structured Rich console logging
- Emoji-based status indicators
- Color-coded log levels
- Full traceback on errors

## Usage

### Interactive Mode (Development)

```bash
python src/main.py
```

This will show the Rich TUI with split-screen and live logs.

### Docker Build

Build the Docker image:

```bash
docker build -t teloavdiscovery:latest .
```

Run the container:

```bash
docker run -v ./test/telegraf.conf:/input/telegraf.conf:ro \
           -v ./output:/output:rw \
           -e POLLING_INTERVAL=60 \
           teloavdiscovery:latest
```

### Docker Compose (Production)

It is only recommended to use this tool within a docker compose setup alongside Telegraf.

#### Docker Compose Example

```yaml
services:
  telegraf:
    image: telegraf:latest
    container_name: telegraf
    volumes:
      - telegraf_config:/etc/telegraf/telegraf.d:ro
    depends_on:
      - opcua_discovery
    command:
      - --watch-config notify
      
  opcua_discovery:
    build:
        context: .
        dockerfile: Dockerfile
    container_name: telegraf_opcua_discovery
    environment:
      - OPCUA_SERVER_URL=opc.tcp://your-opcua-server:4840
      - CONTINUOUS_DISCOVERY=true
    volumes:
      - ./telegraf.conf:/input/telegraf.conf:ro
      - telegraf_config:/output:rw

volumes:
    telegraf_config:
```

## Configuration

See [debug.toml](debug.toml) for configuration options.

Key settings:
- `POLLING_INTERVAL`: Seconds between discovery runs (-1 for single run)
- `TELEGRAF_CONFIG_PATH_IN`: Input Telegraf configuration path
- `TELEGRAF_CONFIG_PATH_OUT`: Output Telegraf configuration path
