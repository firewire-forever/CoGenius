"""
PDF Extractor Module
Extracts structured attack scenario information from PDF files.

Workflow:
PDF -> Remote PDF-RE Service (Markdown) -> LLM -> Structured JSON -> CVE DB Enrichment (optional)

Author: CRCG Backend Team
"""

import os
import json
import re
import base64
import tempfile
from typing import Dict, List, Any, Optional, Set
from pathlib import Path

# HTTP Client
import requests

from flask import current_app


# ========================
# Configuration
# ========================
# PDF-RE Service Configuration
PDF_RE_SERVICE_URL = os.environ.get('PDF_RE_SERVICE_URL', 'http://localhost:8000')

# LLM API Configuration for PDF extraction (loaded from environment variables)
API_URL = os.environ.get('PDF_LLM_API_URL', 'https://api.openai.com/v1/chat/completions')
API_KEY = os.environ.get('PDF_LLM_API_KEY', '')
MODEL_NAME = os.environ.get('PDF_LLM_MODEL', 'gpt-4')

# CVE Database Configuration (from environment variables)
CVE_DB_PATH = os.environ.get('CVE_DB_PATH', 'data/cve_db/cves')  # CVE 数据库根目录


# ========================
# System Prompt for Extraction
# ========================
SYSTEM_PROMPT = "你是一个网络安全专家，擅长从技术文档中提取攻击场景。"

USER_PROMPT_TEMPLATE = """
请从以下Markdown内容中提取攻击场景，并严格按照JSON格式返回。

要求：
1. 返回JSON，下面是格式要求，严格按照要求格式来，其中双括号是转义单括号，输出要用单括号。示例中#后的内容仅作提示，不要出现在返回结果里。
2. 一个攻击场景必须包含下面所有可重复的步骤，不同network中可以包含相同的步骤：Reconnaissance，Weaponization，Delivery，Exploitation，Installation，Command & Control，Actions on Objectives，攻击步骤严格使用上述英文名称的形式，一字不改
3. 不要输出任何解释，一些工具和漏洞的描述信息可以用文档中相关的内容来描述，也可以搜索一些公开的信息来描述，但只有描述可以搜索网络，不要添加任何个人的分析和观点，保持客观中立，描述信息要简洁明了，突出重点
4. 如果某一个节点内没有元素，返回空数组或者空字符串。
5. 描述用的自然语言要使用中文，除了专有名词。此外格式语言和自然语言的分隔符一律用|
6. **【重要】操作系统约束**：严禁使用Windows系列操作系统（Windows 10、Windows Server、Win10、Win2019等）。严禁使用ubuntu22（镜像不可用）。如果文档中提到Windows系统，必须替换为Ubuntu Linux（只能使用ubuntu20、ubuntu18或ubuntu16）。攻击机统一使用kali或ubuntu20。
- scenario指代一个攻击场景，可以有多个攻击场景，每个攻击场景一般包含多个network
- network指代攻击场景中的一个网络层级，按照内外网的方式划分，network1一般指代外部网络，network2可以指代dmz网络和内部网络，以此类推。一个场景至少有内外网两个network
- bridge_node指网络层级之间的桥接节点，这里是举例子，多元组表示关系
- 一般规定network1是外部网络，network2是DMZ网络，network3是内部网络，但不强制要求按照这个顺序来划分网络层级，具体要根据文档内容来划分
- description指network的描述信息，必须详细描述这个网络层级的攻击内容和特点
- steps指攻击步骤，按照提示二中的步骤来展示，每个步骤包含不同的内容，可以有多个步骤，每个步骤包含不同的内容
- summary指对这个网络层级的攻击步骤进行细致描述，必须详细描述每个步骤的内容和目标，必须描述出使用什么工具，不少于150字！！！
- desc指对这个步骤的描述信息，必须非常详细描述这个步骤的攻击内容和特点，每步不少于150字
- node指这个步骤涉及哪些节点
- relationship指节点之间的关系，这里是举例子，永元组表示关系
- nodes表示节点的内容，每个节点包含不同的内容，可以有多个节点，每个节点包含不同的内容
-- type指节点类型，如服务器、工作站、移动设备等，可以用server、workstation、mobile等表示
-- os指节点涉及的操作系统，如Windows、Linux、macOS等，可以用具体的版本号来表示
-- services指节点涉及的服务、软件及其版本号，如Apache 2.4.46、MySQL 8.0.23等，可以用数组来表示
-- ports指节点涉及的端口号，如80、443等，可以用字典来表示，键为端口号，值为涉及的服务或软件
- tools指攻击工具，每个工具包含不同的内容，可以有多个工具，每个工具包含不同的内容
-- des指工具的描述信息，详细描述这个工具的功能和特点，结合文本来谈，不少于150字！！！
-- releation_content指工具的使用相关的信息，简要描述这个工具在攻击中的使用情况，可以包括具体的指令、参数、分析的内容等
-- scrpit指工具的代码或反编译还原的内容，简要描述这个工具在攻击中的代码实现或反编译还原的内容，可以包括具体的代码片段、功能实现等
-- url指工具的相关链接，如官方网站、GitHub仓库等，可以用字符串来表示
-- step指工具使用的步骤，如Reconnaissance、Weaponization等，并必须用自然语言详细描述这个工具在每个步骤中是怎么使用的，格式为步骤|描述，描述不能少于80字
-- node指工具使用的节点，如node1、node2等
-- parameter指工具使用的参数，如具体的命令行参数、配置文件参数等，可以用字符串来表示
- exploits指漏洞利用脚本，每个漏洞利用脚本包含不同的内容，可以有多个漏洞利用脚本，每个漏洞利用脚本包含不同的内容
-- releation_content指文档中对这个脚本的描述
-- scrpit指文档中对工具一些代码或着反编译还原的内容
-- url指工具的相关链接，如官方网站、GitHub仓库等，可以用字符串来表示
- vul_id指漏洞编号，如CVE-2026-12345，可以用字典来表示，键为漏洞编号，全部小写，值为漏洞的描述信息
-- des指漏洞的描述信息，可以上网搜索公开的信息来描述，但只有描述可以搜索网络，不要添加任何个人的分析和观点，保持客观中立，描述信息要简洁明了，突出重点
-- affected_software指漏洞影响的软件及版本，可以用数组来表示
-- releation_content指文档中对这个漏洞的一些使用相关的信息，比如具体使用的指令，参数，分析的内容等
-- scrpit指文档中对这个漏洞利用的一些代码或着反编译还原的内容
-- url指工具的相关链接，如官方网站、GitHub仓库等，可以用字符串来表示
-- step指漏洞利用的步骤，如Reconnaissance、Weaponization等，可以用数组来表示
-- node指漏洞利用的节点，如node1、node2等，可以用数组来表示,
-- parameter指漏洞利用的参数，如具体的命令行参数、配置文件参数等，可以用字符串来表示
输出格式如下：
[
  {{"scenario":{{
    "networks":[network1,network2,network3...],
    "networks_relationship":[((network1,network2),network1.nodes.node2),(network2,network3)],
    "steps_all":[step1.network1.steps.Reconnaissance,step2.network2.steps.Weaponization,step3.network3.steps.Delivery],
    "bridge_node":{{
      (network1,network2):"network1.nodes.node2",
      (network2,network3):"network2.nodes.node1"
    }}
  }}}},
  {{
    "network_name": "network1",
    "description": "攻击者通过互联网对目标企业进行信息收集，并构造钓鱼攻击载荷",
    "steps": {{
      "summary":"总结在这个网络里面主要做了哪些步骤",
      "Reconnaissance":{{
        "desc":"描述",
        "node":[node1,node2],
        "relationship":[(node1,node2),(node2,node3)]
      }},
      "Weaponization":{{
        "desc":"描述",
        "node":[node1,node2],
        "relationship":[(node1,node2),(node2,node3)]
      }},
      "Delivery":{{
        "desc":"描述",
        "node":[node1,node2],
        "relationship":[(node1,node2),(node2,node3)]
      }}
    }},
    "nodes":[
      {{
        "node1":{{
          "type":"server",
          "os":"Kali Linux",
          "services":["Whois","Maltego","GoPhish"],
          "ports":{{
            "80":"http",
            "443":"https"
          }}
        }}
      }},
      {{
        "node2":{{
          "type":"iot",
          "os":"Linux",
          "services":["service1"],
          "ports":{{
            "22":"ssh"
          }}
        }}
      }}
    ],
    "tools":[
      {{
        "theHarvester 4.3.0":{{
          "des":"工具描述",
          "releation_content":"",
          "scrpit":"",
          "url":"",
          "step":[step1],
          "node":[node1],
          "parameter":""
        }}
      }}
    ],
    "exploits":[
      {{
        "phishing_email_generator.py":{{
          "releation_content":"",
          "scrpit":"",
          "url":""
        }}
      }}
    ],
    "vul_id":[
      {{
        "cve-2026-12345":{{
          "des":"漏洞描述",
          "affected_software":["GoPhish"],
          "releation_content":"",
          "scrpit":"",
          "url":"",
          "step":[],
          "node":[],
          "parameter":""
        }}
      }}
    ]
  }}
]

Markdown内容：
----------------
{content}
----------------
"""


# ========================
# System Prompt for CVE Enrichment
# ========================
ENRICH_SYSTEM_PROMPT = "你是一个网络安全专家，擅长结合漏洞数据库信息对攻击场景进行补全与校正。"

ENRICH_USER_PROMPT_TEMPLATE = """
你将收到两部分JSON数据：
1) 原始攻击场景抽取结果（out JSON）
2) 对应漏洞的官方数据库记录（CVE JSON）

任务：
- 依据CVE JSON中的描述、影响范围、参考链接等信息，补全或修正原始攻击场景JSON中vul_id字段的描述信息（des、affected_software、url等）
- 依据CVE JSON中的内容检查并补全原始攻击场景中的所有节点的os、services、ports等信息，必须填写到精确到版本号的内容，可以根据cve库或者结合实际推测，但是不要联网搜索。信息里必须出现版本号。其中os指节点涉及的操作系统，如Windows、Linux、macOS等，可以用具体的版本号来表示，services指节点涉及的服务、软件及其版本号，如Apache 2.4.46、MySQL 8.0.23等，可以用数组来表示。ports指节点涉及的端口号，如80、443等，可以用字典来表示，键为端口号，值为涉及的服务或软件
- **【重要】操作系统约束**：严禁使用Windows系列操作系统和ubuntu22。必须使用ubuntu20、ubuntu18或ubuntu16。攻击机统一使用kali或ubuntu20。
- 检查网络拓扑是否连接，网络拓扑是否合理，理解其中内容，检查是否存在不合理的网络层级划分，是否存在不合理的节点关系等，并进行修正，可以增加node条目和network条目中的相关内容，使之合理。
- 如果out JSON中vul_id为空或缺失，但CVE JSON存在，请新增vul_id条目
- 如果一个攻击场景包含多个漏洞，请将所有漏洞的CVE信息综合用于补全
- 不要编造不存在的CVE编号
- 保持原有结构不变，仅在必要位置补充或更正
- 输出严格JSON（不要额外解释）

原始out JSON：
----------------
{out_json}
----------------

对应CVE JSON：
----------------
{cve_json}
----------------
"""


# ========================
# PDF to Markdown via Remote Service
# ========================
def pdf_to_markdown(pdf_path: str, use_ocr: bool = True, timeout: int = 600) -> str:
    """
    Convert a PDF file to Markdown text via remote PDF-RE service.

    Args:
        pdf_path: Path to the PDF file
        use_ocr: Whether to use OCR mode (high quality, requires GPU on server)
        timeout: Request timeout in seconds

    Returns:
        Markdown text content

    Raises:
        RuntimeError: If the remote service fails
    """
    service_url = os.environ.get('PDF_RE_SERVICE_URL', PDF_RE_SERVICE_URL)

    # Ensure URL has http:// prefix
    if service_url and not service_url.startswith(('http://', 'https://')):
        service_url = f'http://{service_url}'

    try:
        # Read PDF file and encode as base64
        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()
        pdf_b64 = base64.b64encode(pdf_content).decode('utf-8')

        # Call remote PDF-RE service
        response = requests.post(
            f"{service_url}/parse/base64",
            json={
                'content': pdf_b64,
                'use_ocr': use_ocr,
                'timeout': timeout
            },
            timeout=timeout + 30  # Extra buffer for network
        )

        if response.status_code != 200:
            raise RuntimeError(f"PDF-RE service error: {response.status_code} - {response.text}")

        result = response.json()

        if not result.get('success'):
            raise RuntimeError(f"PDF parsing failed: {result.get('error', 'Unknown error')}")

        return result['markdown']

    except requests.exceptions.Timeout:
        raise RuntimeError(f"PDF-RE service request timed out after {timeout}s")
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Cannot connect to PDF-RE service at {service_url}: {e}")
    except Exception as e:
        raise RuntimeError(f"Error calling PDF-RE service: {e}")


# ========================
# LLM API Call
# ========================
def call_llm_api(prompt: str, system_prompt: str = None, api_url: str = None,
                 api_key: str = None, model: str = None, timeout: int = 1200) -> str:
    """
    Call the LLM API to extract structured information.

    Args:
        prompt: The prompt to send to the LLM
        system_prompt: System prompt (optional)
        api_url: API endpoint URL (optional, uses default if not provided)
        api_key: API key (optional, uses default if not provided)
        model: Model name (optional, uses default if not provided)
        timeout: Request timeout in seconds

    Returns:
        LLM response content
    """
    url = api_url or API_URL
    key = api_key or API_KEY
    model_name = model or MODEL_NAME
    sys_prompt = system_prompt or SYSTEM_PROMPT

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }

    try:
        # DeepSeek-R1 is a reasoning model, needs longer timeout
        # Reasoning models can take 10-20 minutes for complex extraction
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)

        if response.status_code != 200:
            raise RuntimeError(f"API error: {response.status_code} - {response.text}")

        result = response.json()
        return result["choices"][0]["message"]["content"]

    except requests.exceptions.Timeout:
        raise RuntimeError(f"API request timed out after {timeout} seconds (DeepSeek-R1 reasoning model)")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"API request failed: {e}")


# ========================
# JSON Parser
# ========================
def safe_json_parse(text: str) -> List[Dict]:
    """
    Safely parse JSON from LLM output.
    Handles cases where LLM might include extra text around the JSON.

    Args:
        text: Raw LLM output text

    Returns:
        Parsed JSON as a list of dictionaries
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON array from the text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Try to extract JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return [json.loads(match.group())]
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Failed to parse JSON from LLM output: {text[:200]}...")


# ========================
# CVE Database Functions
# ========================
def extract_cve_ids(scenario_data: List[Dict]) -> Set[str]:
    """
    Extract all CVE IDs from scenario data.

    Args:
        scenario_data: List of scenario objects

    Returns:
        Set of CVE IDs (uppercase)
    """
    cve_ids = set()

    if isinstance(scenario_data, dict):
        items = [scenario_data]
    elif isinstance(scenario_data, list):
        items = scenario_data
    else:
        return cve_ids

    for item in items:
        if not isinstance(item, dict):
            continue
        vul_list = item.get("vul_id", [])
        if isinstance(vul_list, dict):
            vul_list = [vul_list]
        if not isinstance(vul_list, list):
            continue
        for vul in vul_list:
            if not isinstance(vul, dict):
                continue
            for cve_id in vul.keys():
                if isinstance(cve_id, str) and cve_id.upper().startswith("CVE-"):
                    cve_ids.add(cve_id.upper())

    return cve_ids


def find_cve_json_file(cve_id: str, db_root: str) -> Optional[Path]:
    """
    Find the CVE JSON file in the local CVE database.

    CVE database structure (cvelistV5 format):
    db_root/
    ├── 2021/
    │   ├── 1xxx/
    │   │   ├── CVE-2021-1234.json
    │   │   └── ...
    │   └── ...
    └── ...

    Args:
        cve_id: CVE ID (e.g., "CVE-2021-44228")
        db_root: Root directory of CVE database

    Returns:
        Path to the CVE JSON file, or None if not found
    """
    if not cve_id or not cve_id.upper().startswith("CVE-"):
        return None

    parts = cve_id.upper().split("-")
    if len(parts) < 3:
        return None

    year = parts[1]
    number = parts[2]

    # Standard path: db_root/YEAR/PREFIX/CVE-ID.json
    # PREFIX is the first digit followed by "xxx" (e.g., "4xxx" for CVE-2021-44228)
    prefix = number[0] + "xxx"
    candidate = Path(db_root) / year / prefix / f"{cve_id.upper()}.json"

    if candidate.exists():
        return candidate

    # Fallback: recursive search
    db_root_path = Path(db_root)
    for path in db_root_path.rglob(f"{cve_id.upper()}.json"):
        return path

    return None


def load_cve_record(cve_id: str, db_root: str = None) -> Optional[Dict]:
    """
    Load a CVE record from the local database.

    Args:
        cve_id: CVE ID (e.g., "CVE-2021-44228")
        db_root: Root directory of CVE database (optional, uses CVE_DB_PATH env var)

    Returns:
        CVE record as dictionary, or None if not found
    """
    db_path = db_root or CVE_DB_PATH

    cve_path = find_cve_json_file(cve_id, db_path)
    if not cve_path:
        return None

    try:
        with open(cve_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_cve_records_for_scenario(scenario_data: List[Dict], db_root: str = None,
                                   log_func=None) -> Dict[str, Dict]:
    """
    Load all CVE records mentioned in the scenario data.

    Args:
        scenario_data: List of scenario objects
        db_root: Root directory of CVE database
        log_func: Optional logging function

    Returns:
        Dictionary mapping CVE IDs to their records
    """
    log = log_func or print
    db_path = db_root or CVE_DB_PATH

    cve_ids = extract_cve_ids(scenario_data)
    cve_records = {}

    for cve_id in cve_ids:
        record = load_cve_record(cve_id, db_path)
        if record:
            cve_records[cve_id] = record
            log(f"[CVE_ENRICH] Found CVE record: {cve_id}")
        else:
            log(f"[CVE_ENRICH] CVE record not found: {cve_id}")

    return cve_records


# ========================
# CVE Enrichment Function
# ========================
def enrich_with_cve_database(scenario_data: List[Dict], db_root: str = None,
                              log_func=None) -> List[Dict]:
    """
    Enrich scenario data with information from local CVE database.

    This function takes the extracted scenario data and uses CVE database
    records to fill in missing information (affected software, descriptions, etc.)

    Args:
        scenario_data: List of scenario objects from extract_attack_scenario
        db_root: Root directory of CVE database (optional)
        log_func: Optional logging function

    Returns:
        Enriched scenario data
    """
    log = log_func or print

    # Step 1: Load CVE records
    log("[CVE_ENRICH] Loading CVE records...")
    cve_records = load_cve_records_for_scenario(scenario_data, db_root, log)

    if not cve_records:
        log("[CVE_ENRICH] No CVE records found, skipping enrichment")
        return scenario_data

    log(f"[CVE_ENRICH] Found {len(cve_records)} CVE record(s)")

    # Step 2: Call LLM for enrichment
    log("[CVE_ENRICH] Calling LLM for enrichment...")
    prompt = ENRICH_USER_PROMPT_TEMPLATE.format(
        out_json=json.dumps(scenario_data, ensure_ascii=False),
        cve_json=json.dumps(cve_records, ensure_ascii=False)
    )

    try:
        llm_response = call_llm_api(prompt, system_prompt=ENRICH_SYSTEM_PROMPT)
        log(f"[CVE_ENRICH] LLM response length: {len(llm_response)} chars")

        # Step 3: Parse enriched JSON
        enriched_data = safe_json_parse(llm_response)
        log(f"[CVE_ENRICH] Successfully enriched {len(enriched_data)} scenario(s)")

        return enriched_data

    except Exception as e:
        log(f"[CVE_ENRICH] Enrichment failed: {e}")
        return scenario_data  # Return original data on failure


# ========================
# Main Extraction Function
# ========================
def extract_attack_scenario(
    pdf_path: str,
    max_content_length: int = 12000,
    use_ocr: bool = True,
    timeout: int = 600,
    enable_cve_enrichment: bool = False,
    cve_db_path: str = None,
    log_func=None
) -> Dict[str, Any]:
    """
    Extract structured attack scenario from a PDF file.

    This is the main entry point for PDF extraction.

    Args:
        pdf_path: Path to the PDF file
        max_content_length: Maximum content length to send to LLM (chars)
        use_ocr: Whether to use OCR mode (high quality, requires GPU on PDF-RE server)
        timeout: Timeout for PDF parsing in seconds
        enable_cve_enrichment: Whether to enrich with CVE database (default: False)
        cve_db_path: Path to CVE database (optional, uses CVE_DB_PATH env var)
        log_func: Optional logging function (default: print)

    Returns:
        Dictionary containing structured attack scenario information.
        Structure:
        {
            "success": bool,
            "data": [...],  # List of scenario objects
            "error": str,   # Error message if failed
            "markdown": str # Raw markdown content (for debugging)
        }
    """
    log = log_func or print

    result = {
        "success": False,
        "data": [],
        "error": None,
        "markdown": None
    }

    try:
        # Step 1: Convert PDF to Markdown via remote PDF-RE service
        log(f"[PDF_EXTRACTOR] Converting PDF to Markdown via PDF-RE service: {pdf_path}")
        markdown_content = pdf_to_markdown(pdf_path, use_ocr=use_ocr, timeout=timeout)
        result["markdown"] = markdown_content

        log(f"[PDF_EXTRACTOR] Markdown length: {len(markdown_content)} chars")

        # Step 2: Truncate if too long
        if len(markdown_content) > max_content_length:
            log(f"[PDF_EXTRACTOR] Truncating content from {len(markdown_content)} to {max_content_length}")
            markdown_content = markdown_content[:max_content_length]

        # Step 3: Call LLM to extract structured information
        log("[PDF_EXTRACTOR] Calling LLM API for extraction...")
        prompt = USER_PROMPT_TEMPLATE.format(content=markdown_content)
        llm_response = call_llm_api(prompt)

        log(f"[PDF_EXTRACTOR] LLM response length: {len(llm_response)} chars")

        # Step 4: Parse JSON response
        log("[PDF_EXTRACTOR] Parsing JSON response...")
        parsed_data = safe_json_parse(llm_response)

        # Step 5: CVE Enrichment (optional)
        if enable_cve_enrichment:
            log("[PDF_EXTRACTOR] CVE enrichment enabled, processing...")
            parsed_data = enrich_with_cve_database(parsed_data, cve_db_path, log)

        result["success"] = True
        result["data"] = parsed_data

        log(f"[PDF_EXTRACTOR] Successfully extracted {len(parsed_data)} scenario(s)")

    except Exception as e:
        result["error"] = str(e)
        log(f"[PDF_EXTRACTOR] Error: {e}")

    return result


def extract_attack_scenario_simple(pdf_path: str, enable_cve_enrichment: bool = False) -> str:
    """
    Simple wrapper that returns just the JSON string.
    This matches the existing get_VSDL_script_local interface.

    Args:
        pdf_path: Path to the PDF file
        enable_cve_enrichment: Whether to enrich with CVE database

    Returns:
        JSON string of extracted data, or error message
    """
    try:
        result = extract_attack_scenario(pdf_path, enable_cve_enrichment=enable_cve_enrichment)

        if result["success"]:
            return json.dumps(result["data"], ensure_ascii=False)
        else:
            return json.dumps({"error": result["error"]}, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ========================
# Convenience Functions
# ========================
def get_all_nodes(scenario_data: List[Dict]) -> List[Dict]:
    """
    Extract all nodes from scenario data.

    Args:
        scenario_data: List of scenario objects from extract_attack_scenario

    Returns:
        List of node dictionaries with network context
    """
    nodes = []
    for item in scenario_data:
        if "nodes" in item:
            for node_entry in item["nodes"]:
                nodes.append({
                    "network": item.get("network_name", "unknown"),
                    **node_entry
                })
    return nodes


def get_all_vulnerabilities(scenario_data: List[Dict]) -> List[Dict]:
    """
    Extract all vulnerabilities from scenario data.

    Args:
        scenario_data: List of scenario objects from extract_attack_scenario

    Returns:
        List of vulnerability dictionaries
    """
    vulns = []
    for item in scenario_data:
        if "vul_id" in item:
            for vuln_entry in item["vul_id"]:
                vulns.append(vuln_entry)
    return vulns


def get_all_tools(scenario_data: List[Dict]) -> List[Dict]:
    """
    Extract all tools from scenario data.

    Args:
        scenario_data: List of scenario objects from extract_attack_scenario

    Returns:
        List of tool dictionaries
    """
    tools = []
    for item in scenario_data:
        if "tools" in item:
            for tool_entry in item["tools"]:
                tools.append(tool_entry)
    return tools


# ========================
# Test Entry Point
# ========================
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pdf_extractor.py <pdf_path> [--enrich]")
        print("  --enrich: Enable CVE database enrichment")
        sys.exit(1)

    pdf_path = sys.argv[1]
    enable_enrichment = "--enrich" in sys.argv

    result = extract_attack_scenario(pdf_path, enable_cve_enrichment=enable_enrichment)

    print("\n" + "="*60)
    print("EXTRACTION RESULT")
    print("="*60)

    if result["success"]:
        print(json.dumps(result["data"], indent=2, ensure_ascii=False))
    else:
        print(f"Error: {result['error']}")