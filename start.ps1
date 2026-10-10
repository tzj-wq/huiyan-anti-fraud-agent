# 慧眼识诈一键启动脚本（Windows PowerShell）
# 并行启动后端(8000) + 前端(5173)，首次运行自动安装依赖。
# 用法：.\start.ps1   （在项目根目录执行）

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "[start] 未找到 .venv，正在创建虚拟环境并安装依赖..." -ForegroundColor Cyan
    Push-Location $Backend
    python -m venv .venv
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements.txt
    Pop-Location
}

if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Write-Host "[start] 安装前端依赖..." -ForegroundColor Cyan
    Push-Location $Frontend
    npm install
    Pop-Location
}

$backendLog = Join-Path $Root "backend.log"
$frontendLog = Join-Path $Root "frontend.log"

Write-Host "[start] 启动后端 http://127.0.0.1:8000 ..." -ForegroundColor Green
Start-Process -FilePath $Python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $Backend -RedirectStandardOutput $backendLog -RedirectStandardError (Join-Path $Root "backend.err.log") -WindowStyle Hidden

Write-Host "[start] 启动前端 http://127.0.0.1:5173 ..." -ForegroundColor Green
Start-Process -FilePath "npm" -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173" -WorkingDirectory $Frontend -RedirectStandardOutput $frontendLog -RedirectStandardError (Join-Path $Root "frontend.err.log") -WindowStyle Hidden

Write-Host ""
Write-Host "[start] 等待后端就绪（约 5 秒）..." -ForegroundColor Cyan
Start-Sleep -Seconds 5
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5
    Write-Host "[start] 后端就绪: $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Host "[start] 后端暂未就绪，请稍后运行 .\smoke.ps1 验证；日志见 backend.log / backend.err.log" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  管理端: http://127.0.0.1:5173/manager" -ForegroundColor White
Write-Host "  用户端: http://127.0.0.1:5173/client" -ForegroundColor White
Write-Host "  后端API: http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host ""
Write-Host "[start] 全部完成。运行 .\smoke.ps1 可做一键冒烟验证。" -ForegroundColor Green
