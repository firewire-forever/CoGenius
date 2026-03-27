# --- Stage 1: Builder ---
# This stage builds the Python dependencies
FROM python:3.11-slim as builder

WORKDIR /usr/src/app

# Install build-time system dependencies
RUN rm -f /etc/apt/sources.list.d/* && \
    echo "deb http://mirrors.aliyun.com/debian bookworm main" > /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements file and install wheels
COPY requirements.txt .
RUN pip wheel --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --wheel-dir /usr/src/app/wheels -r requirements.txt

# --- Stage 2: Final Image ---
# This stage creates the final, lean production image
FROM python:3.11-slim

# Create a non-root user for security
RUN addgroup --system app && adduser --system --ingroup app appuser
USER appuser
WORKDIR /home/appuser/app

# Install runtime system dependencies required by libraries like 'unstructured'
# Running as root temporarily for installation
USER root
RUN rm -f /etc/apt/sources.list.d/* && \
    echo "deb http://mirrors.aliyun.com/debian bookworm main" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian bookworm-updates main" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian bookworm-backports main" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libmagic1 \
    poppler-utils \
    tesseract-ocr \
    libheif-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    wget \
    gnupg \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# 安装Java 17 LTS
RUN mkdir -p /etc/apt/keyrings && \
    wget -O - https://packages.adoptium.net/artifactory/api/gpg/key/public | tee /etc/apt/keyrings/adoptium.asc && \
    echo "deb [signed-by=/etc/apt/keyrings/adoptium.asc] https://mirrors.tuna.tsinghua.edu.cn/Adoptium/deb $(awk -F= '/^VERSION_CODENAME/{print$2}' /etc/os-release) main" | tee /etc/apt/sources.list.d/adoptium.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends temurin-17-jdk && \
    rm -rf /var/lib/apt/lists/*

# 安装Terraform
RUN apt-get update && \
    apt-get install -y gnupg software-properties-common && \
    wget -O- https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/hashicorp.list && \
    apt-get update && \
    apt-get install -y terraform && \
    terraform --version

# 安装Ansible
RUN apt-get update && \
    apt-get install -y ansible && \
    ansible --version && \
    ansible-playbook --version && \
    rm -rf /var/lib/apt/lists/*

# 检测架构并设置JAVA_HOME
RUN ARCH=$(dpkg --print-architecture) && \
    echo "Detected architecture: $ARCH" && \
    if [ "$ARCH" = "arm64" ]; then \
        echo "Setting JAVA_HOME for ARM64" && \
        echo "export JAVA_HOME=/usr/lib/jvm/temurin-17-jdk-arm64" >> /etc/profile.d/java.sh; \
    else \
        echo "Setting JAVA_HOME for AMD64/other" && \
        echo "export JAVA_HOME=/usr/lib/jvm/temurin-17-jdk-amd64" >> /etc/profile.d/java.sh; \
    fi && \
    chmod +x /etc/profile.d/java.sh && \
    echo "Profile script created with content:" && \
    cat /etc/profile.d/java.sh

# 设置环境变量 - 同时支持ARM64和AMD64架构
ENV JAVA_HOME_ARM64=/usr/lib/jvm/temurin-17-jdk-arm64
ENV JAVA_HOME_AMD64=/usr/lib/jvm/temurin-17-jdk-amd64
# 启动脚本将在运行时设置正确的JAVA_HOME

# 修改entrypoint脚本添加JAVA_HOME设置
RUN echo '#!/bin/bash\n\
# 设置正确的JAVA_HOME\n\
ARCH=$(dpkg --print-architecture)\n\
if [ "$ARCH" = "arm64" ]; then\n\
    export JAVA_HOME=$JAVA_HOME_ARM64\n\
else\n\
    export JAVA_HOME=$JAVA_HOME_AMD64\n\
fi\n\
export PATH=$PATH:$JAVA_HOME/bin\n\
\n\
# 确认Java安装\n\
echo "Architecture: $ARCH"\n\
echo "JAVA_HOME: $JAVA_HOME"\n\
java -version\n\
\n\
# 执行原始命令\n\
exec "$@"\n' > /home/appuser/app/java_entrypoint.sh && \
    chmod +x /home/appuser/app/java_entrypoint.sh

# 确认Java文件目录结构
RUN ls -la /usr/lib/jvm/

# Copy pre-built wheels from the builder stage and install them
COPY --from=builder /usr/src/app/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

# 创建必要的目录并设置权限
RUN mkdir -p /home/appuser/nltk_data && \
    mkdir -p /home/appuser/models && \
    mkdir -p /tmp/matplotlib && \
    chown -R appuser:app /home/appuser/nltk_data && \
    chown -R appuser:app /home/appuser/models && \
    chmod -R 755 /home/appuser/nltk_data && \
    chmod -R 755 /home/appuser/models && \
    chmod -R 777 /tmp/matplotlib

# 设置环境变量
ENV NLTK_DATA=/home/appuser/nltk_data
ENV HF_DATASETS_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1
ENV HF_HOME=/home/appuser/models
ENV HF_HUB_LOCAL_DIR=/home/appuser/models
ENV UNSTRUCTURED_LOCAL_INFERENCE=1
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

# 复制本地的NLTK数据和模型文件到容器中（在复制应用代码之前）
COPY --chown=appuser:app nltk_data /home/appuser/nltk_data/
COPY --chown=appuser:app models/ /home/appuser/models/

# 确保模型目录有正确的权限
RUN find /home/appuser/models -type d -exec chmod 755 {} \; && \
    find /home/appuser/models -type f -exec chmod 644 {} \;

# Switch back to the non-root user
USER appuser

# Copy the application source code and entrypoint script
COPY --chown=appuser:app . .
COPY --chown=appuser:app entrypoint.sh /home/appuser/app/entrypoint.sh
RUN chmod +x /home/appuser/app/entrypoint.sh

# 添加调试指令
RUN echo "NLTK data files:" && ls -la /home/appuser/nltk_data && \
    echo "Model files:" && ls -la /home/appuser/models/models--unstructuredio--yolo_x_layout/snapshots/*/

# Expose the port Gunicorn will run on
EXPOSE 5000

# Run the entrypoint script when the container starts
ENTRYPOINT ["/home/appuser/app/entrypoint.sh"] 