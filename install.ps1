param(
    [string]$DataRoot = (Join-Path $env:APPDATA "MaiBotOneKeyDesktop")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

try {
    $sourceDir = $PSScriptRoot
    $requiredItems = @("_manifest.json", "plugin.py", "mai_beeper_adapter")

    foreach ($item in $requiredItems) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourceDir $item))) {
            throw "安裝包不完整，缺少：$item"
        }
    }

    if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
        throw "找不到 MaiBot OneKey 的資料資料夾。請先安裝並啟動一次 MaiBot OneKey。"
    }

    $instances = @(
        Get-ChildItem -LiteralPath $DataRoot -Directory |
            Where-Object {
                Test-Path -LiteralPath (Join-Path $_.FullName "modules\MaiBot\plugins") -PathType Container
            } |
            Sort-Object LastWriteTime -Descending
    )

    if ($instances.Count -eq 0) {
        throw "找不到 MaiBot 的 plugins 資料夾。請先啟動一次 MaiBot OneKey。"
    }

    $instance = $instances[0]
    $pluginsDir = Join-Path $instance.FullName "modules\MaiBot\plugins"
    $targetDir = Join-Path $pluginsDir "mai-beeper-adapter"

    $sourceResolved = [System.IO.Path]::GetFullPath($sourceDir).TrimEnd("\")
    $targetResolved = [System.IO.Path]::GetFullPath($targetDir).TrimEnd("\")
    if ($sourceResolved -eq $targetResolved) {
        Write-Host "Mai Beeper Adapter 已在正確位置，不需要重複安裝。" -ForegroundColor Green
        Write-Host "位置：$targetDir"
        exit 0
    }

    $existingConfig = Test-Path -LiteralPath (Join-Path $targetDir "config.toml")
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

    foreach ($file in @("_manifest.json", "plugin.py", "README.md", "LICENSE")) {
        $sourceFile = Join-Path $sourceDir $file
        if (Test-Path -LiteralPath $sourceFile -PathType Leaf) {
            Copy-Item -LiteralPath $sourceFile -Destination $targetDir -Force
        }
    }

    $moduleTarget = Join-Path $targetDir "mai_beeper_adapter"
    New-Item -ItemType Directory -Path $moduleTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $sourceDir "mai_beeper_adapter\*.py") -Destination $moduleTarget -Force

    $installedManifest = Get-Content -LiteralPath (Join-Path $targetDir "_manifest.json") -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($installedManifest.id -ne "mai-beeper.beeper-adapter") {
        throw "安裝後檢查失敗：插件 ID 不正確。"
    }

    Write-Host ""
    Write-Host "Mai Beeper Adapter $($installedManifest.version) 安裝成功！" -ForegroundColor Green
    Write-Host "位置：$targetDir"
    if ($instances.Count -gt 1) {
        Write-Host "偵測到多個 MaiBot，已安裝到最近使用的版本：$($instance.Name)" -ForegroundColor Yellow
    }
    if ($existingConfig) {
        Write-Host "原本的插件設定已保留。"
    }
    Write-Host "請重新開啟 MaiBot OneKey，再到「插件管理」查看。" -ForegroundColor Cyan
    exit 0
}
catch {
    Write-Host ""
    Write-Host "安裝失敗：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
