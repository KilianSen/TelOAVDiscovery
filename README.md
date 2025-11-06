# Telegraf OPCUA Discovery Service

This repository contains a docker container, that automatically discovers OPCUA Variables from a given OPCUA Server
and creates/updates a Telegraf configuration file with the discovered variables.

## Usage

It is only recommended to use this tool within a docker compose setup alongside Telegraf.

### Docker Compose Example

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
    image: ""
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