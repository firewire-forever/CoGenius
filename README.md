# CoGenius 

**Cyber Range Configuration Generator ** - Automated Virtual Cyber Range Generation from Security Documents

---

## Overview

CoGenius  is the core backend service of an automated cyber range generation system. It extracts attack scenario information from security documents (such as CVE vulnerability reports in PDF format), generates VSDL (Virtual Security Description Language) scripts via LLM, compiles them into Terraform and Ansible code, and finally deploys complete virtual cyber range environments on OpenStack.

### Core Workflow

```
PDF Vulnerability Report
         │
         ▼
   [PDF-RE Service] ───► Markdown Text
         │
         ▼
      [LLM API] ───► Structured Attack Scenario JSON
         │
         ▼
   [LLM Agent] ───► VSDL Script
         │
         ▼
[Python VSDL Compiler] ───► Terraform + Ansible Code
         │
         ▼
     [OpenStack] ───► Virtual Cyber Range Environment
```

---

## Key Components

### 1. PDF Extraction Module (`app/services/pdf_extractor.py`)
- Calls external **PDF-RE Service** to convert PDF to Markdown
- Uses LLM to extract structured attack scenario information
- Supports optional CVE database enrichment

### 2. VSDL Generation Module (`app/services/case_service.py`) ⭐ Core Script
- Uses LangChain + ReAct Agent to generate VSDL scripts
- Integrates OpenStack dynamic constraints (minimum disk requirements for images, etc.)
- Supports multi-round iteration to fix VSDL syntax errors

### 3. Python VSDL Compiler (`app/services/vsdl_compiler/`)
A custom VSDL compiler implemented entirely in Python. **No external JAR or Z3 Solver binary required.**

| Module | Function |
|--------|----------|
| `parser.py` | VSDL syntax parsing → AST |
| `validator.py` | SMT constraint validation |
| `generator/terraform.py` | Terraform code generation |
| `generator/ansible.py` | Ansible playbook generation |

### 4. Task Queue System
- **Celery + Redis** for asynchronous task processing
- Supports parallel processing of multiple cyber range generation tasks
- Automatically generates deployment reports and experiment results

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CoGenius                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   ┌────────────┐      ┌──────────┐      ┌────────────────┐           │
│   │ Flask API  │─────►│  Celery  │─────►│  case_service  │           │
│   │   :5000    │      │  Worker  │      │    (Core)      │           │
│   └────────────┘      └──────────┘      └───────┬────────┘           │
│                                                  │                    │
│         ┌────────────────────────────────────────┼────────────────┐  │
│         │                                        │                │  │
│         ▼                                        ▼                │  │
│   ┌───────────────┐                     ┌───────────────┐         │  │
│   │ PDF Extractor │                     │ VSDL Compiler │         │  │
│   │               │                     │   (Python)    │         │  │
│   └───────────────┘                     └───────┬───────┘         │  │
│         │                                       │                 │  │
└─────────┼───────────────────────────────────────┼─────────────────┼──┘
          │                                       │                 │
          ▼                                       ▼                 ▼
   ┌─────────────┐                        ┌─────────────┐    ┌────────────┐
   │ PDF-RE      │                        │  OpenStack  │    │ Callback   │
   │ Service     │                        │  Platform   │    │ Server     │
   │ (External)  │                        │             │    │  :9999     │
   └─────────────┘                        └─────────────┘    └────────────┘
          │                                       │
          ▼                                       ▼
   ┌─────────────┐                        ┌─────────────┐
   │    LLM      │                        │  Virtual    │
   │    API      │                        │  Cyber Range│
   └─────────────┘                        └─────────────┘
```

---

## Prerequisites

### Required External Services

| Service | Purpose | Configuration |
|---------|---------|---------------|
| **OpenStack** | Virtual cyber range deployment | `OPENSTACK_URL`, `OPENSTACK_USER`, `OPENSTACK_PASSWORD` |
| **Redis** | Celery task queue | `CELERY_BROKER_URL` |
| **PDF-RE Service** | PDF to Markdown conversion | `PDF_RE_SERVICE_URL` |
| **LLM API** | VSDL script generation | `LLM_API_URL`, `LLM_API_KEY` |

### SSH Key Configuration (Required)

```bash
# Generate SSH key pair for OpenStack VM access
ssh-keygen -t rsa -b 4096 -f ~/.ssh/vsdl_key -N ""

# Configure environment variables
SSH_PUBKEY_PATH=/home/ubuntu/.ssh/id_rsa.pub
SSH_PRIVATE_KEY_PATH=/home/ubuntu/.ssh/id_rsa
```

### Jumphost Configuration (Optional)

If OpenStack VMs are located in internal network and require jumphost access:

```bash
JUMPHOST_HOST=<jumphost-ip>
JUMPHOST_USER=<ssh-user>
JUMPHOST_PORT=22
JUMPHOST_PASSWORD=<ssh-password>
```

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/<your-username>/crcg_backend.git
cd crcg_backend
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.\.venv\Scripts\activate   # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create `.env` file from template:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# LLM API Configuration
LLM_API_URL=https://api.openai.com/v1
LLM_API_KEY=<your-api-key>
LLM_MODEL=gpt-4

# OpenStack Configuration (REQUIRED)
OPENSTACK_USER=<username>
OPENSTACK_PASSWORD=<password>
OPENSTACK_URL=<auth-url>
OPENSTACK_TENANT_NAME=vsdl
OPENSTACK_DOMAIN=Default

# SSH Key Paths (REQUIRED)
SSH_PUBKEY_PATH=/home/ubuntu/.ssh/id_rsa.pub
SSH_PRIVATE_KEY_PATH=/home/ubuntu/.ssh/id_rsa

# PDF-RE Service
PDF_RE_SERVICE_URL=http://localhost:8000
```

### 5. Initialize Database

```bash
flask db upgrade
```

---

## Running the Application

### Development Mode (Recommended)

The application requires **4 terminals** on the CRCG server:

#### Terminal 1: Main Service (Flask API)

```bash
cd ~/CRCG/CRCG/crcg_backend
source .venv/bin/activate
source .env
python run.py
# Service runs on port 5000
```

#### Terminal 2: Celery Worker (Critical)

```bash
cd ~/CRCG/CRCG/crcg_backend
source .venv/bin/activate
source .env
HF_HOME=/home/appuser HF_HUB_CACHE=/home/appuser/models \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
UNSTRUCTURED_LOCAL_INFERENCE=1 \
celery -A celery_worker:celery_app worker -l info -n worker2@%h
# Main progress logs appear in this terminal
```

#### Terminal 3: Callback Receiver

```bash
cd ~/crcg_callback
python callback_server.py
# Runs on port 9999
```

#### Terminal 4: Test Client

```bash
cd ~/crcg_callback
curl -X POST http://127.0.0.1:5000/api/v1/target-range/generate \
  -F "file=@CVE-2022.pdf" \
  -F "taskId=demo002" \
  -F "callbackUrl=http://127.0.0.1:9999/callback"
```

### Docker Deployment

```bash
# Create .env.docker file
cp .env .env.docker

# Start services
docker-compose up -d

# View logs
docker-compose logs -f worker
```

---

## API Reference

### Generate Cyber Range

```http
POST /api/v1/target-range/generate
Content-Type: multipart/form-data

Parameters:
- file: Scenario file (PDF)
- taskId: Unique task ID
- callbackUrl: Result callback URL

Response: 202 Accepted
{
  "message": "Target generation task accepted.",
  "taskId": "xxx"
}
```

### Health Check

```http
GET /api/v1/health

Response: 200 OK
{
  "status": "healthy"
}
```

### API Documentation

Access Swagger UI at: `http://localhost:5000/api/docs/`

---

## VSDL Language Example

```vsdl
scenario cve_2022_44228 duration 10 {
  // External network
  network external_net {
    addresses range is 203.0.113.0/24;
    gateway has direct access to the Internet;
  }

  // Internal network
  network internal_net {
    addresses range is 192.168.1.0/24;
  }

  // Attacker node
  node attacker {
    ram equal to 4GB;
    disk size equal to 50GB;
    vcpu equal to 2;
    node OS is "kali";
  }

  // Victim node
  node victim {
    ram equal to 8GB;
    disk size equal to 80GB;
    vcpu equal to 4;
    node OS is "ubuntu20";
    mounts software "log4j" version "2.14.1";
  }

  // Network connections
  network external_net {
    node attacker is connected;
    node attacker has IP 203.0.113.100;
  }

  network internal_net {
    node victim is connected;
    node victim has IP 192.168.1.10;
  }

  // Vulnerability definition
  vulnerability log4j_rce {
    cve id is "CVE-2022-44228";
    hosted on node victim;
    vulnerable software "log4j" version "2.14.1";
  }
}
```

---

## Project Structure

```
crcg_backend/
├── app/
│   ├── __init__.py              # Flask application factory
│   ├── config.py                # Configuration management
│   ├── tasks.py                 # Celery task definitions
│   ├── routes/
│   │   ├── main.py              # Main routes
│   │   └── target_range.py      # Cyber range generation API
│   ├── services/
│   │   ├── case_service.py      # ⭐ Core service script
│   │   ├── pdf_extractor.py     # PDF extraction module
│   │   ├── openstack_service.py # OpenStack connection service
│   │   └── vsdl_compiler/       # Python VSDL Compiler
│   │       ├── parser.py        # Syntax parser
│   │       ├── validator.py     # SMT validator
│   │       ├── compiler.py      # Main compiler
│   │       └── generator/
│   │           ├── terraform.py # Terraform generator
│   │           └── ansible.py   # Ansible generator
│   └── utils/
│       ├── logger.py
│       ├── callbacks.py
│       └── response.py
├── tools/
│   ├── terraform                # Terraform binary
│   └── ansible-playbook         # Ansible binary
├── data/                        # Runtime data directory
│   ├── vsdl_scripts/
│   ├── terraform_scripts/
│   ├── ansible_scripts/
│   └── scenario_outputs/
├── celery_worker.py             # Celery worker entry point
├── run.py                       # Flask entry point
├── requirements.txt             # Python dependencies
├── docker-compose.yml           # Docker compose configuration
├── Dockerfile                   # Docker image definition
├── .env.example                 # Environment template
└── README.md                    # This file
```

---

## FAQ

### Q1: Celery Worker cannot connect to Redis

Check if Redis service is running:
```bash
redis-cli ping  # Should return PONG
```

### Q2: OpenStack connection fails

Verify configuration:
```bash
openstack --os-auth-url $OPENSTACK_URL \
           --os-username $OPENSTACK_USER \
           --os-password $OPENSTACK_PASSWORD \
           --os-project-name $OPENSTACK_TENANT_NAME \
           server list
```

### Q3: PDF parsing timeout

PDF-RE service requires GPU for OCR mode. Ensure service is running:
```bash
curl http://localhost:8000/health
```

### Q4: SSH connection fails

Verify SSH key configuration:
```bash
ssh -i $SSH_PRIVATE_KEY_PATH user@vm-ip
```

---

## Technology Stack

| Category | Technology |
|----------|------------|
| Web Framework | Flask 2.2.5 |
| Task Queue | Celery 5.4.0 + Redis |
| LLM | LangChain + OpenAI-compatible API |
| Infrastructure | Terraform + OpenStack |
| Configuration Management | Ansible |
| Database | SQLite (dev) / MySQL (production) |
| API Documentation | Flasgger (Swagger) |
| VSDL Compiler | Custom Python implementation |

---

## Important Notes

1. **VSDL Compiler**: This project uses a custom Python-based VSDL compiler (`app/services/vsdl_compiler/`). External tools like `vsdlc.jar` or `z3` binary are **NOT** required.

2. **LLM API**: The project uses OpenAI-compatible API endpoints. You can use OpenAI, DeepSeek, or any compatible service.

3. **PDF-RE Service**: This is an external service for PDF parsing. You need to set up this service separately or configure an existing one.

4. **OpenStack**: A working OpenStack environment is **required** for actual deployment. For testing without OpenStack, the system can still generate Terraform/Ansible artifacts.

5. **Offline Mode**: The project supports offline mode for HuggingFace models via environment variables, but uses online LLM APIs.

---

## License

MIT License

---

## Contributing

Issues and Pull Requests are welcome!

---

## Contact

For questions, please use GitHub Issues.