"""
VSDL Python Compiler - Main Compiler
Orchestrates parsing, validation, and code generation.
"""

import os
from typing import Dict, Optional, Any
from pathlib import Path

from .parser import VSDLParser
from .validator import SMTValidator, ValidationResult
from .ast_nodes import Scenario, CompilationResult
from .generator import TerraformGenerator, AnsibleGenerator


class VSDLCompiler:
    """
    Main VSDL Compiler class.

    Usage:
        compiler = VSDLCompiler()
        result = compiler.compile("script.vsdl", output_dir="./output")
    """

    def __init__(self, openstack_config: Optional[Dict[str, Any]] = None):
        """
        Initialize the VSDL compiler.

        Args:
            openstack_config: Optional OpenStack configuration for Terraform
        """
        self.parser = VSDLParser()
        self.validator = SMTValidator()
        self.terraform_gen = TerraformGenerator()
        self.ansible_gen = AnsibleGenerator()
        self.openstack_config = openstack_config or {}

    def compile(self, source: str, output_dir: Optional[str] = None,
                validate_only: bool = False) -> CompilationResult:
        """
        Compile a VSDL script.

        Args:
            source: VSDL script source code or file path
            output_dir: Optional output directory for generated files
            validate_only: If True, only validate without generating code

        Returns:
            CompilationResult with status and generated files
        """
        # Check if source is a file path
        if os.path.isfile(source):
            with open(source, 'r', encoding='utf-8') as f:
                source = f.read()

        # Parse
        try:
            scenario = self.parser.parse(source)
        except Exception as e:
            return CompilationResult(
                success=False,
                errors=[f"Parse error: {str(e)}"]
            )

        # Validate
        validation_result = self.validator.validate(scenario)

        if not validation_result.is_sat:
            return CompilationResult(
                success=False,
                scenario=scenario,
                errors=[e.message for e in validation_result.errors],
                warnings=validation_result.warnings
            )

        if validate_only:
            return CompilationResult(
                success=True,
                scenario=scenario,
                warnings=validation_result.warnings
            )

        # Generate code
        terraform_files = self.terraform_gen.generate(scenario, self.openstack_config)
        ansible_files = self.ansible_gen.generate(scenario)

        # Write to output directory if specified
        if output_dir:
            self._write_files(output_dir, terraform_files, 'terraform')
            self._write_files(output_dir, ansible_files, 'ansible')

        return CompilationResult(
            success=True,
            scenario=scenario,
            terraform_files=terraform_files,
            ansible_files=ansible_files,
            warnings=validation_result.warnings
        )

    def compile_file(self, file_path: str, output_dir: Optional[str] = None,
                     validate_only: bool = False) -> CompilationResult:
        """
        Compile a VSDL file.

        Args:
            file_path: Path to the VSDL file
            output_dir: Optional output directory for generated files
            validate_only: If True, only validate without generating code

        Returns:
            CompilationResult with status and generated files
        """
        return self.compile(file_path, output_dir, validate_only)

    def validate(self, source: str) -> ValidationResult:
        """
        Validate a VSDL script without generating code.

        Args:
            source: VSDL script source code or file path

        Returns:
            ValidationResult with SAT status
        """
        # Check if source is a file path
        if os.path.isfile(source):
            with open(source, 'r', encoding='utf-8') as f:
                source = f.read()

        # Parse
        try:
            scenario = self.parser.parse(source)
        except Exception as e:
            return ValidationResult(
                is_sat=False,
                errors=[type('ValidationError', (), {
                    'type': 'parse',
                    'message': str(e),
                    'location': None
                })()],
                warnings=[]
            )

        # Validate
        return self.validator.validate(scenario)

    def _write_files(self, base_dir: str, files: Dict[str, str], subdir: str):
        """Write generated files to the output directory"""
        output_path = Path(base_dir) / subdir
        output_path.mkdir(parents=True, exist_ok=True)

        for filename, content in files.items():
            file_path = output_path / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

    def get_vulnerability_graph(self, source: str) -> Dict[str, Any]:
        """
        Get the vulnerability dependency graph from a VSDL script.

        Args:
            source: VSDL script source code or file path

        Returns:
            Dict with graph structure and analysis
        """
        if os.path.isfile(source):
            with open(source, 'r', encoding='utf-8') as f:
                source = f.read()

        try:
            scenario = self.parser.parse(source)
            return {
                'nodes': [v.to_dict() for v in scenario.vulnerabilities],
                'edges': scenario.get_vulnerability_graph(),
                'node_vulnerabilities': scenario.get_node_vulnerabilities()
            }
        except Exception as e:
            return {'error': str(e)}


def compile_vsdl(source: str, output_dir: Optional[str] = None,
                  openstack_config: Optional[Dict] = None) -> CompilationResult:
    """
    Convenience function to compile a VSDL script.

    Args:
        source: VSDL script source code or file path
        output_dir: Optional output directory for generated files
        openstack_config: Optional OpenStack configuration

    Returns:
        CompilationResult with status and generated files
    """
    compiler = VSDLCompiler(openstack_config)
    return compiler.compile(source, output_dir)