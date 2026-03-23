"""Core Mobile IP objects."""

import ipaddress
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class NodeState(Enum):
    HOME = "home"
    FOREIGN = "foreign"
    HANDOFF = "handoff"


@dataclass
class Packet:
    """Simple packet model."""

    packet_id: int
    src_ip: str
    dst_ip: str
    payload: str
    timestamp: float = field(default_factory=time.time)
    size: int = 64
    ttl: int = 64

    def __repr__(self):
        return f"Packet(id={self.packet_id}, {self.src_ip} -> {self.dst_ip})"


@dataclass
class BindingCacheEntry:
    """HA binding entry."""

    home_address: str
    care_of_address: str
    fa_address: str
    lifetime: float
    registered_at: float = field(default_factory=time.time)

    def is_valid(self) -> bool:
        return (time.time() - self.registered_at) < self.lifetime


class HomeAgent:
    """Tracks bindings and tunnels packets for roaming nodes."""

    def __init__(self, address: str, network: str):
        self.address = address
        self.network = network
        self.home_network = ipaddress.ip_network(network, strict=False)
        self.binding_cache: Dict[str, BindingCacheEntry] = {}
        self.tunneled_packets: List[Packet] = []
        self.lock = threading.Lock()
        logger.info(f"[HA] Home Agent initialized at {self.address} on network {self.network}")

    def _is_home_network_address(self, ip_address_text: str) -> bool:
        """Check whether an IP belongs to the home network."""
        try:
            return ipaddress.ip_address(ip_address_text) in self.home_network
        except ValueError:
            return False

    def register(
        self,
        home_address: str,
        care_of_address: str,
        fa_address: str,
        lifetime: float = 300.0,
    ):
        """Store or refresh an MN binding."""
        with self.lock:
            self.binding_cache[home_address] = BindingCacheEntry(
                home_address=home_address,
                care_of_address=care_of_address,
                fa_address=fa_address,
                lifetime=lifetime,
            )
        logger.info(f"[HA] Registered MN {home_address} -> CoA {care_of_address} via FA {fa_address}")
        return True

    def deregister(self, home_address: str):
        """Remove an MN binding."""
        with self.lock:
            if home_address in self.binding_cache:
                del self.binding_cache[home_address]
        logger.info(f"[HA] Deregistered MN {home_address} (returned home)")

    def intercept_and_tunnel(self, packet: Packet) -> Optional[Packet]:
        """Tunnel packets for MNs away from home."""
        dst = packet.dst_ip
        with self.lock:
            entry = self.binding_cache.get(dst)

        if entry and not entry.is_valid():
            with self.lock:
                current_entry = self.binding_cache.get(dst)
                if current_entry is entry:
                    self.binding_cache.pop(dst, None)
            entry = None

        if entry:
            tunneled = Packet(
                packet_id=packet.packet_id,
                src_ip=self.address,
                dst_ip=entry.care_of_address,
                payload=f"[TUNNELED:{packet.src_ip}->{packet.dst_ip}] {packet.payload}",
                size=packet.size + 20,
            )
            self.tunneled_packets.append(tunneled)
            logger.info(f"[HA] Tunneling {packet} -> {entry.care_of_address}")
            return tunneled

        if self._is_home_network_address(dst):
            return packet
        return None

    def get_binding(self, home_address: str) -> Optional[BindingCacheEntry]:
        with self.lock:
            return self.binding_cache.get(home_address)

    def status(self) -> Dict:
        with self.lock:
            return {
                "address": self.address,
                "network": self.network,
                "registered_nodes": len(self.binding_cache),
                "bindings": {k: v.care_of_address for k, v in self.binding_cache.items()},
                "packets_tunneled": len(self.tunneled_packets),
            }


class ForeignAgent:
    """Handles visiting MNs and tunneled traffic."""

    def __init__(self, address: str, network: str, network_id: int):
        self.address = address
        self.network = network
        self.network_id = network_id
        self.visited_nodes: Dict[str, float] = {}
        self.received_packets: List[Packet] = []
        self.lock = threading.Lock()
        logger.info(f"[FA-{network_id}] Foreign Agent initialized at {self.address} on network {self.network}")

    def advertise(self) -> Dict:
        """Return a simple FA advertisement."""
        return {
            "fa_address": self.address,
            "network": self.network,
            "network_id": self.network_id,
            "timestamp": time.time(),
        }

    def register_visitor(self, mn_home_address: str, ha: HomeAgent, lifetime: float = 300.0) -> bool:
        """Register a visiting MN through the HA."""
        success = ha.register(
            home_address=mn_home_address,
            care_of_address=self.address,
            fa_address=self.address,
            lifetime=lifetime,
        )
        if success:
            with self.lock:
                self.visited_nodes[mn_home_address] = time.time()
            logger.info(f"[FA-{self.network_id}] MN {mn_home_address} registered via this FA")
        return success

    def deregister_visitor(self, mn_home_address: str):
        with self.lock:
            self.visited_nodes.pop(mn_home_address, None)
        logger.info(f"[FA-{self.network_id}] MN {mn_home_address} left this network")

    def serves_mobile_node(self, mn_home_address: str) -> bool:
        with self.lock:
            return mn_home_address in self.visited_nodes

    def decapsulate_and_deliver(self, tunneled_packet: Packet, mn) -> bool:
        """Deliver a tunneled packet to the MN."""
        with self.lock:
            if mn.home_address not in self.visited_nodes:
                return False
        self.received_packets.append(tunneled_packet)
        mn.receive_packet(tunneled_packet)
        logger.info(f"[FA-{self.network_id}] Decapsulated and delivered {tunneled_packet} to MN")
        return True

    def status(self) -> Dict:
        with self.lock:
            return {
                "address": self.address,
                "network": self.network,
                "network_id": self.network_id,
                "visiting_nodes": list(self.visited_nodes.keys()),
                "packets_received": len(self.received_packets),
            }


class MobileNode:
    """Tracks the MN attachment state."""

    def __init__(self, home_address: str, ha: HomeAgent):
        self.home_address = home_address
        self.ha = ha
        self.current_fa: Optional[ForeignAgent] = None
        self.state = NodeState.HOME
        self.sent_packets: List[Packet] = []
        self.received_packets: List[Packet] = []
        self.packet_counter = 0
        self.handoff_count = 0
        self.lock = threading.Lock()
        logger.info(f"[MN] Mobile Node initialized: {self.home_address}")

    def detect_movement(self, new_fa: ForeignAgent) -> bool:
        """Return True when the FA changed."""
        if self.current_fa is None:
            return True
        return self.current_fa.network_id != new_fa.network_id

    def perform_handoff(self, new_fa: ForeignAgent, signaling_delay_ms: float = 0.0):
        """Attach to a new FA and update state."""
        if not self.detect_movement(new_fa):
            logger.info(f"[MN] Movement ignored; already attached to FA-{new_fa.network_id}")
            return 0.0

        with self.lock:
            old_fa = self.current_fa
            self.state = NodeState.HANDOFF

        logger.info("[MN] --- HANDOFF INITIATED ---")
        logger.info(
            f"[MN] Moving from {'Home' if old_fa is None else f'FA-{old_fa.network_id}'} "
            f"-> FA-{new_fa.network_id}"
        )

        handoff_start = time.time()

        if signaling_delay_ms > 0:
            time.sleep(signaling_delay_ms / 1000.0)

        new_fa.register_visitor(self.home_address, self.ha)

        if old_fa and old_fa.network_id != new_fa.network_id:
            old_fa.deregister_visitor(self.home_address)

        handoff_latency = (time.time() - handoff_start) * 1000

        with self.lock:
            self.current_fa = new_fa
            self.state = NodeState.FOREIGN
            self.handoff_count += 1

        logger.info(f"[MN] Handoff complete. Latency: {handoff_latency:.2f} ms")
        return handoff_latency

    def return_home(self):
        """Return to the home network."""
        with self.lock:
            old_fa = self.current_fa

        if old_fa:
            old_fa.deregister_visitor(self.home_address)
        self.ha.deregister(self.home_address)

        with self.lock:
            self.current_fa = None
            self.state = NodeState.HOME

        logger.info(f"[MN] Returned to home network {self.home_address}")

    def send_packet(self, dst_ip: str, payload: str) -> Packet:
        """Build an outbound packet."""
        with self.lock:
            self.packet_counter += 1

        pkt = Packet(
            packet_id=self.packet_counter,
            src_ip=self.home_address,
            dst_ip=dst_ip,
            payload=payload,
        )
        self.sent_packets.append(pkt)
        logger.info(f"[MN] Sending {pkt}")
        return pkt

    def receive_packet(self, packet: Packet):
        """Record an inbound packet."""
        self.received_packets.append(packet)
        logger.info(f"[MN] Received {packet}")

    def status(self) -> Dict:
        with self.lock:
            return {
                "home_address": self.home_address,
                "state": self.state.value,
                "current_fa": self.current_fa.address if self.current_fa else "HOME",
                "handoff_count": self.handoff_count,
                "packets_sent": len(self.sent_packets),
                "packets_received": len(self.received_packets),
            }
