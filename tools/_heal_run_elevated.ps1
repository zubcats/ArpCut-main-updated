$log = "c:\Users\caden\OneDrive\Documents\GitHub\ArpCut-main-updated\tools\_heal_run_log.txt"
function L($m){ $m | Tee-Object -FilePath $log -Append }
'' | Set-Content $log
L "=== heal run $(Get-Date -Format o) ==="
Get-Process ZubCut -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
L "ZubCut stopped (if was running)"
cd "c:\Users\caden\OneDrive\Documents\GitHub\ArpCut-main-updated"
py -3 tools\clear_stale_zubcut_attacks.py 2>&1 | ForEach-Object { L $_ }
1..32 | ForEach-Object { ping -n 1 -w 200 "192.168.137.$_" | Out-Null }
Start-Sleep 1
L "--- ARP after ping ---"
arp -a | Select-String "192.168.137" | ForEach-Object { L $_.Line.Trim() }
py -3 -c "
import sys, subprocess, re, time
sys.path.insert(0, r'c:\Users\caden\OneDrive\Documents\GitHub\ArpCut-main-updated\src')
from scapy.all import ARP, Ether, sendp
gw='192.168.137.1'
out=subprocess.check_output('arp -a', text=True, errors='replace')
pat=re.compile(r'\b(192\.168\.137\.(\d+))\b\s+([0-9a-fA-F:-]{17})\b')
clients=[]
for line in out.splitlines():
    if 'incomplete' in line.lower(): continue
    m=pat.search(line)
    if not m: continue
    ip,last,mac=m.group(1),int(m.group(2)),m.group(3).replace('-',':').upper()
    if last<=1 or last>=255: continue
    clients.append((ip,mac))
mac='E8:4E:06:AB:C4:28'
print('Clients:', clients or 'none')
for ip,vic_mac in clients:
    u=Ether(dst=vic_mac)/ARP(op=2,psrc=gw,hwsrc=mac,pdst=ip,hwdst=vic_mac)
    g=Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,psrc=gw,hwsrc=mac,pdst=gw,hwdst='ff:ff:ff:ff:ff:ff')
    for _ in range(5): sendp([u,g], verbose=0)
    print('Healed', ip, vic_mac)
for _ in range(6):
    sendp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,psrc=gw,hwsrc=mac,pdst=gw,hwdst='ff:ff:ff:ff:ff:ff'), verbose=0)
print('Broadcast heal done')
" 2>&1 | ForEach-Object { L $_ }
L "=== done ==="
