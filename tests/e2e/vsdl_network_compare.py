#!/usr/bin/env python3
import json
from dataclasses import dataclass
from typing import Dict, List, Set
import networkx as nx
from collections import defaultdict
import ipaddress

@dataclass
class VSDLNode:
    """Data class for VSDL node"""
    name: str
    type: str  # 'network' or 'host'
    properties: dict

@dataclass
class VSDLConnection:
    """Data class for VSDL network connection"""
    source: str
    target: str
    ip_address: str = ""

class VSDLNetworkComparer:
    def __init__(self):
        # Keep only two dimensions of weights
        self.weights = {
            'topology': 0.6,    # Network topology structure weight 60%
            'software': 0.4     # Software configuration weight 40%
        }

    def parse_vsdl(self, vsdl_content: str) -> tuple[List[VSDLNode], List[VSDLConnection]]:
        """Parse VSDL file content
        
        Args:
            vsdl_content: VSDL file content
            
        Returns:
            (nodes, connections) tuple
        """
        nodes = []
        connections = []
        current_network = None
        current_node = None
        
        # Parse line by line
        lines = vsdl_content.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('//'):
                continue
                
            # Parse network definition
            if 'network' in line and '{' in line:
                network_name = line.split('network')[1].split('{')[0].strip()
                current_network = network_name
                current_node = None  # Reset current node
                nodes.append(VSDLNode(
                    name=network_name,
                    type='network',
                    properties={
                        'name': network_name
                    }
                ))
                continue
                
            # Parse host node definition
            if line.startswith('node') and '{' in line:
                node_name = line.split('node')[1].split('{')[0].strip()
                current_node = node_name
                node_props = {}
                nodes.append(VSDLNode(
                    name=node_name,
                    type='host',
                    properties=node_props
                ))
                continue
                
            # Parse network properties
            if current_network and 'addresses range is' in line:
                cidr = line.split('addresses range is')[1].strip().rstrip(';')
                for node in nodes:
                    if node.name == current_network:
                        node.properties['cidr'] = cidr
                        break
                continue
                
            # Parse node connections
            if current_network and 'is connected' in line:
                node_name = line.split('node')[1].split('is')[0].strip()
                connections.append(VSDLConnection(
                    source=current_network,
                    target=node_name
                ))
                continue
                
            # Parse IP address assignments
            if current_network and 'has IP' in line:
                parts = line.split('node')[1].split('has IP') if 'node' in line else line.split('has IP')
                node_name = parts[0].strip()
                ip = parts[1].strip().rstrip(';')
                
                # Update connection IP information
                for conn in connections:
                    if (conn.source == current_network and conn.target == node_name) or \
                       (conn.target == current_network and conn.source == node_name):
                        conn.ip_address = ip
                        break
                continue
                
            # Parse host properties
            if current_node and 'node OS is' in line:
                os_name = line.split('node OS is')[1].strip().strip('"').rstrip(';')
                for node in nodes:
                    if node.type == 'host' and node.name == current_node:
                        node.properties['os'] = os_name
                        break
                continue
                
            # Parse software installations
            if current_node and 'mounts software' in line:
                line = line.strip().rstrip(';')
                if 'version' in line:
                    # Handle software declaration with version
                    parts = line.split('mounts software')[1].split('version')
                    sw_name = parts[0].strip()
                    sw_version = parts[1].strip()
                else:
                    # Handle software declaration without version
                    sw_name = line.split('mounts software')[1].strip()
                    sw_version = "unknown"
                    
                for node in nodes:
                    if node.type == 'host' and node.name == current_node:
                        if 'software' not in node.properties:
                            node.properties['software'] = []
                        node.properties['software'].append({
                            'name': sw_name,
                            'version': sw_version
                        })
                        break
                
        return nodes, connections

    def build_topology_graph(self, nodes: List[VSDLNode], connections: List[VSDLConnection]) -> nx.Graph:
        """Build network topology graph
        
        Args:
            nodes: List of nodes
            connections: List of connections
            
        Returns:
            NetworkX graph object
        """
        G = nx.Graph()
        
        # Add nodes
        for node in nodes:
            # Ensure all nodes have type attribute
            G.add_node(node.name, type=node.type, properties=node.properties)
            
        # Add edges (ensure both endpoint nodes exist and have type attribute)
        for conn in connections:
            # If connection nodes don't exist, add them as network type nodes
            if conn.source not in G:
                G.add_node(conn.source, type='network', properties={'name': conn.source})
            if conn.target not in G:
                G.add_node(conn.target, type='network', properties={'name': conn.target})
                
            G.add_edge(conn.source, conn.target, ip=conn.ip_address)
            
        return G

    def normalize_cidr(self, cidr: str) -> str:
        """Normalize CIDR representation
        
        Args:
            cidr: CIDR string
            
        Returns:
            Normalized CIDR
        """
        try:
            net = ipaddress.ip_network(cidr.strip(), strict=False)
            return f"{net.network_address}/{net.prefixlen}"
        except ValueError:
            return cidr

    def calculate_network_similarity(self, net1: dict, net2: dict) -> float:
        """Calculate similarity between two networks
        
        Args:
            net1: First network's properties
            net2: Second network's properties
            
        Returns:
            Similarity score (0-1)
        """
        if 'cidr' not in net1 or 'cidr' not in net2:
            return 0.0
            
        try:
            cidr1 = ipaddress.ip_network(net1['cidr'], strict=False)
            cidr2 = ipaddress.ip_network(net2['cidr'], strict=False)
            
            # Exactly the same
            if cidr1 == cidr2:
                return 1.0
            # Same network address but different mask
            if cidr1.network_address == cidr2.network_address:
                return 0.9
            # Overlapping
            if cidr1.overlaps(cidr2):
                return 0.8
            return 0.0
        except ValueError:
            return 0.0

    def calculate_host_similarity(self, host1: dict, host2: dict) -> float:
        """Calculate similarity between two hosts
        
        Args:
            host1: First host's properties
            host2: Second host's properties
            
        Returns:
            Similarity score (0-1)
        """
        score = 0.0
        total = 0
        
        # Compare operating systems
        if 'os' in host1 and 'os' in host2:
            if host1['os'].lower() == host2['os'].lower():
                score += 1
            total += 1
            
        # Compare software
        sw1 = {f"{sw['name']}:{sw['version']}" for sw in host1.get('software', [])}
        sw2 = {f"{sw['name']}:{sw['version']}" for sw in host2.get('software', [])}
        
        if sw1 or sw2:
            common = len(sw1 & sw2)
            all_sw = len(sw1 | sw2)
            if all_sw > 0:
                score += common / all_sw
            total += 1
            
        return score / total if total > 0 else 0.0

    def calculate_software_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two software names
        
        Args:
            name1: First software name
            name2: Second software name
            
        Returns:
            Similarity score (0-1)
        """
        # Convert to lowercase and remove common suffixes
        def normalize_name(name: str) -> str:
            name = name.lower()
            suffixes = ['_runtime', '_server', '_webapp', '_agent', '_service', '_kit']
            for suffix in suffixes:
                if name.endswith(suffix):
                    name = name.rsplit(suffix, 1)[0]
            return name
            
        name1 = normalize_name(name1)
        name2 = normalize_name(name2)
        
        # Exact match
        if name1 == name2:
            return 1.0
            
        # One is substring of another
        if name1 in name2 or name2 in name1:
            return 0.8
            
        # Calculate Levenshtein distance similarity
        def levenshtein_similarity(s1: str, s2: str) -> float:
            if len(s1) < len(s2):
                s1, s2 = s2, s1
            if not s2:
                return 0.0
                
            previous_row = range(len(s2) + 1)
            for i, c1 in enumerate(s1):
                current_row = [i + 1]
                for j, c2 in enumerate(s2):
                    insertions = previous_row[j + 1] + 1
                    deletions = current_row[j] + 1
                    substitutions = previous_row[j] + (c1 != c2)
                    current_row.append(min(insertions, deletions, substitutions))
                previous_row = current_row
                
            # Normalize edit distance
            max_len = max(len(s1), len(s2))
            similarity = 1 - (previous_row[-1] / max_len)
            return similarity if similarity > 0.6 else 0.0
            
        return levenshtein_similarity(name1, name2)

    def calculate_software_similarity(self, G1: nx.Graph, G2: nx.Graph) -> float:
        """Calculate software configuration similarity, using more flexible matching strategy
        
        Args:
            G1: First network topology graph
            G2: Second network topology graph
            
        Returns:
            Similarity score (0-1)
        """
        # Get all host nodes
        hosts1 = [n for n, attr in G1.nodes(data=True) if attr['type'] == 'host']
        hosts2 = [n for n, attr in G2.nodes(data=True) if attr['type'] == 'host']
        
        if not hosts1 or not hosts2:
            return 0.0
            
        # Collect all software configurations
        sw_sets1 = []
        sw_sets2 = []
        
        for host in hosts1:
            sw_list = G1.nodes[host]['properties'].get('software', [])
            if sw_list:
                sw_sets1.append(sw_list)
                
        for host in hosts2:
            sw_list = G2.nodes[host]['properties'].get('software', [])
            if sw_list:
                sw_sets2.append(sw_list)
        
        if not sw_sets1 or not sw_sets2:
            return 0.0
            
        # Calculate best matches
        total_similarity = 0
        used_indices = set()
        
        for sw_list1 in sw_sets1:
            best_match = 0
            best_idx = -1
            
            for i, sw_list2 in enumerate(sw_sets2):
                if i in used_indices:
                    continue
                    
                # Calculate similarity between two software lists
                matches = 0
                max_matches = max(len(sw_list1), len(sw_list2))
                
                for sw1 in sw_list1:
                    best_sw_match = 0
                    for sw2 in sw_list2:
                        # Calculate software name similarity
                        name_similarity = self.calculate_software_name_similarity(sw1['name'], sw2['name'])
                        
                        # If names are similar, consider version
                        if name_similarity > 0:
                            if sw1['version'] == sw2['version'] or sw1['version'] == 'unknown' or sw2['version'] == 'unknown':
                                version_factor = 1.0
                            else:
                                # Different version but name matches, still give partial score
                                version_factor = 0.8
                                
                            similarity = name_similarity * version_factor
                            best_sw_match = max(best_sw_match, similarity)
                    
                    matches += best_sw_match
                
                similarity = matches / max_matches if max_matches > 0 else 0
                
                if similarity > best_match:
                    best_match = similarity
                    best_idx = i
            
            if best_match > 0:
                total_similarity += best_match
                if best_idx >= 0:
                    used_indices.add(best_idx)
        
        # Calculate average similarity
        max_sets = max(len(sw_sets1), len(sw_sets2))
        return total_similarity / max_sets if max_sets > 0 else 0.0

    def calculate_topology_similarity(self, G1: nx.Graph, G2: nx.Graph) -> dict:
        """Calculate similarity between two network topologies, focusing on structure rather than specific values
        
        Args:
            G1: First network topology graph
            G2: Second network topology graph
            
        Returns:
            Similarity report
        """
        report = {
            'topology_similarity': 0.0,
            'software_similarity': 0.0,
            'weighted_total': 0.0
        }
        
        # 1. Calculate topology structure similarity
        
        # Extract network and host nodes (ignore specific attributes, only look at types)
        networks1 = [n for n, attr in G1.nodes(data=True) if attr['type'] == 'network']
        networks2 = [n for n, attr in G2.nodes(data=True) if attr['type'] == 'network']
        hosts1 = [n for n, attr in G1.nodes(data=True) if attr['type'] == 'host']
        hosts2 = [n for n, attr in G2.nodes(data=True) if attr['type'] == 'host']
        
        # Calculate node type distribution similarity
        network_ratio = min(len(networks1), len(networks2)) / max(len(networks1), len(networks2)) if networks1 and networks2 else 0
        host_ratio = min(len(hosts1), len(hosts2)) / max(len(hosts1), len(hosts2)) if hosts1 and hosts2 else 0
        
        # Calculate connection relationship similarity
        def get_edge_type_signature(G, edge):
            n1_type = G.nodes[edge[0]]['type']
            n2_type = G.nodes[edge[1]]['type']
            return tuple(sorted([n1_type, n2_type]))
            
        edges1 = [get_edge_type_signature(G1, e) for e in G1.edges()]
        edges2 = [get_edge_type_signature(G2, e) for e in G2.edges()]
        
        edge_type_counts1 = defaultdict(int)
        edge_type_counts2 = defaultdict(int)
        
        for e in edges1:
            edge_type_counts1[e] += 1
        for e in edges2:
            edge_type_counts2[e] += 1
            
        # Calculate edge type distribution similarity
        edge_similarity = 0
        all_edge_types = set(edge_type_counts1.keys()) | set(edge_type_counts2.keys())
        
        if all_edge_types:
            matches = 0
            for edge_type in all_edge_types:
                count1 = edge_type_counts1[edge_type]
                count2 = edge_type_counts2[edge_type]
                matches += min(count1, count2)
            edge_similarity = matches / max(len(edges1), len(edges2)) if edges1 or edges2 else 1.0
        
        # Calculate combined topology similarity (node distribution 30%, connection relationships 70%)
        topology_similarity = (
            (network_ratio * 0.15 + host_ratio * 0.15) +  # Node type distribution 30%
            edge_similarity * 0.7                          # Connection relationships 70%
        )
        
        # 2. Calculate software configuration similarity
        software_similarity = self.calculate_software_similarity(G1, G2)
        
        # 3. Calculate weighted total score
        report['topology_similarity'] = topology_similarity * 100
        report['software_similarity'] = software_similarity * 100
        report['weighted_total'] = (
            topology_similarity * self.weights['topology'] +
            software_similarity * self.weights['software']
        ) * 100
        
        return report

    def compare_vsdl_files(self, vsdl1_content: str, vsdl2_content: str) -> dict:
        """Compare network topologies described in two VSDL files
        
        Args:
            vsdl1_content: First VSDL file content
            vsdl2_content: Second VSDL file content
            
        Returns:
            Comparison report
        """
        # Parse VSDL files
        nodes1, connections1 = self.parse_vsdl(vsdl1_content)
        nodes2, connections2 = self.parse_vsdl(vsdl2_content)
        
        # Build topology graphs
        G1 = self.build_topology_graph(nodes1, connections1)
        G2 = self.build_topology_graph(nodes2, connections2)
        
        # Calculate similarity
        return self.calculate_topology_similarity(G1, G2)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Compare network topology similarity between two VSDL files')
    parser.add_argument('vsdl1', help='Path to first VSDL file')
    parser.add_argument('vsdl2', help='Path to second VSDL file')
    
    args = parser.parse_args()
    
    # Read VSDL files
    with open(args.vsdl1, 'r', encoding='utf-8') as f:
        vsdl1_content = f.read()
    with open(args.vsdl2, 'r', encoding='utf-8') as f:
        vsdl2_content = f.read()
    
    # Run comparison
    comparer = VSDLNetworkComparer()
    report = comparer.compare_vsdl_files(vsdl1_content, vsdl2_content)
    
    # Output report
    print("\n=== VSDL Network Topology Comparison Report ===")
    print(f"\nTopology Structure Similarity: {report['topology_similarity']:.2f}%")
    print(f"Software Configuration Similarity: {report['software_similarity']:.2f}%")
    print(f"Weighted Overall Similarity: {report['weighted_total']:.2f}%")

if __name__ == '__main__':
    main() 