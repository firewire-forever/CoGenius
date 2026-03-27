
---

# Cyber Range CoGenius:LLM-Powered Multi-Agent Orchestration for fine-grainedend-to-endvirtual Scenario Generation

## 📌 Overview
Cyber ranges are essential infrastructure for cybersecurity training and research, designed to simulate complex and realistic network environments. However, creating, validating, and deploying cyber range scenarios is often time-consuming, error-prone, and costly.

This project provides an end-to-end execution platform for automating the generation of cyber ranges, powered by multi-agent collaboration. The system includes:

- A coordinated multi-agent architecture for generating scenario logic and automation scripts.

- Supporting infrastructure such as:

    -  vsdlc: a domain-specific compiler for scenario description.

    - OpenStack: for dynamic deployment and resource orchestration.

Our goal is to reduce the barrier to cyber range usage by automating scenario generation, infrastructure orchestration, and service deployment—making cybersecurity simulation more efficient, accessible, and intelligent.

## 🚀 Getting Started with Docker Compose

### 1. Prerequisites

Before getting started, please install the following:

* [Docker](https://docs.docker.com/get-docker/)
* [Docker Compose](https://docs.docker.com/compose/install/)
* [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)

---

### 2. Clone the Repository

```bash
git clone <repository-url>
cd crcg_backend
```

---

### 3. Prepare Required Directories

Create necessary directories for NLTK data and model files:

```bash
mkdir -p nltk_data
mkdir -p models
```

#### 3.1 Download Required Models (Optional but Recommended)

For offline operation, download the YOLO model files:

```bash
# Install huggingface_hub
pip install huggingface_hub

# Download model files
python -c "from huggingface_hub import hf_hub_download; hf_hub_download('unstructuredio/yolo_x_layout', 'yolox_l0.05.onnx', cache_dir='./models')"
```

This will create the required directory structure in the `models` folder.

---

### 4. Configure Environment Variables

This project uses two environment variable files:

1. **`.env`** - For business logic and application settings:
   ```bash
   cp .env.example .env
   ```
   Edit this file to configure business settings like API keys, service URLs, and application parameters.

2. **`.env.docker`** - For container-specific settings:
   ```bash
   cp .env.example .env.docker
   ```
   Edit this file to configure container-specific settings like ports, volumes, and Docker networking options.

Both files need to be properly configured for the system to work correctly.

---

## ⚡ Quick Start

### Run the Service

1. Build and start the services:

   ```bash
   docker-compose up -d
   ```

2. Check the logs to ensure everything is running correctly:

   ```bash
   docker-compose logs -f
   ```

3. To stop the services:

   ```bash
   docker-compose down
   ```

---

## 🛠️ API Reference

### Target Range Generation API

#### Generate a Target Range Scenario

* **Endpoint**: `POST http://127.0.0.1:5000/api/v1/target-range/generate`

* **Content-Type**: `application/json`

* **Request Body Parameters**:

  | Parameter | Type | Required | Description |
  |-----------|------|----------|-------------|
  | `case_id` | integer | Yes | Unique identifier for the case |
  | `file` | base64 | No | Base64 encoded file content (PDF format recommended) |
  | `callback_url` | string | No | URL to receive processing result notifications |

* **Example Requests**:

  1. Generate using a case ID:
     ```bash
     curl -X POST -H "Content-Type: application/json" \
     -d '{"case_id": 1}' \
     http://127.0.0.1:5000/api/v1/target-range/generate
     ```

  2. Generate by uploading a file:
     ```bash
     curl -X POST -H "Content-Type: multipart/form-data" \
     -F "file=@/path/to/scenario.pdf" \
     -F "callback_url=http://yourserver.com/webhook" \
     http://127.0.0.1:5000/api/v1/target-range/generate
     ```

* **Response Format**:

  Success (200 OK):
  ```json
  {
    "status": "success",
    "task_id": "task-123456",
    "message": "Scenario generation started"
  }
  ```

  Error (400 Bad Request):
  ```json
  {
    "status": "error",
    "message": "Invalid request parameters"
  }
  ```

* **Callback Notification Format**:
  
  When processing completes, a POST request will be sent to the callback_url (if provided):
  ```json
  {
    "task_id": "task-123456",
    "status": "completed",
    "result": {
      "vsdl_script": "// Generated VSDL Script content...",
      "generation_time": 45.2
    }
  }
  ```

* **Notes**:
  - Processing is asynchronous and may take several minutes
  - If no callback_url is provided, check the status using the task_id

---

## 📦 Docker Containers

The system consists of three main containers:

1. **Redis**: Message broker for Celery tasks
2. **Web**: Flask web application serving the API endpoints
3. **Worker**: Celery worker for processing background tasks

You can check their status using:

```bash
docker-compose ps
```

---

## 🧪 Development Setup

For development purposes, you might want to run the service locally:

### Option 1: Using start_dev.sh Script (Recommended)

The easiest way to start the application in development mode is by using the provided script:

```bash
# Make the script executable
chmod +x start_dev.sh

# Run the development script
./start_dev.sh
```

This script will automatically:
- Set up the required environment
- Start Redis if needed
- Launch the Flask development server
- Start the Celery worker
- Configure all necessary settings

### Option 2: Manual Setup with Conda

```bash
# Create Conda environment
conda create -n crcg python=3.11
conda activate crcg

# Install dependencies
pip install -r requirements.txt

# Install additional dependencies
sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-eng poppler-utils

# Start Redis (required)
docker-compose up -d redis

# Run development server
python run.py
```

In a separate terminal:
```bash
# Run Celery worker
celery -A celery_worker.celery_app worker --loglevel=info
```