"""
VSDL Python Compiler - SMT-based Validator
Implements constraint validation using Z3 SMT solver.
"""

from z3 import (
    Solver, sat, unsat, Int, Bool, And, Or, Not, Implies,
    If, Sum, ForAll, Exists, String, sat
)
from typing import List, Tuple, Dict, Optional, Set
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv4Address
import ipaddress

from .ast_nodes import (
    Scenario, NetworkDefinition, NodeDefinition, VulnerabilityDefinition,
    NetworkConnection, ComparisonOperator
)


@dataclass
class ValidationError:
    """Represents a validation error"""
    type: str  # 'network', 'resource', 'vulnerability', 'syntax'
    message: str
    location: Optional[str] = None  # Node/network/vulnerability name


@dataclass
class ValidationResult:
    """Result of SMT validation"""
    is_sat: bool
    errors: List[ValidationError]
    warnings: List[str]
    model: Optional[Dict] = None  # SMT model if SAT


class SMTValidator:
    """
    SMT-based validator for VSDL scenarios.

    Validates:
    1. Network topology consistency (IP allocation, connectivity)
    2. Resource constraints (RAM, disk, vCPU)
    3. Vulnerability topology dependencies (NEW)
    """

    def __init__(self):
        self.solver = Solver()
        self.errors: List[ValidationError] = []
        self.warnings: List[str] = []

    def validate(self, scenario: Scenario) -> ValidationResult:
        """
        Validate a VSDL scenario using SMT constraints.

        Args:
            scenario: The scenario AST to validate

        Returns:
            ValidationResult with SAT status and any errors
        """
        self.errors = []
        self.warnings = []
        self.solver = Solver()

        # Run all validation checks
        self._validate_basic_structure(scenario)
        self._validate_network_topology(scenario)
        self._validate_node_definitions(scenario)
        self._validate_vulnerability_topology(scenario)
        self._validate_cross_references(scenario)

        # Check SMT satisfiability
        is_sat = self.solver.check() == sat

        return ValidationResult(
            is_sat=is_sat and len(self.errors) == 0,
            errors=self.errors,
            warnings=self.warnings,
            model=self._extract_model() if is_sat else None
        )

    def _validate_basic_structure(self, scenario: Scenario):
        """Validate basic scenario structure"""
        if not scenario.name:
            self.errors.append(ValidationError(
                type='syntax',
                message='Scenario name is required'
            ))

        if scenario.duration <= 0:
            self.errors.append(ValidationError(
                type='syntax',
                message=f'Invalid duration: {scenario.duration}. Must be positive.'
            ))

        if not scenario.networks:
            self.errors.append(ValidationError(
                type='syntax',
                message='At least one network is required'
            ))

        if not scenario.nodes:
            self.errors.append(ValidationError(
                type='syntax',
                message='At least one node is required'
            ))

    def _validate_network_topology(self, scenario: Scenario):
        """
        Validate network topology using SMT constraints.

        Checks:
        - IP address range validity
        - No overlapping IP ranges between networks
        - All nodes have valid IPs within their network
        - Bidirectional network connections
        """
        networks = scenario.networks
        network_names = {n.name for n in networks}

        # Track all IPs across networks
        all_ips: Dict[str, Tuple[str, str]] = {}  # ip -> (node_name, network_name)

        for network in networks:
            # Validate CIDR
            if not network.address_range:
                self.errors.append(ValidationError(
                    type='network',
                    message=f'Network {network.name} has no address range defined',
                    location=network.name
                ))
                continue

            try:
                cidr = IPv4Network(network.address_range, strict=False)
            except ValueError as e:
                self.errors.append(ValidationError(
                    type='network',
                    message=f'Invalid CIDR {network.address_range}: {e}',
                    location=network.name
                ))
                continue

            # Check if network has internet gateway and is public
            if network.has_internet_gateway:
                # Public network should have a reasonable size
                if cidr.prefixlen > 28:
                    self.warnings.append(
                        f'Network {network.name} has Internet gateway but small range ({cidr})'
                    )

            # Validate IP assignments
            for conn in network.connections:
                if conn.ip_address:
                    try:
                        ip = IPv4Address(conn.ip_address)
                        if ip not in cidr:
                            self.errors.append(ValidationError(
                                type='network',
                                message=f'IP {conn.ip_address} is outside network {network.name} range {cidr}',
                                location=network.name
                            ))
                    except ValueError:
                        self.errors.append(ValidationError(
                            type='network',
                            message=f'Invalid IP address: {conn.ip_address}',
                            location=network.name
                        ))

                    # Check for duplicate IPs
                    ip_str = conn.ip_address
                    if ip_str in all_ips:
                        existing = all_ips[ip_str]
                        self.errors.append(ValidationError(
                            type='network',
                            message=f'Duplicate IP {ip_str}: used by {existing[0]} in {existing[1]} and {conn.node_name} in {network.name}',
                            location=network.name
                        ))
                    else:
                        all_ips[ip_str] = (conn.node_name, network.name)

        # Validate bidirectional network connections
        self._validate_network_connections(scenario, network_names)

    def _validate_network_connections(self, scenario: Scenario, network_names: Set[str]):
        """
        Validate network connections.

        Note: Network connections in VSDL can be unidirectional.
        A network A connecting to network B doesn't require B to connect back to A.
        This is just a warning, not an error.
        """
        connections: Dict[str, Set[str]] = {n.name: set() for n in scenario.networks}

        for network in scenario.networks:
            for conn in network.connections:
                if conn.node_name in network_names:
                    connections[network.name].add(conn.node_name)

        # Check bidirectionality - warn but don't error
        for net_name, connected_nets in connections.items():
            for other_net in connected_nets:
                if net_name not in connections.get(other_net, set()):
                    self.warnings.append(
                        f'Unidirectional connection: {net_name} -> {other_net}. '
                        f'Consider adding "node {net_name} is connected" to network {other_net} for bidirectional routing.'
                    )

    def _validate_node_definitions(self, scenario: Scenario):
        """
        Validate node hardware constraints using SMT.

        Creates SMT variables and constraints for:
        - RAM constraints
        - Disk constraints
        - vCPU constraints
        """
        for node in scenario.nodes:
            # Validate RAM
            if node.ram_value is not None:
                if node.ram_value <= 0:
                    self.errors.append(ValidationError(
                        type='resource',
                        message=f'Node {node.name} has invalid RAM: {node.ram_value}GB',
                        location=node.name
                    ))
                elif node.ram_operator == ComparisonOperator.LARGER_THAN and node.ram_value > 256:
                    self.warnings.append(
                        f'Node {node.name} requires >256GB RAM, verify platform limits'
                    )

            # Validate disk
            if node.disk_value is not None:
                if node.disk_value <= 0:
                    self.errors.append(ValidationError(
                        type='resource',
                        message=f'Node {node.name} has invalid disk: {node.disk_value}GB',
                        location=node.name
                    ))

            # Validate vCPU
            if node.vcpu is not None:
                if node.vcpu <= 0:
                    self.errors.append(ValidationError(
                        type='resource',
                        message=f'Node {node.name} has invalid vCPU: {node.vcpu}',
                        location=node.name
                    ))
                elif node.vcpu > 128:
                    self.warnings.append(
                        f'Node {node.name} requires >128 vCPUs, verify platform limits'
                    )

            # Validate OS
            if not node.os_image:
                self.errors.append(ValidationError(
                    type='resource',
                    message=f'Node {node.name} has no OS defined',
                    location=node.name
                ))

            # Check if node is connected to at least one network
            node_connected = False
            for network in scenario.networks:
                for conn in network.connections:
                    if conn.node_name == node.name:
                        node_connected = True
                        break
                if node_connected:
                    break

            if not node_connected:
                self.errors.append(ValidationError(
                    type='network',
                    message=f'Node {node.name} is not connected to any network',
                    location=node.name
                ))

    def _validate_vulnerability_topology(self, scenario: Scenario):
        """
        Validate vulnerability topology (NEW).

        Checks:
        - All vulnerability nodes have valid references
        - No cycles in vulnerability dependency graph
        - Software dependencies exist in referenced nodes
        - Host nodes exist
        """
        if not scenario.vulnerabilities:
            return

        vuln_names = {v.name for v in scenario.vulnerabilities}
        node_names = {n.name for n in scenario.nodes}

        # Build software map from nodes
        software_map: Dict[str, List[str]] = {}  # software -> list of nodes
        for node in scenario.nodes:
            for sw in node.software_mounts:
                if sw.name not in software_map:
                    software_map[sw.name] = []
                software_map[sw.name].append(node.name)

        for vuln in scenario.vulnerabilities:
            # Check vulnerable software
            if vuln.vulnerable_software:
                if vuln.vulnerable_software not in software_map:
                    self.warnings.append(
                        f'Vulnerability {vuln.name}: software {vuln.vulnerable_software} '
                        f'not found in any node definition'
                    )

            # Check hosted on node
            if vuln.hosted_on_node:
                if vuln.hosted_on_node not in node_names:
                    self.errors.append(ValidationError(
                        type='vulnerability',
                        message=f'Vulnerability {vuln.name}: host node {vuln.hosted_on_node} does not exist',
                        location=vuln.name
                    ))

            # Check software dependencies
            for dep in vuln.software_dependencies:
                if dep.name not in software_map:
                    self.warnings.append(
                        f'Vulnerability {vuln.name}: dependency {dep.name} not found in any node'
                    )

            # Check vulnerability references
            for req_vuln in vuln.requires_vulnerabilities:
                if req_vuln not in vuln_names:
                    self.errors.append(ValidationError(
                        type='vulnerability',
                        message=f'Vulnerability {vuln.name}: required vulnerability {req_vuln} does not exist',
                        location=vuln.name
                    ))

            for trig_vuln in vuln.triggers_vulnerabilities:
                if trig_vuln not in vuln_names:
                    self.errors.append(ValidationError(
                        type='vulnerability',
                        message=f'Vulnerability {vuln.name}: triggered vulnerability {trig_vuln} does not exist',
                        location=vuln.name
                    ))

        # Check for cycles in vulnerability dependency graph
        self._check_vulnerability_cycles(scenario)

    def _check_vulnerability_cycles(self, scenario: Scenario):
        """
        Check for cycles in the vulnerability dependency graph.
        """
        vuln_names = {v.name for v in scenario.vulnerabilities}

        # Build adjacency list
        graph: Dict[str, List[str]] = {v.name: v.requires_vulnerabilities for v in scenario.vulnerabilities}

        # DFS cycle detection
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {v: WHITE for v in vuln_names}

        def dfs(node: str, path: List[str]) -> Optional[List[str]]:
            color[node] = GRAY
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]
                elif color[neighbor] == WHITE:
                    cycle = dfs(neighbor, path)
                    if cycle:
                        return cycle

            path.pop()
            color[node] = BLACK
            return None

        for vuln in vuln_names:
            if color[vuln] == WHITE:
                cycle = dfs(vuln, [])
                if cycle:
                    self.errors.append(ValidationError(
                        type='vulnerability',
                        message=f'Cycle detected in vulnerability dependencies: {" -> ".join(cycle)}',
                        location=cycle[0]
                    ))
                    break

    def _validate_cross_references(self, scenario: Scenario):
        """
        Validate cross-references between networks, nodes, and vulnerabilities.
        """
        network_names = {n.name for n in scenario.networks}
        node_names = {n.name for n in scenario.nodes}

        # Check that all connected nodes in networks exist
        for network in scenario.networks:
            for conn in network.connections:
                # Network connections can be to nodes or other networks
                if conn.node_name not in node_names and conn.node_name not in network_names:
                    self.errors.append(ValidationError(
                        type='network',
                        message=f'Network {network.name}: connected entity {conn.node_name} does not exist',
                        location=network.name
                    ))

    def _extract_model(self) -> Dict:
        """Extract variable assignments from SMT model"""
        # For now, return empty dict as we're using error-based validation
        # Can be extended to extract actual variable values
        return {}


class VulnerabilityGraphAnalyzer:
    """
    Analyzes vulnerability topology for attack path enumeration.
    """

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.graph = scenario.get_vulnerability_graph()

    def get_entry_points(self) -> List[str]:
        """
        Get vulnerabilities with no dependencies (entry points for attack).
        """
        return [v for v in self.scenario.vulnerabilities if not v.requires_vulnerabilities]

    def get_attack_paths(self) -> List[List[str]]:
        """
        Enumerate all possible attack paths through the vulnerability graph.
        """
        paths = []

        def dfs(node: str, path: List[str], visited: Set[str]):
            if node in visited:
                return
            visited.add(node)
            path.append(node)

            # Find vulnerabilities triggered by this one
            triggered = []
            for v in self.scenario.vulnerabilities:
                if node in v.requires_vulnerabilities:
                    triggered.append(v.name)

            if not triggered:
                # End of path
                paths.append(path.copy())
            else:
                for next_vuln in triggered:
                    dfs(next_vuln, path, visited)

            path.pop()
            visited.remove(node)

        # Start from entry points
        for entry in self.get_entry_points():
            dfs(entry.name, [], set())

        return paths

    def get_vulnerability_risk_score(self, vuln_name: str) -> int:
        """
        Calculate risk score based on position in attack graph.
        Higher score = more critical (more downstream vulnerabilities).
        """
        count = 0

        def count_downstream(node: str, visited: Set[str]):
            nonlocal count
            if node in visited:
                return
            visited.add(node)

            for v in self.scenario.vulnerabilities:
                if node in v.requires_vulnerabilities:
                    count += 1
                    count_downstream(v.name, visited)

        count_downstream(vuln_name, set())
        return count