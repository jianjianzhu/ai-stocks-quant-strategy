#!/bin/bash
# ============================================================
# EC2 t2.micro 低配实例 - 纯 pip 安装 pandas-ta
# 
# 背景：
#   - t2.micro 只有 1 vCPU / 1 GB RAM，网络波动大
#   - conda 国外源下载极易卡死，不建议在低配实例上使用
#   - pandas-ta 是纯 Python 包，无 C 编译依赖，pip 一条命令秒装
#   - 无需 gcc、无需 ta-lib 底层 C 源码
#   - 量化回测计算指标场景，可完全替代 talib
#
# 用法: bash install_pandas_ta_ec2.sh
# ============================================================

# ---- 颜色定义 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ---- 日志文件 ----
LOG_FILE="$HOME/pandas_ta_install_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info()  { echo -e "${GREEN}[INFO]${NC}  $(date '+%H:%M:%S') $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $(date '+%H:%M:%S') $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $(date '+%H:%M:%S') $*"; }
log_step()  { echo ""; echo -e "${BLUE}=========================================${NC}"; echo -e "${BLUE}  $*${NC}"; echo -e "${BLUE}=========================================${NC}"; }

# ---- 全局重试设置 ----
PIP_RETRIES=5
PIP_TIMEOUT=60
PIP_CACHE_DIR="$HOME/.cache/pip"

# ---- 镜像源列表（按优先级排列，失败自动降级） ----
# 格式: "名称|index-url|trusted-host1,trusted-host2"
MIRRORS=(
    "清华TUNA|https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/|mirrors.tuna.tsinghua.edu.cn,pypi.tuna.tsinghua.edu.cn"
    "阿里云|https://mirrors.aliyun.com/pypi/simple/|mirrors.aliyun.com"
    "中科大USTC|https://mirrors.ustc.edu.cn/pypi/web/simple/|mirrors.ustc.edu.cn"
    "豆瓣Douban|https://pypi.douban.com/simple/|pypi.douban.com"
    "PyPI官方|https://pypi.org/simple/|pypi.org,files.pythonhosted.org"
)

# ============================================================
# 工具函数
# ============================================================

# 检查上一条命令是否成功，失败则输出错误并继续（不 set -e）
check() {
    if [ $? -ne 0 ]; then
        log_error "$1"
        return 1
    fi
    return 0
}

# pip 安装（带重试 & 超时 & 指定镜像）
pip_install_with_retry() {
    local pkg="$1"
    local index_url="$2"
    shift 2
    local trusted_hosts="$@"

    log_info "安装: $pkg (镜像: $index_url)"

    for i in $(seq 1 $PIP_RETRIES); do
        log_info "  第 $i / $PIP_RETRIES 次尝试..."

        if pip install "$pkg" \
            --timeout "$PIP_TIMEOUT" \
            --retries 3 \
            --cache-dir "$PIP_CACHE_DIR" \
            -i "$index_url" \
            --trusted-host $(echo "$trusted_hosts" | tr ',' ' '); then
            log_info "  ✅ $pkg 安装成功"
            return 0
        fi

        if [ $i -lt $PIP_RETRIES ]; then
            local wait=$((i * 5))
            log_warn "  等待 ${wait}s 后重试..."
            sleep $wait
        fi
    done

    log_error "  ❌ $pkg 安装失败（已重试 $PIP_RETRIES 次）"
    return 1
}

# 遍历所有镜像源安装
try_all_mirrors() {
    local pkg="$1"

    for mirror in "${MIRRORS[@]}"; do
        IFS='|' read -r m_name m_url m_hosts <<< "$mirror"
        log_info "尝试镜像: $m_name"

        if pip_install_with_retry "$pkg" "$m_url" "$m_hosts"; then
            return 0
        fi
        log_warn "镜像 $m_name 失败，切换到下一个..."
    done

    log_error "所有镜像源均失败！"
    return 1
}

# ============================================================
# Step 0: 环境预检
# ============================================================
log_step "Step 0: 环境预检"

# 检查是否为 root / 有 sudo 权限
if [ "$EUID" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi
log_info "运行身份: $(whoami), sudo=$([ -n "$SUDO" ] && echo 'YES' || echo 'NO (root)')"

# 内存检查（t2.micro 只有 ~1GB）
TOTAL_MEM=$(free -m 2>/dev/null | awk '/Mem:/{print $2}' || echo "unknown")
if [ "$TOTAL_MEM" != "unknown" ] && [ "$TOTAL_MEM" -lt 512 ]; then
    log_warn "内存仅 ${TOTAL_MEM}MB，低于 512MB，pip 安装可能被 OOM Killer 杀死"
    log_warn "建议: sudo swapoff -a && sudo dd if=/dev/zero of=/swapfile bs=1M count=1024 && sudo mkswap /swapfile && sudo swapon /swapfile"
fi
log_info "总内存: ${TOTAL_MEM}MB"

# 磁盘检查
DISK_AVAIL=$(df -BM / 2>/dev/null | awk 'NR==2{print $4}' | sed 's/M//' || echo "unknown")
if [ "$DISK_AVAIL" != "unknown" ] && [ "$DISK_AVAIL" -lt 200 ]; then
    log_error "磁盘剩余空间仅 ${DISK_AVAIL}MB，低于 200MB，可能安装失败"
fi
log_info "根分区剩余: ${DISK_AVAIL}MB"

# Python 检查
log_info "Python 版本: $(python --version 2>&1 || python3 --version 2>&1)"

# pip 检查
PIP_CMD="pip"
if ! command -v pip &>/dev/null; then
    if command -v pip3 &>/dev/null; then
        PIP_CMD="pip3"
    else
        log_error "pip 未安装，请先安装 pip"
        exit 1
    fi
fi
log_info "pip 路径: $(which $PIP_CMD)"

# ============================================================
# Step 1: 网络连通性测试
# ============================================================
log_step "Step 1: 网络连通性测试"

TEST_HOSTS=(
    "mirrors.tuna.tsinghua.edu.cn"
    "mirrors.aliyun.com"
    "pypi.org"
)

for host in "${TEST_HOSTS[@]}"; do
    if timeout 5 curl -s -o /dev/null -w "%{http_code}" "https://$host" 2>/dev/null | grep -q "200\|301\|302"; then
        log_info "✅ $host 可达"
    else
        log_warn "❌ $host 不可达或超时"
    fi
done

# ============================================================
# Step 2: 更新 CA 证书（使用国内 yum 镜像）
# ============================================================
log_step "Step 2: 更新 CA 证书"

# Amazon Linux 2 / 2023 通用
$SUDO yum install -y ca-certificates 2>/dev/null && \
    log_info "ca-certificates 安装/更新成功" || \
    log_warn "ca-certificates 安装跳过（可能已是最新）"

$SUDO update-ca-trust force-enable 2>/dev/null || true
$SUDO update-ca-trust extract 2>/dev/null || true
log_info "CA 证书更新完成"

# ============================================================
# Step 3: 配置 pip 永久使用国内镜像
# ============================================================
log_step "Step 3: 配置 pip 永久镜像（清华源）"

mkdir -p ~/.pip ~/.config/pip

cat > ~/.pip/pip.conf << 'PIPEOF'
[global]
index-url = https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/
timeout = 60
retries = 5
trusted-host =
    mirrors.tuna.tsinghua.edu.cn
    pypi.tuna.tsinghua.edu.cn
PIPEOF

# 同时写入 ~/.config/pip/pip.conf（某些 pip 版本读取此路径）
cp ~/.pip/pip.conf ~/.config/pip/pip.conf 2>/dev/null || true

log_info "pip 配置写入: ~/.pip/pip.conf"
log_info "内容如下："
cat ~/.pip/pip.conf

# ============================================================
# Step 4: 升级 pip
# ============================================================
log_step "Step 4: 升级 pip"

$PIP_CMD install --upgrade pip \
    -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ \
    --trusted-host mirrors.tuna.tsinghua.edu.cn \
    --timeout "$PIP_TIMEOUT" \
    --retries 3 2>/dev/null && \
    log_info "pip 升级成功" || \
    log_warn "pip 升级失败，继续使用当前版本"

$PIP_CMD --version

# ============================================================
# Step 5: 安装 pandas-ta（多镜像容灾）
# ============================================================
log_step "Step 5: 安装 pandas-ta（纯 pip，无需 C 编译）"

log_info "pandas-ta 是纯 Python 包，无需 gcc / ta-lib 底层 C 库"
log_info "支持 TA-Lib 全部指标：SMA, EMA, RSI, MACD, Bollinger, ATR..."

if try_all_mirrors "pandas-ta"; then
    INSTALL_SUCCESS=1
else
    INSTALL_SUCCESS=0
fi

# ============================================================
# Step 5b: 可选安装常用量化库
# ============================================================
if [ "$INSTALL_SUCCESS" -eq 1 ]; then
    log_step "Step 5b: 可选安装常用量化依赖"

    DEPS=(
        "numpy"
        "pandas"
    )

    for dep in "${DEPS[@]}"; do
        log_info "安装 $dep..."
        $PIP_CMD install "$dep" \
            --timeout "$PIP_TIMEOUT" \
            --retries 3 \
            -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/ \
            --trusted-host mirrors.tuna.tsinghua.edu.cn 2>/dev/null && \
            log_info "  ✅ $dep" || \
            log_warn "  ⚠️  $dep 安装失败（pandas-ta 可能自带依赖）"
    done
fi

# ============================================================
# Step 6: 验证安装
# ============================================================
log_step "Step 6: 验证安装"

VERIFY_CODE="
import pandas_ta as ta
print(f'pandas-ta 版本: {ta.__version__}')
print(f'可用指标数: {len([m for m in dir(ta) if m.isupper()])}')
# 快速冒烟测试
import numpy as np
import pandas as pd
df = pd.DataFrame({'close': np.random.randn(100).cumsum() + 100})
r = df.ta.sma(length=10)
print(f'sma(10) 计算成功，结果长度: {len(r)}')
print('✅ 冒烟测试通过')
"

if python -c "$VERIFY_CODE" 2>/dev/null; then
    log_info "✅ pandas-ta 安装验证全部通过！"
else
    log_error "⚠️  验证失败，尝试基础导入检查..."
    python -c "import pandas_ta; print('import 成功, 版本:', pandas_ta.__version__)" 2>/dev/null || {
        log_error "❌ 基础 import 也失败"
        log_error "请查看日志: $LOG_FILE"
        log_error "手动排查: python -c 'import pandas_ta'"
    }
fi

# ============================================================
# 汇总
# ============================================================
log_step "安装汇总"

echo "  日志文件    : $LOG_FILE"
echo "  pip 配置    : ~/.pip/pip.conf"
echo "  安装结果    : $([ "$INSTALL_SUCCESS" -eq 1 ] && echo '✅ 成功' || echo '❌ 失败')"
echo ""

if [ "$INSTALL_SUCCESS" -eq 0 ]; then
    echo "========================================="
    echo "  手动恢复方案"
    echo "========================================="
    echo ""
    echo "  方案1 - 指定国内镜像手动安装:"
    echo "    pip install --no-cache-dir pandas-ta \\"
    echo "      -i https://mirrors.aliyun.com/pypi/simple/ \\"
    echo "      --trusted-host mirrors.aliyun.com \\"
    echo "      --timeout 120 --retries 10"
    echo ""
    echo "  方案2 - 先下载 wheel 再离线安装:"
    echo "    pip download pandas-ta -d /tmp/wheels -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/"
    echo "    pip install --no-index --find-links=/tmp/wheels pandas-ta"
    echo ""
    echo "  方案3 - 检查是否需要代理:"
    echo "    export http_proxy=http://your-proxy:port"
    echo "    export https_proxy=http://your-proxy:port"
fi

echo ""
echo "  快速测试:"
echo "    python -c \"import pandas_ta as ta; print(ta.__version__)\""
echo ""

log_info "脚本执行完毕。日志: $LOG_FILE"