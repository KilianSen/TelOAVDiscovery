import logging
import tomllib
import tomli_w
from typing import List, Literal, Set

logger = logging.getLogger("TelOAVDiscovery")

INPUT_TYPES: Set[Literal["opcua_listener", "opcua"]] = {"opcua_listener", "opcua"}

def endpoints_from_config(toml_config: dict) -> List[str]:
    """Extract OPC UA endpoints from Telegraf configuration"""
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

def update_telegraf_config(
    toml_config: dict, 
    output_toml: dict, 
    discovered_nodes_by_endpoint: dict, 
    resolved_endpoints_map: dict
) -> tuple[bool, int]:
    """
    Updates the in-memory toml_config with discovered nodes.
    Returns (config_changed, nodes_updated_count)
    """
    config_changed = False
    nodes_updated_count = 0
    inputs = toml_config.get("inputs", {})

    for input_type in INPUT_TYPES:
        if input_type not in inputs:
            continue

        input_blocks = inputs.get(input_type, [])
        output_blocks = output_toml.get("inputs", {}).get(input_type, []) if output_toml else []

        for idx, config_block in enumerate(input_blocks):
            endpoint = config_block.get("endpoint")
            if endpoint and endpoint in discovered_nodes_by_endpoint:
                nodes = discovered_nodes_by_endpoint[endpoint]
                resolved_endpoint = resolved_endpoints_map.get(endpoint)

                # Safely get existing config from OUT file to compare
                existing_block = output_blocks[idx] if idx < len(output_blocks) else {}
                existing_nodes = existing_block.get("nodes", [])
                existing_endpoint = existing_block.get("endpoint", "")

                # Update endpoint in current config object
                if resolved_endpoint and resolved_endpoint != endpoint:
                    config_block["endpoint"] = resolved_endpoint
                    if existing_endpoint != resolved_endpoint:
                        config_changed = True
                        logger.debug(f"Endpoint changed in output: {existing_endpoint} -> {resolved_endpoint}")

                if nodes:
                    if existing_nodes != nodes:
                        config_block["nodes"] = nodes
                        nodes_updated_count += 1
                        config_changed = True
                        logger.debug("Updated configuration for endpoint: %s", endpoint)
                        logger.debug(" - Previous node count: %d", len(existing_nodes))
                        logger.debug(" - New node count: %d", len(nodes))
                    else:
                        logger.debug("No changes detected for endpoint: %s", endpoint)
                else:
                    logger.warning("No nodes discovered for endpoint %s, skipping update", endpoint)
    
    return config_changed, nodes_updated_count
