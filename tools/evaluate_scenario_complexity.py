#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
漏洞复现场景复杂度评估工具

根据 JSON 场景定义文件，自动评估场景复杂度等级（小/中/大）

复杂度得分 = 网络维度分 + 攻击阶段分 + 节点规模分 + 工具/漏洞分 + 技术深度分
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any


def count_nodes_in_network(network_data: Dict) -> int:
    """统计单个 network 中的节点数量"""
    nodes_list = network_data.get('nodes', [])
    count = 0
    for node_entry in nodes_list:
        if isinstance(node_entry, dict):
            count += len(node_entry)
    return count


def count_tools_and_vulns(network_data: Dict) -> int:
    """统计工具和漏洞数量"""
    tools_count = len(network_data.get('tools', []))
    vulns_count = len(network_data.get('vul_id', []))
    exploits_count = len(network_data.get('exploits', []))
    return tools_count + vulns_count + exploits_count


def has_technical_depth(network_data: Dict) -> int:
    """
    评估技术深度
    1 分：基础利用
    2 分：含 C2 或持久化
    3 分：含横向移动 + 多阶段攻击
    """
    score = 1  # 基础分

    # 将数据转为字符串进行关键词匹配
    text_content = json.dumps(network_data, ensure_ascii=False).lower()

    # C2 通信检测
    c2_keywords = ['command & control', 'c2', 'c&c', 'websocket', 'socket.io', '心跳']
    has_c2 = any(kw in text_content for kw in c2_keywords)

    # 持久化检测
    persistence_keywords = ['persist', '注册表', '开机启动', 'service', 'daemon', 'cron']
    has_persistence = any(kw in text_content for kw in persistence_keywords)

    # 横向移动检测
    lateral_keywords = ['lateral', '横向移动', 'mimikatz', 'credential', '凭证', 'psexec', 'atexec', 'wmi']
    has_lateral = any(kw in text_content for kw in lateral_keywords)

    # 反检测技术
    evasion_keywords = ['obfusc', '反虚拟机', 'anti-vm', 'base64', '编码', '混淆']
    has_evasion = any(kw in text_content for kw in evasion_keywords)

    # 多阶段攻击
    multi_stage_keywords = ['dropper', 'downloader', '第二阶段', 'payload', 'rat']
    has_multi_stage = any(kw in text_content for kw in multi_stage_keywords)

    if has_c2 or has_persistence:
        score = 2
    if has_lateral and (has_c2 or has_persistence):
        score = 3
    if has_multi_stage and has_evasion:
        score = max(score, 3)

    return score


def evaluate_complexity(scenario_data: List[Dict]) -> Dict[str, Any]:
    """
    评估场景复杂度

    Args:
        scenario_data: JSON 解析后的场景数据

    Returns:
        包含各维度得分和最终等级的字典
    """
    result = {
        'network_score': 0,
        'steps_score': 0,
        'nodes_score': 0,
        'tools_score': 0,
        'depth_score': 0,
        'total_score': 0,
        'level': '未知',
        'details': {}
    }

    # 1. 网络维度评分 (1-3 分)
    scenario_info = scenario_data[0].get('scenario', {})
    num_networks = len(scenario_info.get('networks', []))
    result['network_score'] = min(3, num_networks)
    result['details']['num_networks'] = num_networks

    # 2. 攻击阶段评分 (1-3 分)
    steps_all = scenario_info.get('steps_all', [])
    num_steps = len(steps_all)
    if num_steps <= 3:
        result['steps_score'] = 1
    elif num_steps <= 5:
        result['steps_score'] = 2
    else:
        result['steps_score'] = 3
    result['details']['num_steps'] = num_steps
    result['details']['steps'] = steps_all

    # 3. 节点规模评分 (1-3 分)
    total_nodes = 0
    for item in scenario_data:
        if 'nodes' in item:
            total_nodes += count_nodes_in_network(item)

    if total_nodes <= 2:
        result['nodes_score'] = 1
    elif total_nodes <= 4:
        result['nodes_score'] = 2
    else:
        result['nodes_score'] = 3
    result['details']['total_nodes'] = total_nodes

    # 4. 工具/漏洞评分 (1-3 分)
    total_tools_vulns = 0
    for item in scenario_data:
        total_tools_vulns += count_tools_and_vulns(item)

    if total_tools_vulns <= 2:
        result['tools_score'] = 1
    elif total_tools_vulns <= 4:
        result['tools_score'] = 2
    else:
        result['tools_score'] = 3
    result['details']['total_tools_vulns'] = total_tools_vulns

    # 5. 技术深度评分 (1-3 分)
    # 取所有 network 的平均技术深度
    depth_scores = []
    for item in scenario_data:
        if 'network_name' in item or 'steps' in item:
            depth_scores.append(has_technical_depth(item))

    if depth_scores:
        avg_depth = sum(depth_scores) / len(depth_scores)
        result['depth_score'] = round(avg_depth)
    else:
        result['depth_score'] = 1
    result['details']['depth_breakdown'] = depth_scores

    # 计算总分
    result['total_score'] = (
        result['network_score'] +
        result['steps_score'] +
        result['nodes_score'] +
        result['tools_score'] +
        result['depth_score']
    )

    # 确定等级
    if result['total_score'] <= 7:
        result['level'] = '小'
    elif result['total_score'] <= 11:
        result['level'] = '中'
    else:
        result['level'] = '大'

    return result


def evaluate_single_file(file_path: str) -> Dict[str, Any]:
    """评估单个 JSON 文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    result = evaluate_complexity(data)
    result['file'] = os.path.basename(file_path)
    return result


def evaluate_directory(dir_path: str) -> List[Dict[str, Any]]:
    """评估目录下所有 JSON 文件"""
    results = []
    dir_path = Path(dir_path)

    for json_file in sorted(dir_path.glob('*.json')):
        try:
            result = evaluate_single_file(str(json_file))
            results.append(result)
        except Exception as e:
            results.append({
                'file': json_file.name,
                'error': str(e),
                'total_score': -1,
                'level': '错误'
            })

    return results


def print_result(result: Dict[str, Any]) -> None:
    """打印单个评估结果"""
    if 'error' in result:
        print(f"❌ {result['file']}: 评估失败 - {result['error']}")
        return

    print(f"\n{'='*60}")
    print(f"文件：{result['file']}")
    print(f"复杂度等级：【{result['level']}】 总分：{result['total_score']}")
    print(f"-" * 40)
    print(f"  网络维度 ({result['details']['num_networks']}个网络):     {result['network_score']}分")
    print(f"  攻击阶段 ({result['details']['num_steps']}个步骤):     {result['steps_score']}分")
    print(f"  节点规模 ({result['details']['total_nodes']}个节点):     {result['nodes_score']}分")
    print(f"  工具/漏洞 ({result['details']['total_tools_vulns']}个):   {result['tools_score']}分")
    print(f"  技术深度:                       {result['depth_score']}分")
    print(f"  攻击步骤：{', '.join(result['details']['steps'][:5])}...")


def print_summary(results: List[Dict[str, Any]]) -> None:
    """打印汇总统计"""
    print(f"\n{'='*60}")
    print("汇总统计")
    print(f"{'='*60}")

    total = len([r for r in results if 'error' not in r])
    if total == 0:
        print("无有效评估结果")
        return

    levels = {'小': 0, '中': 0, '大': 0}
    scores = []

    for r in results:
        if 'error' not in r:
            levels[r['level']] += 1
            scores.append(r['total_score'])

    print(f"有效场景数：{total}")
    print(f"小复杂度：{levels['小']} 个")
    print(f"中复杂度：{levels['中']} 个")
    print(f"大复杂度：{levels['大']} 个")

    if scores:
        avg_score = sum(scores) / len(scores)
        print(f"平均得分：{avg_score:.2f}")
        print(f"最高分：{max(scores)}")
        print(f"最低分：{min(scores)}")

    # 按复杂度分组输出
    print(f"\n{'='*60}")
    print("按复杂度分组")
    print(f"{'='*60}")

    for level in ['小', '中', '大']:
        items = [r for r in results if r.get('level') == level]
        if items:
            print(f"\n【{level}】复杂度 ({len(items)}个):")
            for item in items:
                print(f"  - {item['file']} (得分：{item['total_score']})")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='漏洞复现场景复杂度评估工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python evaluate_scenario_complexity.py ansible/playbooks/out/
  python evaluate_scenario_complexity.py ansible/playbooks/out/2020_JhoneRAT.json
  python evaluate_scenario_complexity.py --output results.csv ansible/playbooks/out/
        """
    )

    parser.add_argument(
        'path',
        help='JSON 文件或目录路径'
    )

    parser.add_argument(
        '--output', '-o',
        help='输出 CSV 文件路径（可选）'
    )

    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='静默模式，只输出 CSV'
    )

    args = parser.parse_args()

    target_path = Path(args.path)

    if not target_path.exists():
        print(f"错误：路径不存在 - {target_path}")
        return

    # 评估
    if target_path.is_file():
        results = [evaluate_single_file(str(target_path))]
    else:
        results = evaluate_directory(str(target_path))

    # 输出结果
    if not args.quiet:
        for result in results:
            print_result(result)
        print_summary(results)

    # 输出 CSV
    if args.output:
        import csv
        with open(args.output, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['文件名', '复杂度等级', '总分', '网络分', '阶段分', '节点分', '工具分', '深度分', '网络数', '步骤数', '节点数', '工具漏洞数'])

            for r in results:
                if 'error' not in r:
                    writer.writerow([
                        r['file'],
                        r['level'],
                        r['total_score'],
                        r['network_score'],
                        r['steps_score'],
                        r['nodes_score'],
                        r['tools_score'],
                        r['depth_score'],
                        r['details'].get('num_networks', ''),
                        r['details'].get('num_steps', ''),
                        r['details'].get('total_nodes', ''),
                        r['details'].get('total_tools_vulns', '')
                    ])

        if not args.quiet:
            print(f"\nCSV 结果已保存到：{args.output}")


if __name__ == '__main__':
    main()
