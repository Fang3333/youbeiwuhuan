# 邮备无患 · 一键部署（国内网络优化 · 幂等可重跑）
# WorkBuddy 安装技能后直接调用本脚本即可完成部署
$ErrorActionPreference = 'Continue'

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

# 3) 学号密码：只问一次，只存本机（存技能根目录，和抓取脚本路径对齐）
$skillRoot = Split-Path $PSScriptRoot -Parent
$cfg = Join-Path $skillRoot 'config.json'
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
  Write-Host '  [3/5] 学号密码已配置（跳过询问）'
}

# 4) 验证抓取（有 python 才做；没有也不阻塞）
if (Get-Command python -ErrorAction SilentlyContinue) {
  Write-Host '  顺手抓一次教学云作业，验证密码对不对...'
  python (Join-Path $PSScriptRoot 'fetch_undone.py')
} else {
  Write-Host '  （本机没装 python，跳过作业预检；问答功能由部署助手代为执行）'
}

# 5) 把本技能装进 DeepSeek Harness 的技能目录（幂等）
$dshSkills = Join-Path $env:USERPROFILE '.dsh\skills\youbeiwuhuan'
New-Item -ItemType Directory -Force -Path $dshSkills | Out-Null
Copy-Item (Join-Path $skillRoot 'SKILL.md') $dshSkills -Force
Copy-Item (Join-Path $skillRoot 'scripts') (Join-Path $dshSkills 'scripts') -Recurse -Force
Copy-Item (Join-Path $skillRoot 'assets') (Join-Path $dshSkills 'assets') -Recurse -Force
if (Test-Path $cfg) { Copy-Item $cfg $dshSkills -Force }
Write-Host '  [4/5] 技能已装进小管家'

# 6) 模型接入：二选一（API key 快稳花钱 / 免费网页版慢但不要钱）
Write-Host ''
Write-Host '  [5/6] 模型怎么接？'
Write-Host '    [1] API key —— 快、稳、花点小钱（推荐，几块钱用很久）'
Write-Host '    [2] 免费网页版 —— 不要钱，但慢（延迟高）'
$modelChoice = Read-Host '  输入 1 或 2（直接回车默认选 1）'
if (-not $modelChoice) { $modelChoice = '1' }

if ($modelChoice -eq '1') {
  Write-Host ''
  Write-Host '  你选了 API key。请按下面操作（key 是付费凭证，自己填、别发给别人）：'
  Write-Host '    1) 浏览器打开 https://platform.deepseek.com ，手机号注册/登录'
  Write-Host '    2) 左侧「API Keys」→「创建 API Key」→ 复制 sk- 开头的那串'
  Write-Host '    3) 稍后 dsh 网页打开后：设置 → 模型 → DeepSeek → 粘贴 key 保存'
  Write-Host '    4) 模型选 deepseek-flash'
  Write-Host '    （新用户通常有免费额度，不够再充值，最低 10 元）'
} else {
  Write-Host '  你选了免费网页版（慢，但不要钱）。正在装插件...'
  if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Host '      正在装 pnpm ...'
    npm install -g pnpm | Out-Null
  }
  git config --global 'url."git@github.com:".insteadOf' 'https://github.com/' | Out-Null
  $profYaml = Join-Path $env:USERPROFILE '.dsh\profiles\web\pnpm-workspace.yaml'
  New-Item -ItemType Directory -Force -Path (Split-Path $profYaml) | Out-Null
  Set-Content -Path $profYaml -Encoding UTF8 -Value @(
    'packages:',
    '  - .',
    'nodeLinker: hoisted',
    'allowBuilds:',
    '  dsh-deepseek-web-login@https://codeload.github.com/cv-superding/dsh-deepseek-web-login/tar.gz/ece332e68bd74070263c30021e9878e422af6a8a: true'
  )
  Write-Host '      正在装模型插件（首次要下载几分钟）...'
  npx -y @deepseek-ai/dsh plugin --profile web add github:cv-superding/dsh-deepseek-web-login 2>&1 | Out-Null
  Write-Host '      模型插件已就绪'
}

# 7) 查局域网 IP，启动服务并开放给手机
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
  $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and
  $_.InterfaceAlias -notmatch 'VPN|Tailscale|Radmin|Loopback|vEthernet|VirtualBox|VMware|WSL'
} | Select-Object -First 1).IPAddress
Write-Host ''
Write-Host '  [6/6] 启动服务（首次下载要几分钟，稍后会自动打开网页）...'
if ($ip) {
  Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoExit','-Command',"npx -y @deepseek-ai/dsh web --host $ip"
  Write-Host "  局域网地址（手机同 Wi-Fi 用）：http://${ip}:3080/"
} else {
  Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoExit','-Command','npx -y @deepseek-ai/dsh web'
  Write-Host '  未检测到局域网 IP，先用 http://127.0.0.1:3080'
}
Write-Host '  稍后浏览器自动打开：首次需登录你的 DeepSeek 账号（网页版）即可开始用。'
Write-Host '  手机连接步骤见 assets/手机端说明.txt'
Write-Host ''
Write-Host '  完成！'