# ============================================================
# Duoweilai Web · Windows 开发脚本
# ============================================================
# 用法（在 PowerShell 中）:
#   .\scripts\dev.ps1 install    # 安装依赖
#   .\scripts\dev.ps1 dev       # 启动开发服务器
#   .\scripts\dev.ps1 test      # 运行全部测试
#   .\scripts\dev.ps1 lint      # 代码风格检查
#   .\scripts\dev.ps1 format    # 自动格式化
#   .\scripts\dev.ps1 clean     # 清理临时文件
#   .\scripts\dev.ps1 help      # 显示所有命令
# ============================================================

param(
    [Parameter(Position=0)]
    [ValidateSet("install", "dev", "run", "test", "test-e2e", "test-auth", "test-api",
                 "test-logging", "lint", "format", "typecheck", "check",
                 "clean", "distclean", "db-reset", "help")]
    [string]$Command = "help",

    [int]$Port = 8080,
    [string]$Bind = "0.0.0.0",
    [string]$Db = "duoweilai.db",
    [string]$LogLevel = "INFO",
    [string]$LogFormat = "human"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $RepoRoot

$Venv = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$VenvPip = Join-Path $Venv "Scripts\pip.exe"

function Show-Help {
    @"
Duoweilai Web — Windows 开发入口

用法:
  .\scripts\dev.ps1 <command> [options]

命令:
  install       创建虚拟环境并安装依赖
  dev           启动开发服务器
  run           启动 gunicorn（生产模式，Linux/Mac/WSL）
  test          运行全部测试
  test-e2e      仅 e2e 测试
  test-auth     仅 auth 测试
  test-api      仅 api 测试
  test-logging  仅日志模块测试
  lint          ruff check
  format        ruff format
  typecheck     mypy
  check         lint + typecheck + test
  clean         清理临时文件
  distclean     清理一切（含虚拟环境）
  db-reset      删除本地数据库
  help          显示此帮助

选项:
  -Port <n>        端口（默认 8080）
  -Bind <ip>       绑定地址（默认 0.0.0.0）
  -Db <path>       数据库路径（默认 duoweilai.db）
  -LogLevel <lvl>  日志级别 DEBUG/INFO/WARNING/ERROR
  -LogFormat <fmt> human 或 json

示例:
  .\scripts\dev.ps1 dev -Port 9000 -LogLevel DEBUG
  .\scripts\dev.ps1 test -LogFormat json
"@
}

function Test-Venv {
    if (-not (Test-Path $VenvPython)) {
        Write-Host "! 虚拟环境不存在，请先运行: .\scripts\dev.ps1 install" -ForegroundColor Yellow
        exit 1
    }
}

switch ($Command) {
    "help" {
        Show-Help
    }

    "install" {
        Write-Host "==> 创建虚拟环境..." -ForegroundColor Cyan
        if (-not (Test-Path $Venv)) {
            python -m venv $Venv
        }
        & $VenvPip install --upgrade pip wheel setuptools | Out-Null
        Write-Host "==> 安装依赖..." -ForegroundColor Cyan
        & $VenvPip install -r requirements.txt
        if (Test-Path "requirements-dev.txt") {
            & $VenvPip install -r requirements-dev.txt
        }
        Write-Host "✓ 安装完成" -ForegroundColor Green
        Write-Host "  下一步: .\scripts\dev.ps1 dev" -ForegroundColor Cyan
    }

    "dev" {
        Test-Venv
        $env:DUOWEILAI_BIND = $Bind
        $env:DUOWEILAI_PORT = $Port
        $env:DUOWEILAI_DB = $Db
        $env:DUOWEILAI_LOG_LEVEL = $LogLevel
        $env:DUOWEILAI_LOG_FORMAT = $LogFormat
        Write-Host "==> 开发服务器: http://$Bind`:$Port (log=$LogFormat)" -ForegroundColor Cyan
        & $VenvPython server.py
    }

    "run" {
        Test-Venv
        Write-Host "==> 注意: gunicorn 在 Windows 上不支持，请使用 dev 或部署到 Linux" -ForegroundColor Yellow
        Write-Host "   推荐: .\scripts\dev.ps1 dev" -ForegroundColor Yellow
    }

    { @("test", "test-e2e", "test-auth", "test-api", "test-logging") -contains $_ } {
        Test-Venv
        $env:DUOWEILAI_LOG_FORMAT = $LogFormat
        $env:DUOWEILAI_LOG_LEVEL = if ($LogLevel -eq "INFO") { "WARNING" } else { $LogLevel }

        $tests = switch ($Command) {
            "test"        { @("tests\e2e_test.py", "tests\auth_test.py", "tests\api_test.py", "tests\test_logging.py") }
            "test-e2e"    { @("tests\e2e_test.py") }
            "test-auth"   { @("tests\auth_test.py") }
            "test-api"    { @("tests\api_test.py") }
            "test-logging"{ @("tests\test_logging.py") }
        }

        $failed = 0
        foreach ($t in $tests) {
            Write-Host "▶ $t" -ForegroundColor Cyan
            if (-not (& $VenvPython $t)) {
                Write-Host "✗ $t 失败" -ForegroundColor Red
                $failed = 1
            } else {
                Write-Host "✓ $t 通过" -ForegroundColor Green
            }
            Write-Host ""
        }
        exit $failed
    }

    "lint" {
        Test-Venv
        & $VenvPython -m ruff check app/ tests/ server.py
        & $VenvPython -m ruff format --check app/ tests/ server.py
    }

    "format" {
        Test-Venv
        & $VenvPython -m ruff format app/ tests/ server.py
        & $VenvPython -m ruff check --fix app/ tests/ server.py
    }

    "typecheck" {
        Test-Venv
        & $VenvPython -m mypy app/
    }

    "check" {
        & $ScriptDir\dev.ps1 lint
        & $ScriptDir\dev.ps1 typecheck
        & $ScriptDir\dev.ps1 test
    }

    "db-reset" {
        foreach ($suffix in @("", "-wal", "-shm")) {
            $f = "$Db$suffix"
            if (Test-Path $f) { Remove-Item $f -Force }
        }
        Write-Host "✓ 数据库已重置" -ForegroundColor Green
    }

    "clean" {
        Get-ChildItem -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force
        Get-ChildItem -Recurse -Directory -Filter ".pytest_cache" -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force
        Get-ChildItem -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
            Remove-Item -Force
        Get-ChildItem -Filter ".test-db-*" -ErrorAction SilentlyContinue | Remove-Item -Force -Recurse
        Remove-Item -Recurse -Force .ruff_cache, .mypy_cache, htmlcov -ErrorAction SilentlyContinue
        Write-Host "✓ 清理完成" -ForegroundColor Green
    }

    "distclean" {
        & $ScriptDir\dev.ps1 clean
        if (Test-Path $Venv) { Remove-Item $Venv -Recurse -Force }
        Write-Host "✓ 虚拟环境已删除" -ForegroundColor Green
    }
}
