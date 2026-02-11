import os
import socket
import time

PACKET_SIZE = 1024
SEQ_ID_SIZE = 4
MESSAGE_SIZE = PACKET_SIZE - SEQ_ID_SIZE  # 1020

DEST = ("127.0.0.1", 5001)

DEBUG = os.getenv("DEBUG", "0") == "1"


def dprint(*args):
    if DEBUG:
        print(*args, flush=True)


def make_packet(seq_id: int, payload: bytes) -> bytes:
    return int.to_bytes(seq_id, SEQ_ID_SIZE, signed=True, byteorder="big") + payload


def parse_reply(data: bytes):
    if not data or len(data) < SEQ_ID_SIZE:
        return None, b""
    ack_id = int.from_bytes(data[:SEQ_ID_SIZE], signed=True, byteorder="big")
    msg = data[SEQ_ID_SIZE:]
    return ack_id, msg


def run_once(file_path: str, timeout_s: float = 0.5):
    total_bytes = os.path.getsize(file_path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))  # any port except 5001
    sock.settimeout(timeout_s)

    dprint("sender bound at", sock.getsockname(), "dest", DEST, "file bytes", total_bytes)

    t_start = time.time()

    first_send_time = {}
    delays = []

    offset = 0
    last_bucket = -1
    timeouts = 0

    with open(file_path, "rb") as f:
        while offset < total_bytes:
            payload = f.read(MESSAGE_SIZE)
            if not payload:
                break

            if offset not in first_send_time:
                first_send_time[offset] = time.time()

            pkt = make_packet(offset, payload)

            # stop-and-wait retransmit
            while True:
                sock.sendto(pkt, DEST)
                try:
                    data, _ = sock.recvfrom(PACKET_SIZE)
                except socket.timeout:
                    timeouts += 1
                    if DEBUG and timeouts % 200 == 0:
                        dprint("timeouts", timeouts, "at offset", offset)
                    continue

                ack_id, msg = parse_reply(data)
                if ack_id is None:
                    continue

                if msg.startswith(b"ack") and ack_id >= offset + len(payload):
                    delays.append(time.time() - first_send_time[offset])
                    offset += len(payload)

                    # progress print about every ~1MB (only in DEBUG)
                    bucket = offset // (1020 * 1000)
                    if DEBUG and bucket != last_bucket:
                        last_bucket = bucket
                        dprint("progress offset", offset, "/", total_bytes, "latest_ack", ack_id)
                    break

    # FIN phase
    fin_offset = total_bytes
    fin_pkt = make_packet(fin_offset, b"")

    fin_ack_ok = False
    fin_seen = False
    t_end = None
    fin_timeouts = 0

    dprint("data done, sending empty packet seq_id", fin_offset)

    while not (fin_ack_ok and fin_seen):
        sock.sendto(fin_pkt, DEST)
        try:
            data, _ = sock.recvfrom(PACKET_SIZE)
        except socket.timeout:
            fin_timeouts += 1
            if DEBUG and fin_timeouts % 50 == 0:
                dprint("fin wait... ack_ok", fin_ack_ok, "fin_seen", fin_seen, "timeouts", fin_timeouts)
            continue

        ack_id, msg = parse_reply(data)
        if ack_id is None:
            continue

        if msg.startswith(b"ack") and ack_id >= fin_offset:
            fin_ack_ok = True
            if t_end is None:
                t_end = time.time()
            dprint("got final ACK", ack_id)

        if msg.startswith(b"fin"):
            fin_seen = True
            dprint("got FIN", ack_id)

    # send FINACK to let receiver exit
    sock.sendto(make_packet(fin_offset, b"==FINACK=="), DEST)
    dprint("sent FINACK, exiting")

    sock.close()

    if t_end is None:
        t_end = time.time()

    duration = t_end - t_start
    if duration <= 0:
        duration = 1e-9

    throughput = float(total_bytes) / duration
    avg_delay = (sum(delays) / len(delays)) if delays else 0.0
    if avg_delay <= 0:
        avg_delay = 1e-9

    metric = 0.3 * (throughput / 1000.0) + 0.7 * (1.0 / avg_delay)

    return throughput, avg_delay, metric


def main():
    thr, dly, met = run_once("file.mp3")
    print(f"{thr:.7f}")
    print(f"{dly:.7f}")
    print(f"{met:.7f}")


if __name__ == "__main__":
    main()
