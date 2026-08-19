$ErrorActionPreference = 'Stop'

$allProcesses = Get-CimInstance Win32_Process
$processes = foreach ($processId in 2428, 2628) {
    $process = $allProcesses | Where-Object ProcessId -eq $processId
    $parent = $allProcesses | Where-Object ProcessId -eq $process.ParentProcessId
    [ordered]@{
        pid = $process.ProcessId
        parent_pid = $process.ParentProcessId
        parent_name = $parent.Name
        parent_command_line = $parent.CommandLine
        command_line = $process.CommandLine
    }
}

$instances = foreach ($directory in Get-ChildItem -LiteralPath 'D:\QHMT5\instances' -Directory) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $directory.FullName '.env')) {
        if ($line -match '^(SERVICE_PORT|INSTANCE_NAME|MT5_PATH|RELEASE_DIR)=(.*)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }
    [ordered]@{
        directory = $directory.FullName
        service_port = $values.SERVICE_PORT
        instance_name = $values.INSTANCE_NAME
        mt5_path = $values.MT5_PATH
        release_dir = $values.RELEASE_DIR
        app_target = (Get-Item -LiteralPath (Join-Path $directory.FullName 'app')).Target
    }
}

$sourceFiles = foreach ($root in @(
    'D:\QHMT5\runtime\releases\v1\ic',
    'D:\QHMT5\runtime\releases\v1\bybit'
)) {
    if (Test-Path -LiteralPath $root) {
        Get-ChildItem -LiteralPath $root -File -Recurse -Depth 3 |
            Where-Object { $_.Extension -in @('.py', '.ps1', '.json', '.ini', '.env', '.txt') } |
            Select-Object FullName, Length, LastWriteTimeUtc, @{
                Name='SHA256'; Expression={ (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
            }
    }
}

[ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    processes = @($processes)
    instances = @($instances)
    source_files = @($sourceFiles)
} | ConvertTo-Json -Depth 8 -Compress
