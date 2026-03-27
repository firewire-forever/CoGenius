"""
Ansible Helper Utilities

This module provides utilities to improve Ansible playbook execution,
including retry logic for SSH connections and better error handling.
"""

import os
import time
import subprocess
import logging
from typing import List, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

def wait_for_ssh_host(host: str, max_retries: int = 30, retry_interval: int = 30) -> bool:
    """
    Wait for an SSH host to become available.

    Args:
        host: The hostname or IP address to wait for
        max_retries: Maximum number of retry attempts
        retry_interval: Interval between retries in seconds

    Returns:
        True if host is available, False otherwise
    """
    ssh_command = [
        'ssh',
        '-o', 'ConnectTimeout=10',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'BatchMode=yes',  # Don't prompt for password
        '-o', 'UserKnownHostsFile=/dev/null',
        f'ubuntu@{host}',
        'echo "SSH connection successful"'
    ]

    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting SSH connection to {host} (attempt {attempt + 1}/{max_retries})")

            result = subprocess.run(
                ssh_command,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"✅ SSH connection to {host} successful")
                return True
            else:
                logger.warning(f"SSH connection failed (attempt {attempt + 1}): {result.stderr}")

        except subprocess.TimeoutExpired:
            logger.warning(f"SSH connection timed out (attempt {attempt + 1})")
        except Exception as e:
            logger.warning(f"SSH connection error (attempt {attempt + 1}): {str(e)}")

        if attempt < max_retries - 1:
            logger.info(f"Waiting {retry_interval} seconds before next attempt...")
            time.sleep(retry_interval)

    logger.error(f"❌ SSH connection to {host} failed after {max_retries} attempts")
    return False

def execute_ansible_playbook_with_retry(
    inventory_file: str,
    playbook_file: str,
    private_key_path: str,
    max_retries: int = 3,
    retry_interval: int = 60
) -> Dict:
    """
    Execute Ansible playbook with retry logic.

    Args:
        inventory_file: Path to inventory file
        playbook_file: Path to playbook file
        private_key_path: Path to SSH private key
        max_retries: Maximum number of retry attempts
        retry_interval: Interval between retries in seconds

    Returns:
        Dictionary with execution results
    """
    base_command = [
        'ansible-playbook',
        '-i', inventory_file,
        playbook_file,
        f'--private-key={private_key_path}',
        '--timeout=300',
        '--flush-cache'
    ]

    for attempt in range(max_retries):
        try:
            logger.info(f"Executing Ansible playbook (attempt {attempt + 1}/{max_retries}): {playbook_file}")

            result = subprocess.run(
                base_command,
                capture_output=True,
                text=True,
                timeout=1800  # 30 minutes timeout
            )

            # Parse the results
            success = result.returncode == 0
            output = {
                'success': success,
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'attempt': attempt + 1
            }

            if success:
                logger.info(f"✅ Ansible playbook execution successful: {playbook_file}")
                return output
            else:
                logger.warning(f"Ansible playbook failed (attempt {attempt + 1}): {result.stderr}")

                # Check if it's an SSH connection error
                if 'UNREACHABLE' in result.stdout or 'Connection timed out' in result.stderr:
                    logger.info("SSH connection error detected, waiting before retry...")
                    time.sleep(retry_interval)
                    continue
                else:
                    # Non-SSH error, don't retry
                    logger.error(f"Non-retryable error in playbook: {playbook_file}")
                    return output

        except subprocess.TimeoutExpired:
            logger.error(f"Ansible playbook execution timed out (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                time.sleep(retry_interval)
                continue
        except Exception as e:
            logger.error(f"Ansible playbook execution error (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_interval)
                continue

    logger.error(f"❌ Ansible playbook execution failed after {max_retries} attempts: {playbook_file}")
    return {
        'success': False,
        'returncode': -1,
        'stdout': '',
        'stderr': 'Max retries exceeded',
        'attempt': max_retries
    }

def check_ansible_requirements() -> bool:
    """
    Check if Ansible and its requirements are properly installed and configured.

    Returns:
        True if requirements are met, False otherwise
    """
    try:
        # Check if ansible-playbook is available
        result = subprocess.run(
            ['which', 'ansible-playbook'],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            logger.error("❌ ansible-playbook not found in PATH")
            return False

        # Check private key file
        key_path = Path('/home/ubuntu/.ssh/openstack_id_rsa')
        if not key_path.exists():
            logger.error(f"❌ SSH private key not found: {key_path}")
            return False

        # Check if key is readable
        if not os.access(key_path, os.R_OK):
            logger.error(f"❌ SSH private key not readable: {key_path}")
            return False

        logger.info("✅ Ansible requirements check passed")
        return True

    except Exception as e:
        logger.error(f"❌ Error checking Ansible requirements: {str(e)}")
        return False
