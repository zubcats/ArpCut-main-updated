$ErrorActionPreference = 'Continue'
Write-Host 'UDP 67:'
Get-NetUDPEndpoint -LocalPort 67 -EA SilentlyContinue | Format-Table LocalAddress,LocalPort,OwningProcess -AutoSize
Write-Host 'Hotspot adapter:'
Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Direct|Hosted' -or $_.Name -match 'Local Area Connection' } | Format-Table Name,Status,ifIndex -AutoSize
Write-Host 'IPv4:'
Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -match '^192\.168\.(137|1)\.' } | Format-Table IPAddress,InterfaceIndex -AutoSize
Write-Host 'Firewall ICS/DHCP rules:'
netsh advfirewall firewall show rule name=all dir=in | Select-String -Pattern 'DHCP|ICS|137|Shared' | Select-Object -First 20
Write-Host 'SharedAccess params:'
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters' -EA SilentlyContinue | Select-Object ScopeAddress, EnableReboot, *
