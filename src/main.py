import asyncio
import tomllib
from dataclasses import dataclass
from typing import Literal

import tomli_w
from asyncua import Client, ua

from Config import config

INPUT_TYPES: set[Literal["opcua_listener", "opcua"]] = {"opcua_listener", "opcua"}

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
    service_config: ServiceConfig = config(ServiceConfig)
    print("Configuration:", service_config)

    async def fetch_and_update():
        with open(service_config.TELEGRAF_CONFIG_PATH_IN, "rb") as f:
            toml_config = tomllib.load(f)

        endpoints_to_monitor = endpoints_from_config(toml_config)

        discovered_nodes_by_endpoint = {}
        for endpoint in endpoints_to_monitor:
            discovered_nodes_by_endpoint[endpoint] = await discover_nodes(endpoint)

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
                        print(f"No nodes discovered for endpoint {endpoint}, skipping update.")

        try:
            with open(service_config.TELEGRAF_CONFIG_PATH_OUT, "wb") as f:
                tomli_w.dump(toml_config, f)
            print(f"Updated telegraf config written to {service_config.TELEGRAF_CONFIG_PATH_OUT}")
        except Exception as e:
            print(f"Error writing config file: {e}")


    if service_config.POLLING_INTERVAL > 0:
        while True:
            await fetch_and_update()
            print(f"Waiting for {service_config.POLLING_INTERVAL} seconds before next poll...")
            await asyncio.sleep(service_config.POLLING_INTERVAL)
    else:
        await fetch_and_update()


if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("Exiting...")
