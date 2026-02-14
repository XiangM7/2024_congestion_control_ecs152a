import socket
import os
import time
from datetime import datetime
import subprocess
import signal

# total packet size
PACKET_SIZE = 1024
# bytes reserved for sequence id
SEQ_ID_SIZE = 4
# bytes available for message
MESSAGE_SIZE = PACKET_SIZE - SEQ_ID_SIZE
# total packets to send
WINDOW_SIZE = 100

DEST_IP = "127.0.0.1"
DEST_PORT = 5001
RTO = 1.0

# RUNS = 10
# READY_TIMEOUT = 30.0
FIN_TIMEOUT = 10.0

FILE_IN = "file.mp3"
FILE_OUT = os.path.join("hdd", "file2.mp3")


def make_packet(seq_id: int, payload: bytes) -> bytes:
    return int.to_bytes(seq_id, SEQ_ID_SIZE, signed=True, byteorder="big") + payload

def parse_reply(data: bytes):
    if len(data) < SEQ_ID_SIZE:
        return None, b""
    ack_id = int.from_bytes(data[:SEQ_ID_SIZE], signed=True, byteorder="big")
    msg = data[SEQ_ID_SIZE:]
    return ack_id, msg

def metric(throughput_bps: float, avg_delay_s: float) -> float:
    # Metric = 0.3 * Throughput/1000 + 0.7 / AverageDelay
    if avg_delay_s <= 0:
        return 0.0
    return 0.3 * (throughput_bps / 1000.0) + 0.7 / avg_delay_s

# basically, we're using a similar implementation as the other file, but we implemented the sliding window logic.
# we init the seq to 0 and check that it isn't above the size of the file(so we know when to stop)
# we then populate the window(read from disk, store packet info, and begin tracking the ack)
# then we send the packets in the window, and then we wait for the acks
# the biggest difference is that now we just have to wait for at least the first to come back before shifting the window,
# instead of all the packets in the window
# if a packet is stuck, we can remove it and resend the lowest unacked packet(this is like fast retransmit)
# if we timeout, we can resend the lowest unacked packet



def run_once():
# udp socket like the discussion file
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:

        # bind the socket to a OS port(same as other one)
        udp_socket.bind(("0.0.0.0", 0))
        udp_socket.settimeout(RTO)

        first_send_time = {}
        delays = []

        t0 = time.time()

        # this will have packets that have been sent but no ack received yet
        in_flight = {}
        # get the size of the file to know when to stop later
        total_bytes = os.path.getsize("file.mp3")


        # this is going to hold the sequence ids(all of them) so that we can safely move the window
        # w/o worrying that well go out of bounds
        seq_ids = []
        offset = 0

        
        # this is to fill the seq ids list with correct offsets
        with open("file.mp3", "rb") as f:
            while offset < total_bytes:
                seq_ids.append(offset)
                offset += MESSAGE_SIZE


        # next index used to track the window                
        next_index = 0

        # duplicate ack tracking
        last_ack = None
        dup_acks = 0

        # new main loop for sending data w/ sliding window
        with open("file.mp3", "rb") as f:
            while True:
                # if the window(in_flight) is not full, and we have more packets to send, send them
                while len(in_flight) < WINDOW_SIZE and next_index < len(seq_ids):
                    #but also make sure we dont go over
                    sid = seq_ids[next_index]
                    if sid >= total_bytes:
                        break

                        # get the actual payload
                    f.seek(sid)
                    payload = f.read(MESSAGE_SIZE)
                    if not payload:
                        break

                    # record first send time for this packet
                    if sid not in first_send_time:
                        first_send_time[sid] = time.time()

                    # send the packet, add it to in flight, and move next to send
                    udp_socket.sendto(make_packet(sid, payload), (DEST_IP, DEST_PORT))
                    in_flight[sid] = payload
                    next_index += 1

                # if we sent all packets and no packets in flight, done
                if next_index >= len(seq_ids) and not in_flight:
                    break

                # receive acks or timeout then retransmit necessary packets
                try:
                    data, _ = udp_socket.recvfrom(PACKET_SIZE)
                    ack_id, msg = parse_reply(data)

                    if ack_id is None:
                        continue
                    if not msg.startswith(b"ack"):
                        # 
                        continue

                    # track dupe acks
                    if last_ack == ack_id:
                        dup_acks += 1
                    else:
                        last_ack = ack_id
                        dup_acks = 0

                    # remove packets that have been acknowledged
                    now = time.time()
                    to_remove = []
                    for sid, payload in in_flight.items():
                        if sid + len(payload) <= ack_id:
                            to_remove.append(sid)
                            # print("Removing packet:", sid)
                    for sid in to_remove:
                        delays.append(now - first_send_time[sid])
                        del in_flight[sid]

                    # if we are stuck on an ack, we can remove it and resend the lowest unacked packet(this is like fast retransmit)
                    if dup_acks >= 3 and in_flight:
                        base = min(in_flight.keys())
                        udp_socket.sendto(make_packet(base, in_flight[base]), (DEST_IP, DEST_PORT))

                except socket.timeout:
                    # if we timeout, we can resend the lowest unacked packet
                    for sid, payload in list(in_flight.items()):
                        udp_socket.sendto(make_packet(sid, payload), (DEST_IP, DEST_PORT))
                except ConnectionResetError:
                    continue

        # send final closing message
        # Final empty packet
        fin_seq = total_bytes
        fin_pkt = make_packet(fin_seq, b"")

        fin_ack_received = False
        fin_seen = False
        deadline = time.time() + FIN_TIMEOUT

        while not (fin_ack_received and fin_seen):
            if time.time() > deadline:
                raise RuntimeError("finish handshake timeout")

            udp_socket.sendto(fin_pkt, (DEST_IP, DEST_PORT))

            try:
                data, _ = udp_socket.recvfrom(PACKET_SIZE)
            except socket.timeout:
                continue
            except ConnectionResetError:
                continue

            ack_id, msg = parse_reply(data)
            if ack_id is None:
                continue

            if msg.startswith(b"ack") and ack_id == fin_seq:
                fin_ack_received = True
            if msg.startswith(b"fin"):
                fin_seen = True

        # Send FINACK 
        udp_socket.sendto(make_packet(0, b"==FINACK=="), (DEST_IP, DEST_PORT))

        t1 = time.time()

        elapsed = max(t1 - t0, 1e-9)
        throughput = float(total_bytes) / elapsed
        avg_delay = (sum(delays) / len(delays)) if delays else 0.0
        perf = metric(throughput, avg_delay)
        return throughput, avg_delay, perf

# this doesn't work on my machine, doing it manually instead
def run_10_times():
    throughputs = []
    delays = []
    metrics = []

    for i in range(10):
        thr, dly, met = run_once()
        throughputs.append(thr)
        delays.append(dly)
        metrics.append(met)

    avg_thr = sum(throughputs) / 10.0
    avg_dly = sum(delays) / 10.0
    avg_met = sum(metrics) / 10.0

    print(f"{avg_thr:.7f}")
    print(f"{avg_dly:.7f}")
    print(f"{avg_met:.7f}")

def main():
    thr, dly, met = run_once()
    print(f"Throughput: {thr:.7f}")
    print(f"Delay: {dly:.7f}")
    print(f"Metric: {met:.7f}")

if __name__ == "__main__":
    main()
