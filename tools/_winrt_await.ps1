# WinRT IAsyncOperation await for Windows PowerShell 5.1 (AsTask generic via reflection).
function Initialize-WinRtAwaitHelpers {
    if ($script:ZubcutWinRtAwaitReady) { return $true }
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
        $script:ZubcutAsTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() |
            Where-Object {
                $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Length -eq 1
            } | Select-Object -First 1
        $script:ZubcutWinRtAwaitReady = ($null -ne $script:ZubcutAsTaskMethod)
        return $script:ZubcutWinRtAwaitReady
    } catch {
        return $false
    }
}

function Get-WinRtAsyncResultType([object]$asyncOp) {
    if ($null -eq $asyncOp) { return $null }
    foreach ($iface in $asyncOp.GetType().GetInterfaces()) {
        if ($iface.IsGenericType -and $iface.GetGenericTypeDefinition().FullName -eq 'Windows.Foundation.IAsyncOperation`1') {
            return $iface.GetGenericArguments()[0]
        }
    }
    return $null
}

function Complete-WinRtAsync([object]$asyncOp, [string]$label, [int]$timeoutSec) {
    if ($null -eq $asyncOp) { return $null }
    if (-not (Initialize-WinRtAwaitHelpers)) { return $null }
    $resultType = Get-WinRtAsyncResultType $asyncOp
    if ($null -eq $resultType) { return $null }
    try {
        $asTask = $script:ZubcutAsTaskMethod.MakeGenericMethod(@($resultType)).Invoke($null, @($asyncOp))
        if (-not $asTask.Wait($timeoutSec * 1000)) { return $null }
        if ($asTask.IsFaulted) { return $null }
        return $asTask.Result
    } catch {
        return $null
    }
}

function Wait-WinRtAsync([object]$asyncOp, [string]$label, [int]$timeoutSec) {
    return ($null -ne (Complete-WinRtAsync $asyncOp $label $timeoutSec))
}
