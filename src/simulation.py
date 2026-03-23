"""Traffic, loss, and mobility simulation."""

import time
import random
import threading
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from src.mobile_ip import MobileNode, HomeAgent, ForeignAgent, Packet, NodeState

logger = logging.getLogger(__name__)


def get_effective_handoff_interval(pattern: str, handoff_interval: float) -> float:
    """Return the actual spacing between handoffs."""
    if pattern == "ping_pong":
        return handoff_interval * 0.5
    return handoff_interval


@dataclass
class SimulationConfig:
    """Runtime settings."""
    num_foreign_agents: int = 3
    num_packets: int = 50
    handoff_interval: float = 2.0       # seconds between handoffs
    packet_interval: float = 0.3        # seconds between packet transmissions
    base_handoff_latency_ms: float = 20.0
    base_packet_loss_prob: float = 0.02   # 2% baseline
    handoff_loss_prob: float = 0.25       # 25% during handoff window
    handoff_loss_window: float = 0.5      # seconds around handoff
    network_delay_ms: float = 10.0        # base propagation delay
    handoff_delay_ms: float = 80.0        # additional delay during handoff
    mobility_patterns: List[str] = field(
        default_factory=lambda: ["random_walk", "sequential", "ping_pong"]
    )


@dataclass
class PacketStats:
    """Per-packet outcome."""
    packet_id: int
    sent_time: float
    received_time: Optional[float] = None
    lost: bool = False
    delay_ms: float = 0.0
    during_handoff: bool = False

    @property
    def delivered(self) -> bool:
        return self.received_time is not None and not self.lost


class NetworkSimulator:
    """Applies packet loss and delay."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.mn_in_handoff = False
        self.handoff_start_time: Optional[float] = None
        self.lock = threading.Lock()

    def set_handoff_state(self, in_handoff: bool):
        with self.lock:
            self.mn_in_handoff = in_handoff
            if in_handoff:
                self.handoff_start_time = time.time()
            else:
                self.handoff_start_time = None

    def is_in_handoff_window(self) -> bool:
        with self.lock:
            if not self.mn_in_handoff:
                return False
            if self.handoff_start_time is None:
                return False
            elapsed = time.time() - self.handoff_start_time
            return elapsed < self.config.handoff_loss_window

    def transmit(self, packet: Packet) -> Tuple[bool, float]:
        """Return delivery status and delay."""
        in_handoff = self.is_in_handoff_window()

        if in_handoff:
            loss_prob = self.config.handoff_loss_prob
        else:
            loss_prob = self.config.base_packet_loss_prob

        lost = random.random() < loss_prob

        if lost:
            logger.debug(f"[NET] Packet {packet.packet_id} LOST (handoff={in_handoff}, prob={loss_prob:.2f})")
            return False, 0.0

        base_delay = self.config.network_delay_ms + random.uniform(-2, 5)
        if in_handoff:
            base_delay += self.config.handoff_delay_ms + random.uniform(0, 30)

        time.sleep(base_delay / 5000.0)  # scaled down for fast simulation
        return True, base_delay


class MobilitySimulator:
    """Runs MN movement patterns."""

    def __init__(self, mn: MobileNode, fas: List[ForeignAgent],
                 config: SimulationConfig, net_sim: NetworkSimulator):
        self.mn = mn
        self.fas = fas
        self.config = config
        self.net_sim = net_sim
        self.handoff_latencies: List[float] = []
        self.current_fa_index = 0

    def _do_handoff(self, new_fa: ForeignAgent) -> Optional[float]:
        """Run one handoff."""
        if not self.mn.detect_movement(new_fa):
            logger.info(f"[SIM] Skipping duplicate handoff to FA-{new_fa.network_id}")
            return None

        self.net_sim.set_handoff_state(True)
        signaling_delay_ms = max(0.0, self.config.base_handoff_latency_ms + random.uniform(-5, 15))
        latency = self.mn.perform_handoff(new_fa, signaling_delay_ms=signaling_delay_ms)
        remaining_window = max(self.config.handoff_loss_window - (latency / 1000.0), 0.0)
        if remaining_window > 0:
            time.sleep(remaining_window)
        self.net_sim.set_handoff_state(False)
        self.handoff_latencies.append(latency)
        return latency

    def run_random_walk(self, num_handoffs: int) -> List[float]:
        """Pick a different FA at random."""
        latencies = []
        for _ in range(num_handoffs):
            available = [
                idx for idx, fa in enumerate(self.fas)
                if self.mn.current_fa is None or fa.network_id != self.mn.current_fa.network_id
            ]
            if not available:
                break
            next_idx = random.choice(available)
            latency = self._do_handoff(self.fas[next_idx])
            if latency is not None:
                latencies.append(latency)
                time.sleep(self.config.handoff_interval)
        return latencies

    def run_sequential(self, num_handoffs: int) -> List[float]:
        """Walk through the FAs in order."""
        latencies = []
        for i in range(num_handoffs):
            next_idx = i % len(self.fas)
            latency = self._do_handoff(self.fas[next_idx])
            if latency is not None:
                latencies.append(latency)
                time.sleep(self.config.handoff_interval)
        return latencies

    def run_ping_pong(self, num_handoffs: int) -> List[float]:
        """Alternate between two FAs."""
        latencies = []
        fa_pair = [self.fas[0], self.fas[1]] if len(self.fas) >= 2 else [self.fas[0]]
        for i in range(num_handoffs):
            next_fa = fa_pair[i % len(fa_pair)]
            latency = self._do_handoff(next_fa)
            if latency is not None:
                latencies.append(latency)
                time.sleep(get_effective_handoff_interval("ping_pong", self.config.handoff_interval))
        return latencies


class SessionSimulator:
    """Runs traffic during mobility."""

    def __init__(self, mn: MobileNode, ha: HomeAgent,
                 fas: List[ForeignAgent], config: SimulationConfig,
                 net_sim: NetworkSimulator):
        self.mn = mn
        self.ha = ha
        self.fas = fas
        self.fa_by_address = {fa.address: fa for fa in fas}
        self.config = config
        self.net_sim = net_sim
        self.packet_stats: List[PacketStats] = []
        self.running = False
        self.lock = threading.Lock()

    def _deliver_tunneled_packet(self, tunneled_packet: Packet) -> Tuple[bool, float]:
        """Deliver to the target FA and forward if needed."""
        target_fa = self.fa_by_address.get(tunneled_packet.dst_ip)
        if target_fa is None:
            logger.warning(f"[SIM] No FA found for care-of address {tunneled_packet.dst_ip}")
            return False, 0.0

        delivered, delay = self.net_sim.transmit(tunneled_packet)
        if not delivered:
            return False, 0.0

        if target_fa.decapsulate_and_deliver(tunneled_packet, self.mn):
            return True, delay

        current_fa = self.mn.current_fa
        if current_fa and current_fa.address != target_fa.address and current_fa.serves_mobile_node(self.mn.home_address):
            forwarded_packet = Packet(
                packet_id=tunneled_packet.packet_id,
                src_ip=target_fa.address,
                dst_ip=current_fa.address,
                payload=f"[FORWARDED:{target_fa.address}->{current_fa.address}] {tunneled_packet.payload}",
                size=tunneled_packet.size
            )
            forwarded, forward_delay = self.net_sim.transmit(forwarded_packet)
            if forwarded and current_fa.decapsulate_and_deliver(tunneled_packet, self.mn):
                logger.info(
                    f"[SIM] Forwarded in-flight packet {tunneled_packet.packet_id} "
                    f"from FA-{target_fa.network_id} to FA-{current_fa.network_id}"
                )
                return True, delay + forward_delay

        logger.info(f"[SIM] Packet {tunneled_packet.packet_id} dropped at FA-{target_fa.network_id}")
        return False, 0.0

    def _send_worker(self, correspondent_ip: str, total_packets: int):
        """Send packets from the correspondent to the MN."""
        for i in range(total_packets):
            if not self.running:
                break

            pkt = Packet(
                packet_id=i + 1,
                src_ip=correspondent_ip,
                dst_ip=self.mn.home_address,
                payload=f"DATA_SEGMENT_{i+1}"
            )

            in_handoff = self.net_sim.is_in_handoff_window()
            send_time = time.time()
            stat = PacketStats(packet_id=pkt.packet_id, sent_time=send_time,
                               during_handoff=in_handoff)

            routed_packet = self.ha.intercept_and_tunnel(pkt)

            if routed_packet and routed_packet.dst_ip != self.mn.home_address:
                delivered, delay = self._deliver_tunneled_packet(routed_packet)
                if delivered:
                    stat.received_time = time.time()
                    stat.delay_ms = delay
                else:
                    stat.lost = True
            elif routed_packet:
                delivered, delay = self.net_sim.transmit(routed_packet)
                if delivered and self.mn.state == NodeState.HOME:
                    self.mn.receive_packet(routed_packet)
                    stat.received_time = time.time()
                    stat.delay_ms = delay
                else:
                    stat.lost = True
            else:
                stat.lost = True

            with self.lock:
                self.packet_stats.append(stat)

            time.sleep(self.config.packet_interval)

    def run_session(self, correspondent_ip: str, mobility_pattern: str = "sequential"):
        """Run one traffic session."""
        self.running = True
        logger.info(f"\n{'='*60}")
        logger.info(f"[SIM] Starting session | Pattern: {mobility_pattern} | Packets: {self.config.num_packets}")
        logger.info(f"{'='*60}")

        send_thread = threading.Thread(
            target=self._send_worker,
            args=(correspondent_ip, self.config.num_packets),
            daemon=True
        )
        send_thread.start()

        mobility_sim = MobilitySimulator(self.mn, self.fas, self.config, self.net_sim)
        effective_interval = max(
            get_effective_handoff_interval(mobility_pattern, self.config.handoff_interval),
            0.001
        )
        num_handoffs = max(2, int(
            (self.config.num_packets * self.config.packet_interval) / effective_interval
        ))

        handoff_latencies = []
        if mobility_pattern == "random_walk":
            handoff_latencies = mobility_sim.run_random_walk(num_handoffs)
        elif mobility_pattern == "ping_pong":
            handoff_latencies = mobility_sim.run_ping_pong(num_handoffs)
        else:
            handoff_latencies = mobility_sim.run_sequential(num_handoffs)

        send_thread.join(timeout=30)
        self.running = False
        return handoff_latencies

    def compute_metrics(self) -> Dict:
        """Summarize packet outcomes."""
        with self.lock:
            stats = list(self.packet_stats)

        if not stats:
            return {}

        total = len(stats)
        lost = sum(1 for s in stats if s.lost)
        delivered = total - lost
        loss_rate = lost / total if total > 0 else 0

        delays = [s.delay_ms for s in stats if s.delivered]
        avg_delay = sum(delays) / len(delays) if delays else 0
        max_delay = max(delays) if delays else 0
        min_delay = min(delays) if delays else 0

        delivered_times = sorted([s.received_time for s in stats if s.delivered and s.received_time])
        max_gap = 0.0
        if len(delivered_times) > 1:
            gaps = [delivered_times[i+1] - delivered_times[i] for i in range(len(delivered_times)-1)]
            max_gap = max(gaps) * 1000  # ms

        handoff_pkts = [s for s in stats if s.during_handoff]
        handoff_loss = sum(1 for s in handoff_pkts if s.lost) / len(handoff_pkts) if handoff_pkts else 0

        return {
            "total_packets": total,
            "delivered_packets": delivered,
            "lost_packets": lost,
            "packet_loss_rate": round(loss_rate * 100, 2),
            "avg_delay_ms": round(avg_delay, 2),
            "min_delay_ms": round(min_delay, 2),
            "max_delay_ms": round(max_delay, 2),
            "max_session_gap_ms": round(max_gap, 2),
            "session_continuity_pct": round((1 - loss_rate) * 100, 2),
            "handoff_packet_loss_pct": round(handoff_loss * 100, 2),
            "handoff_packets_total": len(handoff_pkts),
        }
