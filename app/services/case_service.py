import json
import shutil
import requests
from flask import current_app
import os
import subprocess
import tempfile
import time
import re
import httpx
import threading
import logging
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.agents import Tool, create_react_agent, AgentExecutor
from langchain_core.prompts import PromptTemplate as CorePromptTemplate
from langchain_core.callbacks import BaseCallbackHandler
from typing import Tuple, Any, Dict, Any

# Create a module-level logger for safe logging (works outside Flask context)
_safe_logger = logging.getLogger(__name__)

def _safe_log(level: str, message: str):
    """
    Safe logging function that works both inside and outside Flask context.
    Uses current_app.logger when available, falls back to standard logging.
    """
    try:
        if level == "error":
            current_app.logger.error(message)
        elif level == "warning":
            current_app.logger.warning(message)
        else:
            current_app.logger.info(message)
    except (RuntimeError, AttributeError):
        # Outside Flask context - use standard logging
        if level == "error":
            _safe_logger.error(message)
        elif level == "warning":
            _safe_logger.warning(message)
        else:
            _safe_logger.info(message)


# ============================================================================
# LangChain Callback Handler for Debugging
# ============================================================================
class AgentDebugCallbackHandler(BaseCallbackHandler):
    """
    Custom callback handler to track LLM calls and agent execution steps.
    Logs detailed timing information for debugging slow/hanging agent calls.
    """

    def __init__(self):
        self.llm_start_times = {}
        self.chain_start_times = {}
        self.tool_start_times = {}

    def _log(self, message: str, level: str = "INFO"):
        """Log with timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        try:
            if level == "ERROR":
                current_app.logger.error(f"[AGENT DEBUG {timestamp}] {message}")
            elif level == "WARNING":
                current_app.logger.warning(f"[AGENT DEBUG {timestamp}] {message}")
            else:
                current_app.logger.info(f"[AGENT DEBUG {timestamp}] {message}")
        except:
            print(f"[AGENT DEBUG {timestamp}] {message}")

    def on_llm_start(self, serialized, prompts, **kwargs):
        """Called when LLM starts generating"""
        run_id = str(kwargs.get('run_id', 'unknown'))
        self.llm_start_times[run_id] = time.time()

        prompt_preview = ""
        if prompts:
            prompt_preview = prompts[0][:200] + "..." if len(prompts[0]) > 200 else prompts[0]
            prompt_preview = prompt_preview.replace('\n', ' ')

        self._log(f"🚀 LLM_CALL_START (run_id={run_id[:8]})")
        self._log(f"   Prompt preview: {prompt_preview}")

        # Log model info if available
        invocation_params = kwargs.get('invocation_params', {})
        if invocation_params:
            model = invocation_params.get('model_name', invocation_params.get('model', 'unknown'))
            self._log(f"   Model: {model}")

    def on_llm_end(self, response, **kwargs):
        """Called when LLM finishes generating"""
        run_id = str(kwargs.get('run_id', 'unknown'))

        if run_id in self.llm_start_times:
            elapsed = time.time() - self.llm_start_times[run_id]
            del self.llm_start_times[run_id]
        else:
            elapsed = 0

        # Get token usage if available
        token_usage = ""
        if hasattr(response, 'llm_output') and response.llm_output:
            token_info = response.llm_output.get('token_usage', {})
            if token_info:
                token_usage = f" (tokens: {token_info.get('total_tokens', 'N/A')})"

        output_preview = ""
        if hasattr(response, 'generations') and response.generations:
            gen = response.generations[0]
            if hasattr(gen, 'text'):
                output_preview = gen.text[:100] + "..." if len(gen.text) > 100 else gen.text
            elif hasattr(gen, 'message'):
                output_preview = gen.message.content[:100] + "..." if len(gen.message.content) > 100 else gen.message.content

        self._log(f"✅ LLM_CALL_END (run_id={run_id[:8]}) - {elapsed:.2f}s{token_usage}")
        self._log(f"   Output preview: {output_preview.replace(chr(10), ' ')}")

    def on_llm_error(self, error, **kwargs):
        """Called when LLM call fails"""
        run_id = str(kwargs.get('run_id', 'unknown'))

        if run_id in self.llm_start_times:
            elapsed = time.time() - self.llm_start_times[run_id]
            del self.llm_start_times[run_id]
        else:
            elapsed = 0

        self._log(f"❌ LLM_CALL_ERROR (run_id={run_id[:8]}) - {elapsed:.2f}s", "ERROR")
        self._log(f"   Error: {str(error)}", "ERROR")

    def on_tool_start(self, serialized, input_str, **kwargs):
        """Called when a tool starts execution"""
        tool_name = serialized.get('name', 'unknown')
        self.tool_start_times[tool_name] = time.time()

        input_preview = str(input_str)[:200] + "..." if len(str(input_str)) > 200 else str(input_str)

        self._log(f"🔧 TOOL_START: {tool_name}")
        self._log(f"   Input preview: {input_preview.replace(chr(10), ' ')}")

    def on_tool_end(self, output, **kwargs):
        """Called when a tool finishes execution"""
        # Get tool name from serialized if available
        serialized = kwargs.get('serialized', {})
        tool_name = serialized.get('name', 'unknown')

        if tool_name in self.tool_start_times:
            elapsed = time.time() - self.tool_start_times[tool_name]
            del self.tool_start_times[tool_name]
        else:
            elapsed = 0
            # Try to find by searching all keys
            for key in list(self.tool_start_times.keys()):
                elapsed = time.time() - self.tool_start_times[key]
                del self.tool_start_times[key]
                break

        output_preview = str(output)[:200] + "..." if len(str(output)) > 200 else str(output)

        self._log(f"✅ TOOL_END: {tool_name} - {elapsed:.2f}s")
        self._log(f"   Output preview: {output_preview.replace(chr(10), ' ')}")

    def on_tool_error(self, error, **kwargs):
        """Called when a tool execution fails"""
        serialized = kwargs.get('serialized', {})
        tool_name = serialized.get('name', 'unknown')

        if tool_name in self.tool_start_times:
            elapsed = time.time() - self.tool_start_times[tool_name]
            del self.tool_start_times[tool_name]
        else:
            elapsed = 0

        self._log(f"❌ TOOL_ERROR: {tool_name} - {elapsed:.2f}s", "ERROR")
        self._log(f"   Error: {str(error)}", "ERROR")

    def on_chain_start(self, serialized, inputs, **kwargs):
        """Called when a chain starts execution"""
        chain_name = serialized.get('name', 'unknown')
        self.chain_start_times[chain_name] = time.time()
        self._log(f"⛓️ CHAIN_START: {chain_name}")

    def on_chain_end(self, outputs, **kwargs):
        """Called when a chain finishes execution"""
        serialized = kwargs.get('serialized', {})
        chain_name = serialized.get('name', 'unknown')

        if chain_name in self.chain_start_times:
            elapsed = time.time() - self.chain_start_times[chain_name]
            del self.chain_start_times[chain_name]
        else:
            elapsed = 0

        self._log(f"✅ CHAIN_END: {chain_name} - {elapsed:.2f}s")

    def on_agent_action(self, action, **kwargs):
        """Called when agent takes an action"""
        self._log(f"🤖 AGENT_ACTION: {action.tool}")
        self._log(f"   Action input preview: {str(action.tool_input)[:100]}")

    def on_agent_finish(self, finish, **kwargs):
        """Called when agent finishes"""
        self._log(f"🏁 AGENT_FINISH")
        if hasattr(finish, 'return_values'):
            output = finish.return_values.get('output', '')
            output_preview = str(output)[:100] + "..." if len(str(output)) > 100 else str(output)
            self._log(f"   Final output preview: {output_preview.replace(chr(10), ' ')}")


# Global callback instance
_agent_debug_callback = AgentDebugCallbackHandler()

# Import Python VSDL Compiler
from app.services.vsdl_compiler import VSDLCompiler, CompilationResult

# Import these modules only when needed to avoid circular imports
def get_vsdl_fixer():
    """Lazy import vsdl_fixer to avoid circular imports"""
    from app.utils.vsdl_fixer import fix_common_unsat_issues
    return fix_common_unsat_issues

def get_openstack_exceptions():
    """Lazy import openstack exceptions"""
    import openstack.exceptions
    return openstack.exceptions

# Import URL fixer
def get_url_fixer():
    """Lazy import URL fixer to avoid circular imports"""
    from app.utils.vsdl_auth_fix_fixed_v2 import fix_openstack_auth_url
    return fix_openstack_auth_url

def get_unsat_analyzers():
    """Lazy import unsat analyzers to avoid circular imports"""
    from app.unsat_analyzer import analyze_unsat
    from app.unsat_analyzer_advanced import analyze_unsat_advanced
    return analyze_unsat, analyze_unsat_advanced

def get_openstack_service_func():
    """Lazy import openstack service to avoid circular imports"""
    from app.services.openstack_service import get_openstack_service
    return get_openstack_service

def _validate_vsdl_fallback(vsdl_script: str) -> Tuple[bool, str]:
    """
    Fallback VSDL validator that works without OpenStack or VSDLC compiler.
    This provides basic syntax and structure validation.
    """
    try:
        current_app.logger.info("[FALLBACK VALIDATOR] Starting fallback validation...")

        # Basic checks
        if not vsdl_script.strip():
            return False, "Empty script"

        if len(vsdl_script) < 50:
            return False, "Script too short to be valid"

        # Check for scenario block
        if "scenario" not in vsdl_script.lower():
            return False, "Missing scenario block"

        # Check for network blocks
        networks = re.findall(r'network\s+(\w+)', vsdl_script)
        if not networks:
            return False, "No network blocks found"

        # Check for node blocks
        nodes = re.findall(r'node\s+(\w+)', vsdl_script)
        if not nodes:
            return False, "No node blocks found"

        # Basic syntax checks
        syntax_issues = []

        # Check for balanced braces
        open_braces = vsdl_script.count('{')
        close_braces = vsdl_script.count('}')
        if open_braces != close_braces:
            syntax_issues.append(f"Unbalanced braces: {open_braces} open, {close_braces} close")

        # Check for semicolons in appropriate places
        statements = re.findall(r'addresses range|node OS|ram|disk|vcpu|gateway|mounts', vsdl_script)
        for statement in statements:
            # Find the line with this statement
            lines = vsdl_script.split('\n')
            for line in lines:
                if statement in line and 'node OS' not in line:  # OS can be without semicolon in some contexts
                    if ';' not in line and '{' not in line and '}' not in line:
                        # Check if it's a standalone statement that should have a semicolon
                        if any(keyword in line for keyword in ['addresses range', 'ram larger than', 'ram equal to', 'disk size', 'disk larger than', 'vcpu equal to', 'gateway has', 'mounts software']):
                            syntax_issues.append(f"Missing semicolon: {line.strip()}")

        # Check network interconnectivity
        if len(networks) > 1:
            for i, network in enumerate(networks):
                for j, other_network in enumerate(networks):
                    if i != j:
                        # Check if network A connects to network B
                        connection_pattern = f'node {other_network} is connected'
                        if connection_pattern not in vsdl_script:
                            syntax_issues.append(f"Missing connection: {network} -> {other_network}")

        # Check for common issues
        if 'gateway has direct access to the Internet' not in vsdl_script and len(networks) > 0:
            # At least one network should be a public network with internet access
            public_network_found = any(f'network {net}' in vsdl_script and '{' in vsdl_script for net in networks)
            if public_network_found:
                # Check if any network has gateway access
                gateway_found = 'gateway has direct access to the Internet' in vsdl_script
                if not gateway_found:
                    # This is not necessarily an error, just a warning
                    current_app.logger.warning("[FALLBACK VALIDATOR] No internet gateway found - this may be intentional")

        # Check IP addresses
        ip_pattern = r'\d+\.\d+\.\d+\.\d+'
        ips = re.findall(ip_pattern, vsdl_script)
        if not ips:
            syntax_issues.append("No IP addresses found")

        # Check resource constraints
        resource_issues = []
        if 'ram larger than' not in vsdl_script and 'ram equal to' not in vsdl_script:
            resource_issues.append("Missing RAM constraints")
        if 'disk size' not in vsdl_script and 'disk larger than' not in vsdl_script:
            resource_issues.append("Missing disk constraints")
        if 'vcpu equal to' not in vsdl_script:
            resource_issues.append("Missing vCPU constraints")

        syntax_issues.extend(resource_issues)

        if syntax_issues:
            return False, f"Fallback validation failed:\n" + "\n".join(syntax_issues)

        current_app.logger.info("[FALLBACK VALIDATOR] Fallback validation passed")
        return True, "Fallback validation successful"

    except Exception as e:
        current_app.logger.error(f"[FALLBACK VALIDATOR] Error during fallback validation: {e}")
        return False, f"Fallback validation error: {str(e)}"

def _fallback_minimal_vsdl() -> str:
    """
    Guaranteed-valid minimal VSDL fallback.
    """
    return """scenario fallback_scenario duration 5 {
  network PublicNetwork {
    addresses range is 203.0.113.0/24;
    gateway has direct access to the Internet;
  }

  node DummyNode {
    ram equal to 2GB;
    disk size equal to 20GB;
    vcpu equal to 1;
    node OS is "ubuntu20";
  }

  network PublicNetwork {
    node DummyNode is connected;
    node DummyNode has IP 203.0.113.10;
  }
}"""

def _is_probably_valid_vsdl(script: str) -> bool:
    """
    Fast, strict pre-check to prevent non-VSDL content from entering VSDLC.
    """
    if not script:
        return False

    s = script.strip()

    # 1. 必须以 scenario 开头
    if not re.match(r'^scenario\s+\w+', s):
        return False

    # 2. 必须包含大括号
    if '{' not in s or '}' not in s:
        return False

    # 3. 禁止明显的失败文本（但不包括历史错误消息，只检查最终状态）
    # 这些词出现在脚本开头或结尾的单独行才认为是失败
    forbidden_patterns = [
        r'^agent stopped',
        r'^iteration limit',
        r'^time limit',
        r'^error:',
    ]
    s_lower = s.lower()
    for pattern in forbidden_patterns:
        if re.search(pattern, s_lower, re.MULTILINE):
            return False

    return True
def _extract_code_from_llm_output(output: str, lang: str = "vsdl") -> str:
    """Extracts code from a markdown code block."""
    current_app.logger.info(f"[DEBUG] _extract_code_from_llm_output called with output length: {len(output)}")

    # A more robust pattern to handle variations in markdown code blocks
    pattern = r'```(?:{lang_pattern})?\s*\n(.*?)\n\s*```'.format(lang_pattern=re.escape(lang))
    match = re.search(pattern, output, re.DOTALL)
    if match:
        extracted_code = match.group(1).strip()
        current_app.logger.info(f"[DEBUG] Extracted code length: {len(extracted_code)}")
        # Check if the extracted code contains our fixer's signature
        if "/* VSDL FIXER:" in extracted_code:
            current_app.logger.info("[DEBUG] Extracted code contains VSDL fixer signature")
        else:
            current_app.logger.warning("[DEBUG] Extracted code does NOT contain VSDL fixer signature - potential data loss!")
        return extracted_code
    # Fallback for outputs that might just be the code itself
    current_app.logger.warning("[DEBUG] No markdown block found, returning raw output")
    return output.strip()
def _extract_vsdl_strict(output: str) -> str:
    """
    ONLY accept ```vsdl``` fenced code blocks.
    """
    pattern = r"```vsdl\s*(.*?)\s*```"
    m = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

def _auto_fix_config_syntax(vsdl_script: str) -> str:
    """
    Auto-fix common config syntax errors in VSDL scripts.
    VSDL parser expects: config "key=value" (STRING format, no escaped quotes)

    Fixes:
    1. config { key="value" } -> config "key=value"
    2. config "key=\"value\"" -> config "key=value"
    """
    # Pattern 1: config { ... } -> config "key=value"
    def fix_brace_config(match):
        content = match.group(1).strip()
        # Parse key=value pairs
        pairs = []
        kv_pattern = r'(\w+)=["\']?([^"\';\s]+)["\']?'
        for kv_match in re.finditer(kv_pattern, content):
            key = kv_match.group(1)
            value = kv_match.group(2)
            pairs.append(f'{key}={value}')

        if pairs:
            return 'config "' + ', '.join(pairs) + '"'
        return match.group(0)

    # Match config { ... }
    fixed = re.sub(
        r'config\s*\{\s*([^{}]+)\s*\}',
        fix_brace_config,
        vsdl_script,
        flags=re.DOTALL
    )

    # Pattern 2: config "key=\"value\"" -> config "key=value"
    # Remove escaped quotes inside config strings
    def fix_escaped_quotes(match):
        content = match.group(1)
        # Remove escaped quotes: \" -> "
        unescaped = content.replace('\\"', '"')
        # Remove quotes around values: key="value" -> key=value
        unescaped = re.sub(r'(\w+)="([^"]*)"', r'\1=\2', unescaped)
        return f'config "{unescaped}"'

    # Match config "..." containing escaped quotes
    fixed = re.sub(
        r'config\s+"([^"]*\\"[^"]*)"',
        fix_escaped_quotes,
        fixed
    )

    return fixed

def _validate_vsdl_for_syntax(vsdl_script: str) -> Tuple[bool, str, str]:
    """
    Validate VSDL script syntax and constraints using Python VSDL Compiler.
    Validation is successful only if syntax is correct AND constraints are satisfiable.

    Returns:
        Tuple[bool, str, str]: (is_valid, report, fixed_script)
        - fixed_script contains auto-fixed config syntax if applicable
    """
    try:
        current_app.logger.info("[VSDL PYTHON COMPILER] Starting validation...")

        # Auto-fix common config syntax errors before validation
        fixed_script = _auto_fix_config_syntax(vsdl_script)
        if fixed_script != vsdl_script:
            current_app.logger.info("[VSDL PYTHON COMPILER] Applied config syntax auto-fix")

        # Create compiler instance
        compiler = VSDLCompiler()

        # Validate the script
        result = compiler.validate(fixed_script)

        if result.is_sat:
            current_app.logger.info("[VSDL PYTHON COMPILER] Validation successful")
            if result.warnings:
                for warning in result.warnings:
                    current_app.logger.warning(f"[VSDL PYTHON COMPILER] Warning: {warning}")
            return True, "Validation successful", fixed_script
        else:
            # Format error messages
            error_messages = []
            for error in result.errors:
                if hasattr(error, 'type') and hasattr(error, 'message'):
                    error_messages.append(f"- [{error.type}] {error.message}")
                    if hasattr(error, 'location') and error.location:
                        error_messages[-1] += f" (Location: {error.location})"
                else:
                    error_messages.append(f"- {str(error)}")

            error_text = "\n".join(error_messages)
            current_app.logger.error(f"[VSDL PYTHON COMPILER] Validation failed:\n{error_text}")

            return False, f"VSDL Validation Failed:\n{error_text}", fixed_script

    except Exception as e:
        current_app.logger.error(f"[VSDL PYTHON COMPILER] Validation error: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())

        # Fall back to basic validation on error
        return _validate_vsdl_fallback(vsdl_script)



def get_VSDL_script_local(file_path: str):
    """
    Generates VSDL script locally using a LangChain-based workflow.
    This workflow includes:
    1. Extracting information from the source file into JSON.
    2. Converting the JSON into a VSDL script.
    3. Validating the script using a local compiler and attempting to fix it in a loop.
    
    Args:
        file_path: Path to the source case file.
        
    Returns:
        Generated VSDL script as a string.
    """
    start_time = time.perf_counter()  # Start the timer
    try:
        # 1. Configuration and Setup
        current_app.logger.info(f"Starting local VSDL generation from file {file_path}")

        # LLM Configuration from Flask app config
        # Create a fresh httpx client for each LLM instance with Connection: close header
        # This forces the server to close the connection after each response, avoiding
        # the "peer closed connection without sending complete message body" error
        # that occurs when DeepSeek server closes idle connections mid-stream.
        current_app.logger.info("[LLM DEBUG] Creating httpx client with timeout=300s...")
        http_client = httpx.Client(
            timeout=httpx.Timeout(300.0, connect=60.0, read=300.0, write=60.0, pool=60.0),
            headers={"Connection": "close"}  # Force connection close after each request
        )

        current_app.logger.info("[LLM DEBUG] Creating ChatOpenAI instance...")
        current_app.logger.info(f"[LLM DEBUG] API URL: {current_app.config.get('LLM_API_URL')}")
        current_app.logger.info(f"[LLM DEBUG] Model: {current_app.config.get('LLM_MODEL','deepseek-chat')}")
        current_app.logger.info(f"[LLM DEBUG] Temperature: 0.1, Max retries: 3")

        llm = ChatOpenAI(
            temperature=0.1,
            openai_api_base=current_app.config.get('LLM_API_URL'),
            openai_api_key=current_app.config.get('LLM_API_KEY'),
            model=current_app.config.get('LLM_MODEL','deepseek-chat'),
            http_client=http_client,
            max_retries=3  # Increase retries for transient failures
        )
        current_app.logger.info("[LLM DEBUG] ChatOpenAI instance created successfully")
        
        # Initialize Services
        openstack_service = get_openstack_service_func()()
        
        # Get dynamic platform constraints from OpenStack
        platform_constraints = openstack_service.get_image_constraints()

        # Master VSDL grammar rules to be shared across prompts
        # NOTE: This template must be "clean" with single braces for the Agent to learn correctly.
        # We will escape it dynamically when needed for Python's .format() method.
        vsdl_rules_template = """### **I. 通用语法规则 (MANDATORY)**

1.  **顶层结构**: 整个文件必须由一个 `scenario` 块包裹。
    ```vsdl
    scenario <场景名称> duration 5 {{
      // 所有 Network 和 Node 定义都在这里
    }}
    ```
2.  **语句结束符**: 每个独立的约束或定义语句（在 `{{}}` 块内）**必须**以分号 `;` 结尾。
3.  **禁止字符**: 任何标识符（如场景名称、网络名称、节点名称）中 **严禁** 使用连字符 `-`。请使用下划线 `_` 或驼峰命名法代替。例如，`my-scenario` 是 **错误** 的，应写为 `my_scenario` 或 `myScenario`。

### **II. 网络定义与互联 (CRITICAL)**

1.  **基础定义**:
    -   使用 `network <网络名称> {{...}}` 定义网络。
    -   网络内部必须指定地址范围: `addresses range is <CIDR>;`
2.  **节点接入网络 (VERY IMPORTANT)**:
    -   要将一个`Node`（如虚拟机）连接到网络中，必须在 `network` 模块内使用以下两个语句：
    -   `node <节点名称> is connected;`
    -   `node <节点名称> has IP <IP地址>;`
    -   **示例**:
      ```vsdl
      network PublicNetwork {{
          addresses range is 203.0.113.0/24;
          // 将 PublicFileServer 节点接入
          node PublicFileServer is connected;
          node PublicFileServer has IP 203.0.113.100;
      }}
      ```
3.  **公共网络访问外网 (CRITICAL)**:
    -   如果一个网络是公共网络（Public Network），需要直接访问互联网，则其定义中**必须**包含 `gateway has direct access to the Internet;` 语句。
4.  **网络之间互联 (CRITICAL)**:
    -   网络互联是节点接入的特殊情况，规则是**双向声明**。
    -   要连接 `NetworkA` 和 `NetworkB`，你**必须**在**双方**的网络定义中都声明对方为节点。
    -   在 `NetworkA` 中添加: `node NetworkB is connected;` 并分配IP `node NetworkB has IP <ip_for_b_in_a>;`
    -   在 `NetworkB` 中添加: `node NetworkA is connected;` 并分配IP `node NetworkA has IP <ip_for_a_in_b>;`
    -   **严禁**创建单独的网关节点 (如 `PublicGW`)。直接使用网络名称作为节点进行连接。
5.  **网络互联正确示例**:
    ```vsdl
    // network PublicNetwork 连接了 network VictimPrivate, 并且可以访问外网
    network PublicNetwork {{
        addresses range is 203.0.113.0/24;
        node VictimPrivate is connected;
        node VictimPrivate has IP 203.0.113.202;
        gateway has direct access to the Internet; // 关键语句
    }}

    // network VictimPrivate 也必须反向连接 network PublicNetwork
    network VictimPrivate {{
        addresses range is 172.16.1.0/24;
        node PublicNetwork is connected;
        node PublicNetwork has IP 172.16.1.254;
    }}
    ```

### **III. 节点定义与平台约束 (MANDATORY)**

1.  **硬件约束语法**:
    -   `vcpu equal to <核数>;`
    -   `ram larger than <大小>GB;` (也支持 `equal to`, `smaller than`)
    -   `disk size equal to <大小>GB;`
    -   `disk larger than <大小>GB;` (或 `smaller than`)
    -   **注意**: 在`disk`语法中, `size`关键字只和`equal to`一起使用。
2.  **软件约束语法**:
    -   **操作系统**: 使用 `node OS is "<镜像名称>";` 语句定义操作系统，名称**必须**用双引号包裹。
    -   **安装软件**: 使用 `mounts software` 语句定义需要安装的软件。所有部分都在一行内，以分号结束。
        - 基础语法: `mounts software <软件名称>;`
        - 带版本: `mounts software <软件名称> version <版本号>;`
        - 带依赖: `mounts software <软件名称> with <依赖1>, <依赖2>;`
        - **【重要】带配置**: `config` 后面**必须**使用花括号 `{{ }}` 包裹键值对！
          - ⚠️ **绝对禁止**在 `config` 后面使用字符串！这是最常见的语法错误！
          - ✅ **正确**: `mounts software bonitasoft version 7.13.0 config {{ port="8080" }};`
          - ✅ **正确**: `mounts software nginx version 1.18 config {{ listen="80" }};`
          - ❌ **错误**: `mounts software bonitasoft config "port=8080";`  ← 这样写会导致解析失败！
          - ❌ **错误**: `mounts software bonitasoft config "port=\"8080\"";`  ← 这是错误的！
        - **组合示例**:
          ```vsdl
          // 安装带版本和配置的软件（无依赖）
          mounts software bonitasoft version 7.13.0 config {{ port="8080" }};

          // 安装带版本、依赖和配置的软件
          mounts software bonitasoft version 7.13.0 with java config {{ port="8080" }};

          // 安装带版本的软件（无配置）
          mounts software apache-tomcat version 9.0.50;
          ```
{platform_constraints}
4.  **【重要】操作系统选择约束**:
    -   **严禁使用Windows系列操作系统**（windows、win10、win2019、windows_server等），因为Windows镜像当前不可用。
    -   **严禁使用ubuntu22**（镜像不可用），如果案例中涉及Ubuntu系统，只能使用 `ubuntu20`、`ubuntu18` 或 `ubuntu16`。
    -   攻击机节点统一使用 `kali` 或 `ubuntu20`。
    -   靶机节点统一使用 `ubuntu20`、`ubuntu18`、`ubuntu16` 或其他Linux发行版（如 `centos-7`、`openeuler20.03`）。
5.  **节点定义正确示例**:
    ```vsdl
    node WebServerNode {{
      ram larger than 8GB;
      disk size equal to 160GB; // 请确保此值满足平台约束
      vcpu equal to 4;
      node OS is "ubuntu20"; // 从可用列表中选择，并使用引号
      mounts software apache version 2.4.41; // 安装软件
    }}
    ```

### **IV. 漏洞拓扑定义 (NEW - 用于描述攻击链)**

1.  **基础语法**:
    -   使用 `vulnerability <漏洞名称> {{ ... }}` 定义漏洞节点
    -   `vulnerable software <软件名> version <版本>;` 指定存在漏洞的软件
    -   `cve id is "CVE-XXXX-XXXX";` 指定CVE编号（用双引号包裹）

2.  **漏洞依赖关系**:
    -   `depends on <软件名>;` 指定触发漏洞所需的软件依赖
    -   `requires vulnerability <漏洞名>;` 指定需要先利用的前置漏洞
    -   `triggers vulnerability <漏洞名>;` 指定此漏洞可以触发的其他漏洞

3.  **托管节点**:
    -   `hosted on node <节点名>;` 指定漏洞所在的物理节点

4.  **完整示例**:
    ```vsdl
    // Log4Shell漏洞定义
    vulnerability Log4Shell {{
      vulnerable software log4j version 2.14.1;
      cve id is "CVE-2021-44228";
      depends on jdk;
      depends on apache-tomcat;
      hosted on node VulnerableServer;
    }}

    // 攻击者的利用工具
    vulnerability JNDIInjection {{
      vulnerable software marshalsec;
      triggers vulnerability Log4Shell;  // 可以触发Log4Shell
      hosted on node AttackerMachine;
    }}

    // 后续攻击链 - 数据库访问
    vulnerability DataAccess {{
      vulnerable software mysql version 8.0;
      requires vulnerability Log4Shell;  // 需要先利用Log4Shell
      hosted on node DatabaseServer;
    }}
    ```

5.  **使用场景**:
    -   根据攻击案例JSON中的"靶场原型系统分析.原子靶标"提取漏洞软件
    -   根据攻击案例JSON中的"攻防模型构建.攻击行动抽象"推断攻击链关系
    -   将相关漏洞定义在对应节点上，构建完整的攻击拓扑图"""
        
        # ============================================================================
        # PDF Processing with marker + SiliconFlow LLM
        # Using new pdf_extractor module for better extraction quality
        # ============================================================================
        from app.services.pdf_extractor import extract_attack_scenario

        # Step 1: Extract structured attack scenario from PDF
        current_app.logger.info("=" * 60)
        current_app.logger.info("[STEP 1] Extracting attack scenario from PDF using marker + SiliconFlow...")
        current_app.logger.info(f"[STEP 1] Processing file: {file_path}")

        extract_start = time.time()

        try:
            # Call remote PDF-RE service for PDF parsing
            # use_ocr=True: Use marker (GPU accelerated) on PDF-RE server for high quality
            # timeout=600: Maximum time for PDF parsing
            extraction_result = extract_attack_scenario(
                pdf_path=file_path,
                max_content_length=12000,
                use_ocr=True,  # Use high-quality OCR mode on GPU server
                timeout=600,   # 10 minutes timeout for PDF parsing
                log_func=lambda msg: current_app.logger.info(msg)
            )

            extract_time = time.time() - extract_start
            current_app.logger.info(f"[STEP 1] ✅ Extraction completed in {extract_time:.2f}s")

            if not extraction_result["success"]:
                error_msg = extraction_result.get("error", "Unknown error")
                current_app.logger.error(f"[STEP 1] ❌ Extraction failed: {error_msg}")
                return f"// Generation failed: {error_msg}"

            # Get the extracted data as JSON string
            json_payload_str = json.dumps(extraction_result["data"], ensure_ascii=False)
            current_app.logger.info(f"[STEP 1] Extracted JSON length: {len(json_payload_str)} chars")

            # Log the extracted data for debugging
            current_app.logger.debug(f"--- Extracted Scenario Data ---")
            current_app.logger.debug(json_payload_str[:1000])
            current_app.logger.debug("--- End of Extracted Data ---")

        except Exception as e:
            current_app.logger.error(f"[STEP 1] ❌ Exception during extraction: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            return f"// Generation failed: {str(e)}"

        current_app.logger.info("=" * 60)

        # Populate the VSDL rules with dynamic platform constraints for the Agent
        final_vsdl_rules_for_agent = vsdl_rules_template.format(platform_constraints=platform_constraints)

        # For the initial generation prompt, we need to escape the braces for .format()
        escaped_vsdl_rules = final_vsdl_rules_for_agent.replace('{', '{{').replace('}', '}}')

        dsl_prompt_template_str = """你是一位精通 **VSDL（Virtual Security Description Language）** 语法的专家，擅长根据攻击案例的分析结果搭建模拟靶场。现在，我将提供一个 JSON 格式的攻击案例分析结果，你需要根据这些信息 **自动生成高度精确且符合部署要求的 VSDL 代码**。
""" + escaped_vsdl_rules + """
### **IV. 生成任务**
-   **严格遵守上述所有规则**，特别是网络互联逻辑和平台约束。
-   根据下方提供的 "场景信息" JSON，生成完整的 VSDL 代码。
-   **仅输出 VSDL 代码**，不要包含任何额外的解释或 Markdown 标记。

### **V. 靶场架构要求（MANDATORY）**
**⚠️ 强制要求：每个靶场场景必须包含以下两种节点类型：**

1. **攻击机节点（AttackerNode）**：
   - **必须至少定义一个攻击机节点**，这是强制要求！
   - 操作系统优先选择 `kali`（如果平台支持），否则使用 `ubuntu20`、`ubuntu18` 或 `ubuntu16`
   - 命名建议：`AttackerMachine`、`AttackerNode`、`KaliAttacker` 等
   - 必须安装常用攻击工具，如：`nmap`、`curl`、`wget`、`python3` 等
   - 必须连接到公网网络（有 Internet 网关的网络）以便访问靶机

2. **靶机节点（VulnerableNode）**：
   - 根据攻击案例定义存在漏洞的靶机
   - 安装存在漏洞的软件或服务
   - 配置相应的漏洞定义（vulnerability）
   - **【重要】操作系统必须使用Linux**：`ubuntu20`、`ubuntu18`、`ubuntu16`、`centos-7`、`openeuler20.03` 等
   - **严禁使用Windows**（win10、windows_server等），即使案例中提到Windows也必须替换为Ubuntu
   - **严禁使用ubuntu22**（镜像不可用）

**⚠️ 操作系统强制约束：**
- ❌ **禁止使用**：windows、win10、win2019、windows_server、win2003、ubuntu22 等
- ✅ **允许使用**：ubuntu20、ubuntu18、ubuntu16、centos-7、openeuler20.03、kali、fedora

**⚠️ 架构检查清单（生成前必须确认）：**
- [ ] 是否定义了至少一个攻击机节点？
- [ ] 攻击机是否连接到公网网络？
- [ ] 靶机是否可以被攻击机访问（在同一网络或有路由）？
- [ ] 是否定义了至少一个 vulnerability？
- [ ] **所有节点的OS是否都是Linux？严禁Windows！**

**示例架构：**
```vsdl
scenario example_attack duration 5 {{
  // 公网网络 - 攻击机接入
  network PublicNetwork {{
    addresses range is 203.0.113.0/24;
    gateway has direct access to the Internet;
    node AttackerMachine is connected;
    node AttackerMachine has IP 203.0.113.10;
  }}

  // 内网网络 - 靶机所在
  network VictimNetwork {{
    addresses range is 172.16.1.0/24;
    node PublicNetwork is connected;
    node PublicNetwork has IP 172.16.1.254;
    node VulnerableServer is connected;
    node VulnerableServer has IP 172.16.1.100;
  }}

  // 攻击机节点（必须存在！）
  node AttackerMachine {{
    ram larger than 4GB;
    disk size equal to 50GB;
    vcpu equal to 2;
    node OS is "kali";  // 或 "ubuntu20" 如果平台不支持kali
    mounts software nmap;
    mounts software curl;
    mounts software python3;
  }}

  // 靶机节点
  node VulnerableServer {{
    ram larger than 8GB;
    disk size equal to 100GB;
    vcpu equal to 4;
    node OS is "ubuntu20";
    mounts software tomcat version 9.0.50;
  }}

  // 漏洞定义
  vulnerability ExampleVuln {{
    vulnerable software tomcat version 9.0.50;
    cve id is "CVE-XXXX-XXXX";
    hosted on node VulnerableServer;
  }}
}}
```

### **VI. JSON输入格式说明**
输入的JSON是一个结构化的攻击场景数组，包含以下关键字段：

**顶层结构：**
- `scenario`: 包含 `networks`（网络列表）、`bridge_node`（网络桥接关系）
- 后续对象：每个代表一个网络层级，包含 `network_name`、`nodes`、`tools`、`vul_id` 等

**关键字段映射到VSDL：**
| JSON字段 | VSDL映射 |
|----------|----------|
| `nodes[].type` | 节点类型（server/workstation/iot） |
| `nodes[].os` | `node OS is "xxx"` |
| `nodes[].services` | `mounts software xxx` |
| `nodes[].ports` | 端口开放配置 |
| `tools[]` | 攻击机安装的工具 |
| `vul_id[]` | `vulnerability` 块定义 |
| `networks` | 对应多个 `network` 块 |
| `bridge_node` | 网络互联关系 |

**读取规则：**
1. 从 `nodes` 数组提取所有节点信息，区分攻击机和靶机
2. 从 `tools` 数组提取攻击工具，安装到攻击机节点
3. 从 `vul_id` 数组提取漏洞信息，定义 `vulnerability` 块
4. 从 `networks` 和 `bridge_node` 构建网络拓扑

### **场景信息**
{json_payload}
"""
        dsl_prompt = PromptTemplate.from_template(dsl_prompt_template_str)
        
        # --- Start of Prompt Debugging ---
        current_app.logger.debug("--- Prompt Template Debugging ---")
        current_app.logger.debug("[1] Template string passed to LangChain's PromptTemplate (should have double braces):")
        current_app.logger.debug(dsl_prompt.template)
        
        # Simulate formatting to see the final prompt sent to the LLM
        try:
            final_prompt_for_llm = dsl_prompt.format(json_payload="{\"example\": \"data\"}")
            current_app.logger.debug("\n[2] Final prompt rendered for LLM (should have single braces):")
            current_app.logger.debug(final_prompt_for_llm)
        except Exception as e:
            current_app.logger.error(f"Could not format prompt for debugging: {e}")
        current_app.logger.debug("--- End of Prompt Debugging ---\n")
        # --- End of Prompt Debugging ---

        dsl_chain = dsl_prompt | llm

        # 2. Step 2: Generate initial VSDL script from extracted JSON
        # Note: Step 1 (PDF extraction) was completed above using pdf_extractor
        current_app.logger.info("=" * 60)
        current_app.logger.info("[STEP 2] Generating initial VSDL script from JSON...")
        current_app.logger.info(f"[STEP 2] Input JSON length: {len(json_payload_str)} chars")

        gen_start = time.time()
        current_app.logger.info("[STEP 2] Calling LLM (dsl_chain.invoke)...")
        current_app.logger.info(f"[STEP 2] LLM API URL: {current_app.config.get('LLM_API_URL')}")
        current_app.logger.info(f"[STEP 2] LLM Model: {current_app.config.get('LLM_MODEL','deepseek-chat')}")

        # LLM 调用超时保护 - 使用线程和超时机制
        LLM_TIMEOUT = 180  # 3分钟超时
        generation_result = [None]
        generation_error = [None]

        def call_dsl_llm():
            try:
                generation_result[0] = dsl_chain.invoke({"json_payload": json_payload_str})
            except Exception as e:
                generation_error[0] = e

        dsl_thread = threading.Thread(target=call_dsl_llm, name="LLM_DSL_Thread")
        dsl_thread.daemon = True
        dsl_thread.start()

        # 等待线程完成，带超时和状态日志
        max_wait = LLM_TIMEOUT
        check_interval = 10
        elapsed = 0

        while dsl_thread.is_alive() and elapsed < max_wait:
            dsl_thread.join(timeout=check_interval)
            if dsl_thread.is_alive():
                elapsed += check_interval
                current_app.logger.warning(
                    f"[STEP 2] ⏳ LLM call still running... {elapsed}s elapsed (max {max_wait}s). "
                    f"Waiting for DeepSeek API response..."
                )

        if dsl_thread.is_alive():
            # 超时了
            gen_time = time.time() - gen_start
            current_app.logger.error(f"[STEP 2] ❌ TIMEOUT! LLM call exceeded {max_wait}s")
            current_app.logger.error(
                f"[STEP 2] This usually means: "
                f"1) DeepSeek API is slow or unresponsive, "
                f"2) Network connectivity issue, "
                f"3) API rate limit reached"
            )
            return f"// LLM API call timeout after {max_wait}s in STEP 2. Please check DeepSeek API status"

        # 检查是否有异常
        if generation_error[0] is not None:
            gen_time = time.time() - gen_start
            current_app.logger.error(f"[STEP 2] ❌ LLM call FAILED after {gen_time:.2f}s: {generation_error[0]}")
            raise generation_error[0]

        gen_time = time.time() - gen_start
        current_app.logger.info(f"[STEP 2] ✅ LLM response received in {gen_time:.2f}s")

        current_app.logger.info(f"[STEP 2] Response length: {len(generation_result[0].content)} chars")
        dsl_script = _extract_code_from_llm_output(generation_result[0].content, 'vsdl')
        current_app.logger.info(f"[STEP 2] Extracted VSDL length: {len(dsl_script)} chars")
        current_app.logger.info(f"[STEP 2] VSDL preview: {dsl_script[:200]}...")
        current_app.logger.info("=" * 60)

        # Pre-process the VSDL script to fix common issues
        current_app.logger.info("Applying pre-processing fixes to VSDL script...")

        # 1. First fix config syntax errors (LLM often generates config "..." instead of config {...})
        current_app.logger.info("[PREPROCESS] Step 1: Fixing config syntax...")
        dsl_script = _auto_fix_config_syntax(dsl_script)

        # 2. Then apply other fixes
        try:
            fix_common_unsat_issues = get_vsdl_fixer()
            original_script = dsl_script
            dsl_script = fix_common_unsat_issues(dsl_script)

            if dsl_script != original_script:
                current_app.logger.info("Applied automatic fixes to VSDL script")
                current_app.logger.info(f"Fixed script:\n{dsl_script}")
            else:
                current_app.logger.info("No automatic fixes needed")
        except Exception as e:
            current_app.logger.warning(f"Failed to apply preprocessing fixes: {e}")

        # 5. Step 3: Validation and Correction using an Agent
        current_app.logger.info("Step 3: Starting validation and correction using an Agent...")

        # Define a validation tool for the agent
        def _validate_vsdl_for_agent(script_to_validate: str) -> str:
          """A wrapper for the VSDL validation tool for agent use."""
          tool_start_time = time.time()
          _safe_log("info", "=" * 50)
          _safe_log("info", "[TOOL DEBUG] >>> VSDL_VALIDATOR TOOL CALLED <<<")
          _safe_log("info", f"[TOOL DEBUG] Input length: {len(script_to_validate)} chars")
          _safe_log("info", f"[TOOL DEBUG] Input preview: {script_to_validate[:300]}...")

    # ① 先提取 vsdl（去掉 ```vsdl fenced block）
          _safe_log("info", "[TOOL DEBUG] Step 1: Extracting VSDL from markdown...")
          cleaned_script = _extract_code_from_llm_output(script_to_validate, 'vsdl')
          _safe_log("info", f"[TOOL DEBUG] Extracted script length: {len(cleaned_script)} chars")

    # ② 再判断是不是 VSDL（关键修复点）
          _safe_log("info", "[TOOL DEBUG] Step 2: Checking if valid VSDL format...")
          if not cleaned_script.strip().lower().startswith("scenario"):
             _safe_log("error", "[TOOL DEBUG] ❌ NOT A VSDL SCRIPT - missing 'scenario' keyword")
             return (
                 "Validation Failed. The input is NOT a VSDL script. "
                 "You MUST output a full scenario block."
                )

         # ③ 尝试真正的 VSDLC 校验
          _safe_log("info", "[TOOL DEBUG] Step 3: Running VSDL compiler validation...")
          try:
              validation_start = time.time()
              is_valid, report, fixed_script = _validate_vsdl_for_syntax(cleaned_script)
              validation_time = time.time() - validation_start
              _safe_log("info", f"[TOOL DEBUG] Validation completed in {validation_time:.2f}s, result: {'VALID' if is_valid else 'INVALID'}")

              if is_valid:
                  tool_elapsed = time.time() - tool_start_time
                  _safe_log("info", f"[TOOL DEBUG] ✅ VALIDATION SUCCESSFUL! Total tool time: {tool_elapsed:.2f}s")
                  _safe_log("info", "=" * 50)
                  return f"""✅ VALIDATION SUCCESSFUL!

The following VSDL script is valid and ready to deploy:

```vsdl
{fixed_script}
```

**IMPORTANT: You MUST now output this exact script in your Final Answer!**
Copy the entire script above into your Final Answer. Do NOT modify it."""

              # 如果是UNSAT错误，尝试fallback验证
              if "unsat" in report.lower() or "UNSAT Classification Report" in report:
                  _safe_log("warning", "[TOOL DEBUG] UNSAT error detected, trying fallback validation...")
                  fallback_valid, fallback_report = _validate_vsdl_fallback(cleaned_script)
                  if fallback_valid:
                      tool_elapsed = time.time() - tool_start_time
                      _safe_log("info", f"[TOOL DEBUG] ✅ FALLBACK VALIDATION SUCCESSFUL! Total tool time: {tool_elapsed:.2f}s")
                      _safe_log("info", "=" * 50)
                      return f"""✅ VALIDATION SUCCESSFUL (fallback)!

The following VSDL script is valid:

```vsdl
{cleaned_script}
```

**IMPORTANT: You MUST now output this exact script in your Final Answer!**"""
                  else:
                      tool_elapsed = time.time() - tool_start_time
                      _safe_log("error", f"[TOOL DEBUG] ❌ FALLBACK ALSO FAILED. Total tool time: {tool_elapsed:.2f}s")
                      _safe_log("error", f"[TOOL DEBUG] Error: {report[:200]}")
                      _safe_log("info", "=" * 50)
                      return f"Fallback validation also failed. Original error: {report}\n\nFallback error: {fallback_report}"
              else:
                  tool_elapsed = time.time() - tool_start_time
                  _safe_log("error", f"[TOOL DEBUG] ❌ VALIDATION FAILED. Total tool time: {tool_elapsed:.2f}s")
                  _safe_log("error", f"[TOOL DEBUG] Error: {report[:200]}")
                  _safe_log("info", "=" * 50)
                  return f"Validation Failed. Fix the following error: {report}"

          except Exception as e:
              tool_elapsed = time.time() - tool_start_time
              _safe_log("error", f"[TOOL DEBUG] ❌ EXCEPTION in validation: {e}. Total tool time: {tool_elapsed:.2f}s")
              # 如果VSDLC校验失败，直接使用fallback验证
              fallback_valid, fallback_report = _validate_vsdl_fallback(cleaned_script)
              if fallback_valid:
                  _safe_log("info", "[TOOL DEBUG] ✅ FALLBACK VALIDATION SUCCESSFUL after exception")
                  _safe_log("info", "=" * 50)
                  return f"""✅ VALIDATION SUCCESSFUL (fallback)!

The following VSDL script is valid:

```vsdl
{cleaned_script}
```

**IMPORTANT: You MUST now output this exact script in your Final Answer!**"""
              else:
                  _safe_log("error", f"[TOOL DEBUG] ❌ ALL VALIDATION FAILED: {fallback_report}")
                  _safe_log("info", "=" * 50)
                  return f"Fallback validation failed: {fallback_report}"

        vsdl_validator_tool = Tool(
            name="vsdl_validator",
            func=_validate_vsdl_for_agent,
            description="Use this tool to validate a VSDL script. It takes the full script as input and returns a validation report. If the report indicates success, your task is complete. Otherwise, you must fix the script based on the error report and try again."
        )

        # Get fixer function for validation tool
        try:
            fix_common_unsat_issues = get_vsdl_fixer()
        except Exception as e:
            current_app.logger.warning(f"Could not load VSDL fixer: {e}")
            fix_common_unsat_issues = lambda x: x

        # 1. Define the tools the agent can use
        tools = [vsdl_validator_tool]

        # 2. Create the prompt template for the agent
        #    This is a highly structured prompt to force the agent to comply.
        agent_prompt_template = CorePromptTemplate.from_template("""You are a STRICT VSDL SYNTAX REPAIR ENGINE.
You are NOT allowed to invent new topology.
You may ONLY fix syntax, missing semicolons, naming errors, and platform constraint mismatches.
Your SOLE purpose is to produce a valid VSDL script by reasoning and using tools.
You MUST strictly follow the output format described below. DO NOT output any explanations, apologies, or conversational text.

**VSDL GRAMMAR RULES:**
---------------------
{final_vsdl_rules}

**TOOLS:**
--------
You have access to the following tools. You must use them when needed.

{tools}

**OUTPUT FORMAT:**
----------------
You MUST use the following format. Do not deviate.

Thought: The thought process behind the next action. Analyze the previous observation and decide what to do next.
Action: The tool to use. Must be one of [{tool_names}].
Action Input: The input to the tool. This MUST be a single VSDL code block enclosed in ```vsdl\n[code]\n```.
Observation: The result from the tool.

... (this Thought/Action/Action Input/Observation can repeat N times)

Thought: The validation was successful. Now I MUST output the complete validated script.
Final Answer:
```vsdl
[THE COMPLETE VALIDATED VSDL SCRIPT HERE - DO NOT SKIP THIS!]
```

**CRITICAL: When validation succeeds, you MUST output the complete VSDL script in the Final Answer. DO NOT just say "validation successful" or skip the script. The Final Answer must contain the full VSDL code block!**

**YOUR TASK:**
-------------
1.  The user will provide you with an initial VSDL script.
2.  Your first step is to use the 'vsdl_validator' tool to check this script.
3.  If the tool returns an error in the 'Observation', you MUST repeat the Thought/Action/Action Input cycle to fix the script and re-validate it.
4.  Continue this process until the 'vsdl_validator' tool returns a success message.
5.  **CRITICAL**: Once validation is successful, you MUST output the complete validated VSDL script in Final Answer format. DO NOT skip this step!

Begin!

{agent_scratchpad}

User's initial script:
{input}""").partial(final_vsdl_rules=final_vsdl_rules_for_agent)

        # 3. Create the agent (the core reasoning engine)
        agent_create_start = time.time()
        current_app.logger.info("[AGENT DEBUG] Creating ReAct agent...")
        try:
            agent = create_react_agent(llm, tools, agent_prompt_template)
            current_app.logger.info(f"[AGENT DEBUG] Agent created in {time.time() - agent_create_start:.2f}s")
        except Exception as e:
            current_app.logger.error(f"[AGENT DEBUG] Failed to create agent: {e}")
            raise

        # 4. Create the agent executor (the runtime for the agent)
        agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,  # Logs the agent's thought process
            max_iterations=10,
            handle_parsing_errors="Check your output and try again. Do not output a tool name that is not in the tool list.",
        )

        # 5. Invoke agent with detailed logging
        current_app.logger.info("=" * 60)
        current_app.logger.info("[AGENT DEBUG] >>> STARTING AGENT EXECUTION <<<")
        current_app.logger.info(f"[AGENT DEBUG] Input script length: {len(dsl_script)} chars")
        current_app.logger.info(f"[AGENT DEBUG] Input script preview: {dsl_script[:200]}...")
        current_app.logger.info(f"[AGENT DEBUG] LLM model: {current_app.config.get('LLM_MODEL', 'unknown')}")
        current_app.logger.info(f"[AGENT DEBUG] LLM API URL: {current_app.config.get('LLM_API_URL', 'unknown')}")
        current_app.logger.info("=" * 60)

        agent_invoke_start = time.time()

        try:
            # 使用线程和超时保护
            agent_result = [None]
            agent_exception = [None]

            def run_agent():
                try:
                    agent_result[0] = agent_executor.invoke({"input": dsl_script})
                except Exception as e:
                    agent_exception[0] = e

            agent_thread = threading.Thread(target=run_agent, name="AgentExecutorThread")
            agent_thread.daemon = True
            agent_thread.start()

            # 等待线程完成，带超时
            # 每10秒打印一次状态，最多等待180秒（3分钟）
            max_wait_seconds = 180
            check_interval = 10
            elapsed = 0

            while agent_thread.is_alive() and elapsed < max_wait_seconds:
                agent_thread.join(timeout=check_interval)
                if agent_thread.is_alive():
                    elapsed += check_interval
                    current_app.logger.warning(
                        f"[AGENT DEBUG] ⏳ Agent still running... {elapsed}s elapsed "
                        f"(max {max_wait_seconds}s). Waiting for LLM response..."
                    )

                    # 每30秒打印一次更详细的状态
                    if elapsed % 30 == 0:
                        current_app.logger.info(
                            f"[AGENT DEBUG] 🔄 Agent execution in progress. "
                            f"This may indicate slow LLM response or complex reasoning."
                        )

            if agent_thread.is_alive():
                # 超时了
                current_app.logger.error(
                    f"[AGENT DEBUG] ❌ TIMEOUT! Agent execution exceeded {max_wait_seconds}s. "
                    f"Forcefully returning pre-processed script."
                )
                current_app.logger.error(
                    f"[AGENT DEBUG] This usually means: "
                    f"1) DeepSeek API is slow or unresponsive, "
                    f"2) Network connectivity issue, "
                    f"3) LLM stuck in infinite reasoning loop"
                )
                return dsl_script  # 返回预处理的脚本

            # 检查是否有异常
            if agent_exception[0] is not None:
                raise agent_exception[0]

            agent_output = agent_result[0]

        except Exception as agent_error:
            agent_elapsed = time.time() - agent_invoke_start
            current_app.logger.error("=" * 60)
            current_app.logger.error(f"[AGENT DEBUG] ❌ AGENT EXECUTION FAILED after {agent_elapsed:.2f}s")
            current_app.logger.error(f"[AGENT DEBUG] Error type: {type(agent_error).__name__}")
            current_app.logger.error(f"[AGENT DEBUG] Error message: {str(agent_error)}")

            # 打印更详细的错误信息
            if hasattr(agent_error, '__cause__') and agent_error.__cause__:
                current_app.logger.error(f"[AGENT DEBUG] Caused by: {agent_error.__cause__}")

            # 检查是否是特定的错误类型
            error_str = str(agent_error).lower()
            if 'timeout' in error_str:
                current_app.logger.error("[AGENT DEBUG] Hint: LLM API timeout - consider increasing timeout or checking API status")
            elif 'connection' in error_str:
                current_app.logger.error("[AGENT DEBUG] Hint: Network connection issue - check if LLM API is reachable")
            elif 'rate limit' in error_str:
                current_app.logger.error("[AGENT DEBUG] Hint: Rate limited by LLM API - wait and retry")
            elif 'parsing' in error_str:
                current_app.logger.error("[AGENT DEBUG] Hint: Agent output parsing failed - LLM may have returned unexpected format")

            current_app.logger.error("=" * 60)
            current_app.logger.info("[AGENT DEBUG] Falling back to pre-processed script without agent correction")
            return dsl_script

        # Agent执行成功
        agent_elapsed = time.time() - agent_invoke_start
        current_app.logger.info("=" * 60)
        current_app.logger.info(f"[AGENT DEBUG] ✅ AGENT EXECUTION COMPLETED in {agent_elapsed:.2f}s")
        current_app.logger.info("=" * 60)

        agent_raw_output = agent_output.get('output', '')
        current_app.logger.info(f"[AGENT DEBUG] Raw output length: {len(agent_raw_output)} chars")
        current_app.logger.info(f"[AGENT DEBUG] Raw output preview: {agent_raw_output[:300]}...")

        final_dsl_script = _extract_vsdl_strict(agent_raw_output)
        current_app.logger.info(f"[AGENT DEBUG] Extracted VSDL length: {len(final_dsl_script)} chars")

        if not final_dsl_script:
            current_app.logger.error("[AGENT DEBUG] ⚠️ Extracted script is EMPTY! Using raw output.")
            final_dsl_script = agent_raw_output


        if not _is_probably_valid_vsdl(final_dsl_script):
            current_app.logger.error(
               "Agent failed to produce valid VSDL, falling back to initial script."
           )
            final_dsl_script = dsl_script
        current_app.logger.info(f"Agent finished. Final proposed VSDL script:\n{final_dsl_script}")

        # Final verification before returning
        is_valid, report, fixed_script = _validate_vsdl_for_syntax(final_dsl_script)
        if is_valid:
            current_app.logger.info("[+] Agent successfully generated a valid script.")
            elapsed_time = time.perf_counter() - start_time
            current_app.logger.info(f"Total time for get_VSDL_script_local (Success with Agent): {elapsed_time:.2f} seconds")
            # Return the fixed script (with auto-corrected config syntax if applicable)
            return fixed_script
        else:
            current_app.logger.error(f"Agent failed to produce a valid script. Final check failed. Report: {report}")
            elapsed_time = time.perf_counter() - start_time
            current_app.logger.info(f"Total time for get_VSDL_script_local (Failure with Agent): {elapsed_time:.2f} seconds")
            return f"// Agent-based generation failed. Final script attempt:\n{fixed_script}\n// Final error:\n{report}"

    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred during VSDL generation for file {file_path}: {e}", exc_info=True)
        raise  # Re-raise the exception to be caught by the Celery task
    finally:
        end_time = time.perf_counter()
        current_app.logger.info(f"VSDL generation for file {file_path} took {end_time - start_time:.2f} seconds.")


def get_VSDL_script(file_path):
    """
    Call LLM API to generate VSDL script
    
    Args:
        file_path: File path
        
    Returns:
        Generated VSDL script
    """
    try:
        # Get LLM API settings from configuration
        api_base_url = current_app.config.get('LLM_API_URL')
        api_key = current_app.config.get('LLM_API_KEY')
        
        # Get file extension and MIME type
        file_extension = os.path.splitext(file_path)[1].lower()
        mime_types = {
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.csv': 'text/csv',
            '.json': 'application/json',
            '.xml': 'application/xml',
            '.html': 'text/html',
            '.htm': 'text/html'
        }
        mime_type = mime_types.get(file_extension, 'application/octet-stream')
        
        try:
            # Build the file upload request
            api_url = api_base_url + '/files/upload'
            
            # Prepare the file for upload
            with open(file_path, 'rb') as f:
                files = {
                    'file': (
                        os.path.basename(file_path),  # Use the original file name
                        f,  # File object
                        mime_type  # MIME type
                    )
                }
                
                # Prepare form data
                data = {
                    'user': 'vsdl-backend'  # User identifier
                }
                
                # Set headers for the request
                headers = {
                    "Authorization": f"Bearer {api_key}"
                }
                
                # Send the file upload request
                upload_response = requests.post(
                    api_url,
                    headers=headers,
                    files=files,
                    data=data
                )
                upload_response.raise_for_status()
            
            # Parse the upload response
            upload_result = upload_response.json()
            file_id = upload_result.get('id')
            current_app.logger.info(f"File upload response: {upload_result}")
            if not file_id:
                raise ValueError("File upload failed: File ID not received")
            # POST
            # /workflows/run
            # Execute the workflow
            # The workflow cannot be executed if not published.

            # Request Body
            # inputs (object) Required Allows passing values for application-defined variables. The inputs parameter contains multiple key-value pairs, where each key corresponds to a specific variable, and the value is the actual value of the variable. A variable of type file list is available when the model supports parsing this type of file. If this variable is a file list, its value should be in list format, with each element containing the following:
            # type (string) Supported types:
            # document Specific types include: 'TXT', 'MD', 'MARKDOWN', 'PDF', 'HTML', 'XLSX', 'XLS', 'DOCX', 'CSV', 'EML', 'MSG', 'PPTX', 'PPT', 'XML', 'EPUB'
            # image Specific types include: 'JPG', 'JPEG', 'PNG', 'GIF', 'WEBP', 'SVG'
            # audio Specific types include: 'MP3', 'M4A', 'WAV', 'WEBM', 'AMR'
            # video Specific types include: 'MP4', 'MOV', 'MPEG', 'MPGA'
            # custom Specific types include: other file types
            # transfer_method (string) Transfer method, remote_url for image address / local_file for uploaded file
            # url (string) Image address (only when transfer method is remote_url)
            # upload_file_id (string) Upload file ID (only when transfer method is local_file)
            # response_mode (string) Required Response mode, supports:
            # streaming Streaming mode (recommended). Implemented using SSE (Server-Sent Events) for typing-like output.
            # blocking Blocking mode, waits for execution to complete before returning results. (Requests may be interrupted if the process is too long). Due to Cloudflare limitations, requests may be interrupted if no response is received within 100 seconds.
            # user (string) Required User identifier for defining the identity of the end user for easy retrieval and statistics. Defined by the developer, and the user ID must be unique in the application.
            # Response
            # When response_mode is blocking, a CompletionResponse object is returned. When response_mode is streaming, a ChunkCompletionResponse object is returned.

            # CompletionResponse
            # Returns the full application result, Content-Type is application/json.

            # workflow_run_id (string) Workflow execution ID
            # task_id (string) Task ID for tracking requests and stopping responses later
            # data (object) Detailed content
            # id (string) Workflow execution ID
            # workflow_id (string) Associated Workflow ID
            # status (string) Execution status: running / succeeded / failed / stopped
            # outputs (json) Optional Output content
            # error (string) Optional Error reason
            # elapsed_time (float) Optional Time elapsed (seconds)
            # total_tokens (int) Optional Total tokens used
            # total_steps (int) Total steps (redundant), default is 0
            # created_at (timestamp) Start time
            # finished_at (timestamp) End time
            # curl command example:
            # curl -X POST 'https://api.dify.ai/v1/workflows/run' \
            # --header 'Authorization: Bearer {api_key}' \
            # --header 'Content-Type: application/json' \
            # --data-raw '{
            #     "inputs": {},
            #     "response_mode": "streaming",
            #     "user": "abc-123"
            # }'
            # Build request to generate VSDL script
            chat_url = api_base_url + '/workflows/run'
            
            # Build the request data
            payload = {
                "inputs": {
                    "case_file": {  # "case_file" is the variable name defined on Dify platform
                        "type": "document",
                        "transfer_method": "local_file",
                        "upload_file_id": file_id
                    }
                },
                "response_mode": "streaming",  # Use streaming mode
                "user": "vsdl-backend"  # User identifier
            }
            
            # Send the generation request
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            # Use streaming request
            response = requests.post(
                chat_url,
                headers=headers,
                json=payload,
                stream=True,  # Enable streaming
                timeout=3600
            )

            
            response.raise_for_status()
            
            # Handle SSE stream response
            complete_result = {}
            vsdl_script = ""  # Use only one variable to store the final result
            
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith('data: '):
                    continue
                    
                data = line[6:]  # Remove 'data: ' prefix
                if data == '[DONE]':
                    break
                    
                try:
                    chunk = json.loads(data)
                    current_app.logger.info(f"Received stream data chunk:{chunk}")
                    
                    # When 'workflow_finished' event is received, get the complete script
                    if chunk.get('event') == 'workflow_finished':
                        outputs = chunk.get('data', {}).get('outputs', {})
                        vsdl_script_with_markdown = outputs.get('vsdl_script', '')
                        
                        if vsdl_script_with_markdown:
                            # Extract VSDL script content from Markdown code block
                            vsdl_script = vsdl_script_with_markdown.replace('```vsdl\n', '').replace('\n```', '').replace('```', '')
                            break   # Exit loop after obtaining the complete result
                except json.JSONDecodeError as e:
                    current_app.logger.error(f"Error decoding stream data chunk:{e}")
            
            current_app.logger.info(f"Generated VSDL script:{vsdl_script}")
            return vsdl_script
            
        except Exception as e:
            # If there is an error calling the API, log the error and return a mock script
            current_app.logger.error(f"Error calling LLM API: {str(e)}")
            # Get the first 100 characters of the file content for error prompt
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_preview = f.read(100)
            except:
                file_preview = "Unable to read file content"
            return f"// LLM API call failed, returning mock VSDL script\n// Error message:  {str(e)}\n// Based on case content: {file_preview}..."
            
    except Exception as e:
        # If there is an error calling the API, log the error and return a mock script
        current_app.logger.error(f"Error calling LLM API: {str(e)}")
        return f"// LLM API call failed, returning mock VSDL script\n// Error message: {str(e)}\n// Based on case content: {file_path[:100]}..."


def compile_VSDL_script(vsdl_script: str, task_id: str = None) -> Tuple[bool, str, Any]:
    """
    Compiles the VSDL script using Python VSDL Compiler to generate artifacts.

    Args:
        vsdl_script: The VSDL script content.
        task_id: Optional task ID for unique keypair naming in parallel execution.
                 If provided, the keypair will be named 'vsdl_key_<task_id>' to avoid
                 conflicts when multiple tasks run simultaneously.

    Returns:
        A tuple (bool, str, Scenario):
        - True if compilation is successful, False otherwise.
        - The path to the output directory if successful, or an error message if it fails.
        - The Scenario object if successful, None otherwise.
        The caller is responsible for cleaning up the temporary directory.
    """
    output_dir = tempfile.mkdtemp()

    # Generate unique keypair name for parallel execution
    if task_id:
        keypair_name = f'vsdl_key_{task_id}'
    else:
        keypair_name = 'vsdl_key'

    try:
        current_app.logger.info(f"[VSDL PYTHON COMPILER] Starting compilation (keypair: {keypair_name})...")

        # Get OpenStack configuration
        openstack_service = get_openstack_service_func()()
        public_net_id = openstack_service.get_external_network_id()  # UUID for Terraform

        # Prepare OpenStack config for Terraform generation
        # Include authentication credentials for Terraform provider
        # Process auth_url: Terraform OpenStack provider requires /v3 for Keystone v3
        auth_url = current_app.config.get('OPENSTACK_URL', '')
        if auth_url and not auth_url.endswith('/v3'):
            # Append /v3 if not already present (Keystone v3 API endpoint)
            if auth_url.endswith('/'):
                auth_url = auth_url + 'v3'
            else:
                auth_url = auth_url + '/v3'

        openstack_config = {
            'public_network_id': public_net_id,
            'ssh_key_name': keypair_name,  # Use unique keypair name for parallel execution
            'ssh_public_key': '',  # Will be read from file
            # OpenStack authentication for Terraform provider
            'auth_url': auth_url,
            'username': current_app.config.get('OPENSTACK_USER', ''),
            'password': current_app.config.get('OPENSTACK_PASSWORD', ''),
            'tenant_name': current_app.config.get('OPENSTACK_TENANT_NAME', 'vsdl'),
            'domain_name': current_app.config.get('OPENSTACK_DOMAIN', 'Default'),
            # Default flavor for instances (m1.large has 80GB disk, sufficient for most images)
            'default_flavor_name': current_app.config.get('OPENSTACK_DEFAULT_FLAVOR', 'm1.large'),
        }

        # Read SSH public key if available
        # Try multiple possible SSH key locations
        possible_ssh_paths = [
            current_app.config.get('SSH_PUBKEY_PATH'),
            '/root/.ssh/vsdl_key.pub',
            '/home/ubuntu/.ssh/id_rsa.pub',
            '/home/ubuntu/.ssh/vsdl_key.pub',
            os.path.expanduser('~/.ssh/id_rsa.pub'),
        ]

        ssh_pubkey = None
        for ssh_path in possible_ssh_paths:
            if ssh_path and os.path.exists(ssh_path):
                try:
                    with open(ssh_path, 'r') as f:
                        ssh_pubkey = f.read().strip()
                    current_app.logger.info(f"Loaded SSH public key from: {ssh_path}")
                    break
                except Exception as e:
                    current_app.logger.warning(f"Failed to read SSH key from {ssh_path}: {e}")

        if ssh_pubkey:
            openstack_config['ssh_public_key'] = ssh_pubkey
        else:
            current_app.logger.warning("No SSH public key found. Instances may not be accessible via SSH.")

        # Log OpenStack auth config (mask password for security)
        current_app.logger.info(f"[VSDL COMPILER] OpenStack auth_config: auth_url={openstack_config.get('auth_url')}, "
                                f"username={openstack_config.get('username')}, "
                                f"tenant_name={openstack_config.get('tenant_name')}, "
                                f"domain_name={openstack_config.get('domain_name')}")

        # Create compiler instance
        compiler = VSDLCompiler(openstack_config=openstack_config)

        # Compile the script
        result = compiler.compile(vsdl_script, output_dir=output_dir)

        if not result.success:
            error_msg = "\n".join(result.errors)
            current_app.logger.error(f"[VSDL PYTHON COMPILER] Compilation failed: {error_msg}")
            shutil.rmtree(output_dir)
            return False, f"VSDL Compilation Failed:\n{error_msg}", None

        current_app.logger.info(f"[VSDL PYTHON COMPILER] Compilation successful. Output at: {output_dir}")

        # Log generated files
        terraform_dir = os.path.join(output_dir, 'terraform')
        ansible_dir = os.path.join(output_dir, 'ansible')

        if os.path.exists(terraform_dir):
            terraform_files = os.listdir(terraform_dir)
            current_app.logger.info(f"[VSDL PYTHON COMPILER] Terraform files: {terraform_files}")

        if os.path.exists(ansible_dir):
            ansible_files = os.listdir(ansible_dir)
            current_app.logger.info(f"[VSDL PYTHON COMPILER] Ansible files: {ansible_files}")

        # Log warnings if any
        if result.warnings:
            for warning in result.warnings:
                current_app.logger.warning(f"[VSDL PYTHON COMPILER] Warning: {warning}")

        return True, output_dir, result.scenario

    except Exception as e:
        error_message = f"An unexpected error occurred during VSDL compilation: {str(e)}"
        current_app.logger.error(error_message, exc_info=True)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        return False, error_message, None


def _ensure_keypair_available(keypair_name: str = 'vsdl_key'):
    """
    Ensure an SSH keypair exists in OpenStack for Terraform to use.

    This function:
    1. Deletes any existing keypair with the same name (to avoid conflicts)
    2. Creates a new keypair using the configured SSH public key

    For parallel execution, each task should use a unique keypair name
    (e.g., vsdl_key_<task_id>) to avoid race conditions.

    Args:
        keypair_name: The name of the keypair to create.
    """
    try:

        # Get OpenStack service (uses SDK with proper auth)
        openstack_service = get_openstack_service_func()()
        conn = openstack_service._conn

        if conn is None:
            current_app.logger.warning("OpenStack connection not available, skipping keypair creation")
            return

        # Get openstack exceptions module
        openstack_exceptions = get_openstack_exceptions()

        # 1. Delete existing keypair if it exists
        try:
            existing_keypair = conn.compute.get_keypair(keypair_name)
            if existing_keypair:
                conn.compute.delete_keypair(existing_keypair)
                current_app.logger.info(f"Deleted existing keypair: {keypair_name}")
            else:
                current_app.logger.info(f"Keypair '{keypair_name}' does not exist, will create new one")
        except openstack_exceptions.ResourceNotFound:
            current_app.logger.info(f"Keypair '{keypair_name}' does not exist (ResourceNotFound), will create new one")
        except Exception as e:
            current_app.logger.warning(f"Failed to delete keypair: {str(e)}")

        # 2. Read SSH public key from configured path
        ssh_pubkey = None
        possible_ssh_paths = [
            current_app.config.get('SSH_PUBKEY_PATH'),
            '/root/.ssh/vsdl_key.pub',
            '/home/ubuntu/.ssh/id_rsa.pub',
            '/home/ubuntu/.ssh/vsdl_key.pub',
            os.path.expanduser('~/.ssh/id_rsa.pub'),
        ]

        for ssh_path in possible_ssh_paths:
            if ssh_path and os.path.exists(ssh_path):
                try:
                    with open(ssh_path, 'r') as f:
                        ssh_pubkey = f.read().strip()
                    current_app.logger.info(f"Loaded SSH public key from: {ssh_path}")
                    break
                except Exception as e:
                    current_app.logger.warning(f"Failed to read SSH key from {ssh_path}: {e}")

        if not ssh_pubkey:
            current_app.logger.error("No SSH public key found. Cannot create keypair in OpenStack.")
            raise RuntimeError("SSH public key not found. Please configure SSH_PUBKEY_PATH or ensure key exists in standard locations.")

        # 3. Create new keypair in OpenStack
        try:
            new_keypair = conn.compute.create_keypair(
                name=keypair_name,
                public_key=ssh_pubkey
            )
            current_app.logger.info(f"Created new keypair in OpenStack: {keypair_name}")
        except Exception as e:
            current_app.logger.error(f"Failed to create keypair '{keypair_name}': {str(e)}")
            raise

        # 4. Clean up old security groups (those created by VSDL compiler)
        # Security group names follow pattern: scenario_timestamp_allow_ssh
        try:
            security_groups = list(conn.network.security_groups())
            deleted_count = 0

            for sg in security_groups:
                # Delete security groups created by our deployments
                # Pattern: ends with _allow_ssh and starts with scenario name
                if sg.name.endswith('_allow_ssh') and sg.name != 'default':
                    try:
                        conn.network.delete_security_group(sg)
                        current_app.logger.info(f"Deleted old security group: {sg.name}")
                        deleted_count += 1
                    except Exception as e:
                        current_app.logger.warning(f"Failed to delete security group {sg.name}: {str(e)}")

            if deleted_count > 0:
                current_app.logger.info(f"Cleaned up {deleted_count} old security groups")
        except Exception as e:
            current_app.logger.warning(f"Failed to clean up security groups: {str(e)}")

    except Exception as e:
        # Log error but don't fail the entire deployment
        current_app.logger.error(f"Failed to ensure keypair availability: {str(e)}")
        raise


def generate_terraform_script(case_output_dir, keypair_name: str = 'vsdl_key'):
    """
    Generate Terraform script

    Args:
        case_output_dir: Case output directory path
        keypair_name: The SSH keypair name to use for OpenStack instances.
                      For parallel execution, each task should use a unique name
                      (e.g., vsdl_key_<task_id>).

    Returns:
        tuple: (success, output directory path or error message)
    """
    try:
        # Log current environment PATH
        current_app.logger.info(f"System PATH environment: {os.environ.get('PATH', 'not set')}")
        current_app.logger.info(f"Current working directory: {os.getcwd()}")

        # Log case_output_dir info
        current_app.logger.info(f"Processing case_output_dir: {case_output_dir}")
        current_app.logger.info(f"case_output_dir exists: {os.path.exists(case_output_dir)}")

        # Get the absolute path of the project root directory
        base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        current_app.logger.info(f"Project root directory: {base_dir}")

        # Ensure keypair exists in OpenStack for Terraform to use
        # Use the provided keypair_name (unique per task for parallel execution)
        _ensure_keypair_available(keypair_name)

        # Get terraform path from environment variable
        terraform_bin = current_app.config.get('TERRAFORM_PATH', 'terraform')
        current_app.logger.info(f"Terraform path being used: {terraform_bin}")
        
        # Check if terraform is executable
        if terraform_bin == 'terraform':
            # Try to get terraform full path
            try:
                terraform_which = subprocess.run(['which', 'terraform'], capture_output=True, text=True)
                if terraform_which.returncode == 0:
                    current_app.logger.info(f"Found terraform at: {terraform_which.stdout.strip()}")
                else:
                    current_app.logger.warning("Terraform not found using 'which' command")
            except Exception as e:
                current_app.logger.warning(f"Error getting terraform path: {str(e)}")
        else:
            current_app.logger.info(f"Checking if specified terraform file exists: {os.path.exists(terraform_bin)}")
            current_app.logger.info(f"Checking if specified terraform file is executable: {os.access(terraform_bin, os.X_OK)}")
        
        # The terraform script content is in the terraform directory (Python compiler output)
        # Also check legacy ttu_0 directory for backward compatibility
        terraform_script_path = os.path.join(case_output_dir, 'terraform')
        if not os.path.exists(terraform_script_path):
            terraform_script_path = os.path.join(case_output_dir, 'ttu_0')  # Legacy JAR output
        current_app.logger.info(f"Terraform script path: {terraform_script_path}")
        
        # Ensure directory exists
        os.makedirs(terraform_script_path, exist_ok=True)
        current_app.logger.info(f"Directory existence check: {os.path.exists(terraform_script_path)}")
        current_app.logger.info(f"Directory contents: {os.listdir(terraform_script_path) if os.path.exists(terraform_script_path) else 'directory does not exist'}")
        
        # Build command
        command = [
            terraform_bin,
            '-chdir=' + terraform_script_path,
            'init',
        ]
        
        # Execute command
        current_app.logger.info(f"Executing command: {' '.join(command)}")
        current_app.logger.info(f"Command environment: PATH={os.environ.get('PATH', 'not set')}")
        
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Log command results
            current_app.logger.info(f"Command exit code: {result.returncode}")
            current_app.logger.info(f"Command stdout: {result.stdout}")
            current_app.logger.info(f"Command stderr: {result.stderr}")
            
            # If init command executes successfully, proceed with terraform apply
            if result.returncode == 0:
                command = [
                    terraform_bin,
                    '-chdir=' + terraform_script_path,
                    'apply',
                    '-auto-approve'
                ]
                current_app.logger.info(f"Executing command: {' '.join(command)}")
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=True
                )
                current_app.logger.info(f"Command exit code: {result.returncode}")
                current_app.logger.info(f"Command stdout: {result.stdout}")
                current_app.logger.info(f"Command stderr: {result.stderr}")
                
                # If apply command executes successfully, return True and terraform_script_path
                if result.returncode == 0:
                    return True, terraform_script_path
                else:
                    return False, f"Terraform apply failed: {result.stderr}"
            else:
                return False, f"Terraform init failed: {result.stderr}"
        except subprocess.CalledProcessError as e:
            current_app.logger.error(f"subprocess.CalledProcessError: cmd={e.cmd}, returncode={e.returncode}")
            current_app.logger.error(f"subprocess.CalledProcessError: stdout={e.stdout}")
            current_app.logger.error(f"subprocess.CalledProcessError: stderr={e.stderr}")
            error_msg = e.stderr.strip()
            return False, f"Terraform execution error: {error_msg}"
    
    except OSError as e:
        # Handle architecture mismatch (e.g., ARM binary on x86_64 system)
        if e.errno == 8:  # Exec format error
            current_app.logger.error(f"Terraform binary architecture mismatch (errno 8): {str(e)}")
            current_app.logger.info("Attempting fallback to system terraform...")

            # Try using system terraform
            try:
                # First check if system terraform is available
                terraform_check = subprocess.run(['which', 'terraform'], capture_output=True, text=True)
                if terraform_check.returncode == 0:
                    system_terraform = terraform_check.stdout.strip()
                    current_app.logger.info(f"Found system terraform at: {system_terraform}")

                    # Re-run terraform init with system terraform
                    init_command = [
                        'terraform',
                        '-chdir=' + terraform_script_path,
                        'init',
                    ]
                    current_app.logger.info(f"Fallback: Executing command: {' '.join(init_command)}")
                    result = subprocess.run(
                        init_command,
                        capture_output=True,
                        text=True,
                        check=True
                    )

                    if result.returncode == 0:
                        # Run terraform apply
                        apply_command = [
                            'terraform',
                            '-chdir=' + terraform_script_path,
                            'apply',
                            '-auto-approve'
                        ]
                        current_app.logger.info(f"Fallback: Executing command: {' '.join(apply_command)}")
                        result = subprocess.run(
                            apply_command,
                            capture_output=True,
                            text=True,
                            check=True
                        )

                        if result.returncode == 0:
                            current_app.logger.info("Terraform deployment successful using system terraform")
                            return True, terraform_script_path
                        else:
                            return False, f"Terraform apply failed (system terraform): {result.stderr}"
                    else:
                        return False, f"Terraform init failed (system terraform): {result.stderr}"
                else:
                    return False, f"Terraform binary architecture mismatch and no system terraform found. Please install terraform or update TERRAFORM_PATH in config."
            except subprocess.CalledProcessError as fallback_e:
                current_app.logger.error(f"Fallback terraform execution failed: {fallback_e}")
                return False, f"Terraform execution error (fallback): {fallback_e.stderr.strip() if fallback_e.stderr else str(fallback_e)}"
            except Exception as fallback_e:
                current_app.logger.error(f"Fallback error: {str(fallback_e)}")
                return False, f"Terraform fallback failed: {str(fallback_e)}"
        else:
            current_app.logger.error(f"OSError occurred: {str(e)}")
            return False, f"Error generating Terraform script: {str(e).strip()}"

    except Exception as e:
        current_app.logger.error(f"Exception occurred: {str(e)}")
        current_app.logger.error(f"Exception type: {type(e)}")
        current_app.logger.error(f"Exception details: ", exc_info=True)
        return False, f"Error generating Terraform script: {str(e).strip()}"

def _wait_for_ssh_ready(hosts: dict, jumphost_config: dict = None, max_wait: int = 300, check_interval: int = 10) -> tuple:
    """
    Wait for SSH to be ready on target hosts.

    This function probes SSH ports through the jumphost to verify that:
    1. The target VM is reachable
    2. SSH service is running and accepting connections

    Args:
        hosts: Dict of {host_name: ip_address}
        jumphost_config: Dict with jumphost settings (host, user, port, key_path)
        max_wait: Maximum wait time in seconds (default 300 = 5 minutes)
        check_interval: Time between checks in seconds

    Returns:
        tuple: (success, dict of failed hosts or error message)
    """
    import socket
    import subprocess
    import time

    if not hosts:
        current_app.logger.warning("No hosts to check for SSH readiness")
        return True, {}

    jumphost_host = jumphost_config.get('host', '') if jumphost_config else ''
    jumphost_user = jumphost_config.get('user', 'user') if jumphost_config else 'user'
    jumphost_port = jumphost_config.get('port', 22) if jumphost_config else 22
    jumphost_key = jumphost_config.get('key_path', '') if jumphost_config else ''

    current_app.logger.info(f"Waiting for SSH to be ready on {len(hosts)} host(s)...")
    current_app.logger.info(f"Max wait time: {max_wait}s, Check interval: {check_interval}s")

    if jumphost_host:
        current_app.logger.info(f"Using jumphost: {jumphost_user}@{jumphost_host}:{jumphost_port}")

    ready_hosts = set()
    failed_hosts = {}
    start_time = time.time()

    while time.time() - start_time < max_wait:
        for host_name, host_ip in hosts.items():
            if host_name in ready_hosts:
                continue

            current_app.logger.info(f"Checking SSH readiness for {host_name} ({host_ip})...")

            try:
                if jumphost_host:
                    # Method 1: Use SSH to test connection through jumphost
                    # Try to actually connect and verify SSH banner exchange
                    # This is more reliable than just checking port
                    check_cmd = [
                        'ssh',
                        '-i', jumphost_key,
                        '-o', 'StrictHostKeyChecking=no',
                        '-o', 'UserKnownHostsFile=/dev/null',
                        '-o', 'ConnectTimeout=10',
                        '-o', 'BatchMode=yes',
                        '-o', 'LogLevel=ERROR',
                        '-p', str(jumphost_port),
                        f'{jumphost_user}@{jumphost_host}',
                        f'nc -z -w5 {host_ip} 22'  # Use netcat to test port
                    ]

                    result = subprocess.run(
                        check_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=20
                    )

                    stderr_str = result.stderr.decode() if result.stderr else ''

                    # Check if netcat succeeded (return code 0)
                    if result.returncode == 0:
                        current_app.logger.info(f"✓ SSH port open on {host_name} ({host_ip})")

                        # Additional check: Try to verify SSH banner
                        banner_cmd = [
                            'ssh',
                            '-i', jumphost_key,
                            '-o', 'StrictHostKeyChecking=no',
                            '-o', 'UserKnownHostsFile=/dev/null',
                            '-o', 'ConnectTimeout=10',
                            '-o', 'BatchMode=yes',
                            '-o', 'LogLevel=ERROR',
                            '-p', str(jumphost_port),
                            f'{jumphost_user}@{jumphost_host}',
                            f'timeout 5 bash -c "echo | nc {host_ip} 22 2>/dev/null | head -1"'
                        ]

                        banner_result = subprocess.run(
                            banner_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=15
                        )

                        banner = banner_result.stdout.decode().strip() if banner_result.stdout else ''
                        if banner and 'SSH' in banner:
                            current_app.logger.info(f"✓ SSH banner verified: {banner}")
                            ready_hosts.add(host_name)
                        else:
                            # Port is open but SSH banner not received yet
                            # VM might still be booting
                            current_app.logger.debug(f"Port open but no SSH banner yet for {host_name}")
                    else:
                        # Check specific error conditions
                        if 'Connection refused' in stderr_str:
                            current_app.logger.debug(f"SSH connection refused for {host_name} - service not ready")
                        elif 'timed out' in stderr_str.lower():
                            current_app.logger.debug(f"SSH connection timed out for {host_name} - host unreachable")
                        else:
                            current_app.logger.debug(f"SSH check failed for {host_name}: {stderr_str}")
                else:
                    # Direct connection test (no jumphost)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    result = sock.connect_ex((host_ip, 22))
                    sock.close()

                    if result == 0:
                        current_app.logger.info(f"✓ SSH ready on {host_name} ({host_ip})")
                        ready_hosts.add(host_name)
                    else:
                        current_app.logger.debug(f"SSH not ready on {host_name}, socket result: {result}")

            except subprocess.TimeoutExpired:
                current_app.logger.debug(f"SSH check timed out for {host_name}")
            except Exception as e:
                current_app.logger.debug(f"SSH check failed for {host_name}: {e}")

        # Check if all hosts are ready
        if len(ready_hosts) == len(hosts):
            current_app.logger.info(f"All {len(hosts)} hosts are SSH-ready!")
            return True, {}

        # Wait before next check
        elapsed = int(time.time() - start_time)
        remaining = len(hosts) - len(ready_hosts)
        current_app.logger.info(f"Waiting for {remaining} host(s)... ({elapsed}s elapsed, max {max_wait}s)")
        time.sleep(check_interval)

    # Timeout reached - report which hosts failed
    failed_hosts = {name: ip for name, ip in hosts.items() if name not in ready_hosts}
    current_app.logger.error(f"SSH readiness check timed out after {max_wait}s. Failed hosts: {failed_hosts}")
    return False, failed_hosts

def generate_ansible_script(case_output_dir, terraform_output=None):
    """
    Generate and execute Ansible script

    Args:
        case_output_dir: Case output directory path
        terraform_output: Optional dict with terraform outputs (IPs, etc.)

    Returns:
        tuple: (success, output directory path or error message)
    """
    try:
        # Get the absolute path of the project root directory
        current_app.logger.info(f"Processing case_output_dir: {case_output_dir}")
        base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

        # Get ansible-playbook path from environment variable
        ansible_playbook_bin = current_app.config.get('ANSIBLE_PLAYBOOK_PATH', 'ansible-playbook')

        # Ansible script location is under the ansible directory in case_output_dir
        ansible_script_path = os.path.join(case_output_dir, 'ansible')
        # Ensure directory exists
        os.makedirs(ansible_script_path, exist_ok=True)

        # Update inventory with terraform outputs if available
        if terraform_output:
            inventory_path = os.path.join(ansible_script_path, 'inventory.ini')
            if os.path.exists(inventory_path):
                current_app.logger.info(f"Updating Ansible inventory with Terraform outputs...")
                _update_ansible_inventory(inventory_path, terraform_output)

                # Log the updated inventory for debugging
                try:
                    with open(inventory_path, 'r') as f:
                        inv_content = f.read()
                    current_app.logger.info(f"Updated inventory.ini contents:\n{inv_content}")
                except Exception as e:
                    current_app.logger.warning(f"Could not read inventory.ini: {e}")

        # Assume the main playbook file is either main.yml or site.yml
        ansible_playbook = os.path.join(ansible_script_path, 'site.yml')

        # If playbook file does not exist, try main.yml
        if not os.path.exists(ansible_playbook):
            ansible_playbook = os.path.join(ansible_script_path, 'main.yml')
            if not os.path.exists(ansible_playbook):
                return False, f"Cannot find Ansible playbook file"

        # Build ansible-playbook command
        # Check if jumphost is configured
        jumphost_host = current_app.config.get('JUMPHOST_HOST', '')

        # Try to find the matching private key for the public key we used
        ssh_private_key_path = None
        possible_private_keys = [
            current_app.config.get('SSH_PRIVATE_KEY_PATH'),
            '/root/.ssh/vsdl_key',
            '/home/ubuntu/.ssh/id_rsa',
            '/home/ubuntu/.ssh/vsdl_key',
            os.path.expanduser('~/.ssh/id_rsa'),
        ]

        for key_path in possible_private_keys:
            if key_path and os.path.exists(key_path):
                ssh_private_key_path = key_path
                current_app.logger.info(f"Using SSH private key: {key_path}")
                break

        if not ssh_private_key_path:
            current_app.logger.warning("No SSH private key found. Using default path.")
            ssh_private_key_path = '/root/.ssh/id_rsa'

        # Wait for SSH to be ready on target hosts before executing Ansible
        # This is crucial because VMs may need time to fully boot and start SSH service
        if terraform_output:
            # Extract host IPs from terraform output
            hosts_to_check = {}
            for node_name, ip_info in terraform_output.items():
                # Use floating_ip if available, otherwise network_ip
                host_ip = ip_info.get('floating_ip') or ip_info.get('network_ip')
                if host_ip:
                    # Extract the short host name (last part after underscore)
                    short_name = node_name.split('_')[-1] if '_' in node_name else node_name
                    hosts_to_check[short_name] = host_ip

            if hosts_to_check:
                jumphost_config = None
                if jumphost_host:
                    jumphost_config = {
                        'host': jumphost_host,
                        'user': current_app.config.get('JUMPHOST_USER', 'user'),
                        'port': current_app.config.get('JUMPHOST_PORT', 22),
                        'key_path': ssh_private_key_path
                    }

                current_app.logger.info(f"=== SSH Readiness Check ===")
                current_app.logger.info(f"Hosts to check: {hosts_to_check}")

                ssh_ready, ssh_failed = _wait_for_ssh_ready(
                    hosts=hosts_to_check,
                    jumphost_config=jumphost_config,
                    max_wait=current_app.config.get('SSH_WAIT_TIMEOUT', 300),
                    check_interval=current_app.config.get('SSH_CHECK_INTERVAL', 10)
                )

                if not ssh_ready:
                    failed_msg = f"SSH readiness check failed for hosts: {ssh_failed}"
                    current_app.logger.error(f"=== SSH Readiness Check FAILED ===")
                    current_app.logger.error(f"Failed hosts: {ssh_failed}")
                    current_app.logger.error(f"This usually means:")
                    current_app.logger.error(f"  1. VM is still booting (increase SSH_WAIT_TIMEOUT)")
                    current_app.logger.error(f"  2. Security group doesn't allow SSH from jumphost")
                    current_app.logger.error(f"  3. SSH service not started on target VM")
                    return False, failed_msg

                current_app.logger.info(f"=== SSH Readiness Check PASSED ===")
            else:
                current_app.logger.warning("No hosts found in terraform output for SSH check")

        # Build command - don't use --private-key when jumphost is configured
        # SSH config file will handle all key settings
        if jumphost_host:
            # Jumphost configured: SSH config file handles everything
            command = [
                ansible_playbook_bin,
                ansible_playbook,
                '-i', os.path.join(ansible_script_path, 'inventory.ini'),
                '-vv'  # Verbose mode for better debugging
            ]
            current_app.logger.info("Jumphost configured: using SSH config for all connection settings")
        else:
            # No jumphost: use --private-key directly
            command = [
                ansible_playbook_bin,
                ansible_playbook,
                '-i', os.path.join(ansible_script_path, 'inventory.ini'),
                '--private-key', ssh_private_key_path
            ]

        # Prepare environment variables
        # Set ANSIBLE_CONFIG to point to our generated ansible.cfg
        # This is necessary because ansible.cfg must be in the current working directory
        # or explicitly specified via ANSIBLE_CONFIG environment variable
        env = os.environ.copy()
        ansible_cfg_path = os.path.join(ansible_script_path, 'ansible.cfg')
        if os.path.exists(ansible_cfg_path):
            env['ANSIBLE_CONFIG'] = ansible_cfg_path
            current_app.logger.info(f"Setting ANSIBLE_CONFIG={ansible_cfg_path}")

            # Log the contents of ansible.cfg for debugging
            try:
                with open(ansible_cfg_path, 'r') as f:
                    cfg_content = f.read()
                current_app.logger.info(f"ansible.cfg contents:\n{cfg_content}")
            except Exception as e:
                current_app.logger.warning(f"Could not read ansible.cfg: {e}")

            # Also log SSH config if it exists
            ssh_config_path = os.path.join(ansible_script_path, 'ssh_config')
            if os.path.exists(ssh_config_path):
                try:
                    with open(ssh_config_path, 'r') as f:
                        ssh_cfg_content = f.read()
                    current_app.logger.info(f"ssh_config contents:\n{ssh_cfg_content}")
                except Exception as e:
                    current_app.logger.warning(f"Could not read ssh_config: {e}")

        # Execute command
        current_app.logger.info(f"Executing command: {' '.join(command)}")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            env=env
        )

        # Print command output
        current_app.logger.info(f"Command stdout: {result.stdout}")
        if result.stderr:
            current_app.logger.error(f"Command stderr: {result.stderr}")

        # Check if execution succeeded
        if result.returncode == 0:
            return True, ansible_script_path
        else:
            return False, f"Ansible playbook execution failed: {result.stderr}"

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else ""
        stdout_msg = e.stdout.strip() if e.stdout else ""
        combined_error = f"{stdout_msg}\n{error_msg}".strip()

        current_app.logger.error(f"=== Ansible Execution Failed ===")
        current_app.logger.error(f"Return code: {e.returncode}")
        current_app.logger.error(f"Stdout: {stdout_msg}")
        current_app.logger.error(f"Stderr: {error_msg}")

        # Analyze the error for common issues and provide helpful guidance
        error_analysis = []

        if "Connection refused" in combined_error:
            error_analysis.append("SSH connection refused - target VM may not have SSH service running yet")
            error_analysis.append("  → Solution: Increase SSH_WAIT_TIMEOUT config or check VM cloud-init logs")

        if "Connection timed out" in combined_error or "timed out" in combined_error:
            error_analysis.append("SSH connection timed out - network or firewall issue")
            error_analysis.append("  → Solution: Check security group rules allow SSH from jumphost")

        if "Permission denied" in combined_error or "permission denied" in combined_error:
            error_analysis.append("SSH permission denied - key authentication failed")
            error_analysis.append("  → Solution: Check SSH key is correct and has proper permissions (600)")

        if "Host key verification failed" in combined_error:
            error_analysis.append("SSH host key verification failed")
            error_analysis.append("  → Solution: Check StrictHostKeyChecking setting in SSH config")

        if "UNREACHABLE" in combined_error:
            error_analysis.append("Ansible host unreachable - check network connectivity")
            error_analysis.append("  → Verify: Can you manually SSH to the target?")

        if "jumphost loop" in combined_error.lower():
            error_analysis.append("SSH jumphost loop detected - SSH config misconfiguration")
            error_analysis.append("  → Solution: Check ssh_config for conflicting Host patterns")

        if error_analysis:
            current_app.logger.error("Error Analysis:")
            for analysis in error_analysis:
                current_app.logger.error(f"  {analysis}")

        return False, f"Ansible execution error: {combined_error}"
    except Exception as e:
        current_app.logger.error(f"=== Unexpected Error in Ansible Execution ===")
        current_app.logger.error(f"Exception type: {type(e).__name__}")
        current_app.logger.error(f"Exception message: {str(e)}")
        import traceback
        current_app.logger.error(f"Traceback: {traceback.format_exc()}")
        return False, f"Error executing Ansible script: {str(e).strip()}"


def _update_ansible_inventory(inventory_path: str, terraform_output: dict):
    """
    Update Ansible inventory with actual IP addresses from Terraform outputs.
    Also configures jumphost settings if JUMPHOST_HOST is set.

    Args:
        inventory_path: Path to inventory.ini file
        terraform_output: Structured dict with node IPs:
            {
                'node_name_with_prefix': {
                    'floating_ip': '203.0.113.100',
                    'network_ip': '172.24.4.191'
                }
            }
    """
    try:
        with open(inventory_path, 'r') as f:
            content = f.read()

        # Determine which IP to use based on jumphost configuration
        jumphost_host = current_app.config.get('JUMPHOST_HOST', '')
        jumphost_user = current_app.config.get('JUMPHOST_USER', 'root')
        jumphost_port = current_app.config.get('JUMPHOST_PORT', '22')
        jumphost_password = current_app.config.get('JUMPHOST_PASSWORD', '')

        # Build a mapping from base node names (without prefix) to IPs
        # Terraform outputs have prefixed names like "scenario_timestamp_NodeName"
        # But Ansible inventory has base names like "NodeName"
        base_node_ips = {}

        for prefixed_name, ip_info in terraform_output.items():
            # IMPORTANT: Always use floating_ip when jumphost is configured!
            # The jumphost (OpenStack controller) can reach floating IPs via Neutron router,
            # but CANNOT reach private network IPs (172.16.x.x) directly.
            #
            # Architecture:
            #   CRCG -> Jumphost -> Neutron Router -> VM (via floating IP)
            #
            # floating_ip (172.24.4.x): reachable from jumphost ✓
            # network_ip (172.16.1.x): NOT reachable from jumphost ✗
            if jumphost_host:
                # With jumphost: use floating IP (reachable via Neutron router)
                ip = ip_info.get('floating_ip') or ip_info.get('network_ip', '')
                current_app.logger.info(f"Using floating IP for {prefixed_name}: {ip} (jumphost configured)")
            else:
                # Without jumphost: also try floating IP first (if directly reachable)
                # Fallback to network IP if floating IP not available
                ip = ip_info.get('floating_ip') or ip_info.get('network_ip', '')
                current_app.logger.info(f"Using floating IP for {prefixed_name}: {ip} (no jumphost)")

            if not ip:
                continue

            # Extract base node name from prefixed name
            # Format: scenario_timestamp_NodeName -> NodeName
            # The prefix is added by terraform generator as: {scenario_name}_{timestamp}_{original_node_name}
            # We need to find the original node name which matches inventory entries

            # Try to find a matching base name by checking if inventory contains it
            # Common patterns: the last segment or last few segments after underscores
            parts = prefixed_name.split('_')
            # Try different suffixes, starting from the last part
            for i in range(len(parts)):
                candidate = '_'.join(parts[i:])  # Try from part i to end
                if candidate.lower() in content.lower() or candidate in content:
                    base_node_ips[candidate] = ip
                    break
            else:
                # If no match found, use the last part as fallback
                base_node_ips[prefixed_name] = ip

        # Now update the inventory with the base node names
        for base_name, ip in base_node_ips.items():
            # Pattern: node_name ansible_host=OLD_IP
            # Match both with and without quotes around the IP
            import re
            pattern = rf'({re.escape(base_name)}\s+ansible_host\s*=\s*)[\d.]+'
            replacement = rf'\g<1>{ip}'
            new_content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)
            if new_content != content:
                content = new_content
                current_app.logger.info(f"Updated inventory: {base_name} -> {ip}")

        # Write updated inventory
        with open(inventory_path, 'w') as f:
            f.write(content)

        current_app.logger.info(f"Updated Ansible inventory with IPs: {base_node_ips}")

        # Create ansible.cfg for jumphost configuration (more reliable than inventory variables)
        if jumphost_host:
             ansible_dir = os.path.dirname(inventory_path)
             # 调用新的 _create_ansible_cfg，不再需要密码
             _create_ansible_cfg(ansible_dir, jumphost_host, jumphost_user, jumphost_port)

    except Exception as e:
        current_app.logger.warning(f"Failed to update Ansible inventory: {e}")


def _create_ansible_cfg(ansible_dir: str, jumphost_host: str, jumphost_user: str, jumphost_port: str):
    """
    Create ansible.cfg using ProxyJump with SSH key.
    Generates an SSH config file for reliable jumphost connections.
    """
    try:
        import os
        ansible_cfg_path = os.path.join(ansible_dir, 'ansible.cfg')
        ssh_config_path = os.path.join(ansible_dir, 'ssh_config')

        # Get the SSH private key path for both jumphost and target hosts
        ssh_private_key = current_app.config.get('SSH_PRIVATE_KEY_PATH', '/root/.ssh/vsdl_key')
        jumphost_key = current_app.config.get('JUMPHOST_KEY_PATH') or ssh_private_key

        # Create SSH config file for reliable ProxyJump
        # CRITICAL: SSH config rules are CUMULATIVE (not overriding)!
        # When multiple Host patterns match, ALL their settings are combined.
        # This causes "jumphost loop" if Host * also matches the jumphost.
        #
        # Solution: Use "Match host" with "exec" condition, or use ProxyCommand
        # to avoid the cumulative rule problem.
        #
        # Best solution: Use explicit host patterns instead of "Host *"
        ssh_config_content = f"""# SSH config generated by VSDL Compiler
# IMPORTANT: SSH rules are CUMULATIVE - use ProxyCommand to avoid loops

# Rule 1: Jumphost (bastion) - direct connection
Host jumphost {jumphost_host}
    HostName {jumphost_host}
    User {jumphost_user}
    Port {jumphost_port}
    IdentityFile {jumphost_key}
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null

# Rule 2: Target hosts - use ProxyCommand through jumphost
# Use explicit IP patterns to avoid matching jumphost (avoids loop!)
# OpenStack floating IPs are typically in 172.24.4.x range
# NOTE: User is NOT specified - Ansible inventory controls it via ansible_user
#   - Ubuntu images use 'ubuntu'
#   - Kali images use 'kali'
#   - Debian images use 'debian'
Host 172.24.4.*
    Port 22
    IdentityFile {ssh_private_key}
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    ProxyCommand ssh -i {jumphost_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {jumphost_port} {jumphost_user}@{jumphost_host} -W %h:%p

# Rule 3: Internal network IPs (172.16.x.x)
Host 172.16.*
    Port 22
    IdentityFile {ssh_private_key}
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    ProxyCommand ssh -i {jumphost_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {jumphost_port} {jumphost_user}@{jumphost_host} -W %h:%p

# Rule 4: 10.x.x.x network
Host 10.*
    Port 22
    IdentityFile {ssh_private_key}
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    ProxyCommand ssh -i {jumphost_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {jumphost_port} {jumphost_user}@{jumphost_host} -W %h:%p

# Rule 5: 203.0.113.x network
Host 203.0.113.*
    Port 22
    IdentityFile {ssh_private_key}
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    ProxyCommand ssh -i {jumphost_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p {jumphost_port} {jumphost_user}@{jumphost_host} -W %h:%p
"""
        with open(ssh_config_path, 'w') as f:
            f.write(ssh_config_content)
        os.chmod(ssh_config_path, 0o600)  # Secure permissions
        current_app.logger.info(f"Created SSH config at: {ssh_config_path}")

        # Create ansible.cfg that uses the SSH config
        cfg_content = f"""[defaults]
inventory = ./inventory.ini
host_key_checking = False
retry_files_enabled = False
timeout = 30

[ssh_connection]
# Use SSH config file for ProxyJump configuration
ssh_args = -F {ssh_config_path}
pipelining = True
timeout = 30
"""

        with open(ansible_cfg_path, 'w') as f:
            f.write(cfg_content)

        current_app.logger.info(f"Created ansible.cfg with SSH config: {ssh_config_path}")
        current_app.logger.info(f"Jumphost: {jumphost_user}@{jumphost_host}:{jumphost_port}")
        current_app.logger.info(f"Jumphost key: {jumphost_key}")
        current_app.logger.info(f"Target key: {ssh_private_key}")

    except Exception as e:
        current_app.logger.warning(f"Failed to create ansible.cfg: {e}")