import socket
import threading
import json
import datetime
import time

HOST = "127.0.0.1"          # change to "0.0.0.0" if other computers should join
PORT = 5555
MAX_CLIENTS = 3
HEARTBEAT_TIMEOUT = 9       # seconds without ping -> red dot (இதயத்துடிப்பு நேர வரம்பு)

clients = {}                # name -> connection
addrs = {}                  # name -> "ip:port"   (சாக்கெட் முகவரி)
last_seen = {}              # name -> last heartbeat time
alive = {}                  # name -> True (green) / False (red)
lock = threading.Lock()

def now():
    return datetime.datetime.now().strftime("%I:%M %p")

def send(conn, obj):
    try:
        conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))
    except OSError:
        pass

def broadcast(obj, skip=None):
    with lock:
        targets = [c for n, c in clients.items() if n != skip]
    for c in targets:
        send(c, obj)

def broadcast_users():
    with lock:
        names = list(clients.keys())
        info = {n: {"addr": addrs.get(n, ""), "alive": alive.get(n, True)}
                for n in names}
    broadcast({"type": "users", "list": names, "max": MAX_CLIENTS, "info": info})

def monitor():
    """Background thread: marks clients red when heartbeat stops."""
    while True:
        time.sleep(2)
        changed = False
        with lock:
            t = time.time()
            for n in list(clients):
                ok = (t - last_seen.get(n, t)) <= HEARTBEAT_TIMEOUT
                if ok != alive.get(n, True):
                    alive[n] = ok
                    changed = True
        if changed:
            broadcast_users()

def handle(conn, addr):
    name = None
    f = conn.makefile("r", encoding="utf-8")
    try:
        first = json.loads(f.readline())
        wanted = first.get("name", "").strip()

        with lock:
            if first.get("type") != "join" or not wanted:
                error = "Please enter a name."
            elif wanted.lower() in [n.lower() for n in clients]:
                error = "That name is already in use."
            elif len(clients) >= MAX_CLIENTS:
                error = "Server is full."
            else:
                error = None
                clients[wanted] = conn
                addrs[wanted] = f"{addr[0]}:{addr[1]}"
                last_seen[wanted] = time.time()
                alive[wanted] = True
                name = wanted

        if error:
            send(conn, {"type": "error", "text": error})
            return

        send(conn, {"type": "joined", "max": MAX_CLIENTS})
        broadcast_users()
        print(f"[+] {name} joined from {addrs[name]}")

        for line in f:
            msg = json.loads(line)
            mtype = msg.get("type")

            # any packet from the client counts as "alive"
            came_back = False
            with lock:
                last_seen[name] = time.time()
                if not alive.get(name, True):
                    alive[name] = True
                    came_back = True
            if came_back:
                broadcast_users()

            # ---- heartbeat ----
            if mtype == "ping":
                send(conn, {"type": "pong"})
                continue

            # ---- typing indicator ----
            if mtype == "typing":
                if msg.get("scope") == "private":
                    to = msg.get("to")
                    with lock:
                        target = clients.get(to)
                    if target and to != name:
                        send(target, {"type": "typing", "from": name})
                else:
                    broadcast({"type": "typing", "from": name}, skip=name)
                continue

            text = msg.get("text", "")[:1000]
            if not text.strip():
                continue

            if mtype == "all":
                # Public -> everyone except sender
                broadcast(
                    {"type": "all", "from": name, "text": text, "time": now()},
                    skip=name
                )

            elif mtype == "private":
                to = msg.get("to")
                if not to or to == name:
                    continue
                with lock:
                    target = clients.get(to)
                if target:
                    # Send ONLY to the selected person
                    send(target, {
                        "type": "private",
                        "from": name,
                        "text": text,
                        "time": now()
                    })
                    print(f"[P] {name} -> {to}: {text[:40]}")

    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        if name:
            with lock:
                clients.pop(name, None)
                addrs.pop(name, None)
                last_seen.pop(name, None)
                alive.pop(name, None)
            broadcast_users()
            print(f"[-] {name} left")
        try:
            conn.close()
        except OSError:
            pass

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen()
    threading.Thread(target=monitor, daemon=True).start()
    print(f"Server running on {HOST}:{PORT}  (max {MAX_CLIENTS} clients)")
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()