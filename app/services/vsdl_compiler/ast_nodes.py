"""
VSDL Python Compiler - AST Node Definitions
Defines the Abstract Syntax Tree nodes for VSDL language.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class ComparisonOperator(Enum):
    EQUAL_TO = "equal to"
    LARGER_THAN = "larger than"
    SMALLER_THAN = "smaller than"


@dataclass
class SoftwareDependency:
    """Software dependency definition"""
    name: str
    version: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    config: Dict[str, str] = field(default_factory=dict)


@dataclass
class NodeDefinition:
    """Physical/Virtual node definition"""
    name: str
    ram_value: Optional[int] = None
    ram_operator: Optional[ComparisonOperator] = None
    disk_value: Optional[int] = None
    disk_operator: Optional[ComparisonOperator] = None
    vcpu: Optional[int] = None
    os_image: Optional[str] = None
    software_mounts: List[SoftwareDependency] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ram": {"value": self.ram_value, "operator": self.ram_operator.value if self.ram_operator else None},
            "disk": {"value": self.disk_value, "operator": self.disk_operator.value if self.disk_operator else None},
            "vcpu": self.vcpu,
            "os": self.os_image,
            "software": [{"name": s.name, "version": s.version, "config": s.config} for s in self.software_mounts]
        }


@dataclass
class NetworkConnection:
    """Network connection definition"""
    node_name: str
    ip_address: Optional[str] = None


@dataclass
class NetworkDefinition:
    """Network segment definition"""
    name: str
    address_range: Optional[str] = None
    connections: List[NetworkConnection] = field(default_factory=list)
    has_internet_gateway: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "address_range": self.address_range,
            "connections": [{"node": c.node_name, "ip": c.ip_address} for c in self.connections],
            "has_internet_gateway": self.has_internet_gateway
        }


@dataclass
class VulnerabilityDefinition:
    """
    Vulnerability topology node definition (NEW)

    Represents a vulnerability in the attack graph, including:
    - The vulnerable software and version
    - CVE identifier
    - Software dependencies required to trigger the vulnerability
    - Relationships with other vulnerability nodes
    - The physical node hosting this vulnerability
    """
    name: str
    vulnerable_software: Optional[str] = None
    vulnerable_version: Optional[str] = None
    cve_id: Optional[str] = None

    # Software dependencies - required software to trigger the vulnerability
    software_dependencies: List[SoftwareDependency] = field(default_factory=list)

    # Vulnerability relationships
    triggers_vulnerabilities: List[str] = field(default_factory=list)  # This vuln can trigger others
    requires_vulnerabilities: List[str] = field(default_factory=list)  # This vuln requires others

    # Physical node hosting
    hosted_on_node: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "vulnerable_software": self.vulnerable_software,
            "vulnerable_version": self.vulnerable_version,
            "cve_id": self.cve_id,
            "software_dependencies": [
                {"name": d.name, "version": d.version} for d in self.software_dependencies
            ],
            "triggers": self.triggers_vulnerabilities,
            "requires": self.requires_vulnerabilities,
            "hosted_on_node": self.hosted_on_node
        }


@dataclass
class Scenario:
    """
    Top-level VSDL scenario

    Contains:
    - Scenario name and duration
    - Network topology definitions
    - Node definitions (hardware/software)
    - Vulnerability topology (NEW)
    """
    name: str
    duration: int
    networks: List[NetworkDefinition] = field(default_factory=list)
    nodes: List[NodeDefinition] = field(default_factory=list)
    vulnerabilities: List[VulnerabilityDefinition] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "duration": self.duration,
            "networks": [n.to_dict() for n in self.networks],
            "nodes": [n.to_dict() for n in self.nodes],
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities]
        }

    def get_vulnerability_graph(self) -> Dict[str, List[str]]:
        """
        Build a directed graph of vulnerability dependencies.

        Returns:
            Dict mapping vulnerability name to list of vulnerabilities it depends on
        """
        graph = {}
        for vuln in self.vulnerabilities:
            graph[vuln.name] = vuln.requires_vulnerabilities.copy()
        return graph

    def get_node_vulnerabilities(self) -> Dict[str, List[str]]:
        """
        Map physical nodes to their hosted vulnerabilities.

        Returns:
            Dict mapping node name to list of vulnerability names
        """
        node_vulns = {}
        for vuln in self.vulnerabilities:
            if vuln.hosted_on_node:
                if vuln.hosted_on_node not in node_vulns:
                    node_vulns[vuln.hosted_on_node] = []
                node_vulns[vuln.hosted_on_node].append(vuln.name)
        return node_vulns


@dataclass
class CompilationResult:
    """Result of VSDL compilation"""
    success: bool
    scenario: Optional[Scenario] = None
    terraform_files: Dict[str, str] = field(default_factory=dict)
    ansible_files: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_sat(self) -> bool:
        """Check if scenario constraints are satisfiable"""
        return self.success and len(self.errors) == 0