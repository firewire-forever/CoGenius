#!/usr/bin/env python3
"""
修复 VSDL 编译器 URL 问题的直接解决方案
"""

import os
import re
import shutil
from pathlib import Path

def fix_vsdl_compiler():
    """
    修复方案：创建一个包装脚本来处理 VSDL 编译器的 URL 问题
    """

    # 1. 创建 VSDL 编译器包装脚本
    wrapper_script = '''#!/bin/bash
# VSDL Compiler Wrapper Script
# This script fixes the OpenStack authentication URL issue

# Get the original VSDL compiler path
VSDLC_PATH="$1"
shift

# Check if we have OpenStack URL in arguments
OPENSTACK_URL_FOUND=false
for arg in "$@"; do
    if [[ $arg == "--openstack_url="* ]]; then
        OPENSTACK_URL_FOUND=true
        break
    fi
done

# If OpenStack URL is found, fix it
if [ "$OPENSTACK_URL_FOUND" = true ]; then
    echo "Fixing OpenStack URL in VSDL compiler arguments..."

    # Create a temporary script to modify arguments
    TEMP_SCRIPT=$(mktemp)

    # Write the argument modification logic
    cat > "$TEMP_SCRIPT" << 'EOF'
#!/bin/bash
MODIFIED_ARGS=()
for arg in "$@"; do
    if [[ $arg == "--openstack_url="* ]]; then
        # Extract the URL
        URL_VALUE=$(echo "$arg" | cut -d'=' -f2-)

        # Remove trailing slash and add /v3/auth/tokens
        FIXED_URL=$(echo "$URL_VALUE" | sed 's:/*$::')/v3/auth/tokens

        # Replace the argument
        MODIFIED_ARGS+=("--openstack_url=$FIXED_URL")
        echo "Modified URL: $URL_VALUE -> $FIXED_URL"
    else
        MODIFIED_ARGS+=("$arg")
    fi
done

# Execute the original VSDL compiler with modified arguments
exec java -jar "$VSDLC_PATH" "${MODIFIED_ARGS[@]}"
EOF

    chmod +x "$TEMP_SCRIPT"

    # Execute the temporary script with all arguments
    exec "$TEMP_SCRIPT" "$VSDLC_PATH" "$@"
fi

# If no OpenStack URL, run normally
exec java -jar "$VSDLC_PATH" "$@"
'''

    # 2. 写入包装脚本
    wrapper_path = Path(__file__).parent / "tools" / "vsdlc_wrapper.sh"
    with open(wrapper_path, 'w') as f:
        f.write(wrapper_script)

    # 3. 使脚本可执行
    wrapper_path.chmod(0o755)

    print(f"✅ 创建了 VSDL 编译器包装脚本: {wrapper_path}")

    # 4. 更新 .env 文件以使用包装脚本
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path, 'r') as f:
            content = f.read()

        # 替换 VSDLC_PATH
        new_content = re.sub(
            r'VSDLC_PATH=tools/vsdlc\.jar',
            'VSDLC_PATH=tools/vsdlc_wrapper.sh',
            content
        )

        with open(env_path, 'w') as f:
            f.write(new_content)

        print("✅ 更新了 .env 文件以使用包装脚本")
    else:
        print("❌ .env 文件不存在，请手动更新 VSDLC_PATH")

    # 5. 创建副本的原始 vsdlc.jar
    original_vsdlc = Path(__file__).parent / "tools" / "vsdlc.jar"
    vsdlc_backup = Path(__file__).parent / "tools" / "vsdlc.jar.original"

    if original_vsdlc.exists():
        shutil.copy2(original_vsdlc, vsdlc_backup)
        print(f"✅ 原始 VSDL 编译器已备份到: {vsdlc_backup}")
    else:
        print("❌ 原始 VSDL 编译器不存在")

    print("\n修复完成！")
    print("重启应用程序后，VSDL 编译器将使用修复的 URL 格式")

def create_direct_fix():
    """
    备选方案：直接修改环境变量以使用正确的认证端点
    """

    env_path = Path(__file__).parent / '.env'

    if env_path.exists():
        with open(env_path, 'r') as f:
            content = f.read()

        # 创建备份
        backup_path = env_path.with_suffix('.env.backup.url')
        with open(backup_path, 'w') as f:
            f.write(content)

        # 直接设置正确的认证 URL
        new_content = re.sub(
            r'OPENSTACK_URL=.*',
            'OPENSTACK_URL=http://222.20.126.26/identity/v3/auth/tokens',
            content
        )

        with open(env_path, 'w') as f:
            f.write(new_content)

        print(f"✅ 备份文件: {backup_path}")
        print("✅ 已更新 OPENSTACK_URL 使用完整的认证端点")
        print("⚠️  注意：这是临时解决方案，可能会影响其他工具")
    else:
        print("❌ .env 文件不存在")

def main():
    print("=== VSDL 编译器 URL 问题修复工具 ===\n")

    print("选择修复方案：")
    print("1. 推荐方案：使用包装脚本（不会影响其他配置）")
    print("2. 快速方案：直接修改 URL（可能影响其他工具）")

    choice = input("\n请选择方案 (1 或 2): ").strip()

    if choice == "1":
        print("\n使用推荐的包装脚本方案...")
        fix_vsdl_compiler()
    elif choice == "2":
        print("\n使用快速修改方案...")
        create_direct_fix()
    else:
        print("无效选择，请重新运行脚本")

if __name__ == "__main__":
    main()
