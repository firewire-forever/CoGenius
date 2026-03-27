#!/bin/bash

SESSION_NAME=crcg

# 如果 session 已存在，直接 attach
tmux has-session -t ${SESSION_NAME} 2>/dev/null
if [ $? -eq 0 ]; then
    tmux attach -t ${SESSION_NAME}
    exit 0
fi

########################################
# 窗口 0：主服务 5000
########################################
tmux new-session -d -s ${SESSION_NAME} -n backend
tmux send-keys -t ${SESSION_NAME}:0 "cd ~/CRCG/CRCG/crcg_backend" C-m
sleep 1
tmux send-keys -t ${SESSION_NAME}:0 "source .venv/bin/activate" C-m
sleep 1
tmux send-keys -t ${SESSION_NAME}:0 "source .env" C-m
sleep 2
tmux send-keys -t ${SESSION_NAME}:0 "python run.py" C-m

########################################
# 窗口 1：celery worker
########################################
tmux new-window -t ${SESSION_NAME} -n celery
sleep 3  # 等主服务先启动

tmux send-keys -t ${SESSION_NAME}:1 "cd ~/CRCG/CRCG/crcg_backend" C-m
sleep 1
tmux send-keys -t ${SESSION_NAME}:1 "source .venv/bin/activate" C-m
sleep 1
tmux send-keys -t ${SESSION_NAME}:1 "source .env" C-m
sleep 1
tmux send-keys -t ${SESSION_NAME}:1 "HF_HOME=/home/appuser \
HF_HUB_CACHE=/home/appuser/models \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
HF_DATASETS_OFFLINE=1 \
UNSTRUCTURED_LOCAL_INFERENCE=1 \
celery -A celery_worker:celery_app worker -l info" C-m

########################################
# 窗口 2：callback 服务（9999）
########################################
tmux new-window -t ${SESSION_NAME} -n callback
sleep 2  # 等主服务和celery先启动

tmux send-keys -t ${SESSION_NAME}:2 "cd ~/crcg_callback" C-m
sleep 1
tmux send-keys -t ${SESSION_NAME}:2 "python callback_server.py" C-m

########################################
# 窗口 3：测试窗口（curl）
########################################
tmux new-window -t ${SESSION_NAME} -n test
sleep 5  # 等主服务 + callback 完全启动

tmux send-keys -t ${SESSION_NAME}:3 "cd ~/crcg_callback" C-m
sleep 1
tmux send-keys -t ${SESSION_NAME}:3 "curl -X POST http://127.0.0.1:5000/api/v1/target-range/generate \
-F \"file=@descrp.pdf\" \
-F \"taskId=demo002\" \
-F \"callbackUrl=http://127.0.0.1:9999/callback\"" C-m

# 默认切回主服务窗口
tmux select-window -t ${SESSION_NAME}:0

# attach
tmux attach -t ${SESSION_NAME}

