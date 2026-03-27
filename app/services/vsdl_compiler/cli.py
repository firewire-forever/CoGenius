#!/usr/bin/env python3
"""
VSDL Python Compiler - CLI Entry Point
"""

import click
import json
import sys
from pathlib import Path

from vsdl_compiler import VSDLCompiler, __version__


@click.group()
@click.version_option(version=__version__)
def cli():
    """VSDL Python Compiler - Compile VSDL scripts to Terraform/Ansible"""
    pass


@cli.command()
@click.argument('source', type=click.Path(exists=True))
@click.option('-o', '--output', type=click.Path(), default='./output',
              help='Output directory for generated files')
@click.option('--validate-only', is_flag=True,
              help='Only validate, do not generate code')
@click.option('--format', 'output_format', type=click.Choice(['text', 'json']),
              default='text', help='Output format')
def compile(source, output, validate_only, output_format):
    """Compile a VSDL script file."""
    compiler = VSDLCompiler()

    try:
        result = compiler.compile(source, output, validate_only)

        if output_format == 'json':
            output_data = {
                'success': result.success,
                'scenario': result.scenario.to_dict() if result.scenario else None,
                'errors': result.errors,
                'warnings': result.warnings,
                'terraform_files': list(result.terraform_files.keys()) if result.terraform_files else [],
                'ansible_files': list(result.ansible_files.keys()) if result.ansible_files else [],
            }
            click.echo(json.dumps(output_data, indent=2))
        else:
            if result.success:
                click.echo(f"✅ Compilation successful!")
                click.echo(f"   Scenario: {result.scenario.name}")
                click.echo(f"   Duration: {result.scenario.duration} TTU")
                click.echo(f"   Networks: {len(result.scenario.networks)}")
                click.echo(f"   Nodes: {len(result.scenario.nodes)}")
                click.echo(f"   Vulnerabilities: {len(result.scenario.vulnerabilities)}")

                if not validate_only:
                    click.echo(f"\n   Generated files in: {output}")
                    click.echo(f"   Terraform files: {len(result.terraform_files)}")
                    click.echo(f"   Ansible files: {len(result.ansible_files)}")

                if result.warnings:
                    click.echo(f"\n   ⚠️  Warnings:")
                    for warning in result.warnings:
                        click.echo(f"      - {warning}")
            else:
                click.echo(f"❌ Compilation failed!")
                for error in result.errors:
                    click.echo(f"   Error: {error}")
                sys.exit(1)

    except Exception as e:
        click.echo(f"❌ Error: {str(e)}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('source', type=click.Path(exists=True))
@click.option('--format', 'output_format', type=click.Choice(['text', 'json', 'dot']),
              default='text', help='Output format')
def graph(source, output_format):
    """Show the vulnerability dependency graph."""
    compiler = VSDLCompiler()

    try:
        graph_data = compiler.get_vulnerability_graph(source)

        if 'error' in graph_data:
            click.echo(f"❌ Error: {graph_data['error']}", err=True)
            sys.exit(1)

        if output_format == 'json':
            click.echo(json.dumps(graph_data, indent=2))
        elif output_format == 'dot':
            # Generate GraphViz DOT format
            click.echo('digraph VulnerabilityGraph {')
            click.echo('  rankdir=LR;')
            click.echo('  node [shape=box];')
            click.echo()

            for node in graph_data['nodes']:
                label = f"{node['name']}\\n{node.get('cve_id', 'N/A')}"
                click.echo(f'  "{node["name"]}" [label="{label}"];')

            click.echo()
            for vuln_name, deps in graph_data['edges'].items():
                for dep in deps:
                    click.echo(f'  "{dep}" -> "{vuln_name}";')

            click.echo('}')
        else:
            click.echo("Vulnerability Dependency Graph:")
            click.echo("=" * 40)

            for node in graph_data['nodes']:
                click.echo(f"\n📍 {node['name']}")
                if node.get('cve_id'):
                    click.echo(f"   CVE: {node['cve_id']}")
                if node.get('vulnerable_software'):
                    click.echo(f"   Software: {node['vulnerable_software']}")
                if node.get('hosted_on_node'):
                    click.echo(f"   Host: {node['hosted_on_node']}")

            if graph_data['edges']:
                click.echo("\n🔗 Dependencies:")
                for vuln, deps in graph_data['edges'].items():
                    if deps:
                        click.echo(f"   {vuln} requires: {', '.join(deps)}")

    except Exception as e:
        click.echo(f"❌ Error: {str(e)}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('source', type=click.Path(exists=True))
def validate(source):
    """Validate a VSDL script."""
    compiler = VSDLCompiler()

    try:
        result = compiler.validate(source)

        if result.is_sat:
            click.echo("✅ Validation passed! Scenario is satisfiable.")
            if result.warnings:
                click.echo("\n⚠️  Warnings:")
                for warning in result.warnings:
                    click.echo(f"   - {warning}")
        else:
            click.echo("❌ Validation failed!")
            click.echo("\nErrors:")
            for error in result.errors:
                click.echo(f"   [{error.type}] {error.message}")
                if error.location:
                    click.echo(f"      Location: {error.location}")
            sys.exit(1)

    except Exception as e:
        click.echo(f"❌ Error: {str(e)}", err=True)
        sys.exit(1)


@cli.command()
def examples():
    """Show example VSDL syntax."""
    example = """
// Example VSDL script with vulnerability topology

scenario my_scenario duration 5 {

  // Network topology
  network PublicNetwork {
    addresses range is 203.0.113.0/24;
    node PrivateNetwork is connected;
    node PrivateNetwork has IP 203.0.113.254;
    gateway has direct access to the Internet;
  }

  network PrivateNetwork {
    addresses range is 172.16.1.0/24;
    node PublicNetwork is connected;
    node PublicNetwork has IP 172.16.1.254;
    node WebServer is connected;
    node WebServer has IP 172.16.1.100;
  }

  // Node definitions
  node WebServer {
    ram larger than 8GB;
    disk size equal to 100GB;
    vcpu equal to 4;
    node OS is "ubuntu20";
    mounts software nginx version 1.18;
    mounts software docker;
  }

  // Vulnerability topology (NEW)
  vulnerability WebVuln {
    vulnerable software nginx version 1.18;
    cve id is "CVE-2021-23017";
    depends on docker;
    hosted on node WebServer;
  }
}
"""
    click.echo(example)


if __name__ == '__main__':
    cli()