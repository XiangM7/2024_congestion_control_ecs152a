# sender_stop_and_wait_Xiang_Mao_and_.py
import os
import socket
import time
import sys

PACKET_SIZE = 1024
SEQ_ID_SIZE = 4
PAYLOAD_SIZE = PACKET_SIZE - SEQ_ID_SIZE  # 1020

DEST_IP = "127.0.0.1"
DEST_PORT = 5001

RTO = 1.0

PROGRESS_STEP = PAYLOAD_SIZE * 1000  # 1020*1000 bytes (~1MB)

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

def run_once(file_path: str):
    total_bytes = os.path.getsize(file_path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))  # bind to any available port
    sock.settimeout(RTO)

    t0 = time.time()

    first_send_time = {}
    delays = []

    offset = 0
    last_bucket = 0

    with open(file_path, "rb") as f:
        while offset < total_bytes:
            payload = f.read(PAYLOAD_SIZE)
            if payload is None:
                payload = b""

            pkt = make_packet(offset, payload)

            if offset not in first_send_time:
                first_send_time[offset] = time.time()

            while True:
                sock.sendto(pkt, (DEST_IP, DEST_PORT))

                try:
                    data, _ = sock.recvfrom(PACKET_SIZE)
                except socket.timeout:
                    continue

                ack_id, msg = parse_reply(data)
                if ack_id is None:
                    continue

                if msg.startswith(b"ack") and ack_id >= offset + len(payload):
                    delays.append(time.time() - first_send_time[offset])
                    old_offset = offset
                    offset += len(payload)

                    # Print progress about every ~1MB (to stderr)
                    old_bucket = old_offset // PROGRESS_STEP
                    new_bucket = offset // PROGRESS_STEP
                    if new_bucket != old_bucket:
                        print(f"{offset}/{total_bytes}", file=sys.stderr)

                    break

    # Final empty packet
    fin_seq = total_bytes
    fin_pkt = make_packet(fin_seq, b"")

    fin_ack_received = False
    fin_seen = False

    while not (fin_ack_received and fin_seen):
        sock.sendto(fin_pkt, (DEST_IP, DEST_PORT))

        try:
            data, _ = sock.recvfrom(PACKET_SIZE)
        except socket.timeout:
            continue

        ack_id, msg = parse_reply(data)
        if ack_id is None:
            continue

        if msg.startswith(b"ack") and ack_id == fin_seq:
            fin_ack_received = True
        if msg.startswith(b"fin"):
            fin_seen = True

    # Send FINACK 
    sock.sendto(make_packet(0, b"==FINACK=="), (DEST_IP, DEST_PORT))

    t1 = time.time()
    sock.close()

    elapsed = max(t1 - t0, 1e-9)
    throughput = float(total_bytes) / elapsed
    avg_delay = (sum(delays) / len(delays)) if delays else 0.0
    perf = metric(throughput, avg_delay)
    return throughput, avg_delay, perf

def main():
    thr, dly, met = run_once("file.mp3")

    # stdout:three floats 
    print(f"{thr:.7f}")
    print(f"{dly:.7f}")
    print(f"{met:.7f}")

if __name__ == "__main__":
    main()
