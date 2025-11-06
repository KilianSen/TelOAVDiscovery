import asyncio
import dataclasses
import json
import tomllib
import os
from dataclasses import dataclass

import tomli_w
from asyncua import Client, ua
import argparse

from typing_extensions import Literal

INPUT_TYPES: set[Literal["opcua_listener", "opcua"]] = {"opcua_listener", "opcua"}

@dataclass
class Config:
    POLLING_INTERVAL: int = -1 # Value in seconds, -1 means no polling
    TELEGRAF_CONFIG_PATH_IN: str = "./input/telegraf.conf"
    TELEGRAF_CONFIG_PATH_OUT: str = "./output/telegraf.conf"

def parse_configuration() -> Config:

    config: dict = {}

    # Read cli args for --config
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, help='Path to configuration TOML file', required=False)
    args = parser.parse_args()
    config_path = args.config

    if config_path is not None:
        # Load configuration from specified TOML file
        with open(config_path, "rb") as f:
            toml_config = tomllib.load(f)
            for k, v in toml_config.items():
                config[k] = v

    # noinspection PyUnresolvedReferences
    dc_fields = Config.__dataclass_fields__

    for k in dc_fields.keys():

        if k == "__dataclass_fields__":
            continue # Skip internal dataclass field

        # Set default value from dataclass, if not already set by TOML Config
        if dc_fields[k].default is not dataclasses.MISSING and k not in config:
            config[k] = dc_fields[k].default

        # Override with value from environment variable, if exists
        env_value = os.getenv(k)
        if env_value is not None:
            config[k] = env_value

        # If key is still missing, raise error
        if k not in config:
            raise ValueError(f"Missing configuration for key: {k}")

    # Parse config dictionary into Config dataclass
    return Config(**config)

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
            nodes_to_add.append({
                "name": browse_name.Name,
                "namespace": str(node_id.NamespaceIndex),
                "identifier_type": node_id.NodeIdType,
                "identifier": str(node_id.Identifier)
            })
        await browse_recursive(child, nodes_to_add)


async def discover_nodes(endpoint: str) -> list[dict]:
    print(f"Discovering nodes on {endpoint}")
    nodes_to_add = []
    try:
        async with Client(url=endpoint) as client:
            objects_node = client.get_objects_node()
            await browse_recursive(objects_node, nodes_to_add)
        print(f"Discovered {len(nodes_to_add)} nodes on {endpoint}")
    except ConnectionError:
        print(f"Could not connect to {endpoint}")
        return []
    return nodes_to_add


async def main_async():
    config = parse_configuration()
    print("Configuration:", config)

    async def fetch_and_update():
        with open(config.TELEGRAF_CONFIG_PATH_IN, "rb") as f:
            toml_config = tomllib.load(f)

        endpoints_to_monitor = endpoints_from_config(toml_config)

        for idx, endpoint in enumerate(endpoints_to_monitor):
            nodes = await discover_nodes(endpoint)

            if not nodes or len(nodes) == 0:
                print(f"No nodes discovered for endpoint {endpoint}, skipping update.")
                continue

            if "opcua_listener" in toml_config.get("inputs", {}):
                toml_config["inputs"]["opcua_listener"][idx]["nodes"] = nodes
            if "opcua" in toml_config.get("inputs", {}):
                 toml_config["inputs"]["opcua"][idx]["nodes"] = nodes

        try:
            with open(config.TELEGRAF_CONFIG_PATH_OUT, "wb") as f:
                tomli_w.dump(toml_config, f)
            print(f"Updated telegraf config written to {config.TELEGRAF_CONFIG_PATH_OUT}")
        except ImportError:
            print("Could not write config, 'toml' library not installed. Please install with 'pip install toml'")
        except Exception as e:
            print(f"Error writing config file: {e}")


    if config.POLLING_INTERVAL > 0:
        while True:
            await fetch_and_update()
            print(f"Waiting for {config.POLLING_INTERVAL} seconds before next poll...")
            await asyncio.sleep(config.POLLING_INTERVAL)
    else:
        await fetch_and_update()


if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("Exiting...")
