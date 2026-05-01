import asyncio
import logging
import socket
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from typing import Union, List, Tuple, Set, Optional

from asyncua import Client, ua
from asyncua.ua import Int32, String, Guid, ByteString

from src.models import AppState

logger = logging.getLogger("TelOAVDiscovery")

def get_identifier_type(identifier: Union[Int32, String, Guid, ByteString, ua.Guid, int, float]) -> str:
    if any(isinstance(identifier, t) for t in [Guid, ua.Guid]):
        return 'g'
    if any(isinstance(identifier, t) for t in [Int32, int, float]):
        return 'i'
    if isinstance(identifier, str):
        return 's'
    return 'b'

async def browse_recursive(node, nodes_to_add: List[dict], seen_node_ids: Set[str], naming_strategy: str = "plain", enable_id_tag: bool = False, include_ns0: bool = False, current_path: List[str] = None):
    if current_path is None:
        current_path = []
        
    try:
        children = await node.get_children()
    except Exception as e:
        logger.debug(f"Failed to get children for node: {e}")
        return

    for child in children:
        try:
            node_id = child.nodeid
            node_id_str = node_id.to_string()

            # Deduplication
            if node_id_str in seen_node_ids:
                continue
            seen_node_ids.add(node_id_str)

            browse_name = await child.read_browse_name()
            browse_name_str = browse_name.Name
            
            node_class = await child.read_node_class()
            if node_class == ua.NodeClass.Variable:
                # Configurable Namespace 0 exclusion
                if not include_ns0 and node_id.NamespaceIndex == 0:
                    continue

                ## Node ID configuration
                node_entry = {
                    "name": "value",
                    "namespace": str(node_id.NamespaceIndex),
                    "identifier_type": get_identifier_type(node_id.Identifier),
                    "identifier": f"{node_id.Identifier}"
                }

                # Apply Naming Strategy
                if naming_strategy == "suffix":
                    node_entry["name"] = f"value_{browse_name_str}"
                elif naming_strategy == "prefix":
                    node_entry["name"] = f"{browse_name_str}_value"
                elif naming_strategy == "path":
                    full_path = current_path + [browse_name_str]
                    node_entry["name"] = "_".join(full_path)
                else:
                    node_entry["name"] = "value"

                # Apply Tagging Strategy (Independent)
                if enable_id_tag:
                    node_entry["default_tags"] = {"id": browse_name_str}

                nodes_to_add.append(node_entry)
                logger.debug(f"Discovered node: {browse_name_str} (ns={node_id.NamespaceIndex})")

            # Always recurse to find nested variables/objects
            await browse_recursive(child, nodes_to_add, seen_node_ids, naming_strategy, enable_id_tag, include_ns0, current_path + [browse_name_str])
        except Exception as e:
            logger.debug(f"Error processing child node: {e}")
            continue

async def discover_nodes(endpoint: str, state: Optional[AppState] = None, naming_strategy: str = "plain", enable_id_tag: bool = False, include_ns0: bool = False, use_tui: bool = False) -> Tuple[str, List[dict]]:
    logger.info(f"Starting discovery on endpoint: {endpoint}")

    resolved_endpoint = endpoint
    try:
        parsed = urlparse(endpoint)
        if parsed.hostname:
            loop = asyncio.get_running_loop()
            ip = await loop.run_in_executor(None, socket.gethostbyname, parsed.hostname)

            if parsed.port:
                new_netloc = f"{ip}:{parsed.port}"
            else:
                new_netloc = ip

            parts = list(parsed)
            parts[1] = new_netloc
            resolved_endpoint = urlunparse(parts)

            if endpoint != resolved_endpoint:
                logger.info(f"Resolved endpoint {endpoint} to {resolved_endpoint}")
    except Exception as e:
        logger.debug(f"Failed to resolve hostname for {endpoint}: {e}")

    nodes_to_add = []
    seen_node_ids = set()

    try:
        logger.debug(f"Connecting to {resolved_endpoint}...")
        async with Client(url=resolved_endpoint) as client:
            logger.debug(f"Connected to {resolved_endpoint}")
            objects_node = client.get_objects_node()
            await browse_recursive(objects_node, nodes_to_add, seen_node_ids, naming_strategy, enable_id_tag, include_ns0)

        logger.info(f"Discovered {len(nodes_to_add)} nodes on {endpoint}")

        if use_tui and state is not None:
            state.endpoint_stats[endpoint] = {
                "status": "Connected",
                "node_count": len(nodes_to_add),
                "nodes": nodes_to_add,
                "last_update": datetime.now()
            }
            state.last_update_time = datetime.now()

    except ConnectionError as e:
        logger.error(f"Connection failed to {endpoint}: {e}")
        if use_tui and state is not None:
            state.endpoint_stats[endpoint] = {
                "status": "Connection Failed",
                "node_count": 0,
                "nodes": [],
                "last_update": datetime.now()
            }
            state.last_update_time = datetime.now()
        return resolved_endpoint, []
    except Exception as e:
        logger.error(f"Unexpected error discovering nodes on {endpoint}: {e}", exc_info=True)
        if use_tui and state is not None:
            state.endpoint_stats[endpoint] = {
                "status": f"Error: {str(e)[:30]}",
                "node_count": 0,
                "nodes": [],
                "last_update": datetime.now()
            }
            state.last_update_time = datetime.now()
        return resolved_endpoint, []

    return resolved_endpoint, nodes_to_add
