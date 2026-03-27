# PDF-RE: PDF Recognition & Extraction Service

GPU加速的PDF解析微服务，支持多种解析后端。

## 功能特点

- 多后端支持：marker (GPU加速OCR)、pdfplumber (快速)、pypdf (基础)
- 自动后端选择：根据GPU可用性和配置自动选择最佳后端
- RESTful API：支持文件上传和Base64编码
- 健康检查：`/health` 端点用于服务监控

## 部署要求

### 基础模式（无GPU）
- Python 3.8+
- pdfplumber / pypdf

### 高质量OCR模式（需要GPU）
- NVIDIA GPU + CUDA
- marker库及其依赖

## 安装

```bash
# 基础安装
pip install -r requirements.txt

# GPU服务器完整安装（包含marker）
pip install -r requirements.txt
pip install marker-pdf
```

## 启动服务

```bash
# 开发模式
python app.py

# 生产模式（推荐）- 注意：marker OCR 解析较慢，需要增加 timeout
# --timeout 600: worker 超时时间 10 分钟（marker 处理大文件需要较长时间）
# --graceful-timeout 600: 优雅关闭超时时间
gunicorn -w 2 -b 0.0.0.0:8000 --timeout 600 --graceful-timeout 600 app:app
```

**⚠️ 重要配置说明：**

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `-w` | 2 | worker 数量，marker 占用大量 GPU 内存，不宜过多 |
| `--timeout` | 600 | worker 超时时间（秒），marker 处理大 PDF 需要较长时间 |
| `--graceful-timeout` | 600 | 优雅关闭超时时间 |

如果遇到 `WORKER TIMEOUT` 错误，请增加 `--timeout` 值。

## API接口

### 健康检查

```
GET /health
```

响应示例：
```json
{
  "status": "healthy",
  "service": "PDF-RE",
  "timestamp": "2026-03-24T10:00:00"
}
```

### 解析PDF（文件上传）

```
POST /parse
Content-Type: multipart/form-data

参数：
- file: PDF文件（必填）
- use_ocr: 是否使用OCR模式（可选，默认true）
- timeout: 超时秒数（可选，默认600）
```

响应示例：
```json
{
  "success": true,
  "markdown": "提取的文本内容...",
  "page_count": 10,
  "processing_time": 5.2
}
```

### 解析PDF（Base64）

```
POST /parse/base64
Content-Type: application/json

{
  "content": "base64编码的PDF内容",
  "use_ocr": true,
  "timeout": 600
}
```

## 客户端调用示例

```python
import requests

# 文件上传方式
with open('document.pdf', 'rb') as f:
    response = requests.post(
        'http://gpu-server:8000/parse',
        files={'file': f},
        data={'use_ocr': 'true'}
    )
result = response.json()

# Base64方式
import base64
with open('document.pdf', 'rb') as f:
    pdf_b64 = base64.b64encode(f.read()).decode()

response = requests.post(
    'http://gpu-server:8000/parse/base64',
    json={'content': pdf_b64, 'use_ocr': True}
)
result = response.json()
```

## 后端说明

| 后端 | 特点 | GPU需求 | 质量 |
|------|------|---------|------|
| marker | 高质量OCR解析 | 推荐 | 最高 |
| pdfplumber | 快速文本提取 | 不需要 | 中等 |
| pypdf | 基础文本提取 | 不需要 | 基础 |

## 配置

在 `app.py` 中修改配置：

```python
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 最大文件大小
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()    # 临时文件目录
```