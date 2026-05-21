netsh advfirewall firewall show rule name=all verbose | Select-String -Pattern 'Rule Name:|zubcut|ZubCut|RemoteIP:|Action:' | ForEach-Object { $_.Line }
