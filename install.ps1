param(
    [string]$DataRoot = (Join-Path $env:APPDATA "MaiBotOneKeyDesktop"),
    [string]$InstanceId = "",
    [string]$InstallFolder = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
}

function Test-IsInsideDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Child,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $childPath = Get-NormalizedPath $Child
    $parentPath = Get-NormalizedPath $Parent
    $prefix = $parentPath + [System.IO.Path]::DirectorySeparatorChar
    return $childPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-Sha256Hash {
    param([Parameter(Mandatory = $true)][string]$Path)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "")
    }
    finally {
        $stream.Dispose()
        $sha256.Dispose()
    }
}

try {
    $sourceDir = Get-NormalizedPath $PSScriptRoot
    foreach ($required in @("_manifest.json", "plugin.py")) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourceDir $required) -PathType Leaf)) {
            throw "安裝包不完整，缺少：$required"
        }
    }

    $sourceManifest = Get-Content -LiteralPath (Join-Path $sourceDir "_manifest.json") -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $pluginId = [string]$sourceManifest.id
    $pluginVersion = [string]$sourceManifest.version
    if ([string]::IsNullOrWhiteSpace($pluginId) -or [string]::IsNullOrWhiteSpace($pluginVersion)) {
        throw "_manifest.json 缺少有效的 id 或 version。"
    }

    $dataRootPath = Get-NormalizedPath $DataRoot
    if (-not (Test-Path -LiteralPath $dataRootPath -PathType Container)) {
        throw "找不到 MaiBot OneKey 資料夾：$dataRootPath"
    }

    $instances = @(
        Get-ChildItem -LiteralPath $dataRootPath -Directory |
            Where-Object {
                Test-Path -LiteralPath (Join-Path $_.FullName "modules\MaiBot\plugins") -PathType Container
            } |
            Sort-Object LastWriteTime -Descending
    )
    if ($InstanceId) {
        $instances = @($instances | Where-Object { $_.Name -eq $InstanceId })
    }
    if ($instances.Count -eq 0) {
        throw "找不到符合條件的 MaiBot OneKey 實例。請先啟動一次 MaiBot OneKey。"
    }

    $instance = $instances[0]
    $pluginsDir = Get-NormalizedPath (Join-Path $instance.FullName "modules\MaiBot\plugins")
    $matchingTargets = @()
    foreach ($directory in @(Get-ChildItem -LiteralPath $pluginsDir -Directory)) {
        $candidateManifest = Join-Path $directory.FullName "_manifest.json"
        if (-not (Test-Path -LiteralPath $candidateManifest -PathType Leaf)) {
            continue
        }
        try {
            $candidate = Get-Content -LiteralPath $candidateManifest -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([string]$candidate.id -eq $pluginId) {
                $matchingTargets += $directory.FullName
            }
        }
        catch {
            continue
        }
    }
    if ($matchingTargets.Count -gt 1) {
        throw "找到多個相同插件 ID 的安裝資料夾，請先整理重複安裝：$pluginId"
    }

    if ($matchingTargets.Count -eq 1) {
        $targetDir = Get-NormalizedPath $matchingTargets[0]
    }
    else {
        $folderName = $InstallFolder.Trim()
        if (-not $folderName) {
            $folderName = ($pluginId -replace '[^A-Za-z0-9._-]', '-')
        }
        if (-not $folderName -or $folderName -in @(".", "..")) {
            throw "無法從插件 ID 建立安全的安裝資料夾名稱。"
        }
        $targetDir = Get-NormalizedPath (Join-Path $pluginsDir $folderName)
    }
    if (-not (Test-IsInsideDirectory -Child $targetDir -Parent $pluginsDir)) {
        throw "安裝目標不在 MaiBot plugins 資料夾內，已停止：$targetDir"
    }
    if ($sourceDir -eq $targetDir) {
        Write-Host "插件已位於正確位置，不需要重複安裝。" -ForegroundColor Green
        exit 0
    }

    $existingConfigPath = Join-Path $targetDir "config.toml"
    $preserveConfig = Test-Path -LiteralPath $existingConfigPath -PathType Leaf
    $existingConfigHash = if ($preserveConfig) {
        Get-Sha256Hash -Path $existingConfigPath
    }
    else {
        ""
    }

    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    $excludedRootFiles = @("install.cmd", "install.ps1")
    foreach ($item in @(Get-ChildItem -LiteralPath $sourceDir -Force)) {
        if ($item.Name -in $excludedRootFiles) {
            continue
        }
        if ($preserveConfig -and $item.Name -eq "config.toml") {
            continue
        }
        Copy-Item -LiteralPath $item.FullName -Destination $targetDir -Recurse -Force
    }

    $requirementsPath = Join-Path $sourceDir "requirements.txt"
    if (Test-Path -LiteralPath $requirementsPath -PathType Leaf) {
        $pythonPath = Join-Path $instance.FullName "python-env\python.exe"
        if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
            throw "插件需要額外套件，但找不到此 MaiBot OneKey 的 Python：$pythonPath"
        }
        & $pythonPath -m pip install --disable-pip-version-check -r $requirementsPath
        if ($LASTEXITCODE -ne 0) {
            throw "requirements.txt 安裝失敗（exit code $LASTEXITCODE）。"
        }
    }

    $installedManifestPath = Join-Path $targetDir "_manifest.json"
    $installedManifest = Get-Content -LiteralPath $installedManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$installedManifest.id -ne $pluginId -or [string]$installedManifest.version -ne $pluginVersion) {
        throw "安裝後 Manifest 檢查失敗。"
    }

    foreach ($sourceFile in @(Get-ChildItem -LiteralPath $sourceDir -File -Recurse -Force)) {
        $relativePath = $sourceFile.FullName.Substring($sourceDir.Length).TrimStart("\", "/")
        if ($relativePath -in $excludedRootFiles) {
            continue
        }
        if ($preserveConfig -and $relativePath -eq "config.toml") {
            continue
        }
        $installedFile = Join-Path $targetDir $relativePath
        if (-not (Test-Path -LiteralPath $installedFile -PathType Leaf)) {
            throw "安裝後缺少檔案：$relativePath"
        }
        $sourceHash = Get-Sha256Hash -Path $sourceFile.FullName
        $installedHash = Get-Sha256Hash -Path $installedFile
        if ($sourceHash -ne $installedHash) {
            throw "安裝後檔案內容不一致：$relativePath"
        }
    }
    if ($preserveConfig) {
        $newConfigHash = Get-Sha256Hash -Path $existingConfigPath
        if ($newConfigHash -ne $existingConfigHash) {
            throw "既有 config.toml 在更新時遭到變更。"
        }
    }

    Write-Host ""
    Write-Host "MaiBot 插件安裝成功：$pluginId $pluginVersion" -ForegroundColor Green
    Write-Host "位置：$targetDir"
    if ($instances.Count -gt 1 -and -not $InstanceId) {
        Write-Host "偵測到多個 MaiBot，已使用最近更新的實例：$($instance.Name)" -ForegroundColor Yellow
    }
    if ($preserveConfig) {
        Write-Host "原本的 config.toml 已保留。"
    }
    Write-Host "請重新開啟 MaiBot OneKey，並在插件管理確認版本。" -ForegroundColor Cyan
    exit 0
}
catch {
    Write-Host ""
    Write-Host "安裝失敗：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
