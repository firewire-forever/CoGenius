import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard-to-guess-string'
    INTERNAL_API_KEY = os.environ.get('INTERNAL_API_KEY') or 'crcg-internal-secret-key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PUBLIC_NET_NAME = os.environ.get('PUBLIC_NET_NAME') or 'public'
    # LLM API configuration
    LLM_API_URL = os.environ.get('LLM_API_URL') or ''
    LLM_API_KEY = os.environ.get('LLM_API_KEY') or ''
    LLM_MODEL = os.environ.get('LLM_MODEL') or ''
    # Ansible configuration
    ANSIBLE_PLAYBOOK_PATH = os.environ.get('ANSIBLE_PLAYBOOK_PATH') or 'ansible-playbook'
    ANSIBLE_GEN_KEY = os.environ.get('ANSIBLE_GEN_KEY') or ''
    ANSIBLE_GEN_URL = os.environ.get('ANSIBLE_GEN_URL') or ''

    # VSDLC configuration (Legacy JAR - kept for backup/rollback)
    VSDLC_PATH = os.environ.get('VSDLC_PATH') or 'tools/vsdlc.jar'  # Legacy: VSDLC JAR compiler path (no longer used)
    VSDL_SCRIPTS_DIR = os.environ.get('VSDL_SCRIPTS_DIR') or 'data/vsdl_scripts'  # Directory for storing VSDL scripts
    VSDLC_OUTPUT_DIR = os.environ.get('VSDLC_OUTPUT_DIR') or 'data/vsdlc_output'  # VSDLC output directory

    # Python VSDL Compiler configuration (New)
    USE_LEGACY_VSDLC = os.environ.get('USE_LEGACY_VSDLC', 'false').lower() == 'true'  # Set to 'true' to use legacy JAR

    # OpenStack configuration
    OPENSTACK_USER = os.environ.get('OPENSTACK_USER') or ''
    OPENSTACK_PASSWORD = os.environ.get('OPENSTACK_PASSWORD') or ''
    OPENSTACK_URL = os.environ.get('OPENSTACK_URL') or ''
    OPENSTACK_TENANT_NAME = os.environ.get('OPENSTACK_TENANT_NAME') or 'vsdl'
    OPENSTACK_DOMAIN = os.environ.get('OPENSTACK_DOMAIN') or 'Default'
    OPENSTACK_DEFAULT_FLAVOR = os.environ.get('OPENSTACK_DEFAULT_FLAVOR') or 'm1.large'
    PUBLIC_NET_NAME = os.environ.get('PUBLIC_NET_NAME') or 'public'
    PUBLIC_NET_ID = os.environ.get('PUBLIC_NET_ID') or ''  # UUID of external network
    SSH_PUBKEY_PATH = os.environ.get('SSH_PUBKEY_PATH') or '/root/.ssh/vsdl_key.pub'
    SSH_PRIVATE_KEY_PATH = os.environ.get('SSH_PRIVATE_KEY_PATH') or '/root/.ssh/vsdl_key'

    # Jumphost (Bastion) configuration for Ansible
    # Set JUMPHOST_HOST to enable SSH ProxyJump through a bastion server
    JUMPHOST_HOST = os.environ.get('JUMPHOST_HOST') or ''  # e.g., '192.168.1.100' or 'jump.example.com'
    JUMPHOST_USER = os.environ.get('JUMPHOST_USER') or 'root'  # SSH user for jumphost
    JUMPHOST_PORT = os.environ.get('JUMPHOST_PORT') or '22'  # SSH port for jumphost
    JUMPHOST_KEY_PATH = os.environ.get('JUMPHOST_KEY_PATH') or ''  # SSH key for jumphost (defaults to SSH_PRIVATE_KEY_PATH)
    JUMPHOST_PASSWORD = os.environ.get('JUMPHOST_PASSWORD') or ''  # SSH password for jumphost (if no key)
    # Solver configuration (Legacy - Python compiler uses Z3 Python API)
    SOLVER_PATH = os.environ.get('SOLVER_PATH') or 'tools/z3'
    SOLVER_ARGS = os.environ.get('SOLVER_ARGS') or '-smt2'

    # TTU configuration
    TTU_DEFAULT = int(os.environ.get('TTU_DEFAULT') or 10)
    TTU_STEP = int(os.environ.get('TTU_STEP') or 5)

    # File storage configuration
    CASE_CONTENT_DIR = os.environ.get('CASE_CONTENT_DIR') or 'data/case_content'  # Directory for storing case content

    # Scenario output directory - stores all generation results per task
    SCENARIO_OUTPUT_DIR = os.environ.get('SCENARIO_OUTPUT_DIR') or 'data/scenario_outputs'  # Directory for storing scenario generation results

    # Terraform configuration
    TERRAFORM_PATH = os.environ.get('TERRAFORM_PATH') or 'tools/terraform'  # Terraform path
    TERRAFORM_SCRIPT_PATH = os.environ.get('TERRAFORM_SCRIPT_PATH') or 'data/terraform_scripts'  # Directory for storing Terraform scripts
    TERRAFORM_OUTPUT_DIR = os.environ.get('TERRAFORM_OUTPUT_DIR') or 'data/terraform_output'  # Terraform output directory

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or \
        'sqlite:///crcg-dev.db'

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or \
        'sqlite:///crcg-test.db'

class ProductionConfig(Config):
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///crcg.db'

config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
