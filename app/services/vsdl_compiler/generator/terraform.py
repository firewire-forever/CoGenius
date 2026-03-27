"""
VSDL Python Compiler - Terraform Code Generator
Generates Terraform configuration from VSDL AST.
"""

from typing import Dict, List, Optional, Set
from jinja2 import Template
from ..ast_nodes import Scenario, NetworkDefinition, NodeDefinition, VulnerabilityDefinition


# ============================================================================
# Windows Image Mapping
# Maps Windows OS names to the SSH-enabled Windows image (win10-ssh)
# This image has OpenSSH Server pre-installed with Admin/Admin123 credentials
# ============================================================================
WINDOWS_IMAGE_MAPPING = {
    'windows': 'win10-ssh',
    'win': 'win10-ssh',
    'win10': 'win10-ssh',
    'win2003': 'win10-ssh',
    'win2008': 'win10-ssh',
    'win2012': 'win10-ssh',
    'win2016': 'win10-ssh',
    'win2019': 'win10-ssh',
    'windows10': 'win10-ssh',
    'windows_server': 'win10-ssh',
}

# SSH-enabled Windows image name
WINDOWS_SSH_IMAGE = 'win10-ssh'


def map_os_image(os_image: Optional[str]) -> Optional[str]:
    """
    Map OS image name, replacing Windows images with SSH-enabled version.

    Args:
        os_image: Original OS image name from VSDL

    Returns:
        Mapped image name (win10-ssh for Windows, original for others)
    """
    if not os_image:
        return os_image

    os_lower = os_image.lower().strip()

    # Check if it's a Windows image
    if os_lower in WINDOWS_IMAGE_MAPPING:
        return WINDOWS_SSH_IMAGE

    # Also check for partial matches (e.g., "Windows 10", "Windows Server 2019")
    if 'win' in os_lower:
        return WINDOWS_SSH_IMAGE

    return os_image


def generate_unique_cidr(existing_cidrs: Set[str], index: int) -> str:
    """
    Generate a unique CIDR that doesn't conflict with existing ones.
    Uses private IP ranges: 10.0.x.0/24 for different networks.

    Args:
        existing_cidrs: Set of already used CIDRs
        index: Network index for base calculation

    Returns:
        A unique CIDR string
    """
    # Use 10.0.index.0/24 pattern for private networks
    # This gives us up to 256 unique /24 networks
    base = 10
    second_octet = (index // 256) % 256
    third_octet = index % 256

    cidr = f"{base}.{second_octet}.{third_octet}.0/24"

    # If somehow conflicts, increment until unique
    while cidr in existing_cidrs:
        third_octet = (third_octet + 1) % 256
        if third_octet == 0:
            second_octet = (second_octet + 1) % 256
        cidr = f"{base}.{second_octet}.{third_octet}.0/24"

    return cidr


def validate_and_fix_cidr(cidr: str, existing_cidrs: Set[str], index: int) -> str:
    """
    Validate CIDR and return a unique one if there's a conflict.

    Args:
        cidr: Original CIDR from VSDL
        existing_cidrs: Set of already used CIDRs
        index: Network index for generating new CIDR

    Returns:
        A unique CIDR string
    """
    if cidr and cidr not in existing_cidrs:
        return cidr

    # CIDR is None or conflicts - generate a new one
    return generate_unique_cidr(existing_cidrs, index)


# Terraform templates
MAIN_TF_TEMPLATE = """
terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 1.51.0"
    }
  }
}

provider "openstack" {
  # Authentication via environment variables:
  # OS_AUTH_URL, OS_USERNAME, OS_PASSWORD, OS_PROJECT_NAME (or OS_TENANT_NAME)
  # OS_USER_DOMAIN_NAME, OS_PROJECT_DOMAIN_NAME
  #
  # If environment variables are not set, use explicit configuration:
  auth_url = "{{ auth_url }}"
  user_name = "{{ username }}"
  password = "{{ password }}"
  tenant_name = "{{ tenant_name }}"
  user_domain_name = "{{ domain_name }}"
  project_domain_name = "{{ domain_name }}"
}

# Shared external router for all networks (enables floating IP for all instances)
resource "openstack_networking_router_v2" "external_router" {
  name                = "{{ scenario_name }}_external_router"
  external_network_id = var.public_network_id
}

{% for network in networks %}
# Network: {{ network.name }}
resource "openstack_networking_network_v2" "{{ network.name | lower }}" {
  name           = "{{ network.name }}"
  admin_state_up = true
}

resource "openstack_networking_subnet_v2" "{{ network.name | lower }}_subnet" {
  name       = "{{ network.name }}_subnet"
  network_id = openstack_networking_network_v2.{{ network.name | lower }}.id
  cidr       = "{{ network.address_range }}"
  ip_version = 4
  gateway_ip = cidrhost("{{ network.address_range }}", 1)

  # DNS nameservers for external hostname resolution
  # Using Google DNS (8.8.8.8, 8.8.4.4) for reliable external resolution
  dns_nameservers = ["8.8.8.8", "8.8.4.4"]
}

# Connect all networks to the external router (enables floating IP access)
resource "openstack_networking_router_interface_v2" "{{ network.name | lower }}_router_interface" {
  router_id = openstack_networking_router_v2.external_router.id
  subnet_id = openstack_networking_subnet_v2.{{ network.name | lower }}_subnet.id
}

{% endfor %}

# Allocate floating IPs for each node
{% for node in nodes %}
resource "openstack_networking_floatingip_v2" "{{ node.name | lower }}_floating_ip" {
  pool = "public"
}
{% endfor %}

# Create a security group that allows SSH access
resource "openstack_compute_secgroup_v2" "allow_ssh" {
  name        = "{{ scenario_name }}_allow_ssh"
  description = "Allow SSH access"

  rule {
    from_port   = 22
    to_port     = 22
    ip_protocol = "tcp"
    cidr        = "0.0.0.0/0"
  }

  rule {
    from_port   = -1
    to_port     = -1
    ip_protocol = "icmp"
    cidr        = "0.0.0.0/0"
  }
}

# SSH Keypair Management:
# The keypair is created by Python SDK before Terraform runs (for parallel execution support).
# Here we just reference the existing keypair using a data source.
# This avoids "keypair already exists" errors when running multiple tasks in parallel.

data "openstack_compute_keypair_v2" "vsdl_key" {
  name = var.ssh_key_name
}

{% for node in nodes %}
# Node: {{ node.name }}
resource "openstack_compute_instance_v2" "{{ node.name | lower }}" {
  name            = "{{ node.name }}"
  image_name      = "{{ node.os_image }}"
  flavor_name     = local.{{ node.name | lower }}_flavor
  security_groups = ["default", openstack_compute_secgroup_v2.allow_ssh.name]
  key_pair        = data.openstack_compute_keypair_v2.vsdl_key.name

  {% for network in node_networks[node.name] %}
  network {
    uuid = openstack_networking_network_v2.{{ network.network_name | lower }}.id
    fixed_ip_v4 = "{{ network.ip_address }}"
  }
  {% endfor %}

  {% if node.user_data %}
  user_data       = file("${path.module}/user_data/{{ node.name }}.sh")
  {% endif %}

  tags = [
    "vsdl_generated",
    {% for vuln in node_vulnerabilities.get(node.name, []) %}
    "vulnerability_{{ vuln }}",
    {% endfor %}
  ]

  # Serial creation: wait for previous instance to be ready before creating this one
  # This avoids network allocation race conditions in OpenStack/Neutron
  {% if node.previous_node %}
  depends_on = [openstack_compute_instance_v2.{{ node.previous_node | lower }}]
  {% endif %}
}

# Associate floating IP with the instance
resource "openstack_compute_floatingip_associate_v2" "{{ node.name | lower }}_floating_ip_assoc" {
  floating_ip = openstack_networking_floatingip_v2.{{ node.name | lower }}_floating_ip.address
  instance_id = openstack_compute_instance_v2.{{ node.name | lower }}.id
}
{% endfor %}
"""

VARIABLES_TF_TEMPLATE = """
variable "public_network_id" {
  description = "ID of the public/external network"
  type        = string
}

variable "ssh_key_name" {
  description = "Name of the SSH keypair in OpenStack"
  type        = string
  default     = "vsdl_key"
}

variable "ssh_public_key" {
  description = "SSH public key content (will be injected into VMs)"
  type        = string
}

variable "default_flavor_name" {
  description = "Default flavor name for all instances"
  type        = string
  default     = "m1.large"
}
"""

OUTPUTS_TF_TEMPLATE = """
{% for node in nodes %}
output "{{ node.name }}_ip" {
  description = "Floating IP address of {{ node.name }}"
  value       = openstack_networking_floatingip_v2.{{ node.name | lower }}_floating_ip.address
}

output "{{ node.name }}_network_ip" {
  description = "Fixed IP of {{ node.name }} on primary network"
  value       = openstack_compute_instance_v2.{{ node.name | lower }}.network.0.fixed_ip_v4
}
{% endfor %}

output "vulnerability_summary" {
  description = "Vulnerability topology summary"
  value = {
    {% for vuln in vulnerabilities %}
    {{ vuln.name }} = {
      cve_id = "{{ vuln.cve_id or 'N/A' }}"
      software = "{{ vuln.vulnerable_software or 'N/A' }}"
      hosted_on = "{{ vuln.hosted_on_node or 'N/A' }}"
      dependencies = [{% for dep in vuln.requires_vulnerabilities %}"{{ dep }}",{% endfor %}]
    }
    {% endfor %}
  }
}
"""

FLAVORS_TF_TEMPLATE = """
# Compute flavors (hardware configurations)
# Select appropriate flavor based on disk requirements
# NOTE: Actual disk sizes may vary by OpenStack deployment!
# Common configurations:
#   m1.small:  1 vCPU, 2GB RAM, 20GB disk
#   m1.medium: 2 vCPU, 4GB RAM, 40GB disk
#   m1.large:  4 vCPU, 8GB RAM, 40-80GB disk (varies by deployment)
#   m1.xlarge: 8 vCPU, 16GB RAM, 160GB disk
#
# IMPORTANT: Windows images (win10-ssh) require 60GB+ disk.
# Kali images also require large disk.
# Using m1.xlarge (160GB) for all Windows/Kali to ensure compatibility.

locals {
  {% for node in nodes %}
  # {{ node.name }}: disk={{ node.disk_value or 'default' }}GB, os={{ node.os_image }}
  {{ node.name | lower }}_flavor = {% if node.disk_value and node.disk_value >= 160 %}"m1.xlarge"{% elif node.disk_value and node.disk_value >= 50 %}"m1.xlarge"{% elif node.disk_value and node.disk_value >= 40 %}"m1.large"{% elif node.os_image and (node.os_image.lower() in ['kali', 'windows', 'win10-ssh'] or 'win' in node.os_image.lower()) %}"m1.xlarge"{% else %}"m1.xlarge"{% endif %}
  {% endfor %}
}
"""


class TerraformGenerator:
    """
    Generates Terraform configuration from VSDL AST.
    """

    def __init__(self):
        self.main_template = Template(MAIN_TF_TEMPLATE)
        self.variables_template = Template(VARIABLES_TF_TEMPLATE)
        self.outputs_template = Template(OUTPUTS_TF_TEMPLATE)
        self.flavors_template = Template(FLAVORS_TF_TEMPLATE)

    def generate(self, scenario: Scenario, openstack_config: Optional[Dict] = None) -> Dict[str, str]:
        """
        Generate Terraform files from a VSDL scenario.

        Args:
            scenario: The VSDL scenario AST
            openstack_config: Optional OpenStack configuration

        Returns:
            Dict mapping filename to content
        """
        # Generate unique prefix for this scenario (to avoid name conflicts)
        import time
        unique_prefix = f"{scenario.name}_{int(time.time())}"

        # Build node-to-network mapping
        node_networks = self._build_node_networks(scenario)

        # Build node-to-vulnerabilities mapping
        node_vulnerabilities = scenario.get_node_vulnerabilities()

        # Generate main.tf with unique prefix and auth config
        main_tf = self._generate_main_tf(scenario, node_networks, node_vulnerabilities, unique_prefix, openstack_config)

        # Generate variables.tf
        variables_tf = self._generate_variables_tf()

        # Generate outputs.tf with unique prefix
        outputs_tf = self._generate_outputs_tf(scenario, unique_prefix)

        # Generate flavors.tf with unique prefix
        flavors_tf = self._generate_flavors_tf(scenario, unique_prefix)

        # Generate terraform.tfvars
        tfvars = self._generate_tfvars(openstack_config)

        # Generate user data scripts
        user_data_scripts = self._generate_user_data_scripts(scenario, node_vulnerabilities)

        files = {
            'main.tf': main_tf,
            'variables.tf': variables_tf,
            'outputs.tf': outputs_tf,
            'flavors.tf': flavors_tf,
            'terraform.tfvars': tfvars,
        }

        # Add user data scripts
        for node_name, script in user_data_scripts.items():
            files[f'user_data/{node_name}.sh'] = script

        return files

    def _build_node_networks(self, scenario: Scenario) -> Dict[str, List[Dict]]:
        """Build mapping of nodes to their connected networks"""
        node_networks = {}

        for network in scenario.networks:
            for conn in network.connections:
                if conn.node_name not in [n.name for n in scenario.nodes]:
                    continue  # Skip network-to-network connections

                if conn.node_name not in node_networks:
                    node_networks[conn.node_name] = []

                node_networks[conn.node_name].append({
                    'network_name': network.name,
                    'ip_address': conn.ip_address,
                    'has_internet': network.has_internet_gateway
                })

        return node_networks

    def _generate_main_tf(self, scenario: Scenario,
                          node_networks: Dict[str, List[Dict]],
                          node_vulnerabilities: Dict[str, List[str]],
                          unique_prefix: str = "",
                          openstack_config: Optional[Dict] = None) -> str:
        """Generate main.tf content with unique resource names and unique CIDRs"""
        # Prepare auth configuration with defaults
        auth_config = {
            'auth_url': openstack_config.get('auth_url', '') if openstack_config else '',
            'username': openstack_config.get('username', '') if openstack_config else '',
            'password': openstack_config.get('password', '') if openstack_config else '',
            'tenant_name': openstack_config.get('tenant_name', 'vsdl') if openstack_config else 'vsdl',
            'domain_name': openstack_config.get('domain_name', 'Default') if openstack_config else 'Default',
        }

        # Track used CIDRs to avoid conflicts
        used_cidrs: Set[str] = set()

        # Build network name to unique CIDR mapping
        network_cidr_map: Dict[str, str] = {}
        network_ip_base_map: Dict[str, str] = {}  # Base IP for node assignments

        # Assign unique CIDRs to each network
        for idx, net in enumerate(scenario.networks):
            original_cidr = net.address_range
            unique_cidr = validate_and_fix_cidr(original_cidr, used_cidrs, idx)
            used_cidrs.add(unique_cidr)
            network_cidr_map[net.name] = unique_cidr

            # Extract base IP for node IP assignments (e.g., "10.0.1.0/24" -> "10.0.1")
            base_ip = unique_cidr.rsplit('.', 1)[0]
            network_ip_base_map[net.name] = base_ip

        # Create a modified scenario with prefixed names and unique CIDRs
        prefixed_networks = []
        for net in scenario.networks:
            prefixed_name = f"{unique_prefix}_{net.name}" if unique_prefix else net.name
            unique_cidr = network_cidr_map[net.name]
            prefixed_networks.append(type('NetworkDefinition', (), {
                'name': prefixed_name,
                'address_range': unique_cidr,
                'connections': net.connections,
                'has_internet_gateway': net.has_internet_gateway
            })())

        prefixed_nodes = []
        previous_prefixed_name = None
        for node in scenario.nodes:
            prefixed_name = f"{unique_prefix}_{node.name}" if unique_prefix else node.name
            # Map Windows images to SSH-enabled version
            mapped_os_image = map_os_image(node.os_image)
            prefixed_nodes.append(type('NodeDefinition', (), {
                'name': prefixed_name,
                'os_image': mapped_os_image,
                'ram_value': node.ram_value,
                'ram_operator': node.ram_operator,
                'disk_value': node.disk_value,
                'disk_operator': node.disk_operator,
                'vcpu': node.vcpu,
                'software_mounts': node.software_mounts,
                'ssh_key_name': getattr(node, 'ssh_key_name', None),
                'user_data': getattr(node, 'user_data', None),
                'previous_node': previous_prefixed_name  # For serial creation
            })())
            previous_prefixed_name = prefixed_name

        # Update node_networks with prefixed names and corrected IPs
        # Track IP assignments per network to avoid duplicates
        network_ip_counters: Dict[str, int] = {}
        prefixed_node_networks = {}
        for node_name, networks in node_networks.items():
            prefixed_node_name = f"{unique_prefix}_{node_name}" if unique_prefix else node_name
            prefixed_node_networks[prefixed_node_name] = []
            for net_info in networks:
                prefixed_net_name = f"{unique_prefix}_{net_info['network_name']}" if unique_prefix else net_info['network_name']
                original_net_name = net_info['network_name']

                # Get the base IP for this network
                base_ip = network_ip_base_map.get(original_net_name, "10.0.1")

                # Generate a unique IP (start from .100 to avoid gateway conflicts)
                if original_net_name not in network_ip_counters:
                    network_ip_counters[original_net_name] = 100  # Start from .100

                # Use original IP if specified and valid, otherwise generate
                original_ip = net_info['ip_address']
                if original_ip:
                    # Check if the IP matches the new CIDR
                    ip_parts = original_ip.split('.')
                    if len(ip_parts) == 4:
                        new_ip = original_ip  # Keep original if valid format
                    else:
                        new_ip = f"{base_ip}.{network_ip_counters[original_net_name]}"
                        network_ip_counters[original_net_name] += 1
                else:
                    new_ip = f"{base_ip}.{network_ip_counters[original_net_name]}"
                    network_ip_counters[original_net_name] += 1

                prefixed_node_networks[prefixed_node_name].append({
                    'network_name': prefixed_net_name,
                    'ip_address': new_ip,
                    'has_internet': net_info['has_internet']
                })

        # Update node_vulnerabilities with prefixed names
        prefixed_node_vulnerabilities = {}
        for node_name, vulns in node_vulnerabilities.items():
            prefixed_node_name = f"{unique_prefix}_{node_name}" if unique_prefix else node_name
            prefixed_node_vulnerabilities[prefixed_node_name] = vulns

        return self.main_template.render(
            networks=prefixed_networks,
            nodes=prefixed_nodes,
            node_networks=prefixed_node_networks,
            node_vulnerabilities=prefixed_node_vulnerabilities,
            auth_url=auth_config['auth_url'],
            username=auth_config['username'],
            password=auth_config['password'],
            tenant_name=auth_config['tenant_name'],
            domain_name=auth_config['domain_name'],
            scenario_name=unique_prefix if unique_prefix else "vsdl_scenario"
        )

    def _generate_variables_tf(self) -> str:
        """Generate variables.tf content"""
        return self.variables_template.render()

    def _generate_outputs_tf(self, scenario: Scenario, unique_prefix: str = "") -> str:
        """Generate outputs.tf content with unique resource names"""
        prefixed_nodes = []
        for node in scenario.nodes:
            prefixed_name = f"{unique_prefix}_{node.name}" if unique_prefix else node.name
            prefixed_nodes.append(type('NodeDefinition', (), {
                'name': prefixed_name
            })())

        return self.outputs_template.render(
            nodes=prefixed_nodes,
            vulnerabilities=scenario.vulnerabilities
        )

    def _generate_flavors_tf(self, scenario: Scenario, unique_prefix: str = "") -> str:
        """Generate flavors.tf content with unique resource names"""
        prefixed_nodes = []
        for node in scenario.nodes:
            prefixed_name = f"{unique_prefix}_{node.name}" if unique_prefix else node.name
            prefixed_nodes.append(type('NodeDefinition', (), {
                'name': prefixed_name,
                'vcpu': node.vcpu,
                'ram_value': node.ram_value,
                'disk_value': node.disk_value
            })())

        return self.flavors_template.render(nodes=prefixed_nodes)

    def _generate_tfvars(self, openstack_config: Optional[Dict]) -> str:
        """Generate terraform.tfvars content"""
        if not openstack_config:
            return '# Configure these variables\npublic_network_id = "YOUR_PUBLIC_NETWORK_ID"\nssh_key_name = "vsdl_key"\nssh_public_key = ""\ndefault_flavor_name = "m1.small"\n'

        lines = []
        if 'public_network_id' in openstack_config:
            lines.append(f'public_network_id = "{openstack_config["public_network_id"]}"')

        # SSH key configuration
        ssh_key_name = openstack_config.get('ssh_key_name', 'vsdl_key')
        lines.append(f'ssh_key_name = "{ssh_key_name}"')

        # SSH public key (must be provided for VM access)
        ssh_public_key = openstack_config.get('ssh_public_key', '')
        if ssh_public_key:
            # Escape any quotes in the SSH key
            ssh_public_key_escaped = ssh_public_key.replace('"', '\\"')
            lines.append(f'ssh_public_key = "{ssh_public_key_escaped}"')
        else:
            lines.append('ssh_public_key = ""')

        # Add flavor name from config or use default
        flavor_name = openstack_config.get('default_flavor_name', 'm1.small')
        lines.append(f'default_flavor_name = "{flavor_name}"')

        return '\n'.join(lines) + '\n'

    def _generate_user_data_scripts(self, scenario: Scenario,
                                     node_vulnerabilities: Dict[str, List[str]]) -> Dict[str, str]:
        """Generate cloud-init user data scripts for each node"""
        scripts = {}

        for node in scenario.nodes:
            script = self._generate_node_user_data(node, node_vulnerabilities.get(node.name, []), scenario)
            scripts[node.name] = script

        return scripts

    def _generate_node_user_data(self, node: NodeDefinition,
                                   vulnerabilities: List[str],
                                   scenario: Scenario) -> str:
        """Generate cloud-init user data for a single node"""
        lines = [
            '#!/bin/bash',
            f'# User data for node: {node.name}',
            f'# Generated by VSDL Python Compiler',
            '',
            '# ==========================================================================',
            '# CRITICAL: Configure DNS FIRST before any apt operations',
            '# Without proper DNS, apt update will fail with "Temporary failure resolving"',
            '# ==========================================================================',
            'echo "Configuring DNS nameservers..."',
            'echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf',
            'echo "nameserver 8.8.4.4" | sudo tee -a /etc/resolv.conf',
            '',
            '# Wait for network to be fully ready',
            'sleep 5',
            '',
            '# Verify DNS is working',
            'echo "Testing DNS resolution..."',
            'ping -c 1 8.8.8.8 || echo "Warning: No internet connectivity"',
            'nslookup archive.ubuntu.com || echo "Warning: DNS resolution issue"',
            '',
            '# Update system packages',
            'apt-get update && apt-get upgrade -y',
            '',
        ]

        # Add software installation
        for sw in node.software_mounts:
            lines.append(f'# Install {sw.name}')
            lines.extend(self._generate_software_installation(sw))

        # Add vulnerability markers
        if vulnerabilities:
            lines.append('')
            lines.append('# Vulnerability markers (for attack simulation)')
            lines.append('mkdir -p /opt/vsdl/vulnerabilities')
            for vuln_name in vulnerabilities:
                vuln = next((v for v in scenario.vulnerabilities if v.name == vuln_name), None)
                if vuln:
                    lines.append(f'echo "Vulnerability: {vuln_name}" > /opt/vsdl/vulnerabilities/{vuln_name}')
                    if vuln.cve_id:
                        lines.append(f'echo "CVE: {vuln.cve_id}" >> /opt/vsdl/vulnerabilities/{vuln_name}')

        return '\n'.join(lines)

    def _generate_software_installation(self, software) -> List[str]:
        """Generate commands to install a software package"""
        lines = []

        # Common software installation patterns
        install_commands = {
            'docker': [
                'curl -fsSL https://get.docker.com -o get-docker.sh',
                'sh get-docker.sh',
                'usermod -aG docker ubuntu || true',
            ],
            'nginx': ['apt-get install -y nginx'],
            'apache': ['apt-get install -y apache2'],
            'mysql': ['apt-get install -y mysql-server'],
            'postgresql': ['apt-get install -y postgresql postgresql-contrib'],
            'redis': ['apt-get install -y redis-server'],
            'mongodb': [
                'wget -qO - https://www.mongodb.org/static/pgp/server-6.0.asc | apt-key add -',
                'echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/6.0 multiverse" | tee /etc/apt/sources.list.d/mongodb-org-6.0.list',
                'apt-get update',
                'apt-get install -y mongodb-org',
            ],
            # Java/JDK installation
            'java': ['apt-get install -y openjdk-11-jdk'],
            'jdk': ['apt-get install -y openjdk-11-jdk'],
            'openjdk': ['apt-get install -y openjdk-11-jdk'],
            'openjdk-8': ['apt-get install -y openjdk-8-jdk'],
            'openjdk-11': ['apt-get install -y openjdk-11-jdk'],
            'openjdk-17': ['apt-get install -y openjdk-17-jdk'],
            # Tomcat installation
            'tomcat': ['apt-get install -y tomcat9'],
            'apache-tomcat': ['apt-get install -y tomcat9'],
            # Bonitasoft - requires Java and Tomcat
            'bonitasoft': [
                '# Installing Bonitasoft dependencies',
                'apt-get install -y openjdk-11-jdk tomcat9',
                '# Download Bonitasoft (if version specified)',
                'mkdir -p /opt/bonitasoft',
                '# Note: Bonitasoft WAR deployment requires manual configuration',
                'echo "Bonitasoft installed - requires manual WAR deployment"',
            ],
        }

        sw_name = software.name.lower()

        if sw_name in install_commands:
            lines.extend(install_commands[sw_name])
        else:
            # Generic installation attempt
            lines.append(f'apt-get install -y {software.name} || echo "Package {software.name} not found, manual installation required"')

        # Add configuration if specified
        if software.config:
            lines.append(f'# Configuration for {software.name}')
            for key, value in software.config.items():
                lines.append(f'echo "{key}={value}" >> /etc/{software.name}/vsdl_config')

        return lines