"""
Advanced UNSAT Analyzer for VSDL Scripts
Provides detailed analysis of UNSAT reasons beyond basic connectivity checks.
"""

import re
import os
from typing import List, Dict, Any
from flask import current_app

def analyze_unsat_advanced(vsdl_script: str) -> List[Dict[str, Any]]:
    """
    Advanced UNSAT analysis that checks multiple potential issues.

    Args:
        vsdl_script: The VSDL script that failed validation

    Returns:
        List of dictionaries with error details and suggested fixes
    """
    errors = []

    # Parse the VSDL script
    try:
        parsed = parse_vsdl_script(vsdl_script)
    except Exception as e:
        errors.append({
            "type": "PARSING_ERROR",
            "message": f"Failed to parse VSDL script: {str(e)}",
            "severity": "CRITICAL",
            "suggestion": "Check script syntax"
        })
        return errors

    # Check for common UNSAT causes
    errors.extend(check_resource_constraints(parsed))
    errors.extend(check_network_connectivity(parsed))
    errors.extend(check_platform_constraints(parsed))
    errors.extend(check_solver_compatibility(parsed))

    # Add context about the specific error
    if not errors:
        errors.append({
            "type": "UNKNOWN_UNSAT",
            "message": "UNSAT detected but no obvious structural issues found",
            "severity": "HIGH",
            "suggestion": "Check for conflicting constraints or solver-specific rules"
        })

    return errors

def parse_vsdl_script(script: str) -> Dict[str, Any]:
    """Parse VSDL script into structured data."""
    parsed = {
        "networks": {},
        "nodes": {},
        "connections": [],
        "resources": {}
    }

    lines = script.split('\n')
    current_network = None
    current_node = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith('//'):
            continue

        # Parse network definition
        if line.startswith('network ') and '{' in line:
            network_name = line.split()[1]
            parsed["networks"][network_name] = {
                "name": network_name,
                "nodes": [],
                "address_range": None,
                "has_gateway": False
            }
            current_network = network_name
            current_node = None
            continue

        # Parse node definition
        if line.startswith('node ') and '{' in line:
            node_name = line.split()[1]
            parsed["nodes"][node_name] = {
                "name": node_name,
                "network": current_network,
                "resources": {},
                "os": None,
                "software": []
            }
            current_node = node_name
            continue

        # Parse network properties
        if current_network:
            if 'addresses range is' in line:
                match = re.search(r'addresses range is ([^;]+);', line)
                if match:
                    parsed["networks"][current_network]["address_range"] = match.group(1)
            elif 'gateway has direct access to the Internet' in line:
                parsed["networks"][current_network]["has_gateway"] = True

        # Parse node properties
        if current_node and current_node in parsed["nodes"]:
            if 'node OS is' in line:
                match = re.search(r'node OS is "([^"]+)";', line)
                if match:
                    parsed["nodes"][current_node]["os"] = match.group(1)

            # Parse resource constraints
            resource_patterns = {
                'ram': r'ram (larger than|equal to|smaller than) (\d+)GB;',
                'disk': r'disk size (equal to|larger than|smaller than) (\d+)GB;',
                'vcpu': r'vcpu (equal to|larger than|smaller than) (\d+);'
            }

            for resource, pattern in resource_patterns.items():
                match = re.search(pattern, line)
                if match:
                    op = match.group(1)
                    value = int(match.group(2))
                    parsed["nodes"][current_node]["resources"][resource] = {
                        "operator": op,
                        "value": value
                    }

    return parsed

def check_resource_constraints(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check for resource constraint issues."""
    errors = []

    # Minimum requirements for each OS
    os_requirements = {
        "ubuntu20": {"ram": 2, "disk": 50},
        "ubuntu18": {"ram": 2, "disk": 40},
        "ubuntu16": {"ram": 2, "disk": 40},
        "kali": {"ram": 8, "disk": 160},
        "centos8": {"ram": 2, "disk": 60},
        "openeuler20.03": {"ram": 2, "disk": 60}
    }

    for node_name, node_data in parsed["nodes"].items():
        os_type = node_data.get("os")
        if os_type and os_type in os_requirements:
            requirements = os_requirements[os_type]
            resources = node_data.get("resources", {})

            # Check RAM
            if "ram" in resources:
                ram_info = resources["ram"]
                if ram_info["operator"] in ["equal to", "smaller than"] and ram_info["value"] < requirements["ram"]:
                    errors.append({
                        "type": "INSUFFICIENT_RAM",
                        "message": f"Node '{node_name}' has insufficient RAM ({ram_info['value']}GB < {requirements['ram']}GB) for OS '{os_type}'",
                        "severity": "HIGH",
                        "suggestion": f"Increase RAM to at least {requirements['ram']}GB for {os_type}"
                    })
            else:
                errors.append({
                    "type": "MISSING_RAM",
                    "message": f"Node '{node_name}' missing RAM constraint",
                    "severity": "MEDIUM",
                    "suggestion": "Add RAM constraint (e.g., 'ram larger than 4GB;')"
                })

            # Check Disk
            if "disk" in resources:
                disk_info = resources["disk"]
                if disk_info["operator"] in ["equal to", "smaller than"] and disk_info["value"] < requirements["disk"]:
                    errors.append({
                        "type": "INSUFFICIENT_DISK",
                        "message": f"Node '{node_name}' has insufficient disk ({disk_info['value']}GB < {requirements['disk']}GB) for OS '{os_type}'",
                        "severity": "HIGH",
                        "suggestion": f"Increase disk to at least {requirements['disk']}GB for {os_type}"
                    })
            else:
                errors.append({
                    "type": "MISSING_DISK",
                    "message": f"Node '{node_name}' missing disk constraint",
                    "severity": "MEDIUM",
                    "suggestion": "Add disk constraint (e.g., 'disk size equal to 50GB;')"
                })

    return errors

def check_network_connectivity(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check for network connectivity issues."""
    errors = []
    networks = parsed["networks"]

    # Find gateway network
    gateway_networks = [name for name, data in networks.items() if data.get("has_gateway")]

    if not gateway_networks:
        errors.append({
            "type": "NO_GATEWAY",
            "message": "No network with internet access (gateway)",
            "severity": "HIGH",
            "suggestion": "Add 'gateway has direct access to the Internet;' to a network"
        })
    elif len(gateway_networks) > 1:
        errors.append({
            "type": "MULTIPLE_GATEWAYS",
            "message": f"Multiple networks have internet access: {', '.join(gateway_networks)}",
            "severity": "MEDIUM",
            "suggestion": "Only one network should have internet access"
        })

    # Check if all networks are connected
    network_graph = build_network_graph(parsed)
    if len(networks) > 1:
        connected_networks = find_connected_networks(network_graph, list(networks.keys())[0])
        disconnected = [name for name in networks if name not in connected_networks]

        if disconnected:
            errors.append({
                "type": "DISCONNECTED_NETWORK",
                "message": f"Networks not connected to main topology: {', '.join(disconnected)}",
                "severity": "HIGH",
                "suggestion": f"Add bidirectional connections between networks using 'node {disconnected[0]} is connected;' and 'node {list(networks.keys())[0]} is connected;'"
            })

    # Check for isolated nodes
    for node_name, node_data in parsed["nodes"].items():
        if not node_data.get("network"):
            errors.append({
                "type": "ISOLATED_NODE",
                "message": f"Node '{node_name}' is not assigned to any network",
                "severity": "HIGH",
                "suggestion": f"Add the node to a network using 'node {node_name} is connected;' in the network definition"
            })

    return errors

def build_network_graph(parsed: Dict[str, Any]) -> Dict[str, set]:
    """Build network connectivity graph."""
    graph = {name: set() for name in parsed["networks"]}

    # Track which networks each node connects to
    node_networks = {}

    # First pass: collect all networks each node is connected to
    for network_name, network_data in parsed["networks"].items():
        for connected_node in network_data.get("nodes", []):
            if connected_node not in node_networks:
                node_networks[connected_node] = set()
            node_networks[connected_node].add(network_name)

    # Second pass: build connections based on nodes that appear in multiple networks
    for node, networks in node_networks.items():
        if len(networks) > 1:
            # This node connects all the networks it appears in
            for net1 in networks:
                for net2 in networks:
                    if net1 != net2:
                        graph[net1].add(net2)
                        graph[net2].add(net1)
        elif len(networks) == 1 and node in parsed["networks"]:
            # If the connected node is itself a network, create a direct connection
            network_with_node = list(networks)[0]
            if network_with_node != node:
                graph[network_with_node].add(node)
                graph[node].add(network_with_node)

    return graph

def find_connected_networks(graph: Dict[str, set], start: str) -> set:
    """Find all networks connected to the start network using DFS."""
    visited = set()
    stack = [start]

    while stack:
        network = stack.pop()
        if network not in visited:
            visited.add(network)
            for connected in graph.get(network, []):
                if connected not in visited:
                    stack.append(connected)

    return visited

def check_platform_constraints(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check for platform-specific constraints."""
    errors = []

    # Check for valid OS types
    valid_os = ["ubuntu20", "ubuntu18", "ubuntu16", "kali", "centos8", "centos-7", "openeuler20.03", "fedora"]
    for node_name, node_data in parsed["nodes"].items():
        os_type = node_data.get("os")
        if os_type and os_type not in valid_os:
            errors.append({
                "type": "INVALID_OS",
                "message": f"Invalid OS type '{os_type}' for node '{node_name}'",
                "severity": "HIGH",
                "suggestion": f"Use one of: {', '.join(valid_os)}"
            })

    # Check for realistic resource values
    for node_name, node_data in parsed["nodes"].items():
        resources = node_data.get("resources", {})
        for resource, info in resources.items():
            if info["value"] > 1024:  # Unusually large values
                errors.append({
                    "type": "UNREALISTIC_RESOURCE",
                    "message": f"Unrealistic {resource} value ({info['value']}) for node '{node_name}'",
                    "severity": "MEDIUM",
                    "suggestion": f"Check if {resource} value is reasonable"
                })

    return errors

def check_solver_compatibility(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check for potential solver-specific issues."""
    errors = []

    # Check for complex constraints that might cause solver issues
    for node_name, node_data in parsed["nodes"].items():
        # Check for conflicting resource constraints
        resources = node_data.get("resources", {})
        if "ram" in resources and "disk" in resources:
            ram = resources["ram"]["value"]
            disk = resources["disk"]["value"]
            # Check for extremely imbalanced ratios
            if ram > 64 and disk < 100:
                errors.append({
                    "type": "UNBALANCED_RESOURCES",
                    "message": f"Unbalanced resources for node '{node_name}': high RAM ({ram}GB) but low disk ({disk}GB)",
                    "severity": "MEDIUM",
                    "suggestion": "Ensure resource ratios are reasonable for the intended workload"
                })

    return errors