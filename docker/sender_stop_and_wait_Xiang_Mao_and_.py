import os
import socket
import time

PACKET_SIZE = 1024
SEQ_ID_SIZE = 4
MESSAGE_SIZE = PACKET_SIZE - SEQ_ID_SIZE  # 1020
DEST = ("127.0.0.1", 5001)

RTO = 0.2  # timeout seconds (可以之后调)

def make_packet(seq_id: int, payload: bytes) -> bytes:
    # seq_id is signed int (receiver uses signed=True)
    return seq_id.to_bytes(SEQ_ID_SIZE, byteorder="big", signed=True) + payload

def parse_reply(data: bytes):
    if len(data) < SEQ_ID_SIZE:
        return None, b""
    seq = int.from_bytes(data[:SEQ_ID_SIZE], byteorder="big", signed=True)
    msg = data[SEQ_ID_SIZE:]
    return seq, msg

def send_stop_and_wait(file_path: str):
    total_bytes = os.path.getsize(file_path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # bind to any port except 5001 (要求)
    sock.bind(("0.0.0.0", 5002))
    sock.settimeout(RTO)

    # per-packet delay: 以“每个offset”为单位
    first_send_time = {}   # offset -> time
    delay_done = {}        # offset -> delay

    t0 = time.time()  # throughput timer (严格说应当从 socket 创建后开始，这里几乎等价)

    offset = 0
    with open(file_path, "rb") as f:
        while offset < total_bytes:
            payload = f.read(MESSAGE_SIZE)
            pkt = make_packet(offset, payload)

            if offset not in first_send_time:
                first_send_time[offset] = time.time()

            # 重传直到收到“累计 ACK >= offset+len(payload)”
            while True:
                sock.sendto(pkt, DEST)
                try:
                    data, _ = sock.recvfrom(PACKET_SIZE)
                except socket.timeout:
                    continue

                ack_id, msg = parse_reply(data)
            if ack_id is None:
                continue
            print("got", ack_id, msg[:10], "at offset", offset)
            if ack_id is None:
                continue
                # receiver always sends msg like b'ack' or b'fin'
                if msg.startswith(b"ack"):
                    if ack_id >= offset + len(payload):
                        delay_done[offset] = time.time() - first_send_time[offset]
                        offset += len(payload)
                        break
                # 其他情况忽略继续等（比如乱序/重复）
                # 注意：stop-and-wait 下通常不会乱序，但 UDP 可能重复

    # 所有数据发完：发空包，seq_id 必须等于 total_bytes（也就是 receiver 最终 ack_id）
    fin_offset = total_bytes
    fin_pkt = make_packet(fin_offset, b"")

    if fin_offset not in first_send_time:
        first_send_time[fin_offset] = time.time()

    got_fin = False
    while not got_fin:
        sock.sendto(fin_pkt, DEST)
        try:
            data, _ = sock.recvfrom(PACKET_SIZE)
        except socket.timeout:
            continue

        sid, msg = parse_reply(data)
        if msg.startswith(b"ack") and sid == fin_offset:
            # 可能会收到 ack
            delay_done[fin_offset] = time.time() - first_send_time[fin_offset]
        if msg.startswith(b"fin"):
            # fin 的 seq 会是 fin_offset + 3
            got_fin = True

    # 按 receiver 的判断发 FINACK（payload 必须完全等于 b'==FINACK==')
    sock.sendto(make_packet(0, b"==FINACK=="), DEST)

    t1 = time.time()

    # metrics
    throughput = total_bytes / (t1 - t0)

    # average per-packet delay：这里的“packet”按你发送的数据包计数（不含最后 FINACK 控制包）
    # 你发的数据包数 = ceil(total_bytes / 1020) + 1(空包)
    data_packet_count = (total_bytes + MESSAGE_SIZE - 1) // MESSAGE_SIZE
    expected_count = data_packet_count + 1  # + empty packet
    # delay_done 里有 offset->delay，确保只算这些
    delays = [delay_done[k] for k in delay_done.keys() if k != 0 or True]
    # 更严谨：按我们发过的 offset 列表来取
    offsets = [i * MESSAGE_SIZE for i in range(data_packet_count)] + [fin_offset]
    delays = [delay_done[o] for o in offsets if o in delay_done]
    avg_delay = sum(delays) / len(delays)

    metric = 0.3 * (throughput / 1000.0) + 0.7 * (1.0 / avg_delay)

    sock.close()
    return throughput, avg_delay, metric

if __name__ == "__main__":
    thr, dly, met = send_stop_and_wait("file.mp3")
    # 作业要求跑 10 次取平均；你跑通后再包一层循环
    print(f"{thr:.7f}")
    print(f"{dly:.7f}")
    print(f"{met:.7f}")
