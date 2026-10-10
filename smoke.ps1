# 慧眼识诈一键冒烟脚本（Windows PowerShell）
# 三连验证：health → 真实检测（含语义 Agent 降级/参与）→ 审核助手（RAG 检索 + 建议）
# 用法：.\smoke.ps1   （在项目根目录执行；后端需已启动，见 .\start.ps1）

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = "http://127.0.0.1:8000"
$Token = "demo-admin-token"
$Pass = 0; $Fail = 0

function Assert-Result([string]$Name, [scriptblock]$Block) {
    try {
        & $Block | Out-Null
        Write-Host "  [OK] $Name" -ForegroundColor Green
        $script:Pass++
    } catch {
        Write-Host "  [FAIL] $Name : $_" -ForegroundColor Red
        $script:Fail++
    }
}

Write-Host "== 慧眼识诈冒烟验证 ==" -ForegroundColor Cyan

Assert-Result "后端健康检查" {
    $health = Invoke-RestMethod -Uri "$Base/health" -TimeoutSec 10
    if ($health.status -ne "ok") { throw "health.status != ok" }
}

Assert-Result "真实检测链路（6 Agent 协同 + LangGraph）" {
    $payload = [ordered]@{
        transaction_id = "TX-SMOKE-$([DateTimeOffset]::Now.ToUnixTimeSeconds())"
        user_id = "U2002"
        amount = 368000
        channel = "APP"
        device_id = "DEV-2002"
        merchant_id = "MCH-NORMAL-001"
        location = "哈尔滨"
        night_operation = $true
        context_clues = @("用户申诉称是本人真实交易，已提供交易凭证与聊天记录截图")
    }
    $body = @{ transaction = $payload } | ConvertTo-Json -Depth 5
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $result = Invoke-RestMethod -Uri "$Base/api/v1/detect/transaction" -Method Post `
        -Headers @{ Authorization = "Bearer $Token" } -ContentType "application/json; charset=utf-8" `
        -Body $bytes -TimeoutSec 60
    $data = $result.data
    if ($data.agent_count -ne 6) { throw "agent_count=$($data.agent_count) != 6" }
    Write-Host "    决策=$($data.decision) 风险分=$($data.risk_score) Agent数=$($data.agent_count)"
    $semantic = $data.agent_results | Where-Object { $_.agent_id -eq "semantic-analysis" }
    if ($semantic -and -not $semantic.degraded) {
        Write-Host "    语义 Agent 真实 LLM 分析成功（$($semantic.evidence.Count) 条证据）"
    } else {
        Write-Host "    语义 Agent 降级剔除（LLM 不可用或无线索，链路正常）"
    }
}

Assert-Result "审核助手（RAG 案例检索）" {
    $result = Invoke-RestMethod -Uri "$Base/api/v1/review-assistant/cases/search?q=大额%20夜间%20申诉&top_k=3" `
        -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec 15
    if (@($result.data.items).Count -lt 1) { throw "RAG 检索无结果（需先 seed 已复核案例）" }
    Write-Host "    检索到 $($result.data.total) 个相似案例"
}

Assert-Result "审核助手（LangGraph 建议生成）" {
    $cases = Invoke-RestMethod -Uri "$Base/api/v1/cases?page_size=1" `
        -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec 15
    $caseId = $cases.data[0].case_id
    $body = @{ case_id = $caseId } | ConvertTo-Json
    $result = Invoke-RestMethod -Uri "$Base/api/v1/review-assistant/advice" -Method Post `
        -Headers @{ Authorization = "Bearer $Token" } -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 60
    $advice = $result.data.advice
    if (-not $advice.recommendation) { throw "建议为空" }
    Write-Host "    建议=$($advice.recommendation) 置信度=$($advice.confidence) 引用案例=$($advice.cited_cases -join ',')"
    if ($result.data.fallback) { Write-Host "    （LLM 建议回退规则模板，链路兜底正常）" }
}

Write-Host ""
Write-Host "== 结果：通过 $Pass 项，失败 $Fail 项 ==" -ForegroundColor Cyan
if ($Fail -gt 0) { exit 1 } else { Write-Host "== 冒烟全部通过，系统可正常演示 ==" -ForegroundColor Green }
