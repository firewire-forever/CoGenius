#!/bin/bash

# 使用方法: ./release_resource.sh <project_name>
# 示例: ./release_resource.sh demo

# 检查参数
if [ "$#" -ne 1 ]; then
    echo "用法: $0 <project_name>"
    exit 1
fi

PROJECT_NAME="$1"

# 启动子 Shell，避免污染当前终端环境
(
    # 加载 OpenStack 环境变量（只在子 Shell 中生效）
    source /opt/stack/devstack/openrc admin admin

    # 获取项目 ID
    PROJECT_ID=$(openstack project show "$PROJECT_NAME" -f value -c id 2>/dev/null)

    if [ -z "$PROJECT_ID" ]; then
        echo "错误：无法找到项目 '$PROJECT_NAME'"
        exit 2
    fi

    echo "项目名: $PROJECT_NAME"
    echo "项目ID: $PROJECT_ID"

  # 删除所有实例
  SERVER_IDS=$(openstack server list --project "$PROJECT_ID" -f value -c ID)
  if [ -z "$SERVER_IDS" ]; then
      echo "没有找到任何实例。"
  else
      for server_id in $SERVER_IDS; do
          echo "正在删除实例: $server_id"
          openstack server delete "$server_id"
          if [ $? -eq 0 ]; then
              echo "✔ 已成功删除实例 $server_id"
          else
              echo "✘ 删除实例 $server_id 失败"
          fi
      done
      echo "所有实例清理完成。"
  fi
  
  # 获取所有浮动 IP ID
  FIP_IDS=$(openstack floating ip list --project "$PROJECT_ID" -f value -c ID)
  
  if [ -z "$FIP_IDS" ]; then
      echo "没有找到任何浮动 IP。"
  else
      # 释放浮动 IP
      for fip_id in $FIP_IDS; do
          echo "正在删除浮动 IP: $fip_id"
          openstack floating ip delete "$fip_id"
          if [ $? -eq 0 ]; then
              echo "✔ 已成功删除 $fip_id"
          else
              echo "✘ 删除 $fip_id 失败"
          fi
      done
      echo "所有浮动 IP 清理完成。"
  fi
  
  # 获取所有路由器 ID
  ROUTER_IDS=$(openstack router list --project "$PROJECT_ID" -f value -c ID)
  
  if [ -z "$ROUTER_IDS" ]; then
      echo "没有找到任何路由器。"
  else
      # 删除路由器
      for router_id in $ROUTER_IDS; do
          echo "正在删除路由器: $router_id"
  
          # 获取并移除所有接口（更稳健的方法）
          SUBNET_IDS=$(openstack router show "$router_id" -f json | jq -r '.interfaces_info[]?.subnet_id')
  
          for subnet_id in $SUBNET_IDS; do
              echo "  - 移除接口 subnet $subnet_id"
              openstack router remove subnet "$router_id" "$subnet_id"
          done
  
          # 清除外部网关（如果有）
          openstack router unset --external-gateway "$router_id" || true
  
          # 删除路由器
          openstack router delete "$router_id"
          if [ $? -eq 0 ]; then
              echo "✔ 已成功删除路由器 $router_id"
          else
              echo "✘ 删除路由器 $router_id 失败"
          fi
      done
      echo "所有路由器清理完成。"
  fi
  
  # 删除所有自定义网络（排除 shared 和 public）
  NETWORK_IDS=$(openstack network list --project "$PROJECT_ID" -f json | jq -r '.[] | select((.Shared != true) and (.Name != "public")) | .ID')
  
  if [ -z "$NETWORK_IDS" ]; then
      echo "没有可删除的网络。"
  else
      for net_id in $NETWORK_IDS; do
          echo "正在删除网络: $net_id"
  
          # 删除网络上所有端口
          PORT_IDS=$(openstack port list --network "$net_id" -f value -c ID)
          for port_id in $PORT_IDS; do
              echo "  - 删除端口 $port_id"
              openstack port delete "$port_id"
          done
  
          # 删除网络
          openstack network delete "$net_id"
          if [ $? -eq 0 ]; then
              echo "✔ 已成功删除网络 $net_id"
          else
              echo "✘ 删除网络 $net_id 失败"
          fi
      done
      echo "所有网络清理完成。"
  fi
)

# 子 Shell 结束，环境变量恢复，不污染当前终端
