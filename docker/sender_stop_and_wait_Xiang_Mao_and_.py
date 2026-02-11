import os
import socket
import time

PACKET_SIZE = 1024
SEQ_ID_SIZE = 4
PAYLOAD_SIZE = PACKET_SIZE - SEQ_ID_SIZE  # 1020

DEST_IP = "127.0.0.1"
DEST_PORT = 5001

# 超时重传间隔（网络 profile 有延迟/丢包，别设太小）
RTO = 1.0

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
    # 注意 avg_delay 不能为 0
    if avg_delay_s <= 0:
        return 0.0
    return 0.3 * (throughput_bps / 1000.0) + 0.7 / avg_delay_s

def run_once(file_path: str, debug: bool = False):
    total_bytes = os.path.getsize(file_path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # 自动绑定一个空闲端口（满足“不要绑定 5001”）
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(RTO)

    # throughput 计时：从 socket 创建后开始（严格一点这里就立刻开始）
    t0 = time.time()

    # per-packet delay：每个 offset 的“第一次发送时间”
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

            # stop-and-wait：发送当前包直到收到累计 ACK 覆盖它
            while True:
                sock.sendto(pkt, (DEST_IP, DEST_PORT))
                if debug:
                    print(f"sent offset={offset} len={len(payload)}")

                try:
                    data, _ = sock.recvfrom(PACKET_SIZE)
                except socket.timeout:
                    if debug:
                        print(f"timeout waiting ack for offset={offset}, retransmit")
                    continue

                ack_id, msg = parse_reply(data)
                if ack_id is None:
                    continue

                if debug:
                    print(f"got ack_id={ack_id} msg={msg[:10]}")

                # receiver 的 ack_id 是“期望下一个字节 offset”
                # 只要 ack_id >= offset + len(payload) 说明当前包被确认
                if msg.startswith(b"ack") and ack_id >= offset + len(payload):
                    delays.append(time.time() - first_send_time[offset])
                    offset += len(payload)

                    # 可选：每 1MB 打印一次进度（debug 时）
                    if debug and (offset // (1020 * 1000)) != ((offset - len(payload)) // (1020 * 1000)):
                        print(f"progress: {offset}/{total_bytes}")
                    break

    # 发送“空 payload 的结束包”，seq_id 必须等于 total_bytes（README 第4条）
    fin_seq = total_bytes
    fin_pkt = make_packet(fin_seq, b"")

    fin_ack_received = False
    fin_seen = False

    # 需要同时等到：ack(=total_bytes) + fin（receiver 会发两条）
    while not (fin_ack_received and fin_seen):
        sock.sendto(fin_pkt, (DEST_IP, DEST_PORT))
        if debug:
            print("sent final empty packet")

        try:
            data, _ = sock.recvfrom(PACKET_SIZE)
        except socket.timeout:
            if debug:
                print("timeout waiting ack/fin for final empty packet, retransmit")
            continue

        ack_id, msg = parse_reply(data)
        if ack_id is None:
            continue

        if debug:
            print(f"got final reply ack_id={ack_id} msg={msg[:10]}")

        if msg.startswith(b"ack") and ack_id == fin_seq:
            fin_ack_received = True
        if msg.startswith(b"fin"):
            fin_seen = True

    # README 第6条：收到 ack+fin 后，发 ==FINACK== 让 receiver 退出
    sock.sendto(make_packet(0, b"==FINACK=="), (DEST_IP, DEST_PORT))
    if debug:
        print("sent ==FINACK==")

    t1 = time.time()
    sock.close()

    elapsed = max(t1 - t0, 1e-9)
    throughput = float(total_bytes) / elapsed
    avg_delay = (sum(delays) / len(delays)) if delays else 0.0
    perf = metric(throughput, avg_delay)
    return throughput, avg_delay, perf

def main():
    debug = (os.getenv("DEBUG", "0") == "1")

    # 作业要求跑 10 次取平均/方差，但你现在先跑通一次
    thr, dly, met = run_once("file.mp3", debug=debug)

    # 输出必须是浮点数，不带单位，保留 7 位小数
    print(f"{thr:.7f}")
    print(f"{dly:.7f}")
    print(f"{met:.7f}")

if __name__ == "__main__":
    main()
