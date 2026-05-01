import asyncio
import logging
import os
import signal
import sys
import tomllib
import traceback
from datetime import datetime, timedelta

import aiofiles
import tomli_w
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler

from src.Config import config
from src.models import ServiceConfig, AppState
from src.discovery import discover_nodes
from src.telegraf import endpoints_from_config, update_telegraf_config
from src.tui import TUILogHandler, generate_tui_layout

# Setup logger
logger = logging.getLogger("TelOAVDiscovery")

# Global flag for graceful shutdown
shutdown_event = asyncio.Event()

def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_event.set()

async def fetch_and_update(service_config: ServiceConfig, state: AppState, use_tui: bool):
    """Core orchestration of discovery and configuration update"""
    config_changed = False

    logger.info("Reading Telegraf configuration from %s", service_config.TELEGRAF_CONFIG_PATH_IN)

    try:
        async with aiofiles.open(service_config.TELEGRAF_CONFIG_PATH_IN, "rb") as f:
            data = await f.read()
        toml_config = tomllib.loads(data.decode("utf-8"))

        if data != state.last_config_in:
            state.last_config_in = data
            config_changed = True
            logger.info("Detected change in input configuration file")
    except FileNotFoundError:
        logger.error("Configuration file not found: %s", service_config.TELEGRAF_CONFIG_PATH_IN)
        return
    except Exception as e:
        logger.error("Failed to read configuration: %s", e)
        return

    try:
        async with aiofiles.open(service_config.TELEGRAF_CONFIG_PATH_OUT, "rb") as f:
            output_data = await f.read()
            output_toml = tomllib.loads(output_data.decode("utf-8"))
    except FileNotFoundError:
        output_toml = None
        config_changed = True
    except Exception as e:
        logger.error("Failed to read output configuration: %s", e)
        return

    endpoints_to_monitor = endpoints_from_config(toml_config)
    logger.info("Found %d endpoint(s) to monitor", len(endpoints_to_monitor))

    # Parallelize discovery
    discovery_tasks = [
        discover_nodes(
            endpoint, 
            state=state,
            naming_strategy=service_config.NAMING_STRATEGY, 
            enable_id_tag=service_config.ENABLE_ID_TAG,
            include_ns0=service_config.INCLUDE_NS0, 
            use_tui=use_tui
        )
        for endpoint in endpoints_to_monitor
    ]
    
    results = await asyncio.gather(*discovery_tasks, return_exceptions=True)
    
    discovered_nodes_by_endpoint = {}
    resolved_endpoints_map = {}
    
    for endpoint, result in zip(endpoints_to_monitor, results):
        if isinstance(result, Exception):
            logger.error(f"Error discovering nodes for {endpoint}: {result}")
            discovered_nodes_by_endpoint[endpoint] = []
            resolved_endpoints_map[endpoint] = endpoint
        else:
            resolved, nodes = result
            discovered_nodes_by_endpoint[endpoint] = nodes
            resolved_endpoints_map[endpoint] = resolved

    # Update logic moved to src.telegraf
    logic_changed, nodes_updated_count = update_telegraf_config(
        toml_config, output_toml, discovered_nodes_by_endpoint, resolved_endpoints_map
    )
    
    if logic_changed:
        config_changed = True

    if config_changed:
        try:
            output_content = tomli_w.dumps(toml_config)
            async with aiofiles.open(service_config.TELEGRAF_CONFIG_PATH_OUT, "wb") as f:
                await f.write(output_content.encode("utf-8"))
            logger.info("Updated Telegraf config written to %s (%d endpoint(s) updated)",
                        service_config.TELEGRAF_CONFIG_PATH_OUT, nodes_updated_count)
        except Exception as e:
            logger.error("Error writing config file: %s", e)
    else:
        logger.info("No configuration changes detected, skipping file write")

    # Set next update time if polling
    if service_config.POLLING_INTERVAL > 0:
        state.next_update_time = datetime.now() + timedelta(seconds=service_config.POLLING_INTERVAL)

async def main_async():
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Detect if we're in an interactive TTY
    use_tui = sys.stdout.isatty() and sys.stdin.isatty()
    
    # Initialize App State
    state = AppState()

    # Setup logging
    logger.setLevel(logging.DEBUG)

    if use_tui:
        tui_handler = TUILogHandler(state)
        tui_handler.setLevel(logging.INFO)
        logger.addHandler(tui_handler)
    else:
        console_handler = RichHandler(rich_tracebacks=True)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    loglevel_env = os.getenv("LOGLEVEL", "").upper()
    if loglevel_env in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        logger.setLevel(getattr(logging, loglevel_env))
        logger.info("Log level set to %s from environment variable", loglevel_env)

    try:
        service_config: ServiceConfig = config(ServiceConfig)
        state.polling_interval = service_config.POLLING_INTERVAL
        if not use_tui:
            logger.info("Configuration: %s", service_config)
    except Exception as e:
        logger.critical("Failed to load configuration: %s", e, exc_info=True)
        return

    # Initially copy existing config to output path
    try:
        async with aiofiles.open(service_config.TELEGRAF_CONFIG_PATH_IN, "rb") as f_in:
            content = await f_in.read()
        async with aiofiles.open(service_config.TELEGRAF_CONFIG_PATH_OUT, "wb") as f_out:
            await f_out.write(content)
    except Exception as e:
        logger.error("Failed to copy initial config file: %s", e)

    console = Console() if use_tui else None

    if use_tui and service_config.POLLING_INTERVAL > 0:
        with Live(generate_tui_layout(state), console=console, refresh_per_second=4, screen=True) as live:
            while not shutdown_event.is_set():
                await fetch_and_update(service_config, state, use_tui)

                for _ in range(service_config.POLLING_INTERVAL * 4):
                    if shutdown_event.is_set():
                        break
                    live.update(generate_tui_layout(state))
                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=0.25)
                    except asyncio.TimeoutError:
                        pass
    elif use_tui:
        await fetch_and_update(service_config, state, use_tui)
        console.print(generate_tui_layout(state))
        console.print("\nDiscovery complete.")
    elif service_config.POLLING_INTERVAL > 0:
        while not shutdown_event.is_set():
            await fetch_and_update(service_config, state, use_tui)
            logger.info("Waiting for %d seconds before next poll...", service_config.POLLING_INTERVAL)
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=service_config.POLLING_INTERVAL)
            except asyncio.TimeoutError:
                pass
    else:
        await fetch_and_update(service_config, state, use_tui)

if __name__ == '__main__':
    print("Starting TelOAVDiscovery...", flush=True)
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting gracefully...")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        traceback.print_exc()
