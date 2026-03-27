#!/usr/bin/env python3
import os
import yaml
from typing import List, Dict, Set, Tuple
from dataclasses import dataclass
import re

@dataclass
class Software:
    name: str
    version: str = "unknown"
    type: str = "unknown"  # apt, pip, archive, etc.

class PlaybookAnalyzer:
    def __init__(self):
        # Software name normalization mapping
        self.software_aliases = {
            'openjdk': 'java',
            'java': 'java',
            'logstash': 'logstash',
            'log4j': 'log4j',
            'apache-log4j': 'log4j',
            'tomcat': 'tomcat',
            'apache-tomcat': 'tomcat',
            'ldap': 'ldap',
            'jndi': 'jndi'
        }
        
        # Version extraction regex patterns
        self.version_patterns = [
            r'[\-_](\d+\.\d+\.\d+(?:\-\w+)?)',  # Match patterns like 2.17.1 or 2.17.1-bin
            r'[\-_](\d+\.\d+)',                  # Match patterns like 2.17
            r'[\-_](\d+)',                       # Match single number
        ]

    def normalize_software_name(self, name: str) -> str:
        """Normalize software name"""
        name = name.lower()
        # Remove common suffixes
        name = re.sub(r'[-_](bin|src|aarch64|arm64|x64|x86|linux)', '', name)
        
        # Find matching standard name
        for alias, standard_name in self.software_aliases.items():
            if alias in name:
                return standard_name
        return name

    def extract_version(self, text: str) -> str:
        """Extract version number from text"""
        for pattern in self.version_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return "unknown"

    def extract_software_from_apt(self, task: dict) -> List[Software]:
        """Extract software information from apt task"""
        result = []
        if 'name' in task['apt']:
            names = task['apt']['name']
            if isinstance(names, str):
                names = [names]
            for name in names:
                result.append(Software(
                    name=self.normalize_software_name(name),
                    version=self.extract_version(name),
                    type='apt'
                ))
        return result

    def extract_software_from_get_url(self, task: dict) -> List[Software]:
        """Extract software information from get_url task"""
        result = []
        if 'url' in task['get_url']:
            url = task['get_url']['url']
            # Extract software name and version from URL
            name = url.split('/')[-1]
            normalized_name = self.normalize_software_name(name)
            version = self.extract_version(url)
            result.append(Software(
                name=normalized_name,
                version=version,
                type='archive'
            ))
        return result

    def analyze_playbook(self, playbook_path: str) -> List[Software]:
        """Analyze a single playbook file"""
        with open(playbook_path, 'r', encoding='utf-8') as f:
            try:
                content = yaml.safe_load(f)
                if not content:
                    return []
                    
                software_list = []
                for play in content:
                    if 'tasks' not in play:
                        continue
                        
                    for task in play['tasks']:
                        if 'apt' in task:
                            software_list.extend(self.extract_software_from_apt(task))
                        elif 'get_url' in task:
                            software_list.extend(self.extract_software_from_get_url(task))
                            
                return software_list
            except yaml.YAMLError:
                print(f"Error parsing YAML file: {playbook_path}")
                return []

    def analyze_directory(self, directory_path: str) -> List[Software]:
        """Analyze all playbook files in a directory"""
        all_software = []
        for filename in os.listdir(directory_path):
            if filename.endswith('.yml') and 'playbook' in filename.lower():
                full_path = os.path.join(directory_path, filename)
                all_software.extend(self.analyze_playbook(full_path))
        return all_software

    def calculate_software_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two software names"""
        # Normalize names
        name1 = self.normalize_software_name(name1)
        name2 = self.normalize_software_name(name2)
        
        # Exact match
        if name1 == name2:
            return 1.0
            
        # One is substring of another
        if name1 in name2 or name2 in name1:
            return 0.8
            
        # Levenshtein distance similarity
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

    def calculate_version_similarity(self, ver1: str, ver2: str) -> float:
        """Calculate version number similarity"""
        if ver1 == ver2:
            return 1.0
        if ver1 == "unknown" or ver2 == "unknown":
            return 0.8
            
        # Extract main parts of version numbers
        def get_version_parts(version: str) -> List[int]:
            parts = re.findall(r'\d+', version)
            return [int(p) for p in parts[:3]]  # Compare only up to 3 version parts
            
        try:
            parts1 = get_version_parts(ver1)
            parts2 = get_version_parts(ver2)
            
            # Pad version parts
            while len(parts1) < 3:
                parts1.append(0)
            while len(parts2) < 3:
                parts2.append(0)
                
            # Calculate version differences
            weights = [0.5, 0.3, 0.2]  # Major version has higher weight
            similarity = 0
            for i in range(3):
                if parts1[i] == parts2[i]:
                    similarity += weights[i]
                elif abs(parts1[i] - parts2[i]) == 1:
                    similarity += weights[i] * 0.5
                    
            return similarity
        except:
            return 0.5  # Return medium similarity when version parsing fails

    def calculate_similarity(self, software_list1: List[Software], software_list2: List[Software]) -> dict:
        """Calculate similarity between two software lists"""
        if not software_list1 or not software_list2:
            return {
                'similarity': 0.0,
                'matched_pairs': [],
                'unmatched_software1': software_list1,
                'unmatched_software2': software_list2
            }
            
        # Calculate similarity for each software pair
        similarity_matrix = []
        for sw1 in software_list1:
            row = []
            for sw2 in software_list2:
                name_similarity = self.calculate_software_name_similarity(sw1.name, sw2.name)
                if name_similarity > 0:
                    version_similarity = self.calculate_version_similarity(sw1.version, sw2.version)
                    # Name weight 70%, version weight 30%
                    similarity = name_similarity * 0.7 + version_similarity * 0.3
                else:
                    similarity = 0
                row.append(similarity)
            similarity_matrix.append(row)
            
        # Use greedy algorithm to find best matches
        matched_pairs = []
        unmatched_software1 = list(software_list1)
        unmatched_software2 = list(software_list2)
        
        while similarity_matrix and max(map(max, similarity_matrix)) > 0.6:  # Only match software with similarity > 0.6
            # Find maximum similarity
            max_similarity = 0
            max_i = 0
            max_j = 0
            for i in range(len(similarity_matrix)):
                for j in range(len(similarity_matrix[i])):
                    if similarity_matrix[i][j] > max_similarity:
                        max_similarity = similarity_matrix[i][j]
                        max_i = i
                        max_j = j
                        
            # Add matched pair
            sw1 = unmatched_software1[max_i]
            sw2 = unmatched_software2[max_j]
            matched_pairs.append((sw1, sw2, max_similarity))
            
            # Remove matched software
            del unmatched_software1[max_i]
            del unmatched_software2[max_j]
            del similarity_matrix[max_i]
            for row in similarity_matrix:
                if len(row) > max_j:
                    del row[max_j]
                    
        # Calculate overall similarity
        if matched_pairs:
            total_similarity = sum(sim for _, _, sim in matched_pairs) / max(len(software_list1), len(software_list2))
        else:
            total_similarity = 0
            
        return {
            'similarity': total_similarity,
            'matched_pairs': matched_pairs,
            'unmatched_software1': unmatched_software1,
            'unmatched_software2': unmatched_software2
        }

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Compare software configurations between two Ansible playbook directories')
    parser.add_argument('dir1', help='Path to first playbook directory')
    parser.add_argument('dir2', help='Path to second playbook directory')
    
    args = parser.parse_args()
    
    analyzer = PlaybookAnalyzer()
    
    # Analyze both directories
    software_list1 = analyzer.analyze_directory(args.dir1)
    software_list2 = analyzer.analyze_directory(args.dir2)
    
    # Calculate similarity
    result = analyzer.calculate_similarity(software_list1, software_list2)
    
    # Output report
    print("\n=== Playbook Software Configuration Comparison Report ===")
    print(f"\nOverall Similarity: {result['similarity']*100:.2f}%")
    
    print("\nMatched Software Pairs:")
    for sw1, sw2, sim in result['matched_pairs']:
        print(f"- {sw1.name} ({sw1.version}) <-> {sw2.name} ({sw2.version}): {sim*100:.2f}%")
    
    if result['unmatched_software1']:
        print("\nUnmatched Software in Directory 1:")
        for sw in result['unmatched_software1']:
            print(f"- {sw.name} ({sw.version})")
    
    if result['unmatched_software2']:
        print("\nUnmatched Software in Directory 2:")
        for sw in result['unmatched_software2']:
            print(f"- {sw.name} ({sw.version})")

if __name__ == '__main__':
    main() 