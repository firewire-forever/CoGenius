"""
VSDL OpenStack Authentication Fix - 修复版本 2
解决过度修复问题
"""

import re
import logging
from typing import Tuple

# 设置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def fix_openstack_auth_url(auth_url: str) -> str:
    """
    Fix OpenStack authentication URL for VSDL compiler.

    Args:
        auth_url: The original OpenStack authentication URL

    Returns:
        The fixed URL that works with VSDL compiler
    """
    # Remove trailing slash
    auth_url = auth_url.rstrip('/')

    logger.info(f"开始修复URL: {auth_url}")

    # 如果已经是最终的正确格式，直接返回
    if auth_url.endswith('/v3/auth/tokens'):
        logger.info(f"URL已经是正确格式: {auth_url}")
        return auth_url

    # 检查并修复过度添加的 /auth/tokens（主要问题）
    if auth_url.endswith('/v3/auth/tokens/auth/tokens'):
        # 移除末尾多余的 /auth/tokens
        fixed_url = auth_url[:-12]  # 移除 '/auth/tokens'
        logger.info(f"修复过度添加的认证URL: {auth_url} -> {fixed_url}")
        return fixed_url

    if '/v3/auth/tokens/auth/tokens' in auth_url:
        # 移除中间多余的 /auth/tokens
        fixed_url = auth_url.replace('/v3/auth/tokens/auth/tokens', '/v3/auth/tokens')
        logger.info(f"修复包含双重认证的URL: {auth_url} -> {fixed_url}")
        return fixed_url

    # 检查其他多余的 /auth/tokens
    if auth_url.endswith('/auth/tokens'):
        # 从类似 identity/v3/auth/tokens/auth/tokens 的 URL 中移除多余的 /auth/tokens
        fixed_url = auth_url[:-12]  # 移除末尾的 '/auth/tokens'
        logger.info(f"移除多余的 /auth/tokens: {auth_url} -> {fixed_url}")
        return fixed_url

    # 如果已经包含 /auth/tokens 但不是 v3 版本，修复为 v3 版本
    if '/auth/tokens' in auth_url:
        # 修复类似 /identity/auth/tokens 的 URL
        if '/identity/auth/tokens' in auth_url:
            fixed_url = auth_url.replace('/identity/auth/tokens', '/identity/v3/auth/tokens')
            logger.info(f"修复认证URL版本: {auth_url} -> {fixed_url}")
            return fixed_url

    # 如果URL包含 identity 但没有 /v3，只添加 /v3
    # 因为VSDL编译器会自动添加 /auth/tokens
    if '/identity' in auth_url and '/v3' not in auth_url:
        fixed_url = f"{auth_url}/v3"
        logger.info(f"添加v3版本路径（编译器会自动添加认证路径）: {auth_url} -> {fixed_url}")
        return fixed_url

    # 如果是基础身份端点，只添加 /v3
    # 因为VSDL编译器会自动添加 /auth/tokens
    if auth_url.endswith('/identity'):
        fixed_url = f"{auth_url}/v3"
        logger.info(f"添加v3版本（编译器会自动添加认证路径）: {auth_url} -> {fixed_url}")
        return fixed_url

    # 如果 URL 已经有 /v3/auth/tokens，保持不变
    if '/v3/auth/tokens' in auth_url:
        logger.info(f"URL已包含v3认证路径: {auth_url}")
        return auth_url

    # 如果是通用 URL，添加 /v3/auth/tokens
    fixed_url = f"{auth_url}/v3/auth/tokens"
    logger.info(f"添加标准v3认证路径: {auth_url} -> {fixed_url}")
    return fixed_url

def detect_and_fix_vsdl_url_error(stderr: str) -> bool:
    """
    Detect if the error is due to VSDL compiler's URL transformation issue.

    Args:
        stderr: The stderr output from VSDL compiler

    Returns:
        True if it's the URL transformation error, False otherwise
    """
    error_indicators = [
        '/identity/auth/tokens',
        '/v3/auth/tokens/auth/tokens',  # 主要问题指标
        'NOT FOUND',
        '404',
        'ClientResponseException',
        'OpenStack4j'
    ]

    has_indicators = any(indicator in stderr for indicator in error_indicators)
    logger.info(f"检测到错误指标: {has_indicators}")

    # Check if it's specifically an auth URL error
    auth_url_indicators = [
        'POST http',
        'identity/auth/tokens',
        'identity/v3/auth/tokens/auth/tokens',
        'authentication'
    ]

    auth_error = any(indicator in stderr.lower() for indicator in auth_url_indicators)
    logger.info(f"检测到认证URL错误: {auth_error}")

    return has_indicators and auth_error

def create_custom_auth_params(original_params: dict) -> dict:
    """
    Create custom authentication parameters that work around VSDL compiler issues.

    Args:
        original_params: Original authentication parameters

    Returns:
        Modified authentication parameters
    """
    params = original_params.copy()

    # Fix the auth URL
    original_url = params.get('auth_url')
    if original_url:
        fixed_url = fix_openstack_auth_url(original_url)
        if fixed_url != original_url:
            logger.info(f"Fixed OpenStack auth URL: {original_url} -> {fixed_url}")
            params['auth_url'] = fixed_url

    return params

def validate_openstack_connection_directly(auth_params: dict) -> Tuple[bool, str]:
    """
    Test OpenStack connection directly using requests.

    Args:
        auth_params: Authentication parameters

    Returns:
        Tuple of (success, message)
    """
    try:
        import requests

        auth_url = auth_params.get('auth_url')
        username = auth_params.get('username')
        password = auth_params.get('password')
        project_name = auth_params.get('project_name')
        project_domain = auth_params.get('project_domain_name', 'Default')
        user_domain = auth_params.get('user_domain_name', 'Default')

        # Build the auth request
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        data = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": username,
                            "password": password,
                            "domain": {"name": user_domain}
                        }
                    }
                },
                "scope": {
                    "project": {
                        "name": project_name,
                        "domain": {"name": project_domain}
                    }
                }
            }
        }

        logger.info(f"Testing direct connection to: {auth_url}")
        response = requests.post(
            auth_url,
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code == 201:
            logger.info("✅ Direct OpenStack authentication successful")
            return True, "Direct authentication successful"
        else:
            error_msg = f"Direct authentication failed: {response.status_code} - {response.text[:200]}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg

    except Exception as e:
        error_msg = f"Direct authentication error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg

def test_url_fix():
    """
    测试 URL 修复功能
    """
    test_cases = [
        # 基础身份端点（现在只加 /v3，编译器会自动加 /auth/tokens）
        ("http://222.20.126.26/identity", "http://222.20.126.26/identity/v3"),
        ("http://222.20.126.26/identity/", "http://222.20.126.26/identity/v3"),

        # 错误的认证端点
        ("http://222.20.126.26/identity/auth/tokens", "http://222.20.126.26/identity/v3"),

        # 正确的v3端点（不变）
        ("http://222.20.126.26/identity/v3", "http://222.20.126.26/identity/v3"),

        # 过度添加的认证端点（主要问题）
        ("http://222.20.126.26/identity/v3/auth/tokens/auth/tokens", "http://222.20.126.26/identity/v3/auth/tokens"),
        ("http://222.20.126.26/identity/v3/auth/tokens/auth/tokens/", "http://222.20.126.26/identity/v3/auth/tokens"),

        # 其他情况
        ("http://example.com/identity", "http://example.com/identity/v3"),
        ("http://example.com/identity/", "http://example.com/identity/v3"),
        ("http://example.com", "http://example.com/v3"),

        # 已经有完整路径的情况
        ("http://example.com/v3", "http://example.com/v3"),
    ]

    print("=== URL 修复测试 v2 ===")
    all_passed = True

    for input_url, expected_output in test_cases:
        actual_output = fix_openstack_auth_url(input_url)
        status = "✅" if actual_output == expected_output else "❌"
        if status == "❌":
            all_passed = False
        print(f"{status} 输入: {input_url}")
        print(f"   期望: {expected_output}")
        print(f"   实际: {actual_output}")
        print()

    print(f"\n=== 测试结果 ===")
    print(f"整体状态: {'✅ 所有测试通过' if all_passed else '❌ 部分测试失败'}")

    return all_passed

if __name__ == "__main__":
    test_url_fix()