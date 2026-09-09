# ============================================================
# Duoweilai Web — 统一命令入口
# ============================================================
# 用法:
#   make help       # 显示所有可用命令
#   make install    # 安装依赖
#   make dev        # 启动开发服务器
#   make test       # 运行全部测试
#
# 跨平台: Linux / macOS / WSL / Git Bash
# Windows 原生命令行请用 scripts/dev.ps1
# ============================================================

# ---------- 变量（可用环境变量覆盖） ----------
PYTHON    ?= python3
VENV      ?= .venv
PORT      ?= 8080
BIND      ?= 0.0.0.0
DB        ?= duoweilai.db
LOG_LEVEL ?= INFO
# LOG_FORMAT: human（默认，彩色可读）| json（结构化，便于日志聚合）

# 在 *nix 上 venv 路径用 bin/, Windows 上是 Scripts/
VENV_BIN := $(VENV)/bin
ifeq ($(OS),Windows_NT)
	VENV_BIN := $(VENV)/Scripts
endif

# 启用 bash 严格模式
.SHELLFLAGS := -eu -o pipefail
.SHELL := /bin/bash

.DEFAULT_GOAL := help

# ---------- 颜色（终端支持时） ----------
GREEN  := \033[32m
CYAN   := \033[36m
YELLOW := \033[33m
RESET  := \033[0m

# ---------- 帮助 ----------
.PHONY: help
help: ## 显示所有可用命令
	@echo ""
	@echo "$(CYAN)Duoweilai Web$(RESET) — 统一开发入口"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "; printf "  $(CYAN)%-15s$(RESET) %s\n", "命令", "说明"} \
		/^[a-zA-Z_-]+:.*?## / {printf "  $(GREEN)%-15s$(RESET) %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)
	@echo ""
	@echo "$(YELLOW)提示：$(RESET)变量可覆盖，例如 $(CYAN)make dev PORT=9000 LOG_LEVEL=DEBUG$(RESET)"

# ---------- 安装 ----------
.PHONY: install
install: ## 创建虚拟环境并安装依赖
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(VENV_BIN)/pip install --upgrade pip wheel setuptools
	$(VENV_BIN)/pip install -r requirements.txt
	@if [ -f requirements-dev.txt ]; then \
		$(VENV_BIN)/pip install -r requirements-dev.txt; \
	fi
	@echo "$(GREEN)✓ 安装完成$(RESET)。运行 '$(CYAN)make dev$(RESET)' 启动开发服务器"

.PHONY: install-dev
install-dev: install ## 安装（含开发依赖：lint/typecheck/coverage）

.PHONY: freeze
freeze: ## 导出当前依赖快照
	$(VENV_BIN)/pip freeze > requirements-frozen.txt
	@echo "$(GREEN)✓$(RESET) 已写入 requirements-frozen.txt"

# ---------- 运行 ----------
.PHONY: dev
dev: ## 启动开发服务器（默认端口 8080）
	@if [ ! -d $(VENV) ]; then echo "$(YELLOW)! 虚拟环境不存在，先 make install$(RESET)"; exit 1; fi
	DUOWEILAI_BIND=$(BIND) \
	DUOWEILAI_PORT=$(PORT) \
	DUOWEILAI_DB=$(DB) \
	DUOWEILAI_LOG_LEVEL=$(LOG_LEVEL) \
	DUOWEILAI_LOG_FORMAT=$${LOG_FORMAT:-human} \
	$(VENV_BIN)/python server.py

.PHONY: run
run: ## 生产模式启动 gunicorn（4 worker, 监听 127.0.0.1:8090）
	@if [ ! -d $(VENV) ]; then echo "$(YELLOW)! 虚拟环境不存在，先 make install$(RESET)"; exit 1; fi
	DUOWEILAI_BIND=127.0.0.1 \
	DUOWEILAI_LOG_LEVEL=$(LOG_LEVEL) \
	DUOWEILAI_LOG_FORMAT=$${LOG_FORMAT:-json} \
	$(VENV_BIN)/gunicorn -w 4 -b 127.0.0.1:8090 \
		--access-logfile - --error-logfile - \
		--access-logformat '%(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s' \
		"app:create_app()"

.PHONY: adduser
adduser: ## 创建靓号用户：make adduser ID=888888 EMAIL=u@e.com PASS=secret
	@if [ -z "$(ID)" ] || [ -z "$(EMAIL)" ] || [ -z "$(PASS)" ]; then \
		echo "$(YELLOW)用法:$(RESET) make adduser ID=<id> EMAIL=<email> PASS=<password>"; \
		exit 1; \
	fi
	$(VENV_BIN)/python server.py adduser $(ID) $(EMAIL) $(PASS)

# ---------- 测试 ----------
.PHONY: test
test: ## 运行全部测试（e2e + auth + api）
	@if [ ! -d $(VENV) ]; then echo "$(YELLOW)! 虚拟环境不存在，先 make install$(RESET)"; exit 1; fi
	@failed=0; \
	for t in tests/e2e_test.py tests/auth_test.py tests/api_test.py; do \
		echo "$(CYAN)▶ $$t$(RESET)"; \
		if ! DUOWEILAI_LOG_FORMAT=json $(VENV_BIN)/python $$t; then \
			failed=1; \
			echo "$(YELLOW)✗ $$t 失败$(RESET)"; \
		else \
			echo "$(GREEN)✓ $$t 通过$(RESET)"; \
		fi; \
		echo ""; \
	done; \
	exit $$failed

.PHONY: test-e2e
test-e2e: ## 仅 e2e 测试
	$(VENV_BIN)/python tests/e2e_test.py

.PHONY: test-auth
test-auth: ## 仅 auth 测试
	$(VENV_BIN)/python tests/auth_test.py

.PHONY: test-api
test-api: ## 仅 api 测试
	$(VENV_BIN)/python tests/api_test.py

.PHONY: test-logging
test-logging: ## 仅日志模块测试
	$(VENV_BIN)/python tests/test_logging.py

.PHONY: coverage
coverage: ## 运行测试 + 覆盖率报告
	@if [ ! -d $(VENV) ]; then echo "$(YELLOW)! 虚拟环境不存在$(RESET)"; exit 1; fi
	$(VENV_BIN)/coverage run --source=app tests/e2e_test.py
	$(VENV_BIN)/coverage run --source=app --append tests/auth_test.py
	$(VENV_BIN)/coverage run --source=app --append tests/api_test.py
	$(VENV_BIN)/coverage report --fail-under=60
	@echo ""
	@echo "$(CYAN)HTML 报告：$(RESET) htmlcov/index.html（运行 make coverage-html 打开）"

.PHONY: coverage-html
coverage-html: coverage ## 生成 HTML 覆盖率报告
	$(VENV_BIN)/coverage html

# ---------- 代码质量 ----------
.PHONY: lint
lint: ## 检查代码风格（ruff）
	@if [ ! -d $(VENV) ]; then echo "$(YELLOW)! 虚拟环境不存在$(RESET)"; exit 1; fi
	$(VENV_BIN)/ruff check app/ tests/ server.py
	$(VENV_BIN)/ruff format --check app/ tests/ server.py

.PHONY: format
format: ## 自动格式化 + 自动修复（ruff）
	$(VENV_BIN)/ruff format app/ tests/ server.py
	$(VENV_BIN)/ruff check --fix app/ tests/ server.py

.PHONY: typecheck
typecheck: ## 静态类型检查（mypy）
	$(VENV_BIN)/mypy app/

.PHONY: check
check: lint typecheck test ## 全套质量门禁（lint + typecheck + test）

# ---------- 工具 ----------
.PHONY: db-shell
db-shell: ## 打开 SQLite shell（需本机有 sqlite3）
	@command -v sqlite3 >/dev/null || { echo "$(YELLOW)未找到 sqlite3$(RESET)"; exit 1; }
	sqlite3 $(DB)

.PHONY: db-reset
db-reset: ## 删除本地数据库（开发用）
	rm -f $(DB) $(DB)-wal $(DB)-shm
	@echo "$(GREEN)✓$(RESET) 数据库已重置"

.PHONY: clean
clean: ## 清理临时文件（__pycache__、.pyc、ruff/mypy 缓存、测试产物）
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@rm -f duoweilai.db duoweilai.db-wal duoweilai.db-shm reset_link.log
	@rm -f .test-db-*.db .test-db-*.db-wal .test-db-*.db-shm
	@rm -rf .ruff_cache .mypy_cache htmlcov .coverage
	@echo "$(GREEN)✓ 清理完成$(RESET)"

.PHONY: distclean
distclean: clean ## 清理一切，包括虚拟环境
	rm -rf $(VENV)
	@echo "$(GREEN)✓$(RESET) 虚拟环境已删除"

# ---------- 部署（远程服务器管理） ----------
.PHONY: deploy
deploy: ## 部署到服务器：make deploy HOST=root@1.2.3.4
	@if [ -z "$(HOST)" ]; then \
		echo "$(YELLOW)用法:$(RESET) make deploy HOST=user@server"; exit 1; \
	fi
	@if [ ! -f ~/.ssh/id_ed25519 ] && [ ! -f ~/.ssh/id_rsa ]; then \
		echo "$(YELLOW)! 未找到 SSH 私钥，请先生成：ssh-keygen -t ed25519$(RESET)"; exit 1; \
	fi
	./deploy/deploy.sh $(HOST)

.PHONY: remote-status
remote-status: ## 远程查看服务状态：make remote-status HOST=...
	@if [ -z "$(HOST)" ]; then echo "$(YELLOW)用法:$(RESET) make remote-status HOST=user@server"; exit 1; fi
	ssh $(HOST) "sudo systemctl status duoweilai --no-pager"

.PHONY: remote-logs
remote-logs: ## 远程实时跟踪日志：make remote-logs HOST=...
	@if [ -z "$(HOST)" ]; then echo "$(YELLOW)用法:$(RESET) make remote-logs HOST=user@server"; exit 1; fi
	ssh -t $(HOST) "sudo journalctl -u duoweilai -f --no-pager"

.PHONY: remote-restart
remote-restart: ## 远程重启服务：make remote-restart HOST=...
	@if [ -z "$(HOST)" ]; then echo "$(YELLOW)用法:$(RESET) make remote-restart HOST=user@server"; exit 1; fi
	ssh $(HOST) "sudo systemctl restart duoweilai && sudo systemctl status duoweilai --no-pager"

.PHONY: remote-tail
remote-tail: ## 远程查看最近 N 行日志：make remote-tail HOST=... [N=100]
	@if [ -z "$(HOST)" ]; then echo "$(YELLOW)用法:$(RESET) make remote-tail HOST=user@server [N=100]"; exit 1; fi
	ssh $(HOST) "sudo journalctl -u duoweilai -n $${N:-100} --no-pager"
