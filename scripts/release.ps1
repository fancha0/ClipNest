param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Notes = "",
    # 自有服务器上传（推荐，国内用户直连）：
    #   -SshTarget root@fn.lshiya.top -SshPort 50022 -PublicBaseUrl https://fn.lshiya.top:18443/clipnest
    # 不填则回退到 GitHub Release 流程。
    [string]$SshTarget = "",
    [int]$SshPort = 22,
    [string]$RemoteDir = "/www/wwwroot/clipnest/clipnest",
    [string]$PublicBaseUrl = ""
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonPath = Join-Path $root ".venv\Scripts\python.exe"
$tag = "v$Version"

Push-Location $root
try {
    Write-Output "==> 1/5 写入版本号 $Version"
    Set-Content -Path (Join-Path $root "clipboard_manager\version.py") -Value "APP_VERSION = `"$Version`"" -Encoding UTF8

    Write-Output "==> 2/5 打包（先结束运行中的 ClipNest）"
    taskkill /F /IM ClipNest.exe 2>$null | Out-Null
    Start-Sleep -Seconds 2
    & $pythonPath -m PyInstaller --noconfirm ClipNest.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $exePath = Join-Path $root "dist\ClipNest\ClipNest.exe"
    if (-not (Test-Path -LiteralPath $exePath)) { throw "EXE not found: $exePath" }

    Write-Output "==> 3/5 压缩更新包（内容为 ClipNest 目录内文件，便于自动更新覆盖）"
    $zipPath = Join-Path $root "dist\ClipNest-Windows.zip"
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $root "dist\ClipNest\*") -DestinationPath $zipPath -Force
    $zipMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Output "    更新包：$zipPath ($zipMb MB)"

    Write-Output "==> 4/5 提交并推送 tag $tag"
    git add clipboard_manager/version.py
    git commit -m "chore: release $tag" --allow-empty
    git tag $tag
    git push origin HEAD
    git push origin $tag

    Write-Output "==> 5/5 发布更新"
    $releaseBody = if ($Notes) { $Notes } else { "Release $tag" }

    if ($SshTarget) {
        if (-not $PublicBaseUrl) {
            throw "使用 -SshTarget 时必须同时提供 -PublicBaseUrl（用户可访问的下载基础地址，如 https://example.com/clipnest）。"
        }
        $manifestPath = Join-Path $root "dist\latest.json"
        $manifest = @{
            version = $Version
            notes   = $releaseBody
            url     = "$PublicBaseUrl/ClipNest-Windows.zip"
            size    = (Get-Item $zipPath).Length
        } | ConvertTo-Json
        Set-Content -Path $manifestPath -Value $manifest -Encoding UTF8

        ssh -p $SshPort $SshTarget "mkdir -p $RemoteDir"
        if ($LASTEXITCODE -ne 0) { throw "SSH 连接失败：$SshTarget" }
        scp -P $SshPort $zipPath "${SshTarget}:${RemoteDir}/ClipNest-Windows.zip"
        if ($LASTEXITCODE -ne 0) { throw "上传更新包失败" }
        scp -P $SshPort $manifestPath "${SshTarget}:${RemoteDir}/latest.json"
        if ($LASTEXITCODE -ne 0) { throw "上传更新清单失败" }
        Write-Output "    已上传：${SshTarget}:${RemoteDir}"
        Write-Output "    清单地址：$PublicBaseUrl/latest.json"
        Write-Output "    记得把 update_service.py 里的 UPDATE_MANIFEST_URL 设为该地址后重新打包分发。"
        return
    }

    if (-not $env:GITHUB_TOKEN) {
        Write-Output "    未设置 GITHUB_TOKEN，跳过自动创建 Release。"
        Write-Output "    手动步骤：打开 https://github.com/fancha0/ClipNest/releases/new"
        Write-Output "    选择 tag $tag，上传 $zipPath 即可。"
        return
    }

    $headers = @{
        Authorization = "Bearer $env:GITHUB_TOKEN"
        Accept        = "application/vnd.github+json"
        "User-Agent"  = "ClipNest-Release"
    }
    $release = Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/fancha0/ClipNest/releases" `
        -Headers $headers `
        -ContentType "application/json" `
        -Body (@{ tag_name = $tag; name = $tag; body = $releaseBody } | ConvertTo-Json)
    Write-Output "    Release 已创建：$($release.html_url)"

    $uploadUri = "https://uploads.github.com/repos/fancha0/ClipNest/releases/$($release.id)/assets?name=ClipNest-Windows.zip"
    Invoke-RestMethod -Method Post -Uri $uploadUri `
        -Headers $headers `
        -ContentType "application/zip" `
        -InFile $zipPath
    Write-Output "    更新包已上传，应用内“检查更新”即可获取。"
}
finally {
    Pop-Location
}
