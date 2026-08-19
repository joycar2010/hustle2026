$ErrorActionPreference = 'Stop'

$entries = foreach ($path in @('D:\QHCELL\pool\s1', 'D:\QHCELL\pool\s3')) {
    if (Test-Path -LiteralPath $path) {
        $directory = Get-Item -LiteralPath $path
        $children = foreach ($child in Get-ChildItem -LiteralPath $directory.FullName -Force) {
            [ordered]@{
                name = $child.Name
                full_name = $child.FullName
                link_type = $child.LinkType
                target = @($child.Target)
                length = $child.Length
            }
        }
        [ordered]@{
            directory = $directory.FullName
            children = @($children)
        }
    }
}

$configs = foreach ($path in @(
    'D:\QHCELL\pool\s1\inst\.env',
    'D:\QHCELL\pool\s3\inst\.env'
)) {
    if (Test-Path -LiteralPath $path) {
        $file = Get-Item -LiteralPath $path
        $safeLines = Get-Content -LiteralPath $file.FullName | Where-Object {
            $_ -match '^(SERVICE_PORT|INSTANCE_NAME|APP_DIR|WORKING_DIR|PYTHON|CELL_ID|ACCOUNT|LOGIN|PLATFORM)='
        }
        if ($safeLines) {
            [ordered]@{ path = $file.FullName; lines = @($safeLines | ForEach-Object { [string]$_ }) }
        }
    }
}

$runtimeFiles = foreach ($path in @(
    'D:\QHCELL\pool\s1\inst\app\main.py',
    'D:\QHCELL\pool\s3\inst\app\main.py'
)) {
    if (Test-Path -LiteralPath $path) {
        $file = Get-Item -LiteralPath $path
        [ordered]@{
            path = $file.FullName
            length = $file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        }
    }
}

[ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    entries = @($entries)
    configs = @($configs)
    runtime_files = @($runtimeFiles)
} | ConvertTo-Json -Depth 10 -Compress
