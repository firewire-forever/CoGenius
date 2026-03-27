#!/usr/bin/env python3
"""
修复 SSH 连接问题的方案
"""

import os
from pathlib import Path

def option1_use_floating_ip():
    """方案 1：为实例分配浮动 IP"""
    print("""
=== 方案 1：为实例分配浮动 IP ===

原理：
- 给 OpenStack 实例分配公网浮动 IP
- 让您的应用服务器可以直接通过 SSH 访问

步骤：
1. 在 OpenStack 控制台创建浮动 IP
2. 将浮动 IP 绑定到 Workstation 和 FileServer 实例
3. 修改 Ansible inventory 使用浮动 IP

命令示例：
openstack floating ip create public_network
openstack server add floating ip <instance_id> <floating_ip>

注意：需要确保您的 OpenStack 环境有可用的公网网络。
""")

def option2_ssh_proxy():
    """方案 2：通过堡垒机中转"""
    print("""
=== 方案 2：通过堡垒机中转 ===

原理：
- 在 OpenStack 环境中创建一个堡垒机（Bastion Host）
- 所有 SSH 连接先通过堡垒机，再转发到目标实例

适用场景：
- OpenStack 环境有公网 IP 的堡垒机
- 安全策略不允许直接访问私有网络

Ansible 配置示例：
ansible_host=<bastion_ip>
ansible_ssh_common_args='-o ProxyCommand="ssh -W %h:%p -i <bastion_key> ubuntu@<bastion_ip>"'
""")

def option3_openstack_direct():
    """方案 3：直接在 OpenStack 环境中运行"""
    print("""
=== 方案 3：直接在 OpenStack 环境中运行 ===

原理：
- 将您的 Flask 应用也部署到 OpenStack 环境中
- 这样应用和实例在同一网络，可以直接访问 SSH

适用场景：
- 生产环境部署
- 需要高可用性

部署方式：
1. 创建应用服务器实例
2. 部署 Flask 应用
3. 配置内部网络通信
""")

def option4_modify_ansible():
    """方案 4：修改 Ansible 执行方式"""
    print("""
=== 方案 4：修改 Ansible 执行方式 ===

原理：
- 在 OpenStack 控制节点上直接执行 Ansible
- 或者使用 OpenStack 的直接 SSH 功能

修改建议：
1. 将 Ansible 执行移到 OpenStack 控制节点
2. 使用正确的 SSH 密钥和路径

SSH 密钥检查：
""")

    # 检查 SSH 密钥文件
    key_paths = [
        '/home/ubuntu/.ssh/openstack_id_rsa',
        '/home/ubuntu/.ssh/openstack_id_rsa.pub'
    ]

    for path in key_paths:
        if Path(path).exists():
            print(f"✅ {path} 存在")
            # 检查权限
            stat = Path(path).stat()
            if path.endswith('.pub'):
                print(f"   权限: {oct(stat.st_mode)[-3:]}")
            else:
                if oct(stat.st_mode)[-3:] == '600':
                    print(f"   权限: {oct(stat.st_mode)[-3:]} ✅ (正确)")
                else:
                    print(f"   权限: {oct(stat.st_mode)[-3:]} ❌ (应该是 600)")
        else:
            print(f"❌ {path} 不存在")

def main():
    print("=== SSH 连接问题诊断和解决方案 ===\n")

    print("问题分析：")
    print("- 您的应用服务器 IP: 222.20.126.170:10125")
    print("- OpenStack 服务器 IP: 222.20.126.26:22")
    print("- 实例私有 IP: 172.16.1.100, 172.16.1.200")
    print("- 原因：应用服务器无法访问 OpenStack 私有网络\n")

    print("可选解决方案：\n")

    option1_use_floating_ip()
    print("\n" + "="*60 + "\n")

    option2_ssh_proxy()
    print("\n" + "="*60 + "\n")

    option3_openstack_direct()
    print("\n" + "="*60 + "\n")

    option4_modify_ansible()

    print("\n" + "="*60)
    print("推荐方案：")
    print("1. 如果需要快速测试 → 方案 4（检查 SSH 配置）")
    print("2. 如果需要长期运行 → 方案 1（浮动 IP）")
    print("3. 如果有安全限制 → 方案 2（堡垒机）")

if __name__ == "__main__":
    main()
