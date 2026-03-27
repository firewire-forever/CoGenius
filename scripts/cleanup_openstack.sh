#!/bin/bash
#
# OpenStack Resource Cleanup Script
# 一键清理OpenStack资源并报告清理情况
#

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
TOTAL_DELETED=0
TOTAL_ERRORS=0
declare -a ERROR_LOG

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
    ((TOTAL_DELETED++))
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    ((TOTAL_ERRORS++))
    ERROR_LOG+=("$1")
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Header
echo "========================================"
echo "   OpenStack Resource Cleanup Script"
echo "========================================"
echo ""

# Check if OpenStack credentials are loaded
if [ -z "$OS_AUTH_URL" ] || [ -z "$OS_USERNAME" ]; then
    echo -e "${RED}错误: OpenStack环境变量未设置!${NC}"
    echo "请先source你的OpenStack rc文件:"
    echo "  source openrc.sh"
    echo "或者设置以下环境变量:"
    echo "  export OS_AUTH_URL=..."
    echo "  export OS_USERNAME=..."
    echo "  export OS_PASSWORD=..."
    echo "  export OS_PROJECT_NAME=..."
    exit 1
fi

log_info "当前项目: ${OS_PROJECT_NAME:-vsdl}"
log_info "认证URL: ${OS_AUTH_URL}"
echo ""

# ============ 1. DELETE SERVERS ============
echo "========================================"
echo "Step 1: 清理云服务器 (Servers)"
echo "========================================"

SERVERS=$(openstack server list -f value -c ID -c Name 2>/dev/null || true)
SERVER_COUNT=$(echo "$SERVERS" | grep -c -v '^$' 2>/dev/null || echo "0")

if [ -z "$SERVERS" ] || [ "$SERVER_COUNT" -eq 0 ]; then
    log_info "没有发现云服务器"
else
    log_info "发现 ${SERVER_COUNT} 台云服务器"

    while IFS= read -r line; do
        if [ -n "$line" ]; then
            SERVER_ID=$(echo "$line" | awk '{print $1}')
            SERVER_NAME=$(echo "$line" | awk '{print $2}')
            log_info "正在删除服务器: ${SERVER_NAME} (${SERVER_ID})"

            if openstack server delete --wait "$SERVER_ID" 2>&1; then
                log_success "已删除服务器: ${SERVER_NAME}"
            else
                log_error "删除服务器失败: ${SERVER_NAME} (${SERVER_ID})"
            fi
        fi
    done <<< "$SERVERS"
fi
echo ""

# ============ 2. DELETE FLOATING IPs ============
echo "========================================"
echo "Step 2: 清理浮动IP (Floating IPs)"
echo "========================================"

FLOATING_IPS=$(openstack floating ip list -f value -c ID -c "Floating IP Address" 2>/dev/null || true)
FLOAT_COUNT=$(echo "$FLOATING_IPS" | grep -c -v '^$' 2>/dev/null || echo "0")

if [ -z "$FLOATING_IPS" ] || [ "$FLOAT_COUNT" -eq 0 ]; then
    log_info "没有发现浮动IP"
else
    log_info "发现 ${FLOAT_COUNT} 个浮动IP"

    while IFS= read -r line; do
        if [ -n "$line" ]; then
            FLOAT_ID=$(echo "$line" | awk '{print $1}')
            FLOAT_ADDR=$(echo "$line" | awk '{print $2}')
            log_info "正在释放浮动IP: ${FLOAT_ADDR} (${FLOAT_ID})"

            if openstack floating ip delete "$FLOAT_ID" 2>&1; then
                log_success "已释放浮动IP: ${FLOAT_ADDR}"
            else
                log_error "释放浮动IP失败: ${FLOAT_ADDR} (${FLOAT_ID})"
            fi
        fi
    done <<< "$FLOATING_IPS"
fi
echo ""

# ============ 3. DELETE ROUTERS ============
echo "========================================"
echo "Step 3: 清理路由器 (Routers)"
echo "========================================"

ROUTERS=$(openstack router list -f value -c ID -c Name 2>/dev/null || true)
ROUTER_COUNT=$(echo "$ROUTERS" | grep -c -v '^$' 2>/dev/null || echo "0")

if [ -z "$ROUTERS" ] || [ "$ROUTER_COUNT" -eq 0 ]; then
    log_info "没有发现路由器"
else
    log_info "发现 ${ROUTER_COUNT} 个路由器"

    while IFS= read -r line; do
        if [ -n "$line" ]; then
            ROUTER_ID=$(echo "$line" | awk '{print $1}')
            ROUTER_NAME=$(echo "$line" | awk '{print $2}')

            log_info "正在移除路由器网关: ${ROUTER_NAME}"
            openstack router unset --external-gateway "$ROUTER_ID" 2>/dev/null || true

            # Get and remove all interfaces
            PORTS=$(openstack port list --router "$ROUTER_ID" -f value -c ID 2>/dev/null || true)
            while IFS= read -r PORT_ID; do
                if [ -n "$PORT_ID" ]; then
                    log_info "  移除路由器接口: ${PORT_ID}"
                    openstack router remove port "$ROUTER_ID" "$PORT_ID" 2>/dev/null || true
                fi
            done <<< "$PORTS"

            log_info "正在删除路由器: ${ROUTER_NAME}"
            if openstack router delete "$ROUTER_ID" 2>&1; then
                log_success "已删除路由器: ${ROUTER_NAME}"
            else
                log_warning "标准删除失败，尝试 OVN 强制清理: ${ROUTER_NAME}"
                # OVN 强制清理 - 删除 OVN 北向数据库中的逻辑路由器
                OVN_LR_NAME="neutron-${ROUTER_ID}"
                if sudo ovn-nbctl lr-list 2>/dev/null | grep -q "$OVN_LR_NAME"; then
                    log_info "  强制删除 OVN 逻辑路由器: ${OVN_LR_NAME}"
                    sudo ovn-nbctl lr-del "$OVN_LR_NAME" 2>/dev/null && log_success "OVN 路由器已清理"
                fi
            fi
        fi
    done <<< "$ROUTERS"
fi
echo ""

# ============ 3.5 OVN FORCE CLEANUP ============
echo "========================================"
echo "Step 3.5: OVN 强制清理 (需要 sudo)"
echo "========================================"

# 检查是否有 sudo 权限
if sudo -n true 2>/dev/null; then
    log_info "正在清理 OVN 残留资源..."

    # 清理所有残留的 OVN 逻辑路由器（以 neutron- 开头）
    OVN_ROUTERS=$(sudo ovn-nbctl lr-list 2>/dev/null | grep "neutron-" | awk '{print $2}' | tr -d '()' || true)
    if [ -n "$OVN_ROUTERS" ]; then
        log_info "发现 OVN 残留路由器"
        while IFS= read -r lr_name; do
            if [ -n "$lr_name" ]; then
                log_info "  清理 OVN 路由器: ${lr_name}"
                sudo ovn-nbctl lr-del "$lr_name" 2>/dev/null && log_success "已清理: ${lr_name}"
            fi
        done <<< "$OVN_ROUTERS"
    else
        log_info "没有发现 OVN 残留路由器"
    fi

    # 清理残留的 OVN 逻辑交换机端口（router 类型）
    OVN_LSPS=$(sudo ovn-nbctl lsp-list 2>/dev/null | grep "type: router" || true)
    if [ -n "$OVN_LSPS" ]; then
        log_info "发现 OVN 残留路由器端口"
        echo "$OVN_LSPS" | while read -r line; do
            LSP_NAME=$(echo "$line" | awk '{print $1}')
            if [ -n "$LSP_NAME" ]; then
                log_info "  清理 OVN 端口: ${LSP_NAME}"
                sudo ovn-nbctl lsp-del "$LSP_NAME" 2>/dev/null || true
            fi
        done
    fi
else
    log_warning "没有 sudo 权限，跳过 OVN 强制清理"
    log_warning "如果有资源删除失败，请手动运行: sudo ovn-nbctl lr-del neutron-<router-id>"
fi
echo ""

# ============ 4. DELETE PORTS ============
echo "========================================"
echo "Step 4: 清理端口 (Ports)"
echo "========================================"

# Get all ports that are not bound to routers or external networks
PORTS=$(openstack port list -f value -c ID -c Name -c "Device Owner" 2>/dev/null | grep -v "network:router\|network:ha_router_replication\|network:floatingip\|network:dhcp" || true)
PORT_COUNT=$(echo "$PORTS" | grep -c -v '^$' 2>/dev/null || echo "0")

if [ -z "$PORTS" ] || [ "$PORT_COUNT" -eq 0 ]; then
    log_info "没有发现需要清理的端口"
else
    log_info "发现 ${PORT_COUNT} 个端口"

    while IFS= read -r line; do
        if [ -n "$line" ]; then
            PORT_ID=$(echo "$line" | awk '{print $1}')
            PORT_NAME=$(echo "$line" | awk '{print $2}')

            log_info "正在删除端口: ${PORT_NAME:-$PORT_ID}"
            if openstack port delete "$PORT_ID" 2>&1; then
                log_success "已删除端口: ${PORT_NAME:-$PORT_ID}"
            else
                log_error "删除端口失败: ${PORT_NAME:-$PORT_ID}"
            fi
        fi
    done <<< "$PORTS"
fi
echo ""

# ============ 5. DELETE NETWORKS ============
echo "========================================"
echo "Step 5: 清理网络 (Networks)"
echo "========================================"

# Get all networks except external ones
NETWORKS=$(openstack network list -f value -c ID -c Name -c "Router External" 2>/dev/null | grep "False" || true)
NET_COUNT=$(echo "$NETWORKS" | grep -c -v '^$' 2>/dev/null || echo "0")

if [ -z "$NETWORKS" ] || [ "$NET_COUNT" -eq 0 ]; then
    log_info "没有发现需要清理的网络"
else
    log_info "发现 ${NET_COUNT} 个网络"

    while IFS= read -r line; do
        if [ -n "$line" ]; then
            NET_ID=$(echo "$line" | awk '{print $1}')
            NET_NAME=$(echo "$line" | awk '{print $2}')

            log_info "正在删除网络: ${NET_NAME}"
            if openstack network delete "$NET_ID" 2>&1; then
                log_success "已删除网络: ${NET_NAME}"
            else
                log_error "删除网络失败: ${NET_NAME} (${NET_ID})"
            fi
        fi
    done <<< "$NETWORKS"
fi
echo ""

# ============ 6. DELETE SECURITY GROUPS ============
echo "========================================"
echo "Step 6: 清理安全组 (Security Groups)"
echo "========================================"

# Get all security groups except default
SEC_GROUPS=$(openstack security group list -f value -c ID -c Name 2>/dev/null | grep -v "default" || true)
SG_COUNT=$(echo "$SEC_GROUPS" | grep -c -v '^$' 2>/dev/null || echo "0")

if [ -z "$SEC_GROUPS" ] || [ "$SG_COUNT" -eq 0 ]; then
    log_info "没有发现需要清理的安全组"
else
    log_info "发现 ${SG_COUNT} 个安全组"

    while IFS= read -r line; do
        if [ -n "$line" ]; then
            SG_ID=$(echo "$line" | awk '{print $1}')
            SG_NAME=$(echo "$line" | awk '{print $2}')

            log_info "正在删除安全组: ${SG_NAME}"
            if openstack security group delete "$SG_ID" 2>&1; then
                log_success "已删除安全组: ${SG_NAME}"
            else
                log_error "删除安全组失败: ${SG_NAME} (${SG_ID})"
            fi
        fi
    done <<< "$SEC_GROUPS"
fi
echo ""

# ============ 7. DELETE KEYPAIRS ============
echo "========================================"
echo "Step 7: 清理密钥对 (Keypairs)"
echo "========================================"

KEYPAIRS=$(openstack keypair list -f value -c Name 2>/dev/null || true)
KP_COUNT=$(echo "$KEYPAIRS" | grep -c -v '^$' 2>/dev/null || echo "0")

if [ -z "$KEYPAIRS" ] || [ "$KP_COUNT" -eq 0 ]; then
    log_info "没有发现密钥对"
else
    log_info "发现 ${KP_COUNT} 个密钥对"

    while IFS= read -r line; do
        if [ -n "$line" ]; then
            KP_NAME="$line"
            log_info "正在删除密钥对: ${KP_NAME}"

            if openstack keypair delete "$KP_NAME" 2>&1; then
                log_success "已删除密钥对: ${KP_NAME}"
            else
                log_error "删除密钥对失败: ${KP_NAME}"
            fi
        fi
    done <<< "$KEYPAIRS"
fi
echo ""

# ============ 8. DELETE VOLUMES ============
echo "========================================"
echo "Step 8: 清理云硬盘 (Volumes)"
echo "========================================"

VOLUMES=$(openstack volume list -f value -c ID -c Name 2>/dev/null || true)
VOL_COUNT=$(echo "$VOLUMES" | grep -c -v '^$' 2>/dev/null || echo "0")

if [ -z "$VOLUMES" ] || [ "$VOL_COUNT" -eq 0 ]; then
    log_info "没有发现云硬盘"
else
    log_info "发现 ${VOL_COUNT} 个云硬盘"

    while IFS= read -r line; do
        if [ -n "$line" ]; then
            VOL_ID=$(echo "$line" | awk '{print $1}')
            VOL_NAME=$(echo "$line" | awk '{print $2}')

            log_info "正在删除云硬盘: ${VOL_NAME:-$VOL_ID}"
            if openstack volume delete "$VOL_ID" 2>&1; then
                log_success "已删除云硬盘: ${VOL_NAME:-$VOL_ID}"
            else
                log_error "删除云硬盘失败: ${VOL_NAME:-$VOL_ID}"
            fi
        fi
    done <<< "$VOLUMES"
fi
echo ""

# ============ SUMMARY ============
echo "========================================"
echo "           清理完成 - 汇总报告"
echo "========================================"
echo ""

# Show current resource counts
log_info "当前资源使用情况:"
echo ""

INSTANCE_COUNT=$(openstack server list -f value -c ID 2>/dev/null | grep -c -v '^$' || echo "0")
FLOAT_COUNT=$(openstack floating ip list -f value -c ID 2>/dev/null | grep -c -v '^$' || echo "0")
ROUTER_COUNT=$(openstack router list -f value -c ID 2>/dev/null | grep -c -v '^$' || echo "0")
NETWORK_COUNT=$(openstack network list -f value -c ID 2>/dev/null | grep -c -v '^$' || echo "0")

echo "  服务器 (Servers): ${INSTANCE_COUNT}"
echo "  浮动IP (Floating IPs): ${FLOAT_COUNT}"
echo "  路由器 (Routers): ${ROUTER_COUNT}"
echo "  网络 (Networks): ${NETWORK_COUNT}"
echo ""

# Summary
echo -e "${GREEN}成功删除: ${TOTAL_DELETED} 个资源${NC}"
if [ "$TOTAL_ERRORS" -gt 0 ]; then
    echo -e "${RED}失败数量: ${TOTAL_ERRORS} 个${NC}"
    echo ""
    echo "错误详情:"
    for err in "${ERROR_LOG[@]}"; do
        echo -e "  ${RED}- ${err}${NC}"
    done
fi
echo ""

log_info "清理完成! $(date)"
echo ""

# Show remaining resources
echo "========================================"
echo "        剩余资源列表"
echo "========================================"
echo ""
log_info "服务器:"
openstack server list -f table 2>/dev/null || echo "  无"

echo ""
log_info "网络:"
openstack network list -f table 2>/dev/null || echo "  无"

echo ""
log_info "路由器:"
openstack router list -f table 2>/dev/null || echo "  无"