"""
VSDL OpenStack Authentication Fix - 修复版本

This module provides a workaround for the VSDL compiler's incorrect URL transformation.
The VSDL compiler automatically appends "/auth/tokens" to the OpenStack URL,
which doesn't work with some OpenStack deployments.
"""

import re
import logging
from typing import Tuple
from flask import current_app

logger = logging.getLogger(__name__)

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

    # 基于您的 CURL 测试结果，我们知道正确的修复方式
    # 输入: http://222.20.126.26/identity
    # 输出: http://222.20.126.26/identity/v3/auth/tokens

    # 如果是基础身份端点，添加 /v3/auth/tokens
    if auth_url.endswith('/identity'):
        return f"{auth_url}/v3/auth/tokens"

    # 如果URL包含 identity 但没有 /v3/auth/tokens，添加它
    if '/identity' in auth_url and '/v3/auth/tokens' not in auth_url:
        return f"{auth_url}/v3/auth/tokens"

    # 如果 URL 已经是错误的 /identity/auth/tokens，修复它
    if '/identity/auth/tokens' in auth_url:
        return auth_url.replace('/identity/auth/tokens', '/identity/v3/auth/tokens')

    # 如果 URL 已经有 /v3/auth/tokens，保持不变
    if '/v3/auth/tokens' in auth_url:
        return auth_url

    # 如果是通用 URL，添加 /v3/auth/tokens
    return f"{auth_url}/v3/auth/tokens"

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
        'NOT FOUND',
        '404',
        'ClientResponseException',
        'OpenStack4j'
    ]

    has_indicators = any(indicator in stderr for indicator in error_indicators)

    # Check if it's specifically an auth URL error
    auth_url_indicators = [
        'POST http',
        'identity/auth/tokens',
        'authentication'
    ]

    return has_indicators and any(indicator in stderr.lower() for indicator in auth_url_indicators)

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
        ("http://222.20.126.26/identity", "http://222.20.126.26/identity/v3/auth/tokens"),
        ("http://222.20.126.26/identity/", "http://222.20.126.26/identity/v3/auth/tokens"),
        ("http://222.20.126.26/identity/auth/tokens", "http://222.20.126.26/identity/v3/auth/tokens"),
        ("http://example.com/identity", "http://example.com/identity/v3/auth/tokens"),
    ]

    print("=== URL 修复测试 ===")
    for input_url, expected_output in test_cases:
        actual_output = fix_openstack_auth_url(input_url)
        status = "✅" if actual_output == expected_output else "❌"
        print(f"{status} 输入: {input_url}")
        print(f"   期望: {expected_output}")
        print(f"   实际: {actual_output}")
        print()

if __name__ == "__main__":
    test_url_fix()
