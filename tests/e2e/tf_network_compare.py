#!/usr/bin/env python3
import json
import subprocess
import os
from typing import Dict, List, Tuple, Set
import difflib
from dataclasses import dataclass
from pathlib import Path
import ipaddress
import networkx as nx
from collections import defaultdict

@dataclass
class NetworkEntity:
    """Data class for network entity"""
    type: str
    name: str
    properties: dict
    id: str = ""  # Resource ID

class TerraformNetworkComparer:
    def __init__(self, path1: str, path2: str):
        """Initialize comparer
        
        Args:
            path1: Path to first Terraform configuration directory
            path2: Path to second Terraform configuration directory
        """
        self.path1 = Path(path1)
        self.path2 = Path(path2)
        # Define entity weights
        self.weights = {
            'subnet': 0.5,    # Subnet weight increased to 50%
            'router': 0.3,    # Router 30%
            'port': 0.2       # Port 20%
        }
        # Define key properties to normalize
        self.key_properties = {
            'subnet': ['cidr', 'network_id', 'availability_zone'],
            'router': ['routes', 'next_hop_type'],
            'port': ['fixed_ips', 'security_groups']
        }
        
    def normalize_cidr(self, cidr: str) -> str:
        """Normalize CIDR representation
        
        Args:
            cidr: CIDR string
            
        Returns:
            Normalized CIDR
        """
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            return f"{net.network_address}/{net.prefixlen}"
        except ValueError:
            return cidr

    def build_entity_key(self, entity_type: str, props: dict) -> str:
        """Build unique identifier key for entity
        
        Args:
            entity_type: Entity type
            props: Property dictionary
            
        Returns:
            Unique identifier key
        """
        if entity_type == 'subnet':
            return f"subnet::{props.get('cidr', '')}::{props.get('network_id', '')}"
        elif entity_type == 'router':
            routes = props.get('routes', [])
            route_keys = [f"{r.get('destination', '')}::{r.get('next_hop_type', '')}" 
                         for r in routes]
            return f"router::{','.join(sorted(route_keys))}"
        else:  # port
            ips = props.get('fixed_ips', [])
            ip_keys = [str(ip.get('ip_address', '')) for ip in ips]
            return f"port::{','.join(sorted(ip_keys))}"

    def normalize_properties(self, entity_type: str, properties: dict) -> dict:
        """Normalize entity properties, ignoring non-critical attributes like names
        
        Args:
            entity_type: Entity type
            properties: Property dictionary
            
        Returns:
            Normalized property dictionary
        """
        normalized = {}
        for key in self.key_properties.get(entity_type, []):
            if key not in properties:
                continue
                
            value = properties[key]
            if key == 'cidr':
                normalized[key] = self.normalize_cidr(value)
            elif key == 'network_id':
                normalized[key] = value.lower().strip()
            elif key == 'routes':
                normalized[key] = sorted([
                    {
                        'destination': self.normalize_cidr(r.get('destination', '')),
                        'next_hop_type': r.get('next_hop_type', '').lower()
                    }
                    for r in value
                ], key=lambda x: x['destination'])
            elif key == 'fixed_ips':
                normalized[key] = sorted([
                    {
                        'ip_address': self.normalize_cidr(ip.get('ip_address', '')),
                        'subnet_id': ip.get('subnet_id', '').lower()
                    }
                    for ip in value
                ], key=lambda x: x['ip_address'])
            elif key == 'security_groups':
                normalized[key] = sorted([sg.lower() for sg in value])
            elif key == 'availability_zone':
                normalized[key] = value.split('-')[-1] if value else ''
            
        return normalized

    def build_topology_graph(self, entities: Dict[str, List[NetworkEntity]]) -> nx.Graph:
        """Build network topology graph with error handling
        
        Args:
            entities: Network entity dictionary
            
        Returns:
            NetworkX graph object
        """
        G = nx.Graph()
        
        # Add nodes
        for entity_type in ['subnet', 'router']:
            for entity in entities[entity_type]:
                try:
                    props = self.normalize_properties(entity_type, entity.properties)
                    node_id = entity.id or entity.name or f"{entity_type}-{len(G.nodes)}"
                    G.add_node(node_id, type=entity_type, properties=props)
                except Exception as e:
                    print(f"[ERROR] Failed to add node: {entity_type} {entity.name}, reason: {e}")
        
        # Add edges
        for port in entities['port']:
            try:
                props = port.properties
                fixed_ips = props.get('fixed_ips', [])
                if not fixed_ips:
                    continue
                
                for ip_info in fixed_ips:
                    subnet_id = ip_info.get('subnet_id')
                    if not subnet_id:
                        continue
                        
                    subnet_node = next(
                        (n for n, attr in G.nodes(data=True)
                         if attr['type'] == 'subnet' and 
                         attr['properties'].get('network_id') == subnet_id),
                        None
                    )
                    
                    if subnet_node:
                        port_id = port.id or port.name or f"port-{len(G.nodes)}"
                        port_props = self.normalize_properties('port', props)
                        if port_id not in G.nodes:
                            G.add_node(port_id, type='port', properties=port_props)
                        G.add_edge(subnet_node, port_id, type='port')
                    else:
                        print(f"[WARN] Port {port.name} could not find corresponding subnet (subnet_id={subnet_id})")
            except Exception as e:
                print(f"[ERROR] Failed to add edge: port {port.name}, reason: {e}")
        
        return G

    def calculate_graph_similarity(self, G1: nx.Graph, G2: nx.Graph) -> float:
        """Calculate similarity between two graphs, considering node type weights
        
        Args:
            G1: First graph
            G2: Second graph
            
        Returns:
            Similarity score (0-1)
        """
        # Quick pre-check
        if G1.number_of_nodes() != G2.number_of_nodes() or G1.number_of_edges() != G2.number_of_edges():
            return self._calculate_partial_similarity(G1, G2)
            
        if not nx.fast_could_be_isomorphic(G1, G2):
            return self._calculate_partial_similarity(G1, G2)
            
        # Check complete isomorphism
        def node_match(n1, n2):
            return (n1['type'] == n2['type'] and 
                   self.normalize_properties(n1['type'], n1['properties']) ==
                   self.normalize_properties(n2['type'], n2['properties']))
            
        def edge_match(e1, e2):
            return e1.get('type') == e2.get('type')
            
        if nx.is_isomorphic(G1, G2, node_match=node_match, edge_match=edge_match):
            return 1.0
            
        return self._calculate_partial_similarity(G1, G2)

    def _calculate_partial_similarity(self, G1: nx.Graph, G2: nx.Graph) -> float:
        """Calculate partial graph similarity
        
        Args:
            G1: First graph
            G2: Second graph
            
        Returns:
            Similarity score (0-1)
        """
        # Count nodes by type
        def count_nodes_by_type(G):
            counts = defaultdict(int)
            for n, attr in G.nodes(data=True):
                counts[attr['type']] += 1
            return counts
            
        counts1 = count_nodes_by_type(G1)
        counts2 = count_nodes_by_type(G2)
        
        # Calculate node match rate
        node_similarities = {}
        for node_type in ['subnet', 'router', 'port']:
            total = max(counts1[node_type], counts2[node_type])
            matched = min(counts1[node_type], counts2[node_type])
            node_similarities[node_type] = matched / total if total > 0 else 1.0
        
        # Calculate edge match rate
        edge_similarity = min(G1.number_of_edges(), G2.number_of_edges()) / max(G1.number_of_edges(), G2.number_of_edges()) if max(G1.number_of_edges(), G2.number_of_edges()) > 0 else 1.0
        
        # Calculate weighted total similarity
        weighted_similarity = sum(
            node_similarities[ntype] * weight 
            for ntype, weight in self.weights.items()
        )
        
        return weighted_similarity

    def run_comparison(self) -> dict:
        """Run complete comparison process
        
        Returns:
            Comparison result report
        """
        try:
            # Generate JSON files
            json1 = self.generate_plan_json(self.path1)
            json2 = self.generate_plan_json(self.path2)
            
            # Extract network entities
            entities1 = self.extract_network_entities(json1)
            entities2 = self.extract_network_entities(json2)
            
            # Build topology graphs
            graph1 = self.build_topology_graph(entities1)
            graph2 = self.build_topology_graph(entities2)
            
            # Calculate similarities
            entity_report = self.compare_entities(entities1, entities2)
            graph_similarity = self.calculate_graph_similarity(graph1, graph2)
            
            # Calculate weighted total score
            entity_similarity = sum(
                entity_report['summary'][et]['accuracy'] * weight
                for et, weight in self.weights.items()
            )
            
            # Final report
            report = {
                'entity_comparison': entity_report,
                'similarities': {
                    'entity_matching': entity_similarity * 100,
                    'graph_structure': graph_similarity * 100,
                    'weighted_total': (entity_similarity * 0.6 + graph_similarity * 0.4) * 100
                }
            }
            
            return report
            
        except Exception as e:
            print(f"[ERROR] Error during comparison process: {str(e)}")
            raise

    def generate_plan_json(self, tf_path: Path) -> Path:
        """Generate Terraform plan JSON file
        
        Args:
            tf_path: Terraform configuration directory path
            
        Returns:
            JSON file path
        """
        original_dir = os.getcwd()
        try:
            os.chdir(tf_path)
            
            # Run terraform init
            subprocess.run(['terraform', 'init'], check=True)
            
            # Generate plan file
            subprocess.run(['terraform', 'plan', '-out=plan.tfplan'], check=True)
            
            # Convert to JSON
            json_path = tf_path / 'plan.json'
            with open(json_path, 'w') as f:
                subprocess.run(['terraform', 'show', '-json', 'plan.tfplan'], 
                             check=True, stdout=f)
            
            return json_path
        finally:
            os.chdir(original_dir)

    def extract_network_entities(self, json_path: Path) -> Dict[str, List[NetworkEntity]]:
        """Extract network entities from JSON file
        
        Args:
            json_path: plan.json file path
            
        Returns:
            Dictionary of network entities by type
        """
        with open(json_path) as f:
            plan_data = json.load(f)

        entities = {
            'subnet': [],
            'router': [],
            'port': []
        }
        
        resources = plan_data.get('planned_values', {}).get('root_module', {}).get('resources', [])
        
        for resource in resources:
            if resource['type'] == 'openstack_networking_subnet_v2':
                entities['subnet'].append(NetworkEntity(
                    type='subnet',
                    name=resource['values'].get('name', ''),
                    properties={
                        'cidr': resource['values'].get('cidr', ''),
                        'network_id': resource['values'].get('network_id', '')
                    }
                ))
            elif resource['type'] == 'openstack_networking_router_v2':
                entities['router'].append(NetworkEntity(
                    type='router',
                    name=resource['values'].get('name', ''),
                    properties={
                        'routes': resource['values'].get('routes', [])
                    }
                ))
            elif resource['type'] == 'openstack_networking_port_v2':
                entities['port'].append(NetworkEntity(
                    type='port',
                    name=resource['values'].get('name', ''),
                    properties={
                        'fixed_ips': resource['values'].get('fixed_ips', [])
                    }
                ))
        
        return entities

    def compare_entities(self, entities1: Dict[str, List[NetworkEntity]], 
                        entities2: Dict[str, List[NetworkEntity]]) -> dict:
        """Compare two sets of network entities, using hash table to optimize matching process
        
        Args:
            entities1: First set of network entities
            entities2: Second set of network entities
            
        Returns:
            Comparison result report
        """
        report = {
            'summary': {},
            'details': {}
        }
        
        for entity_type in ['subnet', 'router', 'port']:
            # Build hash tables
            hash1 = defaultdict(int)
            hash2 = defaultdict(int)
            
            # Generate entity keys and count
            for e in entities1[entity_type]:
                norm_props = self.normalize_properties(entity_type, e.properties)
                key = self.build_entity_key(entity_type, norm_props)
                hash1[key] += 1
            
            for e in entities2[entity_type]:
                norm_props = self.normalize_properties(entity_type, e.properties)
                key = self.build_entity_key(entity_type, norm_props)
                hash2[key] += 1
            
            # Calculate exact matches
            exact_matches = 0
            for key, count1 in hash1.items():
                count2 = hash2.get(key, 0)
                exact_matches += min(count1, count2)
            
            # Calculate similarity for non-exact matches
            remaining1 = [(e, self.normalize_properties(entity_type, e.properties)) 
                         for e in entities1[entity_type]
                         if self.build_entity_key(entity_type, self.normalize_properties(entity_type, e.properties)) not in hash2]
            
            remaining2 = [(e, self.normalize_properties(entity_type, e.properties)) 
                         for e in entities2[entity_type]
                         if self.build_entity_key(entity_type, self.normalize_properties(entity_type, e.properties)) not in hash1]
            
            partial_matches = 0
            used_indices = set()
            
            for i, (e1, props1) in enumerate(remaining1):
                best_match_score = 0
                best_match_idx = -1
                
                for j, (e2, props2) in enumerate(remaining2):
                    if j in used_indices:
                        continue
                    
                    similarity = self.calculate_property_similarity(entity_type, props1, props2)
                    if similarity > best_match_score:
                        best_match_score = similarity
                        best_match_idx = j
                
                if best_match_score > 0.8:  # Similarity threshold
                    partial_matches += 1
                    used_indices.add(best_match_idx)
            
            total = max(len(entities1[entity_type]), len(entities2[entity_type]))
            # Ensure match rate doesn't exceed 100%
            matches = min(exact_matches + partial_matches, total)
            accuracy = matches / total if total > 0 else 1.0
            
            report['summary'][entity_type] = {
                'total_in_1': len(entities1[entity_type]),
                'total_in_2': len(entities2[entity_type]),
                'exact_matches': exact_matches,
                'partial_matches': partial_matches,
                'accuracy': accuracy
            }
            
        return report

    def calculate_property_similarity(self, entity_type: str, props1: dict, props2: dict) -> float:
        """Calculate similarity between two entity properties
        
        Args:
            entity_type: Entity type
            props1: First property set
            props2: Second property set
            
        Returns:
            Similarity score (0-1)
        """
        if entity_type == 'subnet':
            try:
                net1 = ipaddress.ip_network(props1.get('cidr', ''), strict=False)
                net2 = ipaddress.ip_network(props2.get('cidr', ''), strict=False)
                if net1 == net2:
                    return 1.0
                if net1.network_address == net2.network_address:
                    return 0.9
                if net1.overlaps(net2):
                    return 0.8
                return 0.0
            except ValueError:
                return 0.0
        elif entity_type == 'router':
            routes1 = props1.get('routes', [])
            routes2 = props2.get('routes', [])
            if not routes1 and not routes2:
                return 1.0
            if not routes1 or not routes2:
                return 0.0
            
            matched = 0
            total = max(len(routes1), len(routes2))
            for r1 in routes1:
                for r2 in routes2:
                    if (r1.get('destination') == r2.get('destination') and
                        r1.get('next_hop_type') == r2.get('next_hop_type')):
                        matched += 1
                        break
            return matched / total
        else:  # port
            ips1 = props1.get('fixed_ips', [])
            ips2 = props2.get('fixed_ips', [])
            if not ips1 and not ips2:
                return 1.0
            if not ips1 or not ips2:
                return 0.0
            
            matched = 0
            total = max(len(ips1), len(ips2))
            for ip1 in ips1:
                for ip2 in ips2:
                    try:
                        net1 = ipaddress.ip_network(ip1.get('ip_address', '').split('/')[0] + '/24', strict=False)
                        net2 = ipaddress.ip_network(ip2.get('ip_address', '').split('/')[0] + '/24', strict=False)
                        if net1.overlaps(net2):
                            matched += 1
                            break
                    except ValueError:
                        continue
            return matched / total

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Compare network topologies between two Terraform configurations')
    parser.add_argument('path1', help='Path to first Terraform configuration directory')
    parser.add_argument('path2', help='Path to second Terraform configuration directory')
    parser.add_argument('--output', '-o', help='Path to output JSON report file')
    
    args = parser.parse_args()
    
    comparer = TerraformNetworkComparer(args.path1, args.path2)
    report = comparer.run_comparison()
    
    # Format output
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    else:
        print("\n=== Network Topology Comparison Report ===")
        print("\nSimilarity Statistics:")
        print(f"  - Network Structure Similarity: {report['similarities']['graph_structure']:.2f}%")
        print(f"  - Configuration Match Similarity: {report['similarities']['entity_matching']:.2f}%")
        print(f"  - Weighted Overall Similarity: {report['similarities']['weighted_total']:.2f}%")
        
        print("\nResource Type Statistics:")
        for entity_type in ['subnet', 'router', 'port']:
            summary = report['entity_comparison']['summary'][entity_type]
            print(f"\n{entity_type.upper()}:")
            print(f"  - Total in Config 1: {summary['total_in_1']}")
            print(f"  - Total in Config 2: {summary['total_in_2']}")
            print(f"  - Exact Matches: {summary['exact_matches']}")
            print(f"  - Partial Matches: {summary['partial_matches']}")
            print(f"  - Total Match Rate: {summary['accuracy']*100:.2f}%")

if __name__ == '__main__':
    main() 