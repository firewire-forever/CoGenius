#!/usr/bin/env python3
"""
Data Analysis Script for CoGenius Experimental Results
This script analyzes the experiment results and generates statistics and visualizations.

Author: CoGenius Team
License: MIT
"""

import os
import re
import glob
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple
import json

# Try to import optional dependencies
try:
    import matplotlib.pyplot as plt
    import numpy as np
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("Warning: matplotlib not installed. Plots will not be generated.")


def parse_experiment_result(file_path: str) -> Dict:
    """
    Parse a single experiment result file.

    Returns:
        Dict with keys: pdf_name, task_id, timestamp, success, timing, scenario
    """
    result = {
        'pdf_name': '',
        'task_id': '',
        'timestamp': '',
        'success': False,
        'terraform_success': False,
        'ansible_success': False,
        'timing': {
            'end_to_end_latency': 0,
            'iac_build_time': 0,
            'pdf_extraction': 0,
            'vsdl_generation': 0,
            'vsdl_compilation': 0,
            'terraform': 0,
            'ansible': 0
        },
        'scenario': {
            'name': '',
            'duration': 0,
            'networks': 0,
            'nodes': 0,
            'vulnerabilities': 0
        }
    }

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract PDF name
    match = re.search(r'PDF文件:\s*(.+)\.pdf', content)
    if match:
        result['pdf_name'] = match.group(1) + '.pdf'

    # Extract task ID
    match = re.search(r'任务ID:\s*(\S+)', content)
    if match:
        result['task_id'] = match.group(1)

    # Extract timestamp
    match = re.search(r'记录时间:\s*(.+)', content)
    if match:
        result['timestamp'] = match.group(1).strip()

    # Extract deployment status
    if '彻底成功部署: ✅ 是' in content:
        result['success'] = True

    if 'Terraform 部署:  ✅ 成功' in content:
        result['terraform_success'] = True

    if 'Ansible 配置:    ✅ 成功' in content:
        result['ansible_success'] = True

    # Extract timing
    match = re.search(r'端到端延迟:\s*([\d.]+)\s*秒', content)
    if match:
        result['timing']['end_to_end_latency'] = float(match.group(1))

    match = re.search(r'IAC平均构建时间:\s*([\d.]+)\s*秒', content)
    if match:
        result['timing']['iac_build_time'] = float(match.group(1))

    match = re.search(r'1\.\s*PDF提取:\s*([\d.]+)\s*秒', content)
    if match:
        result['timing']['pdf_extraction'] = float(match.group(1))

    match = re.search(r'2\.\s*VSDL生成:\s*([\d.]+)\s*秒', content)
    if match:
        result['timing']['vsdl_generation'] = float(match.group(1))

    match = re.search(r'3\.\s*VSDL编译:\s*([\d.]+)\s*秒', content)
    if match:
        result['timing']['vsdl_compilation'] = float(match.group(1))

    match = re.search(r'4\.\s*Terraform部署:\s*([\d.]+)\s*秒', content)
    if match:
        result['timing']['terraform'] = float(match.group(1))

    match = re.search(r'5\.\s*Ansible配置:\s*([\d.]+)\s*秒', content)
    if match:
        result['timing']['ansible'] = float(match.group(1))

    # Extract scenario info
    match = re.search(r'场景名称:\s*(\S+)', content)
    if match:
        result['scenario']['name'] = match.group(1)

    match = re.search(r'场景时长:\s*(\d+)\s*TTU', content)
    if match:
        result['scenario']['duration'] = int(match.group(1))

    match = re.search(r'网络数量:\s*(\d+)', content)
    if match:
        result['scenario']['networks'] = int(match.group(1))

    match = re.search(r'节点数量:\s*(\d+)', content)
    if match:
        result['scenario']['nodes'] = int(match.group(1))

    match = re.search(r'漏洞数量:\s*(\d+)', content)
    if match:
        result['scenario']['vulnerabilities'] = int(match.group(1))

    return result


def analyze_all_results(data_dir: str) -> Tuple[List[Dict], Dict]:
    """
    Analyze all experiment results in the directory.

    Returns:
        Tuple of (list of all results, summary statistics)
    """
    results = []
    pattern = os.path.join(data_dir, '*exresults.txt')

    for file_path in glob.glob(pattern):
        result = parse_experiment_result(file_path)
        results.append(result)

    # Calculate summary statistics
    summary = {
        'total_experiments': len(results),
        'successful_deployments': sum(1 for r in results if r['success']),
        'partial_success': sum(1 for r in results if r['terraform_success'] and not r['ansible_success']),
        'failed_deployments': sum(1 for r in results if not r['terraform_success']),
        'avg_end_to_end_latency': 0,
        'avg_iac_build_time': 0,
        'avg_vsdl_generation': 0,
        'total_networks': 0,
        'total_nodes': 0,
        'total_vulnerabilities': 0,
        'by_year': defaultdict(int)
    }

    if results:
        summary['avg_end_to_end_latency'] = sum(r['timing']['end_to_end_latency'] for r in results) / len(results)
        summary['avg_iac_build_time'] = sum(r['timing']['iac_build_time'] for r in results) / len(results)
        summary['avg_vsdl_generation'] = sum(r['timing']['vsdl_generation'] for r in results) / len(results)
        summary['total_networks'] = sum(r['scenario']['networks'] for r in results)
        summary['total_nodes'] = sum(r['scenario']['nodes'] for r in results)
        summary['total_vulnerabilities'] = sum(r['scenario']['vulnerabilities'] for r in results)

        # Extract year from PDF name
        for r in results:
            match = re.match(r'(\d{4})_', r['pdf_name'])
            if match:
                summary['by_year'][match.group(1)] += 1

    return results, summary


def print_summary(summary: Dict):
    """Print summary statistics to console."""
    print("=" * 70)
    print("COGENIUS EXPERIMENTAL RESULTS SUMMARY")
    print("=" * 70)
    print()

    print("DEPLOYMENT STATISTICS")
    print("-" * 40)
    print(f"Total experiments:      {summary['total_experiments']}")
    print(f"Successful deployments: {summary['successful_deployments']} ({100*summary['successful_deployments']/max(1,summary['total_experiments']):.1f}%)")
    print(f"Partial success:        {summary['partial_success']}")
    print(f"Failed deployments:     {summary['failed_deployments']}")
    print()

    print("TIME METRICS (seconds)")
    print("-" * 40)
    print(f"Avg end-to-end latency: {summary['avg_end_to_end_latency']:.2f}s ({summary['avg_end_to_end_latency']/60:.2f} min)")
    print(f"Avg IAC build time:      {summary['avg_iac_build_time']:.2f}s ({summary['avg_iac_build_time']/60:.2f} min)")
    print(f"Avg VSDL generation:     {summary['avg_vsdl_generation']:.2f}s")
    print()

    print("SCENARIO STATISTICS")
    print("-" * 40)
    print(f"Total networks:        {summary['total_networks']}")
    print(f"Total nodes:           {summary['total_nodes']}")
    print(f"Total vulnerabilities: {summary['total_vulnerabilities']}")
    print()

    print("BY YEAR")
    print("-" * 40)
    for year in sorted(summary['by_year'].keys()):
        print(f"  {year}: {summary['by_year'][year]} experiments")
    print()


def generate_plots(results: List[Dict], output_dir: str):
    """Generate visualization plots."""
    if not HAS_MATPLOTLIB:
        print("Skipping plot generation (matplotlib not available)")
        return

    # Set up the plots
    plt.style.use('seaborn-v0_8-whitegrid')

    # Plot 1: Time metrics distribution
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # End-to-end latency distribution
    latencies = [r['timing']['end_to_end_latency'] / 60 for r in results]  # Convert to minutes
    axes[0, 0].hist(latencies, bins=10, color='steelblue', edgecolor='black', alpha=0.7)
    axes[0, 0].set_xlabel('End-to-End Latency (minutes)')
    axes[0, 0].set_ylabel('Count')
    axes[0, 0].set_title('Distribution of End-to-End Latency')

    # IAC build time distribution
    iac_times = [r['timing']['iac_build_time'] / 60 for r in results]
    axes[0, 1].hist(iac_times, bins=10, color='coral', edgecolor='black', alpha=0.7)
    axes[0, 1].set_xlabel('IAC Build Time (minutes)')
    axes[0, 1].set_ylabel('Count')
    axes[0, 1].set_title('Distribution of IAC Build Time')

    # Stage breakdown
    stages = ['PDF\nExtraction', 'VSDL\nGeneration', 'VSDL\nCompilation', 'Terraform\nDeployment', 'Ansible\nConfiguration']
    avg_times = [
        sum(r['timing']['pdf_extraction'] for r in results) / len(results),
        sum(r['timing']['vsdl_generation'] for r in results) / len(results),
        sum(r['timing']['vsdl_compilation'] for r in results) / len(results),
        sum(r['timing']['terraform'] for r in results) / len(results),
        sum(r['timing']['ansible'] for r in results) / len(results)
    ]
    bars = axes[1, 0].bar(stages, avg_times, color=['#2ecc71', '#3498db', '#9b59b6', '#e74c3c', '#f39c12'])
    axes[1, 0].set_ylabel('Time (seconds)')
    axes[1, 0].set_title('Average Time by Stage')
    axes[1, 0].tick_params(axis='x', rotation=0)

    # Deployment success rate
    success_counts = [
        sum(1 for r in results if r['success']),
        sum(1 for r in results if r['terraform_success'] and not r['ansible_success']),
        sum(1 for r in results if not r['terraform_success'])
    ]
    labels = ['Success', 'Partial', 'Failed']
    colors = ['#2ecc71', '#f39c12', '#e74c3c']
    axes[1, 1].pie(success_counts, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    axes[1, 1].set_title('Deployment Success Rate')

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'experiment_statistics.png'), dpi=150, bbox_inches='tight')
    print(f"Saved plot to: {os.path.join(output_dir, 'experiment_statistics.png')}")

    plt.close()


def export_json(results: List[Dict], summary: Dict, output_path: str):
    """Export results to JSON format."""
    output = {
        'summary': {
            'total_experiments': summary['total_experiments'],
            'successful_deployments': summary['successful_deployments'],
            'success_rate': summary['successful_deployments'] / max(1, summary['total_experiments']),
            'avg_end_to_end_latency_seconds': round(summary['avg_end_to_end_latency'], 2),
            'avg_iac_build_time_seconds': round(summary['avg_iac_build_time'], 2),
            'total_networks': summary['total_networks'],
            'total_nodes': summary['total_nodes'],
            'total_vulnerabilities': summary['total_vulnerabilities']
        },
        'experiments': results
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved JSON to: {output_path}")


def main():
    """Main entry point."""
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # The data directory is at the same level as the code directory
    doi_dir = os.path.dirname(script_dir)
    data_dir = os.path.join(doi_dir, 'data', 'experiment_results')
    output_dir = doi_dir

    print(f"Analyzing results from: {data_dir}")
    print()

    # Analyze results
    results, summary = analyze_all_results(data_dir)

    # Print summary
    print_summary(summary)

    # Generate plots
    generate_plots(results, output_dir)

    # Export JSON
    export_json(results, summary, os.path.join(output_dir, 'experiment_data.json'))

    print("=" * 70)
    print("Analysis complete!")
    print("=" * 70)


if __name__ == '__main__':
    main()