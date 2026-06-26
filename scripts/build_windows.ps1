param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonPath = $PythonExe
if (-not [System.IO.Path]::IsPathRooted($pythonPath)) {
    $pythonPath = Join-Path $root $pythonPath
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python executable not found: $pythonPath"
}

Push-Location $root
try {
    $appName = "ClipNest"
    Write-Output "Using Python: $pythonPath"

    $hasPyInstaller = (& $pythonPath -c "import importlib.util; print('1' if importlib.util.find_spec('PyInstaller') else '0')" | Select-Object -First 1).Trim() -eq "1"
    if (-not $hasPyInstaller) {
        & $pythonPath -m pip install pyinstaller
    }

    $distDir = Join-Path $root "dist"
    $buildDir = Join-Path $root "build"
    $appDir = Join-Path $distDir $appName
    $iconPath = Join-Path $root "assets\\clipnest.ico"
    $iconPngPath = Join-Path $root "assets\\clipnest.png"
    $normalizedIconPath = Join-Path $root "assets\\clipnest.build.ico"
    $iconSourcePath = $null
    $useCustomIcon = $false
    if (Test-Path -LiteralPath $iconPath) {
        $iconSourcePath = $iconPath
    }
    elseif (Test-Path -LiteralPath $iconPngPath) {
        $iconSourcePath = $iconPngPath
    }
    if ($iconSourcePath -and [System.IO.Path]::GetExtension($iconSourcePath).ToLowerInvariant() -eq ".ico") {
        $normalizedIconPath = $iconSourcePath
        $useCustomIcon = $true
        Write-Output "Using ICO directly: $normalizedIconPath"
    }
    elseif ($iconSourcePath) {
        & $pythonPath -c @'
import struct, sys
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter

src, dst = sys.argv[1], sys.argv[2]
img = QImage(src)
if img.isNull():
    sys.exit(2)

canvas = QImage(256, 256, QImage.Format.Format_ARGB32)
canvas.fill(0)
scaled = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
p = QPainter(canvas)
x = (256 - scaled.width()) // 2
y = (256 - scaled.height()) // 2
p.drawImage(x, y, scaled)
p.end()

png_bytes = QByteArray()
buf = QBuffer(png_bytes)
if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
    sys.exit(3)
ok = canvas.save(buf, 'PNG')
buf.close()
if not ok:
    sys.exit(4)

data = bytes(png_bytes)
icon_dir = struct.pack('<HHH', 0, 1, 1)
entry = struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(data), 22)
with open(dst, 'wb') as f:
    f.write(icon_dir + entry + data)
sys.exit(0)
'@ $iconSourcePath $normalizedIconPath
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $normalizedIconPath)) {
            $useCustomIcon = $true
            Write-Output "Custom icon prepared: $normalizedIconPath"
        }
        else {
            Write-Output "Icon normalize failed, fallback to default icon."
        }
    }
    else {
        Write-Output "No custom icon source found in assets, using default icon."
    }
    if (Test-Path -LiteralPath $buildDir) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
    if (Test-Path -LiteralPath $appDir) {
        Remove-Item -LiteralPath $appDir -Recurse -Force
    }

    $pyInstallerArgs = @(
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        $appName
    )
    if (Test-Path -LiteralPath $iconPath) {
        $pyInstallerArgs += @("--add-data", "$iconPath;assets")
    }
    if ($useCustomIcon) {
        $pyInstallerArgs += @("--icon", $normalizedIconPath)
        Write-Output "Using icon: $normalizedIconPath"
    }
    else {
        Write-Output "Using default app icon."
    }
    $pyInstallerArgs += "main.py"

    & $pythonPath -m PyInstaller @pyInstallerArgs

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    $exePath = Join-Path $appDir "$appName.exe"
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "EXE not found at expected path: $exePath"
    }

    $desktopDir = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopDir "$appName.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = (Split-Path -Path $exePath -Parent)
    $shortcut.IconLocation = $exePath
    $shortcut.Save()

    Write-Output "Build complete: $exePath"
    Write-Output "Desktop shortcut created: $shortcutPath"
}
finally {
    Pop-Location
}
