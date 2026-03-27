"""
VSDL Python Compiler - Lexer and Parser
Implements lexical analysis and parsing using Lark parser generator.
"""

from lark import Lark, Transformer, Token
from typing import List, Optional, Tuple
from .ast_nodes import (
    Scenario, NetworkDefinition, NetworkConnection, NodeDefinition,
    VulnerabilityDefinition, SoftwareDependency, ComparisonOperator
)


# VSDL Grammar Definition using Lark's EBNF
VSDL_GRAMMAR = r"""
start: scenario

scenario: "scenario" IDENTIFIER "duration" NUMBER "{" statement* "}"

statement: network_def
         | node_def
         | vulnerability_def

// Network definitions
network_def: "network" IDENTIFIER "{" network_stmt* "}"

network_stmt: address_range
            | node_connected
            | node_has_ip
            | gateway_internet

address_range: "addresses" "range" "is" CIDR ";"
node_connected: "node" IDENTIFIER "is" "connected" ";"
node_has_ip: "node" IDENTIFIER "has" "IP" IP_ADDR ";"
gateway_internet: "gateway" "has" "direct" "access" "to" "the" "Internet" ";"

// Node definitions
node_def: "node" IDENTIFIER "{" node_stmt* "}"

node_stmt: ram_constraint
         | disk_constraint
         | vcpu_constraint
         | os_definition
         | software_mount

// Original VSDL syntax from Java: "ram larger than 4 GB" or "ram size equal to 4 GB"
// Also support compact format: "ram larger than 4GB"
ram_constraint: "ram" ("size")? ram_op (NUMBER unit? | NUMBER_WITH_UNIT) ";"

disk_constraint: "disk" ("size")? disk_op (NUMBER unit? | NUMBER_WITH_UNIT) ";"

unit: "GB" | "MB" | "TB"

ram_op: "larger" "than" -> ram_larger_op
      | "smaller" "than" -> ram_smaller_op
      | "equal" "to" -> ram_equal_op

disk_op: "larger" "than" -> disk_larger_op
       | "smaller" "than" -> disk_smaller_op
       | "equal" "to" -> disk_equal_op

vcpu_constraint: "vcpu" "equal" "to" NUMBER ";"

os_definition: "node" "OS" "is" STRING ";"

software_mount: "mounts" "software" SOFTWARE_NAME software_options? ";"

software_options: software_version? software_with? software_config?
software_version: "version" VERSION_OR_NUMBER
software_with: "with" SOFTWARE_NAME ("," SOFTWARE_NAME)*
software_config: "config" STRING

// Vulnerability definitions (NEW)
vulnerability_def: "vulnerability" IDENTIFIER "{" vuln_stmt* "}"

vuln_stmt: vulnerable_software
         | cve_id
         | depends_on_software
         | triggers_vulnerability
         | requires_vulnerability
         | hosted_on_node

vulnerable_software: "vulnerable" "software" SOFTWARE_NAME ("version" VERSION_OR_NUMBER)? ";"
cve_id: "cve" "id" "is" STRING ";"
depends_on_software: "depends" "on" SOFTWARE_NAME ("version" VERSION_OR_NUMBER)? ";"
triggers_vulnerability: "triggers" "vulnerability" IDENTIFIER ";"
requires_vulnerability: "requires" "vulnerability" IDENTIFIER ";"
hosted_on_node: "hosted" "on" "node" IDENTIFIER ";"

// Tokens - order matters! More specific patterns first
IDENTIFIER: /[a-zA-Z_][a-zA-Z0-9_]*/
SOFTWARE_NAME: /[a-zA-Z_][a-zA-Z0-9_\-]*/  // Allow hyphens in software names
CIDR: /\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\/\d{1,2}/
IP_ADDR: /\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/
VERSION_OR_NUMBER: /\d+(\.\d+)+|\d+/  // Match version like 2.14.1 or simple number like 11
NUMBER: /\d+/
NUMBER_WITH_UNIT: /\d+(GB|MB|TB)/  // Compact format like 4GB, 80GB
STRING: /"[^"]*"/

%ignore /\s+/
%ignore /\/\/[^\n]*/
%ignore /\/\*[\s\S]*?\*\//
"""


class VSDLTransformer(Transformer):
    """
    Transforms Lark parse tree into AST nodes.
    """

    def start(self, items):
        print(f"[DEBUG] start() called with {len(items)} items")
        return items[0]

    def statement(self, items):
        """Transform statement rule to return the inner element directly."""
        print(f"[DEBUG] statement() called with {len(items)} items: {[type(i).__name__ if not isinstance(i, str) else i for i in items]}")
        return items[0]  # Return the network_def, node_def, or vulnerability_def

    def scenario(self, items):
        print(f"[DEBUG] scenario() called with {len(items)} items: {[type(i).__name__ if not isinstance(i, str) else i for i in items]}")
        name = str(items[0])
        duration = int(items[1])
        statements = items[2:]

        networks = []
        nodes = []
        vulnerabilities = []

        for stmt in statements:
            if isinstance(stmt, NetworkDefinition):
                networks.append(stmt)
            elif isinstance(stmt, NodeDefinition):
                nodes.append(stmt)
            elif isinstance(stmt, VulnerabilityDefinition):
                vulnerabilities.append(stmt)

        return Scenario(
            name=name,
            duration=duration,
            networks=networks,
            nodes=nodes,
            vulnerabilities=vulnerabilities
        )

    def network_def(self, items):
        print(f"[DEBUG] network_def() called with {len(items)} items")
        name = str(items[0])
        stmts = items[1:]

        address_range = None
        connections = []
        has_internet_gateway = False

        for stmt in stmts:
            print(f"[DEBUG] network_def stmt: {stmt}")
            if isinstance(stmt, tuple):
                if stmt[0] == 'address_range':
                    address_range = stmt[1]
                elif stmt[0] == 'connected':
                    connections.append(NetworkConnection(node_name=stmt[1]))
                elif stmt[0] == 'has_ip':
                    # Update the last connection with IP
                    if connections:
                        connections[-1].ip_address = stmt[1]
                elif stmt[0] == 'gateway':
                    has_internet_gateway = True

        return NetworkDefinition(
            name=name,
            address_range=address_range,
            connections=connections,
            has_internet_gateway=has_internet_gateway
        )

    def network_stmt(self, items):
        """Transform network_stmt to return the inner statement directly."""
        print(f"[DEBUG] network_stmt() called with {len(items)} items: {items}")
        return items[0]

    def address_range(self, items):
        return ('address_range', str(items[0]))

    def node_connected(self, items):
        return ('connected', str(items[0]))

    def node_has_ip(self, items):
        if len(items) >= 2:
            return ('has_ip', str(items[1]))
        return ('has_ip', '')

    def gateway_internet(self, items):
        return ('gateway', True)

    def node_def(self, items):
        print(f"[DEBUG] node_def() called with {len(items)} items")
        name = str(items[0])
        stmts = items[1:]

        ram_value = None
        ram_operator = None
        disk_value = None
        disk_operator = None
        vcpu = None
        os_image = None
        software_mounts = []

        for stmt in stmts:
            print(f"[DEBUG] node_def stmt: {type(stmt).__name__ if not isinstance(stmt, dict) else 'dict'}: {stmt if not isinstance(stmt, dict) else list(stmt.keys())}")
            if isinstance(stmt, dict):
                if 'ram' in stmt:
                    ram_value = stmt['ram']['value']
                    ram_operator = stmt['ram']['operator']
                elif 'disk' in stmt:
                    disk_value = stmt['disk']['value']
                    disk_operator = stmt['disk']['operator']
                elif 'vcpu' in stmt:
                    vcpu = stmt['vcpu']
                elif 'os' in stmt:
                    os_image = stmt['os']
                elif 'software' in stmt:
                    software_mounts.append(stmt['software'])

        return NodeDefinition(
            name=name,
            ram_value=ram_value,
            ram_operator=ram_operator,
            disk_value=disk_value,
            disk_operator=disk_operator,
            vcpu=vcpu,
            os_image=os_image,
            software_mounts=software_mounts
        )

    def node_stmt(self, items):
        """Transform node_stmt to return the inner statement directly."""
        print(f"[DEBUG] node_stmt() called with {len(items)} items: {items}")
        return items[0]

    def ram_constraint(self, items):
        # items: [optional_size_keyword, operator, value, optional_unit]
        # After parsing: [ram_op_result, NUMBER, optional_unit] or similar
        print(f"[DEBUG] ram_constraint() called with {len(items)} items: {items}")
        if len(items) < 2:
            return {'ram': {'value': 0, 'operator': ComparisonOperator.EQUAL_TO}}

        # Find the operator and value
        operator = None
        value = None

        for item in items:
            if isinstance(item, dict) and 'operator' in item:
                operator = item['operator']
            elif isinstance(item, int):
                value = item

        if operator is None:
            operator = ComparisonOperator.EQUAL_TO
        if value is None:
            value = 0

        return {'ram': {'value': value, 'operator': operator}}

    def ram_op(self, items):
        # This shouldn't be called directly as we have specific rules
        pass

    def ram_larger_op(self, items):
        return {'operator': ComparisonOperator.LARGER_THAN}

    def ram_smaller_op(self, items):
        return {'operator': ComparisonOperator.SMALLER_THAN}

    def ram_equal_op(self, items):
        return {'operator': ComparisonOperator.EQUAL_TO}

    def disk_constraint(self, items):
        print(f"[DEBUG] disk_constraint() called with {len(items)} items: {items}")
        if len(items) < 2:
            return {'disk': {'value': 0, 'operator': ComparisonOperator.EQUAL_TO}}

        operator = None
        value = None

        for item in items:
            if isinstance(item, dict) and 'operator' in item:
                operator = item['operator']
            elif isinstance(item, int):
                value = item

        if operator is None:
            operator = ComparisonOperator.EQUAL_TO
        if value is None:
            value = 0

        return {'disk': {'value': value, 'operator': operator}}

    def disk_larger_op(self, items):
        return {'operator': ComparisonOperator.LARGER_THAN}

    def disk_smaller_op(self, items):
        return {'operator': ComparisonOperator.SMALLER_THAN}

    def disk_equal_op(self, items):
        return {'operator': ComparisonOperator.EQUAL_TO}

    def vcpu_constraint(self, items):
        return {'vcpu': int(items[0])}

    def os_definition(self, items):
        return {'os': str(items[0]).strip('"')}

    def software_mount(self, items):
        name = str(items[0])
        version = None
        dependencies = []
        config = {}

        if len(items) > 1 and isinstance(items[1], dict):
            opts = items[1]
            version = opts.get('version')
            dependencies = opts.get('with', [])
            config = opts.get('config', {})

        return {'software': SoftwareDependency(
            name=name,
            version=version,
            dependencies=dependencies,
            config=config
        )}

    def software_options(self, items):
        result = {'version': None, 'with': [], 'config': ''}
        for item in items:
            if isinstance(item, dict):
                if 'version' in item:
                    result['version'] = item['version']
                elif 'with' in item:
                    result['with'] = item['with']
                elif 'config' in item:
                    result['config'] = item['config']
        return result

    def software_version(self, items):
        return {'version': str(items[0])}

    def software_with(self, items):
        return {'with': [str(i) for i in items]}

    def software_config(self, items):
        # config 现在是一个字符串
        config_str = str(items[0]).strip('"')
        # 尝试解析为 key=value 格式，否则返回原始字符串
        config_dict = {}
        try:
            for pair in config_str.split(';'):
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    config_dict[key.strip()] = value.strip().strip('"')
        except Exception:
            pass
        return {'config': config_dict if config_dict else config_str}

    # Vulnerability parsing
    def vulnerability_def(self, items):
        name = str(items[0])
        stmts = items[1:]

        vulnerable_software = None
        vulnerable_version = None
        cve_id = None
        software_dependencies = []
        triggers = []
        requires = []
        hosted_on = None

        for stmt in stmts:
            if isinstance(stmt, dict):
                if 'vulnerable_software' in stmt:
                    vulnerable_software = stmt['vulnerable_software']
                    vulnerable_version = stmt.get('vulnerable_version')
                elif 'cve_id' in stmt:
                    cve_id = stmt['cve_id']
                elif 'depends_on' in stmt:
                    software_dependencies.append(stmt['depends_on'])
                elif 'triggers' in stmt:
                    triggers.append(stmt['triggers'])
                elif 'requires' in stmt:
                    requires.append(stmt['requires'])
                elif 'hosted_on' in stmt:
                    hosted_on = stmt['hosted_on']

        return VulnerabilityDefinition(
            name=name,
            vulnerable_software=vulnerable_software,
            vulnerable_version=vulnerable_version,
            cve_id=cve_id,
            software_dependencies=software_dependencies,
            triggers_vulnerabilities=triggers,
            requires_vulnerabilities=requires,
            hosted_on_node=hosted_on
        )

    def vuln_stmt(self, items):
        """Transform vuln_stmt to return the inner statement directly."""
        print(f"[DEBUG] vuln_stmt() called with {len(items)} items: {items}")
        return items[0]

    def vulnerable_software(self, items):
        result = {'vulnerable_software': str(items[0])}
        if len(items) > 1:
            result['vulnerable_version'] = str(items[1])
        return result

    def cve_id(self, items):
        return {'cve_id': str(items[0]).strip('"')}

    def depends_on_software(self, items):
        dep = SoftwareDependency(name=str(items[0]))
        if len(items) > 1:
            dep.version = str(items[1])
        return {'depends_on': dep}

    def triggers_vulnerability(self, items):
        return {'triggers': str(items[0])}

    def requires_vulnerability(self, items):
        return {'requires': str(items[0])}

    def hosted_on_node(self, items):
        return {'hosted_on': str(items[0])}

    # Token transformations
    def STRING(self, token):
        return str(token)

    def NUMBER(self, token):
        return int(token)

    def IDENTIFIER(self, token):
        return str(token)

    def SOFTWARE_NAME(self, token):
        return str(token)

    def CIDR(self, token):
        return str(token)

    def IP_ADDR(self, token):
        return str(token)

    def VERSION_OR_NUMBER(self, token):
        return str(token)

    def NUMBER_WITH_UNIT(self, token):
        """Extract number from compact format like '4GB' -> 4"""
        import re
        match = re.match(r'(\d+)(GB|MB|TB)', str(token))
        if match:
            return int(match.group(1))
        return int(str(token).rstrip('GBMTB'))

    def unit(self, items):
        """Unit token - just return the value, we use GB as default."""
        return str(items[0]) if items else 'GB'


class VSDLParser:
    """
    VSDL Parser - parses VSDL scripts into AST.
    """

    def __init__(self):
        self.parser = Lark(
            VSDL_GRAMMAR,
            parser='lalr',
            transformer=VSDLTransformer(),
            start='start'
        )

    def parse(self, source: str) -> Scenario:
        """
        Parse a VSDL script string into an AST.

        Args:
            source: VSDL script source code

        Returns:
            Scenario AST node

        Raises:
            Exception: If parsing fails
        """
        import traceback
        try:
            return self.parser.parse(source)
        except IndexError as e:
            print(f"\n=== DEBUG: IndexError in parser ===")
            print(f"Error: {e}")
            traceback.print_exc()
            raise ValueError(f"VSDL parsing error (IndexError): {str(e)}")
        except Exception as e:
            print(f"\n=== DEBUG: General error in parser ===")
            print(f"Error type: {type(e).__name__}")
            print(f"Error: {e}")
            traceback.print_exc()
            raise ValueError(f"VSDL parsing error: {str(e)}")

    def parse_file(self, file_path: str) -> Scenario:
        """
        Parse a VSDL file into an AST.

        Args:
            file_path: Path to the VSDL file

        Returns:
            Scenario AST node
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        return self.parse(source)