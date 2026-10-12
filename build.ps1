$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败' }
}
& $runtime -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw '安装构建依赖失败' }
& $runtime -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw '测试失败，取消打包' }
& $runtime tools\icon_board.py
if ($LASTEXITCODE -ne 0) { throw '图标预览生成失败' }
& $runtime tools\preview_tray_clock.py
if ($LASTEXITCODE -ne 0) { throw '托盘时长预览生成失败' }
& $runtime tools\preview_taskbar_clock.py
if ($LASTEXITCODE -ne 0) { throw '加宽时间条预览生成失败' }
& $runtime tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw '图标导出或校验失败' }
$appVersion = & $runtime -c "from timelight import __version__; print(__version__)"
$distributionPath = Join-Path 'dist' $appVersion
$bundlePath = Join-Path $distributionPath 'Shiguang'
$savedBuildPath = $env:PATH
try {
    # A development host may have Poppler/ICU DLLs on PATH. Qt on Windows uses
    # the operating system ICU; never collect unrelated tools' DLLs.
    $pythonBase = & $runtime -c "import sys; print(sys.base_prefix)"
    $env:PATH = "$(Split-Path -Parent $runtime);$pythonBase;$env:SystemRoot\System32;$env:SystemRoot"
    & $runtime -m PyInstaller --clean --noconfirm --windowed --onedir --distpath $distributionPath --name Shiguang --icon assets\app.ico --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtWebEngineCore main.py
    if ($LASTEXITCODE -ne 0) { throw '打包失败' }
} finally {
    $env:PATH = $savedBuildPath
}
Copy-Item -LiteralPath README.md -Destination (Join-Path $bundlePath '使用说明.md') -Force
Copy-Item -LiteralPath THIRD_PARTY_NOTICES.md -Destination (Join-Path $bundlePath 'THIRD_PARTY_NOTICES.md') -Force
if (Test-Path -LiteralPath licenses) {
    $absoluteBundle = (Resolve-Path -LiteralPath $bundlePath).Path
    $runtimeFiles = @(Get-ChildItem -LiteralPath (Join-Path $absoluteBundle '_internal') -Recurse -File |
        Where-Object { $_.Extension -in '.dll','.pyd' } |
        ForEach-Object { $_.FullName.Substring($absoluteBundle.Length + 1).Replace('\','/') } |
        Sort-Object)
    $inventory = @("Windows x64 onedir build $appVersion, inventoried $(Get-Date -Format 'yyyy-MM-dd') after clean-PATH build.", '') + $runtimeFiles
    Set-Content -LiteralPath 'licenses\bundled-runtime-files.txt' -Value $inventory -Encoding utf8
    Copy-Item -LiteralPath licenses -Destination (Join-Path $bundlePath 'licenses') -Recurse -Force
}
Write-Output "已生成 $bundlePath\Shiguang.exe"
