# 邮备无患 · 一键部署（国内网络优化 · 幂等可重跑）
# WorkBuddy 安装技能后直接调用本脚本即可完成部署
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ''
Write-Host '  == 邮备无患 · 一键部署 =='

# 1) Node.js：没有就自动装
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  if (Test-Path 'C:\Program Files\nodejs\node.exe') {
    $env:Path = 'C:\Program Files\nodejs;' + $env:Path
  } else {
    Write-Host '  正在自动安装 Node.js（约 1 分钟）...'
    winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements | Out-Null
    if (Test-Path 'C:\Program Files\nodejs\node.exe') { $env:Path = 'C:\Program Files\nodejs;' + $env:Path }
  }
}
node --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host '  Node.js 安装失败：请手动去 https://nodejs.org 安装后重跑本脚本'
  exit 1
}
Write-Host '  [1/3] Node.js 就绪'

# 2) npm 国内镜像（下载提速、防超时）
npm config set registry https://registry.npmmirror.com | Out-Null
Write-Host '  [2/3] npm 已切国内镜像'

# 3) 学号密码：只问一次，只存本机
$cfg = Join-Path $PSScriptRoot 'config.json'
if (-not (Test-Path $cfg)) {
  Write-Host ''
  $sno = Read-Host '  学号'
  $pwd = Read-Host '  教务密码（输完按回车）'
  if ($sno -and $pwd) {
    @{账号=@{学号=$sno;密码=$pwd};教学云=@{密码=''}} | ConvertTo-Json -Depth 3 | Out-File -Encoding utf8 $cfg
    Write-Host '  已保存（只存在这台电脑上）'
  } else {
    Write-Host '  学号密码没填全，请重跑'
    exit 1
  }
} else {
  Write-Host '  [3/3] 学号密码已配置（跳过询问）'
}

# 4) 验证抓取（有 python 才做；没有也不阻塞）
if (Get-Command python -ErrorAction SilentlyContinue) {
  Write-Host '  顺手抓一次教学云作业，验证密码对不对...'
  python (Join-Path $PSScriptRoot 'fetch_undone.py')
} else {
  Write-Host '  （本机没装 python，跳过作业预检；问答功能由部署助手代为执行）'
}

# 5) 启动 DeepSeek Harness（首次会联网下载，网页自动打开）
Write-Host ''
Write-Host '  启动服务（首次下载要几分钟）...'
Start-Process 'http://127.0.0.1:3080'
npx -y @deepseek-ai/dsh web