# PS5 at 192.168.137.2 shows ARP Incomplete — bind MAC from tethering clients + open firewall.
$log = Join-Path $PSScriptRoot '_fix_ps5_arp_incomplete.log'
function L($m) { $m | Tee-Object -FilePath $log -Append }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    '' | Set-Content $log -Force
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Get-Content $log
    exit
}
. (Join-Path $PSScriptRoot '_hotspot_2ghz_apply.ps1')
'' | Set-Content $log -Force
L "=== Fix ARP Incomplete $(Get-Date -Format o) ==="

$ap = Get-HotspotPrivateAdapter
if ($ap) {
    Set-NetConnectionProfile -InterfaceIndex $ap.ifIndex -NetworkCategory Private -EA SilentlyContinue
    L "Hotspot profile: Private"
}

# Allow all on hotspot subnet (Public profile was blocking PS5<->PC)
netsh advfirewall firewall delete rule name=ZubCut-Hotspot-Full-In 2>$null | Out-Null
netsh advfirewall firewall delete rule name=ZubCut-Hotspot-Full-Out 2>$null | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-Full-In dir=in action=allow remoteip=192.168.137.0/24 enable=yes profile=any | Out-Null
netsh advfirewall firewall add rule name=ZubCut-Hotspot-Full-Out dir=out action=allow remoteip=192.168.137.0/24 enable=yes profile=any | Out-Null
L 'Firewall: allow all 137.x in/out'

$ps5Ip = '192.168.137.2'
$mac = $null
$mgr = Get-TetheringManager
if ($mgr) {
  try {
    foreach ($c in $mgr.GetTetheringClients()) {
      $cm = ($c.MacAddress -as [string])
      $host = ($c.HostName -as [string])
      L "Tether client: $cm host=$host"
      if ($cm) { $mac = $cm -replace '-', ':' }
    }
  } catch { L "GetTetheringClients: $_" }
}

if (-not $mac) {
  L 'No MAC from tethering API — check neighbor after ping'
}

if ($mac) {
  $macDash = ($mac -replace ':', '-').ToUpper()
  L "Static ARP: $ps5Ip -> $macDash"
  netsh interface ip delete neighbors "Local Area Connection* 12" $ps5Ip 2>$null | Out-Null
  arp -d $ps5Ip 2>$null | Out-Null
  arp -s $ps5Ip $macDash 2>&1 | ForEach-Object { L $_ }
}

# Gratuitous ARP burst
$py = @"
import sys, subprocess, re
sys.path.insert(0, r'$(Join-Path (Split-Path $PSScriptRoot -Parent) 'src')')
from scapy.all import ARP, Ether, sendp
gw, ps5 = '192.168.137.1', '$ps5Ip'
mac = '$($mac -replace "'", "")'
out = subprocess.check_output('getmac /fo csv /nh /v', shell=True, text=True, errors='replace')
pc = 'E8:4E:06:AB:C4:28'
for line in out.splitlines():
    if '137' in line or 'Direct' in line or 'Wireless' in line:
        m = re.search(r'([0-9A-F]{2}-){5}[0-9A-F]{2}', line, re.I)
        if m: pc = m.group(0).replace('-',':').upper(); break
if mac:
    vm = mac.upper()
    for _ in range(8):
        sendp(Ether(dst=vm)/ARP(op=2,psrc=gw,hwsrc=pc,pdst=ps5,hwdst=vm), verbose=0)
        sendp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,psrc=gw,hwsrc=pc,pdst=gw,hwdst='ff:ff:ff:ff:ff:ff'), verbose=0)
print('sent', pc, '->', ps5, mac or 'no-mac')
"@
py -3 -c $py 2>&1 | ForEach-Object { L $_ }

Start-Sleep 2
$ping = Test-Connection $ps5Ip -Count 2 -Quiet -EA SilentlyContinue
L "Ping $ps5Ip : $ping"
Get-NetNeighbor -IPAddress $ps5Ip -EA SilentlyContinue | Format-List IPAddress,LinkLayerAddress,State | Out-String | ForEach-Object { L $_.TrimEnd() }
arp -a | Select-String '192\.168\.137\.2' | ForEach-Object { L $_.Line.Trim() }

if ($ping) {
  L 'SUCCESS: Layer-2 fixed. Internet should flow via existing ICS.'
} else {
  L 'Still no L2 — toggle hotspot OFF 15s ON with PS5 connected, then re-run this script.'
}
