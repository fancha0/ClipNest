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
    [string]$PublicBaseUrl = "",
    [string]$InnoSetup = "C:\Users\lll\Tools\Inno Setup 7\ISCC.exe"
)

$ErrorActionPreference = "Stop"

# PowerShell 5.1 会把原生命令（git / scp / PyInstaller / ISCC）写到 stderr 的
# 正常进度输出当成 NativeCommandError，配合上面的 EAP=Stop 会直接中断发版。
# 凡是调用原生命令都走这个包装器，临时放开 EAP 后再按退出码判断成败。
function Invoke-NativeCommand {
    param([scriptblock]$Action)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Action
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonPath = Join-Path $root ".venv\Scripts\python.exe"
$tag = "v$Version"

Push-Location $root
try {
    Write-Output "==> 1/5 写入版本号 $Version"
    [System.IO.File]::WriteAllText(
        (Join-Path $root "clipboard_manager\version.py"),
        "APP_VERSION = `"$Version`"",
        (New-Object System.Text.UTF8Encoding($false)))

    Write-Output "==> 2/5 打包（先结束运行中的 ClipNest）"
    cmd /c "taskkill /F /IM ClipNest.exe >nul 2>&1"
    Start-Sleep -Seconds 2
    if ((Invoke-NativeCommand { & $pythonPath -m PyInstaller --noconfirm --clean ClipNest.spec }) -ne 0) {
        throw "PyInstaller build failed."
    }

    $exePath = Join-Path $root "dist\ClipNest\ClipNest.exe"
    if (-not (Test-Path -LiteralPath $exePath)) { throw "EXE not found: $exePath" }

    Write-Output "==> 3/5 压缩更新包（内容为 ClipNest 目录内文件，便于自动更新覆盖）"
    $zipPath = Join-Path $root "dist\ClipNest-Windows.zip"
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $root "dist\ClipNest\*") -DestinationPath $zipPath -Force
    $zipMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    $zipSha256 = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output "    更新包：$zipPath ($zipMb MB)"

    $setupPath = Join-Path $root "dist\ClipNest-Setup.exe"
    if (Test-Path -LiteralPath $InnoSetup) {
        Write-Output "==> 3b/5 编译安装包（Inno Setup）"
        if ((Invoke-NativeCommand { & $InnoSetup (Join-Path $root "installer\clipnest.iss") "/DMyAppVersion=$Version" | Out-Null }) -ne 0) {
            throw "Inno Setup 编译安装包失败"
        }
        $setupMb = [math]::Round((Get-Item $setupPath).Length / 1MB, 1)
        Write-Output "    安装包：$setupPath ($setupMb MB)"
    } else {
        Write-Output "    未找到 Inno Setup（$InnoSetup），跳过安装包编译"
        $setupPath = $null
    }

    Write-Output "==> 4/5 提交并推送 tag $tag"
    git add clipboard_manager/version.py
    if ((Invoke-NativeCommand { git commit -m "chore: release $tag" --allow-empty }) -ne 0) {
        throw "git commit 失败"
    }
    if ((Invoke-NativeCommand { git tag $tag }) -ne 0) {
        throw "git tag 失败（该 tag 是否已存在？）"
    }
    if ((Invoke-NativeCommand { git push origin HEAD }) -ne 0) {
        throw "git push 分支失败"
    }
    if ((Invoke-NativeCommand { git push origin $tag }) -ne 0) {
        throw "git push tag 失败"
    }

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
            sha256  = $zipSha256
        } | ConvertTo-Json
        [System.IO.File]::WriteAllText($manifestPath, $manifest, (New-Object System.Text.UTF8Encoding($false)))

        if ((Invoke-NativeCommand { ssh -p $SshPort $SshTarget "mkdir -p $RemoteDir" }) -ne 0) {
            throw "SSH 连接失败：$SshTarget"
        }
        if ((Invoke-NativeCommand { scp -P $SshPort $zipPath "${SshTarget}:${RemoteDir}/ClipNest-Windows.zip" }) -ne 0) {
            throw "上传更新包失败"
        }
        if ((Invoke-NativeCommand { scp -P $SshPort $manifestPath "${SshTarget}:${RemoteDir}/latest.json" }) -ne 0) {
            throw "上传更新清单失败"
        }
        if ($setupPath -and (Test-Path -LiteralPath $setupPath)) {
            if ((Invoke-NativeCommand { scp -P $SshPort $setupPath "${SshTarget}:${RemoteDir}/ClipNest-Setup.exe" }) -ne 0) {
                throw "上传安装包失败"
            }
            Write-Output "    安装包地址：$PublicBaseUrl/ClipNest-Setup.exe"
        }
        Write-Output "    已上传：${SshTarget}:${RemoteDir}"
        Write-Output "    清单地址：$PublicBaseUrl/latest.json"
    }

    if (-not $env:GITHUB_TOKEN) {
        if (-not $SshTarget) {
            Write-Output "    未设置 GITHUB_TOKEN，跳过自动创建 Release。"
            Write-Output "    手动步骤：打开 https://github.com/fancha0/ClipNest/releases/new"
            Write-Output "    选择 tag $tag，上传 $zipPath 即可。"
        }
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

    if ($setupPath -and (Test-Path -LiteralPath $setupPath)) {
        $setupUploadUri = "https://uploads.github.com/repos/fancha0/ClipNest/releases/$($release.id)/assets?name=ClipNest-Setup.exe"
        Invoke-RestMethod -Method Post -Uri $setupUploadUri `
            -Headers $headers `
            -ContentType "application/octet-stream" `
            -InFile $setupPath
        Write-Output "    安装包已上传。"
    }
}
finally {
    Pop-Location
}
