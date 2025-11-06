from dataclasses import MISSING, is_dataclass
import json
import tomllib
import os

import argparse
from typing import Type, get_origin, get_args, Union

import tomli_w


def _convert_env_var(value: str, target_type: Type):
    """Helper to convert environment variable string to a target type."""
    origin = get_origin(target_type)
    args = get_args(target_type)

    if origin is Union:
        # For Union, try to convert to each type in order
        for arg in args:
            try:
                return _convert_env_var(value, arg)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        raise ValueError(f"Could not convert '{value}' to any of {args}")

    if origin in (list, dict) or target_type in (list, dict):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON for {target_type}: {value}")

    if target_type is bool:
        return value.lower() in ('true', '1', 'yes', 'on')
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is str:
        return value

    # Fallback for other types or if no specific conversion is found
    try:
        return target_type(value)
    except (TypeError, ValueError):
        return value


def config[X](target: Type[X], config_path: str | None = None) -> X:
    """
    A small off the shelf configuration parser that supports:
    - Loading from a TOML or JSON configuration file specified via --config CLI argument
    - Overriding configuration values via environment variables
    - Using default values from the dataclass definition

    :param config_path: Optional path to configuration file (TOML or JSON). If None, will check --config CLI arg.
    :param target: Target dataclass type to parse configuration into
    :return: Parsed configuration dataclass instance
    """

    if not is_dataclass(target):
        raise TypeError("target must be a dataclass type")

    config: dict = {}

    # Read cli args for --config
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, help='Path to configuration TOML file', required=False)
    args = parser.parse_known_args()[0]
    if args.config is not None and config_path is None:
        config_path = args.config

    if config_path is not None:
        # Load configuration from specified config file
        match config_path.split('.')[-1].lower():
            case "toml":
                with open(config_path, "rb") as f:
                    for k, v in tomllib.load(f).items():
                        config[k] = v
            case "json":
                with open(config_path, "r", encoding="utf-8") as f:
                    for k, v in json.load(f).items():
                        config[k] = v
            case other:
                raise ValueError(f"unsupported configuration file format: {other}")

    # noinspection PyUnresolvedReferences
    dc_fields = target.__dataclass_fields__

    for k in dc_fields.keys():
        # Set default value from dataclass, if not already set by TOML Config
        if k not in config:
            if dc_fields[k].default is not MISSING:
                config[k] = dc_fields[k].default
            elif dc_fields[k].default_factory is not MISSING:
                config[k] = dc_fields[k].default_factory()

        # Override with value from environment variable, if exists
        env_value = os.getenv(k.upper())

        if env_value is not None:
            # Try to convert env var to the field's type
            field_type = dc_fields[k].type
            config[k] = _convert_env_var(env_value, field_type)

        # If key is still missing, raise error
        if k not in config:
            raise ValueError(f"Missing configuration for key: {k}")

    # Parse config dictionary into Config dataclass
    return target(**config)

def dump_config(config_instance: object, path: str) -> None:
    """
    Dumps the given configuration dataclass instance to a TOML/JSON file.
    :param config_instance: Configuration dataclass instance to dump
    :param path: Path to output file (TOML or JSON based on file extension)
    """
    if not is_dataclass(config_instance):
        raise TypeError("config_instance must be a dataclass instance")

    config_dict = {}
    for field in config_instance.__dataclass_fields__.keys():
        config_dict[field] = getattr(config_instance, field)

    match path.split('.')[-1].lower():
        case "toml":
            with open(path, "wb") as f:
                tomli_w.dump(config_dict, f)
        case "json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, indent=4)
        case other:
            raise ValueError(f"unsupported configuration file format: {other}")
