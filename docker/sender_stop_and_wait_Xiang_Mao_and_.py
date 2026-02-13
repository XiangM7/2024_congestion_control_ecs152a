
import os
import socket
import time
import subprocess
import signal

PACKET_SIZE = 1024
SEQ_ID_SIZE = 4
PAYLOAD_SIZE = PACKET_SIZE - SEQ_ID_SIZE  

DEST_IP = "127.0.0.1"
DEST_PORT = 5001

RTO = 1.0
RUNS = 10

FILE_IN = "file.mp3"
FILE_OUT = os.path.join("hdd", "file2.mp3")

READY_TIMEOUT = 30.0   
FIN_TIMEOUT = 10.0     


def make_packet(seq_id: int, payload: bytes) -> bytes:
    return int.to_bytes(seq_id, SEQ_ID_SIZE, signed=True, byteorder="big") + payload


def parse_reply(data: bytes):
    if len(data) < SEQ_ID_SIZE:
        return None, b""
    ack_id = int.from_bytes(data[:SEQ_ID_SIZE], signed=True, byteorder="big")
    msg = data[SEQ_ID_SIZE:]
    return ack_id, msg


def metric(throughput_bps: float, avg_delay_s: float) -> float:
    if avg_delay_s <= 0:
        return 0.0
    return 0.3 * (throughput_bps / 1000.0) + 0.7 / avg_delay_s


def silent_run(cmd):
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_simulator_silent():
    # kill any old container name 
    silent_run(["docker", "rm", "-f", "ecs152a-simulator"])

    # start simulator script in background
    p = subprocess.Popen(
        ["bash", "./start-simulator.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return p


def wait_receiver_ready():
    # Wait until docker logs contains "Receiver running" 
    deadline = time.time() + READY_TIMEOUT
    while time.time() < deadline:
        r = subprocess.run(
            ["docker", "logs", "ecs152a-simulator"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if "Receiver running" in r.stdout:
            return
        time.sleep(0.2)
    raise RuntimeError("receiver not ready (timeout)")


def stop_simulator(sim_proc):
    # receiver should exit after FINACK; still do cleanup
    silent_run(["docker", "rm", "-f", "ecs152a-simulator"])
    try:
        os.killpg(os.getpgid(sim_proc.pid), signal.SIGTERM)
    except Exception:
        pass


def run_once(file_path: str):
    total_bytes = os.path.getsize(file_path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(RTO)

    t0 = time.time()
    first_send_time = {}
    delays = []
    offset = 0

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
                    offset += len(payload)
                    break

    # Final empty packet
    fin_seq = total_bytes
    fin_pkt = make_packet(fin_seq, b"")

    fin_ack_received = False
    fin_seen = False
    deadline = time.time() + FIN_TIMEOUT

    while not (fin_ack_received and fin_seen):
        if time.time() > deadline:
           
            raise RuntimeError("finish handshake timeout")

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

    sock.sendto(make_packet(0, b"==FINACK=="), (DEST_IP, DEST_PORT))

    t1 = time.time()
    sock.close()

    elapsed = max(t1 - t0, 1e-9)
    throughput = float(total_bytes) / elapsed
    avg_delay = (sum(delays) / len(delays)) if delays else 0.0
    perf = metric(throughput, avg_delay)
    return throughput, avg_delay, perf


def main():
    # Must run from directory
    if not os.path.exists("./start-simulator.sh"):
        raise SystemExit("Run from docker/ directory.")
    if not os.path.exists(FILE_IN):
        raise SystemExit("file.mp3 not found in docker/ directory.")

    thr_list, dly_list, met_list = [], [], []

    for _ in range(RUNS):
        # clean receiver output file each run
        try:
            os.remove(FILE_OUT)
        except FileNotFoundError:
            pass

        sim = start_simulator_silent()
        try:
            wait_receiver_ready()
            thr, dly, met = run_once(FILE_IN)
            thr_list.append(thr)
            dly_list.append(dly)
            met_list.append(met)
        finally:
            stop_simulator(sim)

    thr_avg = sum(thr_list) / RUNS
    dly_avg = sum(dly_list) / RUNS
    met_avg = sum(met_list) / RUNS

    
    print(f"{thr_avg:.7f}")
    print(f"{dly_avg:.7f}")
    print(f"{met_avg:.7f}")


if __name__ == "__main__":
    main()
