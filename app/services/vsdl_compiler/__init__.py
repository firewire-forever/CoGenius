"""
VSDL Python Compiler
A simplified Python implementation of VSDL (Virtual Security Description Language) compiler
with extended vulnerability topology support.

Features:
- Parse VSDL scripts into AST
- SMT-based constraint validation
- Terraform code generation
- Ansible playbook generation
- Extended vulnerability topology support

Usage:
    from vsdl_compiler import VSDLCompiler

    compiler = VSDLCompiler()
    result = compiler.compile("script.vsdl", output_dir="./output")

    if result.success:
        print(f"Scenario: {result.scenario.name}")
        print(f"Networks: {len(result.scenario.networks)}")
        print(f"Nodes: {len(result.scenario.nodes)}")
        print(f"Vulnerabilities: {len(result.scenario.vulnerabilities)}")
    else:
        for error in result.errors:
            print(f"Error: {error}")
"""

__version__ = '0.1.0'

from .ast_nodes import (
    Scenario,
    NetworkDefinition,
    NodeDefinition,
    VulnerabilityDefinition,
    SoftwareDependency,
    NetworkConnection,
    ComparisonOperator,
    CompilationResult,
)

from .parser import VSDLParser
from .validator import SMTValidator, ValidationResult, ValidationError, VulnerabilityGraphAnalyzer
from .compiler import VSDLCompiler, compile_vsdl

__all__ = [
    # Main API
    'VSDLCompiler',
    'compile_vsdl',

    # AST Nodes
    'Scenario',
    'NetworkDefinition',
    'NodeDefinition',
    'VulnerabilityDefinition',
    'SoftwareDependency',
    'NetworkConnection',
    'ComparisonOperator',
    'CompilationResult',

    # Components
    'VSDLParser',
    'SMTValidator',
    'ValidationResult',
    'ValidationError',
    'VulnerabilityGraphAnalyzer',
]