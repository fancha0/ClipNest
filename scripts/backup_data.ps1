# ClipNest 数据一键备份
# 用途：在“清空条目 / 折腾数据”之前，先把数据库安全地备份一份。
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\scripts\backup_data.ps1
#   （可选）指定备份目录：
#   powershell -ExecutionPolicy Bypass -File .\scripts\backup_data.ps1 -Destination "D:\ClipNestBackup"

param(
    [string]$Destination = ""
)

$ErrorActionPreference = "Stop"
$appData = $env:APPDATA

# 定位数据目录：与程序内部逻辑一致（优先使用含数据库的旧目录）
$dataDir = $null
foreach ($name in @("FluxClip", "CrossClipboard")) {
    $candidate = Join-Path $appData $name
    if (Test-Path -LiteralPath (Join-Path $candidate "clipboard.db")) {
        $dataDir = $candidate
        break
    }
}
if (-not $dataDir) {
    $dataDir = Join-Path $appData "ClipNest"
}

$db = Join-Path $dataDir "clipboard.db"
if (-not (Test-Path -LiteralPath $db)) {
    Write-Output "找不到数据库文件：$db"
    Write-Output "请先运行一次 ClipNest 生成数据后再试。"
    exit 1
}

# 运行中时 WAL 可能未落盘，建议先退出
$running = Get-Process -Name ClipNest -ErrorAction SilentlyContinue
if ($running) {
    Write-Output "[提示] 检测到 ClipNest 正在运行。为保证备份一致，建议先退出 ClipNest。"
    $answer = Read-Host "仍要继续备份吗？(y/N)"
    if ($answer -notin @("y", "Y")) {
        Write-Output "已取消。"
        exit 0
    }
}

if (-not $Destination) {
    $Destination = Join-Path $dataDir "backups"
}
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$target = Join-Path $Destination ("clipnest_backup_" + $stamp)
New-Item -ItemType Directory -Path $target -Force | Out-Null

$copied = @()
foreach ($suffix in @("", "-wal", "-shm")) {
    $src = "$db$suffix"
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination $target -Force
        $copied += (Split-Path $src -Leaf)
    }
}

Write-Output "备份完成：$target"
foreach ($name in $copied) {
    Write-Output ("  - " + $name)
}
Write-Output ""
Write-Output "还原方法：关闭 ClipNest 后，把备份目录里的文件复制回："
Write-Output "  $dataDir"
