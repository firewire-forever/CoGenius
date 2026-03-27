from celery import shared_task, current_task
from app.services.case_service import (
    get_VSDL_script_local,
    compile_VSDL_script,
    generate_terraform_script,
    generate_ansible_script
)
from app.utils.callbacks import send_callback
from flask import current_app
import time
import shutil
import os
import base64
import sys
import socket
import requests
import json
from datetime import datetime
from typing import Dict, Any, Optional
import threading

# 线程锁，确保多worker并发写入实验结果文件时不会冲突
_experiment_results_lock = threading.Lock()


# ============================================================================
# 实验结果记录模块
# ============================================================================

def _get_experiment_results_dir() -> str:
    """
    获取实验结果目录路径，如果不存在则创建。
    目录位置: app/experimental_results/
    """
    # 获取 app 目录 (tasks.py 所在目录)
    app_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(app_dir, 'experimental_results')

    if not os.path.exists(results_dir):
        os.makedirs(results_dir, exist_ok=True)
        print(f"[EXPERIMENT] Created experiment results directory: {results_dir}")

    return results_dir


def _get_pdf_name_from_path(file_path: str) -> str:
    """
    从文件路径中提取PDF文件名（不含扩展名）。
    例如: /path/to/CVE-2022-12322.pdf -> CVE-2022-12322
    """
    filename = os.path.basename(file_path)
    # 移除扩展名
    name_without_ext = os.path.splitext(filename)[0]
    return name_without_ext


def _save_experiment_results(
    pdf_name: str,
    task_id: str,
    scenario,
    timing_info: Dict[str, float],
    tf_success: bool,
    ansible_success: bool,
    terraform_output: dict,
    error_message: str = None
) -> str:
    """
    保存实验结果到文件。

    文件命名规则: {pdf_name}exresults.txt
    例如: CVE-2022-12322.pdf -> CVE-2022-12322exresults.txt

    Args:
        pdf_name: PDF文件名（不含扩展名）
        task_id: Celery任务ID
        scenario: VSDL Scenario对象
        timing_info: 各阶段耗时信息
        tf_success: Terraform是否成功
        ansible_success: Ansible是否成功
        terraform_output: Terraform输出的IP信息
        error_message: 错误信息（如果有）

    Returns:
        保存的文件路径
    """
    with _experiment_results_lock:
        results_dir = _get_experiment_results_dir()
        result_file = os.path.join(results_dir, f"{pdf_name}exresults.txt")

        # 判断是否彻底成功
        full_success = tf_success and ansible_success

        # 计算总耗时
        total_time = timing_info.get('total_time', 0)

        # IAC构建时间 = PDF提取 + VSDL生成 + 编译时间
        iac_build_time = (
            timing_info.get('pdf_extraction_time', 0) +
            timing_info.get('vsdl_generation_time', 0) +
            timing_info.get('compilation_time', 0)
        )

        # 端到端延迟 = 总时间
        end_to_end_latency = total_time

        # 构建结果内容
        lines = []

        # === 实验关键指标摘要 ===
        lines.append("=" * 80)
        lines.append("实验结果摘要")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"PDF文件: {pdf_name}.pdf")
        lines.append(f"任务ID: {task_id}")
        lines.append(f"记录时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # 成功状态
        lines.append("-" * 40)
        lines.append("【部署状态】")
        lines.append("-" * 40)
        if full_success:
            lines.append("彻底成功部署: ✅ 是")
        else:
            lines.append("彻底成功部署: ❌ 否")
            if not tf_success:
                lines.append("  - Terraform部署失败")
            elif not ansible_success:
                lines.append("  - Ansible配置失败")
        if error_message:
            lines.append(f"错误信息: {error_message}")
        lines.append("")

        # 时间指标
        lines.append("-" * 40)
        lines.append("【时间指标】")
        lines.append("-" * 40)
        lines.append(f"端到端延迟: {end_to_end_latency:.2f} 秒 ({end_to_end_latency/60:.2f} 分钟)")
        lines.append(f"IAC平均构建时间: {iac_build_time:.2f} 秒 ({iac_build_time/60:.2f} 分钟)")
        lines.append("")
        lines.append("各阶段耗时明细:")
        lines.append(f"  1. PDF提取: {timing_info.get('pdf_extraction_time', 0):.2f} 秒")
        lines.append(f"  2. VSDL生成: {timing_info.get('vsdl_generation_time', 0):.2f} 秒")
        lines.append(f"  3. VSDL编译: {timing_info.get('compilation_time', 0):.2f} 秒")
        lines.append(f"  4. Terraform部署: {timing_info.get('terraform_time', 0):.2f} 秒")
        lines.append(f"  5. Ansible配置: {timing_info.get('ansible_time', 0):.2f} 秒")
        lines.append(f"  总计: {total_time:.2f} 秒")
        lines.append("")

        # 场景概览
        if scenario:
            lines.append("-" * 40)
            lines.append("【场景概览】")
            lines.append("-" * 40)
            lines.append(f"场景名称: {scenario.name}")
            lines.append(f"场景时长: {scenario.duration} TTU")
            lines.append(f"网络数量: {len(scenario.networks) if scenario.networks else 0}")
            lines.append(f"节点数量: {len(scenario.nodes) if scenario.nodes else 0}")
            lines.append(f"漏洞数量: {len(scenario.vulnerabilities) if scenario.vulnerabilities else 0}")
            lines.append("")

        lines.append("=" * 80)
        lines.append("完整部署报告")
        lines.append("=" * 80)
        lines.append("")

        # 生成完整部署报告
        report = generate_deployment_report(
            task_id=task_id,
            scenario=scenario,
            terraform_output=terraform_output,
            tf_success=tf_success,
            ansible_success=ansible_success,
            elapsed_time=total_time
        )
        lines.append(report)

        # 写入文件
        try:
            with open(result_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"[EXPERIMENT] Saved experiment results to: {result_file}")
            return result_file
        except Exception as e:
            print(f"[EXPERIMENT] Failed to save experiment results: {e}")
            return None


def _save_scenario_output(
    task_id: str,
    vsdl_script: str,
    output_dir: str,
    scenario,
    terraform_output: dict,
    tf_success: bool,
    ansible_success: bool,
    elapsed_time: float,
    error_message: str = None
) -> str:
    """
    Save all generation results to a dedicated scenario output directory.

    Directory structure:
    scenario_outputs/{task_id}/
    ├── vsdl_script.vsdl          # Generated VSDL script
    ├── metadata.json             # Task metadata (timestamps, status, etc.)
    ├── deployment_report.txt     # Human-readable deployment report
    ├── terraform_output.json     # IP addresses and Terraform outputs
    ├── terraform/                # Copy of Terraform files
    └── ansible/                  # Copy of Ansible files

    Args:
        task_id: Celery task ID
        vsdl_script: Generated VSDL script content
        output_dir: Compilation output directory (temp)
        scenario: VSDL Scenario object
        terraform_output: Terraform output IPs
        tf_success: Whether Terraform deployment succeeded
        ansible_success: Whether Ansible configuration succeeded
        elapsed_time: Total elapsed time in seconds
        error_message: Error message if failed

    Returns:
        Path to the scenario output directory
    """
    # Create scenario output directory
    scenario_output_base = current_app.config.get('SCENARIO_OUTPUT_DIR', 'data/scenario_outputs')
    os.makedirs(scenario_output_base, exist_ok=True)

    # Use task_id as directory name for uniqueness
    scenario_output_dir = os.path.join(scenario_output_base, task_id)
    os.makedirs(scenario_output_dir, exist_ok=True)

    current_app.logger.info(f"[{task_id}] Saving scenario output to: {scenario_output_dir}")

    try:
        # 1. Save VSDL script
        vsdl_path = os.path.join(scenario_output_dir, 'vsdl_script.vsdl')
        with open(vsdl_path, 'w', encoding='utf-8') as f:
            f.write(vsdl_script)
        current_app.logger.info(f"[{task_id}] Saved VSDL script to: {vsdl_path}")

        # 2. Save metadata
        metadata = {
            "task_id": task_id,
            "scenario_name": scenario.name if scenario else None,
            "scenario_duration": scenario.duration if scenario else None,
            "created_at": datetime.now().isoformat(),
            "elapsed_time_seconds": round(elapsed_time, 2),
            "status": {
                "terraform": "success" if tf_success else "failed",
                "ansible": "success" if ansible_success else ("skipped" if not tf_success else "failed"),
                "overall": "success" if (tf_success and ansible_success) else "partial" if tf_success else "failed"
            },
            "error_message": error_message,
            "networks": [{"name": n.name, "address_range": n.address_range} for n in scenario.networks] if scenario and scenario.networks else [],
            "nodes": [{"name": n.name, "os": n.os_image, "vcpu": n.vcpu} for n in scenario.nodes] if scenario and scenario.nodes else [],
            "vulnerabilities": [{"name": v.name, "cve_id": v.cve_id} for v in scenario.vulnerabilities] if scenario and scenario.vulnerabilities else []
        }

        metadata_path = os.path.join(scenario_output_dir, 'metadata.json')
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        current_app.logger.info(f"[{task_id}] Saved metadata to: {metadata_path}")

        # 3. Save deployment report
        report = generate_deployment_report(
            task_id=task_id,
            scenario=scenario,
            terraform_output=terraform_output,
            tf_success=tf_success,
            ansible_success=ansible_success,
            elapsed_time=elapsed_time
        )
        report_path = os.path.join(scenario_output_dir, 'deployment_report.txt')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        current_app.logger.info(f"[{task_id}] Saved deployment report to: {report_path}")

        # 4. Save Terraform output
        if terraform_output:
            tf_output_path = os.path.join(scenario_output_dir, 'terraform_output.json')
            with open(tf_output_path, 'w', encoding='utf-8') as f:
                json.dump(terraform_output, f, indent=2)
            current_app.logger.info(f"[{task_id}] Saved Terraform output to: {tf_output_path}")

        # 5. Copy Terraform files
        if output_dir and os.path.exists(output_dir):
            current_app.logger.info(f"[{task_id}] Checking output_dir contents: {os.listdir(output_dir)}")

            terraform_src = os.path.join(output_dir, 'terraform')
            if os.path.exists(terraform_src):
                terraform_dst = os.path.join(scenario_output_dir, 'terraform')
                # Use dirs_exist_ok to avoid error if destination exists
                shutil.copytree(terraform_src, terraform_dst, dirs_exist_ok=True)
                current_app.logger.info(f"[{task_id}] Copied Terraform files to: {terraform_dst}")
            else:
                current_app.logger.warning(f"[{task_id}] Terraform source directory not found: {terraform_src}")

            # 6. Copy Ansible files
            ansible_src = os.path.join(output_dir, 'ansible')
            if os.path.exists(ansible_src):
                ansible_dst = os.path.join(scenario_output_dir, 'ansible')
                # Use dirs_exist_ok to avoid error if destination exists
                shutil.copytree(ansible_src, ansible_dst, dirs_exist_ok=True)
                current_app.logger.info(f"[{task_id}] Copied Ansible files to: {ansible_dst}")
            else:
                current_app.logger.warning(f"[{task_id}] Ansible source directory not found: {ansible_src}")
        else:
            current_app.logger.warning(f"[{task_id}] Output directory not found or empty: {output_dir}")

        current_app.logger.info(f"[{task_id}] ✅ Scenario output saved successfully to: {scenario_output_dir}")
        return scenario_output_dir

    except Exception as e:
        import traceback
        current_app.logger.error(f"[{task_id}] Failed to save scenario output: {e}")
        current_app.logger.error(f"[{task_id}] Traceback: {traceback.format_exc()}")
        return scenario_output_dir

@shared_task(ignore_result=True, bind=True)
def process_scenario_file_task(self, file_path: str, callback_url: str):
    """
    A Celery task that processes a scenario file to generate deployment artifacts.
    It is a stateless task that receives a file path and a callback URL.
    The result (a zip file of artifacts or an error) is sent back via the callback.
    """
    task_id = self.request.id
    current_app.logger.info(f"Starting scenario processing task {task_id} for file: {file_path}")
    output_dir = None
    scenario = None
    start_time = time.time()

    # 获取PDF文件名（用于实验结果记录）
    pdf_name = _get_pdf_name_from_path(file_path)
    current_app.logger.info(f"[{task_id}] PDF name for experiment: {pdf_name}")

    # 初始化时间记录字典
    timing_info = {
        'pdf_extraction_time': 0,
        'vsdl_generation_time': 0,
        'compilation_time': 0,
        'terraform_time': 0,
        'ansible_time': 0,
        'total_time': 0
    }

    # 用于追踪各阶段时间
    step_start_time = None

    # 调试信息：环境变量检查
    current_app.logger.info(f"[{task_id}] 环境变量检查:")
    current_app.logger.info(f"[{task_id}] HF_HOME = {os.environ.get('HF_HOME', 'Not set')}")
    current_app.logger.info(f"[{task_id}] HF_HUB_LOCAL_DIR = {os.environ.get('HF_HUB_LOCAL_DIR', 'Not set')}")
    current_app.logger.info(f"[{task_id}] TRANSFORMERS_OFFLINE = {os.environ.get('TRANSFORMERS_OFFLINE', 'Not set')}")
    current_app.logger.info(f"[{task_id}] HF_HUB_OFFLINE = {os.environ.get('HF_HUB_OFFLINE', 'Not set')}")
    current_app.logger.info(f"[{task_id}] UNSTRUCTURED_LOCAL_INFERENCE = {os.environ.get('UNSTRUCTURED_LOCAL_INFERENCE', 'Not set')}")
    
    # 调试信息：检查模型文件
    hf_home = os.environ.get('HF_HOME', '/home/appuser/models')
    model_path = os.path.join(hf_home, 'models--unstructuredio--yolo_x_layout', 'snapshots')
    current_app.logger.info(f"[{task_id}] 检查模型目录: {model_path}")
    
    if os.path.exists(model_path):
        current_app.logger.info(f"[{task_id}] 模型目录存在，内容: {os.listdir(model_path)}")
        for snapshot_dir in os.listdir(model_path):
            snapshot_path = os.path.join(model_path, snapshot_dir)
            if os.path.isdir(snapshot_path):
                current_app.logger.info(f"[{task_id}] 快照目录: {snapshot_path}, 内容: {os.listdir(snapshot_path)}")
    else:
        current_app.logger.warning(f"[{task_id}] 模型目录不存在: {model_path}")
    
    # 调试信息：Python路径
    current_app.logger.info(f"[{task_id}] Python路径: {sys.path}")
    
    # 调试信息：网络连接测试
    current_app.logger.info(f"[{task_id}] 开始网络连接测试...")
    
    # 1. DNS解析测试
    try:
        current_app.logger.info(f"[{task_id}] 测试DNS解析 huggingface.co...")
        ip_address = socket.gethostbyname("huggingface.co")
        current_app.logger.info(f"[{task_id}] DNS解析成功: huggingface.co -> {ip_address}")
    except socket.gaierror as e:
        current_app.logger.error(f"[{task_id}] DNS解析失败: {str(e)}")
    
    # 2. Socket连接测试
    try:
        current_app.logger.info(f"[{task_id}] 测试Socket连接到 huggingface.co:443...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(("huggingface.co", 443))
        s.close()
        current_app.logger.info(f"[{task_id}] Socket连接成功")
    except Exception as e:
        current_app.logger.error(f"[{task_id}] Socket连接失败: {str(e)}")
    
    # 3. HTTP请求测试
    try:
        current_app.logger.info(f"[{task_id}] 测试HTTP请求到 https://huggingface.co...")
        response = requests.get("https://huggingface.co", timeout=5)
        current_app.logger.info(f"[{task_id}] HTTP请求成功: 状态码={response.status_code}")
    except Exception as e:
        current_app.logger.error(f"[{task_id}] HTTP请求失败: {str(e)}")
    
    try:
        # ========== Step 1: VSDL脚本生成 (包含PDF提取 + LLM生成) ==========
        step_start_time = time.time()
        current_app.logger.info(f"[{task_id}] Step 1: Generating VSDL script (PDF extraction + LLM)...")
        vsdl_script = get_VSDL_script_local(file_path)

        # Basic validation of the generated script
        if not vsdl_script or vsdl_script.strip().startswith('//'):
            raise ValueError(f"VSDL script generation failed or returned an empty/error script: {vsdl_script}")

        # 记录VSDL生成时间（包含PDF提取和LLM调用）
        timing_info['vsdl_generation_time'] = time.time() - step_start_time
        current_app.logger.info(f"[{task_id}] VSDL script generated successfully. Time: {timing_info['vsdl_generation_time']:.2f}s")

        # ========== Step 2: VSDL编译 ==========
        step_start_time = time.time()
        current_app.logger.info(f"[{task_id}] Step 2: Compiling VSDL script...")
        # Pass task_id for unique keypair naming in parallel execution
        success, output_dir, scenario = compile_VSDL_script(vsdl_script, task_id=task_id)

        if not success:
            # The error message from compile_VSDL_script is in the `output_dir` variable on failure
            raise Exception(f"VSDL compilation failed: {output_dir}")

        timing_info['compilation_time'] = time.time() - step_start_time
        current_app.logger.info(f"[{task_id}] VSDL script compiled successfully. Time: {timing_info['compilation_time']:.2f}s. Artifacts at: {output_dir}")

        # ========== Step 3: Terraform部署 ==========
        step_start_time = time.time()
        current_app.logger.info(f"[{task_id}] Step 3: Starting Terraform deployment...")
        # Use unique keypair name for parallel execution
        keypair_name = f'vsdl_key_{task_id}'
        tf_success, tf_result = generate_terraform_script(output_dir, keypair_name=keypair_name)
        ansible_success = False  # Initialize

        if not tf_success:
            current_app.logger.warning(f"[{task_id}] Terraform deployment failed: {tf_result}")
            # Continue without deployment - just return artifacts
            terraform_output = None
            timing_info['terraform_time'] = time.time() - step_start_time
        else:
            timing_info['terraform_time'] = time.time() - step_start_time
            current_app.logger.info(f"[{task_id}] Terraform deployment successful. Time: {timing_info['terraform_time']:.2f}s")
            # Parse terraform outputs for Ansible
            terraform_output = _get_terraform_outputs(output_dir)

            # ========== Step 4: Ansible配置 ==========
            step_start_time = time.time()
            current_app.logger.info(f"[{task_id}] Step 4: Starting Ansible configuration...")
            ansible_success, ansible_result = generate_ansible_script(output_dir, terraform_output)

            if not ansible_success:
                current_app.logger.warning(f"[{task_id}] Ansible configuration failed: {ansible_result}")
            else:
                current_app.logger.info(f"[{task_id}] Ansible configuration successful: {ansible_result}")

            timing_info['ansible_time'] = time.time() - step_start_time
            current_app.logger.info(f"[{task_id}] Ansible configuration time: {timing_info['ansible_time']:.2f}s")

        # Step 5: Package the resulting artifacts into a zip file
        zip_file_path = f"{output_dir}.zip"
        shutil.make_archive(output_dir, 'zip', output_dir)
        current_app.logger.info(f"[{task_id}] Artifacts zipped successfully to: {zip_file_path}")

        # Step 6: Encode the zip file in base64 to send in JSON payload
        with open(zip_file_path, "rb") as f:
            encoded_zip = base64.b64encode(f.read()).decode('utf-8')

        # Step 7: Send a success callback with the base64-encoded zip file
        result_data = {
            "message": "Scenario processed and deployed successfully." if tf_success else "Scenario processed successfully (deployment skipped).",
            "artifacts_zip_b64": encoded_zip,
            "terraform_success": tf_success,
            "terraform_output": terraform_output
        }
        send_callback(callback_url, task_id, 'SUCCESS', data=result_data)
        current_app.logger.info(f"[{task_id}] Successfully sent success callback to {callback_url}.")

        # Step 8: 计算总耗时并生成部署报告
        elapsed_time = time.time() - start_time
        timing_info['total_time'] = elapsed_time

        report = generate_deployment_report(
            task_id=task_id,
            scenario=scenario,
            terraform_output=terraform_output,
            tf_success=tf_success,
            ansible_success=ansible_success,
            elapsed_time=elapsed_time
        )
        # Print report to logger (will show in terminal 2)
        for line in report.split('\n'):
            current_app.logger.info(line)

        # Step 9: Save all outputs to dedicated scenario output directory
        _save_scenario_output(
            task_id=task_id,
            vsdl_script=vsdl_script,
            output_dir=output_dir,
            scenario=scenario,
            terraform_output=terraform_output,
            tf_success=tf_success,
            ansible_success=ansible_success,
            elapsed_time=elapsed_time
        )

        # Step 10: 保存实验结果（成功情况）
        _save_experiment_results(
            pdf_name=pdf_name,
            task_id=task_id,
            scenario=scenario,
            timing_info=timing_info,
            tf_success=tf_success,
            ansible_success=ansible_success,
            terraform_output=terraform_output
        )

    except Exception as e:
        error_message = f"Task {task_id} failed: {str(e)}"
        current_app.logger.error(error_message, exc_info=True)

        # 调试信息：更详细的错误报告
        import traceback
        current_app.logger.error(f"[{task_id}] 详细错误追踪: {traceback.format_exc()}")

        # 计算总耗时
        elapsed_time = time.time() - start_time
        timing_info['total_time'] = elapsed_time

        # Save failed scenario output if we have the VSDL script
        if 'vsdl_script' in locals():
            _save_scenario_output(
                task_id=task_id,
                vsdl_script=vsdl_script,
                output_dir=output_dir,
                scenario=scenario,
                terraform_output=None,
                tf_success=False,
                ansible_success=False,
                elapsed_time=elapsed_time,
                error_message=error_message
            )

        # 保存实验结果（失败情况）
        _save_experiment_results(
            pdf_name=pdf_name,
            task_id=task_id,
            scenario=scenario,
            timing_info=timing_info,
            tf_success=False,
            ansible_success=False,
            terraform_output=None,
            error_message=error_message
        )

        # Send a failure callback
        send_callback(callback_url, task_id, 'FAILED', error=error_message)
        current_app.logger.info(f"[{task_id}] Successfully sent failure callback to {callback_url}.")
        
    
    finally:
        # Clean up: remove the local file and any generated directories/zip files
        if os.path.exists(file_path):
            os.remove(file_path)
            current_app.logger.info(f"[{task_id}] Cleaned up input file: {file_path}")
        if output_dir and os.path.exists(output_dir):
            shutil.rmtree(output_dir)
            current_app.logger.info(f"[{task_id}] Cleaned up output directory: {output_dir}")
        
        # Check if zip_file_path was created before trying to delete it
        if 'zip_file_path' in locals() and os.path.exists(zip_file_path):
             os.remove(zip_file_path)
             current_app.logger.info(f"[{task_id}] Cleaned up zip file: {zip_file_path}")


def _get_terraform_outputs(output_dir: str) -> dict:
    """
    Extract IP addresses and other outputs from Terraform.

    Args:
        output_dir: Path to the compilation output directory

    Returns:
        Dict with structured IP mapping:
        {
            'node_name': {
                'floating_ip': '203.0.113.100',
                'network_ip': '172.24.4.191'
            }
        }
    """
    import subprocess
    import re

    terraform_dir = os.path.join(output_dir, 'terraform')
    if not os.path.exists(terraform_dir):
        terraform_dir = os.path.join(output_dir, 'ttu_0')

    if not os.path.exists(terraform_dir):
        return {}

    try:
        # Run terraform output -json to get outputs
        result = subprocess.run(
            ['terraform', '-chdir=' + terraform_dir, 'output', '-json'],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            current_app.logger.warning(f"Failed to get terraform outputs: {result.stderr}")
            return {}

        outputs = json.loads(result.stdout)

        # Parse outputs into structured format
        # Terraform outputs format: {node_name}_ip (floating) and {node_name}_network_ip (internal)
        node_ips = {}

        for key, value in outputs.items():
            ip_value = value.get('value', '')
            if not ip_value:
                continue

            # Match pattern: {node_name}_ip (floating IP) or {node_name}_network_ip (internal IP)
            # The node name may contain underscores, so we need to handle this carefully

            if key.endswith('_network_ip'):
                # Internal/fixed IP
                node_name = key[:-11]  # Remove '_network_ip'
                if node_name not in node_ips:
                    node_ips[node_name] = {}
                node_ips[node_name]['network_ip'] = ip_value
            elif key.endswith('_ip') and not key.endswith('_network_ip'):
                # Floating IP
                node_name = key[:-3]  # Remove '_ip'
                if node_name not in node_ips:
                    node_ips[node_name] = {}
                node_ips[node_name]['floating_ip'] = ip_value

        current_app.logger.info(f"Extracted Terraform outputs (structured): {node_ips}")
        return node_ips

    except Exception as e:
        current_app.logger.warning(f"Error getting terraform outputs: {e}")
        return {}


def generate_deployment_report(
    task_id: str,
    scenario,
    terraform_output: dict,
    tf_success: bool,
    ansible_success: bool,
    elapsed_time: float
) -> str:
    """
    生成美观的部署报告

    Args:
        task_id: 任务 ID
        scenario: VSDL Scenario 对象
        terraform_output: Terraform 输出的 IP 信息
        tf_success: Terraform 是否成功
        ansible_success: Ansible 是否成功
        elapsed_time: 总耗时（秒）

    Returns:
        格式化的报告字符串
    """
    lines = []

    # 标题
    lines.append("")
    lines.append("╔" + "═" * 78 + "╗")
    lines.append("║" + " VSDL 部署报告 ".center(78, "═") + "║")
    lines.append("╚" + "═" * 78 + "╝")
    lines.append("")

    # 基本信息
    lines.append("┌" + "─" * 38 + " 基本信息 " + "─" * 29 + "┐")
    lines.append(f"│ 任务 ID:     {task_id}")
    lines.append(f"│ 场景名称:    {scenario.name if scenario else 'N/A'}")
    lines.append(f"│ 场景时长:    {scenario.duration if scenario else 'N/A'} TTU")
    lines.append(f"│ 总耗时:      {elapsed_time:.1f} 秒 ({elapsed_time/60:.1f} 分钟)")
    lines.append(f"│ 完成时间:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("└" + "─" * 78 + "┘")
    lines.append("")

    # 部署状态总览
    lines.append("┌" + "─" * 32 + " 部署状态总览 " + "─" * 32 + "┐")
    tf_status = "✅ 成功" if tf_success else "❌ 失败"
    ansible_status = "✅ 成功" if ansible_success else ("⚠️ 部分失败" if tf_success else "⏭️ 跳过")
    overall_status = "✅ 成功" if (tf_success and ansible_success) else ("⚠️ 部分成功" if tf_success else "❌ 失败")

    lines.append(f"│ Terraform 部署:  {tf_status}")
    lines.append(f"│ Ansible 配置:    {ansible_status}")
    lines.append(f"│ 总体状态:        {overall_status}")
    lines.append("└" + "─" * 78 + "┘")
    lines.append("")

    # 网络拓扑
    if scenario and scenario.networks:
        lines.append("┌" + "─" * 33 + " 网络拓扑 " + "─" * 35 + "┐")
        lines.append("│")
        for network in scenario.networks:
            lines.append(f"│ 🌐 网络: {network.name}")
            lines.append(f"│    地址范围: {network.address_range or 'N/A'}")
            lines.append(f"│    网关:     {'是' if network.has_internet_gateway else '否'}")
            if network.connections:
                lines.append("│    连接节点:")
                for conn in network.connections:
                    ip_info = f" ({conn.ip_address})" if conn.ip_address else ""
                    lines.append(f"│       • {conn.node_name}{ip_info}")
            lines.append("│")
        lines.append("└" + "─" * 78 + "┘")
        lines.append("")

    # 虚拟机节点
    if scenario and scenario.nodes:
        lines.append("┌" + "─" * 31 + " 虚拟机节点 " + "─" * 34 + "┐")
        lines.append("│")
        for node in scenario.nodes:
            # 获取 IP 地址
            node_ip_info = terraform_output.get(node.name, {}) if terraform_output else {}
            floating_ip = node_ip_info.get('floating_ip', 'N/A')
            network_ip = node_ip_info.get('network_ip', 'N/A')

            lines.append(f"│ 🖥️  节点: {node.name}")
            lines.append(f"│    操作系统: {node.os_image or 'N/A'}")

            # 硬件配置
            ram_info = f"{node.ram_value} GB" if node.ram_value else "N/A"
            if node.ram_operator:
                ram_info = f"{node.ram_operator.value} {ram_info}"
            disk_info = f"{node.disk_value} GB" if node.disk_value else "N/A"
            if node.disk_operator:
                disk_info = f"{node.disk_operator.value} {disk_info}"

            lines.append(f"│    CPU:      {node.vcpu or 'N/A'} vCPU")
            lines.append(f"│    内存:     {ram_info}")
            lines.append(f"│    磁盘:     {disk_info}")
            lines.append(f"│    浮动 IP:  {floating_ip}")
            lines.append(f"│    内网 IP:  {network_ip}")

            # 软件列表
            if node.software_mounts:
                lines.append("│    软件:")
                for sw in node.software_mounts:
                    version_info = f" v{sw.version}" if sw.version else ""
                    status_icon = "✅" if tf_success else "⏳"
                    lines.append(f"│       {status_icon} {sw.name}{version_info}")
            lines.append("│")
        lines.append("└" + "─" * 78 + "┘")
        lines.append("")

    # 漏洞信息
    if scenario and scenario.vulnerabilities:
        lines.append("┌" + "─" * 31 + " 漏洞信息 " + "─" * 36 + "┐")
        lines.append("│")
        for vuln in scenario.vulnerabilities:
            lines.append(f"│ 🔓 漏洞: {vuln.name}")
            if vuln.cve_id:
                lines.append(f"│    CVE:           {vuln.cve_id}")
            if vuln.vulnerable_software:
                version_info = f" {vuln.vulnerable_version}" if vuln.vulnerable_version else ""
                lines.append(f"│    受影响软件:    {vuln.vulnerable_software}{version_info}")
            if vuln.hosted_on_node:
                lines.append(f"│    托管节点:      {vuln.hosted_on_node}")
            if vuln.requires_vulnerabilities:
                lines.append(f"│    前置漏洞:      {', '.join(vuln.requires_vulnerabilities)}")
            if vuln.triggers_vulnerabilities:
                lines.append(f"│    触发漏洞:      {', '.join(vuln.triggers_vulnerabilities)}")
            lines.append("│")
        lines.append("└" + "─" * 78 + "┘")
        lines.append("")

    # 底部
    lines.append("╔" + "═" * 78 + "╗")
    lines.append("║" + " 部署完成 ".center(78, "═") + "║")
    lines.append("╚" + "═" * 78 + "╝")
    lines.append("")

    return "\n".join(lines) 