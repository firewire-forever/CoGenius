#!/usr/bin/env python3
"""
修复 SSH 私钥配置问题
"""

import os
from dotenv import load_dotenv

def fix_ssh_key_config():
    """修复 SSH 私钥配置"""

    # 加载 .env 文件
    env_path = '.env'
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"✅ 已加载 .env 文件: {env_path}")
    else:
        print(f"❌ .env 文件不存在: {env_path}")
        return False

    # 获取当前配置
    ssh_pubkey = os.getenv('SSH_PUBKEY_PATH')
    ssh_privkey = os.getenv('SSH_PRIVATE_KEY_PATH')

    print(f"\n当前配置:")
    print(f"SSH_PUBKEY_PATH: '{ssh_pubkey}'")
    print(f"SSH_PRIVATE_KEY_PATH: '{ssh_privkey}'")

    # 检查 SSH 私钥配置
    if ssh_privkey and '=' in ssh_privkey:
        print(f"\n❌ 发现 SSH 私钥配置问题")
        print(f"   当前值: {ssh_privkey}")
        print(f"   这看起来像是环境变量名而不是实际路径")

        # 修复为正确的路径
        correct_privkey = '/home/ubuntu/.ssh/openstack_id_rsa'

        # 备份原文件
        backup_path = '.env.backup.ssh_fix'
        with open(env_path, 'r') as f:
            original_content = f.read()

        with open(backup_path, 'w') as f:
            f.write(original_content)
        print(f"✅ 已备份原文件到: {backup_path}")

        # 修复配置
        fixed_content = original_content.replace(
            f'SSH_PRIVATE_KEY_PATH={ssh_privkey}',
            f'SSH_PRIVATE_KEY_PATH={correct_privkey}'
        )

        with open(env_path, 'w') as f:
            f.write(fixed_content)

        print(f"✅ 已修复 SSH 私钥配置")
        print(f"   新值: SSH_PRIVATE_KEY_PATH={correct_privkey}")

        # 验证修复
        with open('.env', 'r') as f:
            fixed_env = f.read()
        if f'SSH_PRIVATE_KEY_PATH={correct_privkey}' in fixed_env:
            print(f"✅ 修复验证成功")
            return True
        else:
            print(f"❌ 修复验证失败")
            return False

    else:
        print(f"\n✅ SSH 私钥配置看起来正常")
        return True

def verify_ssh_files():
    """验证 SSH 密钥文件"""
    print(f"\n=== 验证 SSH 密钥文件 ===")

    ssh_pubkey_path = '/home/ubuntu/.ssh/openstack_id_rsa.pub'
    ssh_privkey_path = '/home/ubuntu/.ssh/openstack_id_rsa'

    # 检查公钥
    if os.path.exists(ssh_pubkey_path):
        print(f"✅ 公钥文件存在: {ssh_pubkey_path}")
    else:
        print(f"❌ 公钥文件不存在: {ssh_pubkey_path}")

    # 检查私钥
    if os.path.exists(ssh_privkey_path):
        print(f"✅ 私钥文件存在: {ssh_privkey_path}")
    else:
        print(f"❌ 私钥文件不存在: {ssh_privkey_path}")

def main():
    """主函数"""
    print("=== SSH 密钥配置修复工具 ===")

    # 修复 SSH 配置
    if fix_ssh_key_config():
        print(f"\n✅ SSH 配置修复成功")
    else:
        print(f"\n❌ SSH 配置修复失败")
        return

    # 验证 SSH 文件
    verify_ssh_files()

    print(f"\n=== 修复完成 ===")
    print("请重启应用程序使修复生效")

if __name__ == "__main__":
    main()
