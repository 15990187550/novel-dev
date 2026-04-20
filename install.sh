#!/bin/bash
set -e

echo "=== Novel Dev 安装脚本 ==="

# 检测操作系统
OS="$(uname -s)"
echo "检测到操作系统: $OS"

# 1. 安装 PostgreSQL
install_postgres() {
    if command -v psql &> /dev/null; then
        echo "PostgreSQL 已安装"
    else
        echo "正在安装 PostgreSQL..."
        if [[ "$OS" == "Darwin" ]]; then
            if command -v brew &> /dev/null; then
                brew install postgresql@17 pgvector
            else
                echo "需要 Homebrew，请从 https://brew.sh 安装"
                exit 1
            fi
        elif [[ "$OS" == "Linux" ]]; then
            if command -v apt-get &> /dev/null; then
                sudo apt-get install -y postgresql postgresql-contrib
                # pgvector 需要单独安装
            elif command -v yum &> /dev/null; then
                sudo yum install -y postgresql-server postgresql-devel
            fi
        fi
    fi
}

# 2. 启动 PostgreSQL
start_postgres() {
    if [[ "$OS" == "Darwin" ]]; then
        if brew services list | grep -q "postgresql@17.*started"; then
            echo "PostgreSQL 服务已运行"
        else
            echo "启动 PostgreSQL 服务..."
            brew services start postgresql@17
        fi
    else
        sudo systemctl start postgresql 2>/dev/null || sudo service postgresql start 2>/dev/null || true
    fi
}

# 3. 创建数据库
setup_database() {
    echo "设置数据库..."
    if [[ "$OS" == "Darwin" ]]; then
        export PGPASSWORD=""
        USER=$(whoami)

        # 创建数据库（如果不存在）
        createdb novel_dev 2>/dev/null || true

        # 启用 pgvector
        psql -d novel_dev -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true
    fi
}

# 4. 安装 Python 依赖
install_python_deps() {
    echo "安装 Python 依赖..."
    pip install -e ".[dev]" --quiet
}

# 5. 运行数据库迁移
run_migrations() {
    echo "运行数据库迁移..."
    export DATABASE_URL="postgresql+asyncpg://$(whoami)@localhost/novel_dev"
    alembic upgrade head
}

# 6. 启动 Embedding 服务
start_embedding_service() {
    echo "启动 Embedding 服务..."
    # 检查是否已在运行
    if curl -s http://127.0.0.1:9997/v1/models &>/dev/null; then
        echo "Embedding 服务已在运行"
    else
        cd "$(dirname "$0")"
        nohup python3 embedding_server.py > /tmp/embedding_server.log 2>&1 &
        echo "Embedding 服务已启动 (PID: $!)"
        # 等待服务就绪
        for i in {1..30}; do
            if curl -s http://127.0.0.1:9997/v1/models &>/dev/null; then
                echo "Embedding 服务就绪"
                return
            fi
            sleep 1
        done
        echo "警告: Embedding 服务可能未正常启动"
    fi
}

# 主流程
install_postgres
start_postgres
setup_database
install_python_deps
run_migrations
start_embedding_service

echo ""
echo "=== 安装完成 ==="
echo "数据库: postgresql://$(whoami)@localhost/novel_dev"
echo "Embedding: http://127.0.0.1:9997"
echo ""
echo "启动应用: python -m novel_dev.api.routes"
echo "或使用: uvicorn novel_dev.api.routes:app --reload"