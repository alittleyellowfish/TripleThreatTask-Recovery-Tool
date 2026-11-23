param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'

$buildDir = Join-Path $PSScriptRoot 'build'
$distDir = Join-Path $PSScriptRoot 'dist'
$nativeDir = Join-Path $PSScriptRoot 'src\native'
$profilePath = Join-Path $PSScriptRoot 'src\data\profile.json'
$uiPath = Join-Path $PSScriptRoot 'src\ui'
$version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION') -Raw).Trim()
$parsedVersion = [version]::Parse($version)
$fileVersion = "$($parsedVersion.Major), $($parsedVersion.Minor), $([Math]::Max(0, $parsedVersion.Build)), $([Math]::Max(0, $parsedVersion.Revision))"
$productName = '三面混沌任务恢复工具'
$artifactName = "${productName}-v$version"
$versionFile = Join-Path $buildDir 'windows-version.txt'

New-Item -ItemType Directory -Path $buildDir, $distDir -Force | Out-Null
$versionInfo = @"
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=($fileVersion), prodvers=($fileVersion),
        mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)
    ),
    kids=[
        StringFileInfo([StringTable('080404B0', [
            StringStruct('FileDescription', '$productName'),
            StringStruct('FileVersion', '$version'),
            StringStruct('OriginalFilename', '$artifactName.exe'),
            StringStruct('ProductName', '$productName'),
            StringStruct('ProductVersion', '$version')
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0804, 1200])])
    ]
)
"@
[IO.File]::WriteAllText($versionFile, $versionInfo, [Text.UTF8Encoding]::new($false))

& $Python -m PyInstaller --noconfirm --onefile --windowed --noupx `
    --name $artifactName `
    --icon (Join-Path $uiPath 'app-icon.ico') `
    --version-file $versionFile `
    --distpath $distDir `
    --workpath (Join-Path $buildDir 'pyinstaller') `
    --specpath $buildDir `
    --collect-data webview `
    --add-data "$(Join-Path $PSScriptRoot 'LICENSE');licenses" `
    --add-data "$(Join-Path $PSScriptRoot 'NOTICE');licenses" `
    --add-data "$(Join-Path $PSScriptRoot 'docs\third-party-notices.md');licenses" `
    --add-binary "$nativeDir\pbz_codec.dll;native" `
    --add-data "$nativeDir\*.json;native" `
    --add-data "$nativeDir\*.md;native" `
    --add-data "$nativeDir\*.txt;native" `
    --add-data "$profilePath;data" `
    --add-data "$uiPath;ui" `
    (Join-Path $PSScriptRoot 'src\app.py')

if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller build failed.'
}

Write-Output (Join-Path $distDir "$artifactName.exe")

