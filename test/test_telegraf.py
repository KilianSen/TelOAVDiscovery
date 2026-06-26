"""Minimal guard tests for node injection routing. Run: python -m test.test_telegraf"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.telegraf import node_container, update_telegraf_config


def test_node_container_prefers_group():
    block = {"endpoint": "x", "group": [{"name": "opcua", "sampling_interval": "10ms", "nodes": []}]}
    assert node_container(block) is block["group"][0]


def test_node_container_falls_back_to_block():
    block = {"endpoint": "x", "nodes": []}
    assert node_container(block) is block


def test_group_injection_preserves_sampling_interval():
    nodes = [{"name": "P_CC", "namespace": "1", "identifier_type": "s", "identifier": "P_CC"}]
    cfg = {"inputs": {"opcua_listener": [{
        "endpoint": "opc.tcp://s:4840",
        "group": [{"name": "opcua", "sampling_interval": "10ms", "nodes": []}],
    }]}}
    changed, count = update_telegraf_config(cfg, None, {"opc.tcp://s:4840": nodes}, {})
    grp = cfg["inputs"]["opcua_listener"][0]["group"][0]
    assert changed and count == 1
    assert grp["nodes"] == nodes              # nodes landed in the group
    assert grp["sampling_interval"] == "10ms" # and the setting survived


def test_input_level_injection_without_group():
    nodes = [{"name": "value", "namespace": "1", "identifier_type": "s", "identifier": "P_CC"}]
    cfg = {"inputs": {"opcua_listener": [{"endpoint": "opc.tcp://s:4840", "nodes": []}]}}
    changed, count = update_telegraf_config(cfg, None, {"opc.tcp://s:4840": nodes}, {})
    assert changed and count == 1
    assert cfg["inputs"]["opcua_listener"][0]["nodes"] == nodes


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
