import socket
import threading
import json
import queue
import os
import time
import datetime
import tkinter as tk

HOST = "127.0.0.1"
PORT = 5555

# ---------- colours ----------
BG = "#0b0f17"
PANEL = "#0f1520"
CARD = "#111a29"
LINE = "#1c2636"
TEXT = "#e6edf7"
MUTED = "#8a97ab"
ACCENT = "#1e90ff"
CYAN = "#00d4ff"
GREEN = "#00e676"
RED = "#ff5252"
FONT = "Segoe UI"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALL = "All Chat"

HEARTBEAT_EVERY = 3000      # ms - send ping (இதயத்துடிப்பு)
PONG_TIMEOUT = 10           # sec - no pong -> "Server not responding"
TYPING_EXPIRE = 3           # sec - hide "typing..." after this
TYPING_THROTTLE = 2         # sec - send typing event at most this often

# ---------- history storage ----------
def history_path(name):
    return os.path.join(BASE_DIR, f"history_{name.lower()}.json")

def load_history(name):
    try:
        with open(history_path(name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_history(name, data):
    with open(history_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def flat_button(parent, text, cmd, bg=ACCENT, fg="white", size=10, padx=14, pady=6):
    return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, bd=0,
                     activebackground=bg, activeforeground=fg, cursor="hand2",
                     font=(FONT, size, "bold"), padx=padx, pady=pady, relief="flat")

# =====================================================
#                    JOIN SCREEN
# =====================================================
class JoinScreen:
    def __init__(self, root):
        self.root = root
        root.title("")
        root.geometry("460x420")
        root.configure(bg=BG)
        root.resizable(False, False)

        self.frame = tk.Frame(root, bg=BG)
        self.frame.pack(fill="both", expand=True)

        tk.Label(self.frame, text="MULTI CLIENT CHAT", bg=BG, fg=TEXT,
                 font=(FONT, 20, "bold")).pack(pady=(60, 2))
        tk.Label(self.frame, text="REAL-TIME SOCKET COMMUNICATION", bg=BG, fg=MUTED,
                 font=(FONT, 8)).pack(pady=(0, 40))

        self.name_var = tk.StringVar()
        entry = tk.Entry(self.frame, textvariable=self.name_var, bg=CARD, fg=TEXT,
                         insertbackground=TEXT, bd=0, font=(FONT, 13), justify="center",
                         highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        entry.pack(ipady=10, padx=70, fill="x")
        entry.focus_set()
        entry.bind("<Return>", lambda e: self.join())

        flat_button(self.frame, "JOIN CHAT", self.join, size=12, pady=10).pack(
            padx=70, pady=20, fill="x")

        self.msg = tk.Label(self.frame, text="", bg=BG, fg=RED, font=(FONT, 9))
        self.msg.pack()

    def join(self):
        name = self.name_var.get().strip()
        if not name:
            self.msg.config(text="Please enter your name.")
            return
        try:
            sock = socket.create_connection((HOST, PORT), timeout=5)
            rfile = sock.makefile("r", encoding="utf-8")
            sock.sendall((json.dumps({"type": "join", "name": name}) + "\n").encode())
            reply = json.loads(rfile.readline())
            sock.settimeout(None)
        except Exception:
            self.msg.config(text="Cannot connect. Start server.py first.")
            return
        if reply.get("type") != "joined":
            self.msg.config(text=reply.get("text", "Could not join."))
            sock.close()
            return
        self.frame.destroy()
        ChatApp(self.root, sock, rfile, name, reply.get("max", 3))

# =====================================================
#                     CHAT SCREEN
# =====================================================
class ChatApp:
    def __init__(self, root, sock, rfile, name, max_clients):
        self.root = root
        self.sock = sock
        self.rfile = rfile
        self.name = name
        self.max_clients = max_clients

        self.session_start = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
        self.chats = {ALL: []}
        self.unread = {}
        self.current = ALL
        self.users = []
        self.info = {}              # name -> {"addr": "ip:port", "alive": True/False}
        self.typing = {}            # name -> last time typing event arrived
        self.last_typing_sent = 0
        self.last_pong = time.time()
        self.connected = True
        self.q = queue.Queue()

        root.title("")
        root.geometry("1100x700")
        root.minsize(900, 560)
        root.resizable(True, True)
        root.configure(bg=BG)

        self.build_ui()
        self.refresh_sidebar()
        self.render()
        threading.Thread(target=self.listen, daemon=True).start()
        self.root.after(100, self.poll)
        self.root.after(HEARTBEAT_EVERY, self.heartbeat)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def build_ui(self):
        r = self.root
        r.grid_rowconfigure(1, weight=1)
        r.grid_columnconfigure(0, weight=1)

        # header
        head = tk.Frame(r, bg=BG, height=70)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_propagate(False)
        head.grid_columnconfigure(1, weight=1)

        tk.Label(head, text="💬", bg=BG, fg=CYAN, font=(FONT, 22)).grid(row=0, column=0, padx=20)
        mid = tk.Frame(head, bg=BG)
        mid.grid(row=0, column=1)
        tk.Label(mid, text="MULTI CLIENT CHAT", bg=BG, fg=TEXT, font=(FONT, 18, "bold")).pack(pady=(10, 0))
        tk.Label(mid, text="REAL-TIME SOCKET COMMUNICATION", bg=BG, fg=MUTED, font=(FONT, 8)).pack()

        right = tk.Frame(head, bg=BG)
        right.grid(row=0, column=2, padx=20)
        tk.Label(right, text="● SERVER", bg=BG, fg=GREEN, font=(FONT, 10, "bold")).pack(anchor="e")
        tk.Label(right, text=f"{HOST}:{PORT}", bg=BG, fg=MUTED, font=(FONT, 8)).pack(anchor="e")

        # body
        body = tk.Frame(r, bg=PANEL)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        # ---- left sidebar ----
        side = tk.Frame(body, bg=PANEL, width=270)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)

        top_btns = tk.Frame(side, bg=PANEL)
        top_btns.pack(fill="x", padx=10, pady=(14, 8))
        flat_button(top_btns, "＋ New Chat", self.new_chat, size=10).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        flat_button(top_btns, "🕘 History", self.open_history, bg=CARD, fg=CYAN, size=10).pack(
            side="left", fill="x", expand=True, padx=(4, 0))

        tk.Label(side, text="CHATS", bg=PANEL, fg=MUTED, font=(FONT, 10, "bold")).pack(
            anchor="w", padx=14, pady=(8, 4))

        self.side_search = tk.StringVar()
        self.side_search.trace_add("write", lambda *a: self.refresh_sidebar())
        tk.Entry(side, textvariable=self.side_search, bg=CARD, fg=TEXT, insertbackground=TEXT,
                 bd=0, font=(FONT, 10), highlightthickness=1, highlightbackground=LINE,
                 highlightcolor=ACCENT).pack(fill="x", padx=10, ipady=6)

        self.chat_list = tk.Frame(side, bg=PANEL)
        self.chat_list.pack(fill="both", expand=True, pady=8)

        # ---- centre ----
        centre = tk.Frame(body, bg=BG)
        centre.grid(row=0, column=1, sticky="nsew")
        centre.grid_rowconfigure(1, weight=1)
        centre.grid_columnconfigure(0, weight=1)

        ch = tk.Frame(centre, bg=PANEL, height=70)
        ch.grid(row=0, column=0, sticky="ew")
        ch.grid_propagate(False)
        ch.grid_columnconfigure(0, weight=1)

        titles = tk.Frame(ch, bg=PANEL)
        titles.grid(row=0, column=0, sticky="w", padx=20, pady=8)
        self.chat_title = tk.Label(titles, text="", bg=PANEL, fg=TEXT, font=(FONT, 15, "bold"))
        self.chat_title.pack(anchor="w")
        self.chat_sub = tk.Label(titles, text="", bg=PANEL, fg=MUTED, font=(FONT, 9))
        self.chat_sub.pack(anchor="w")

        self.msg_search = tk.StringVar()
        self.msg_search.trace_add("write", lambda *a: self.render())
        tk.Label(ch, text="🔍", bg=PANEL, fg=MUTED).grid(row=0, column=1)
        tk.Entry(ch, textvariable=self.msg_search, bg=CARD, fg=TEXT, insertbackground=TEXT, bd=0,
                 width=24, font=(FONT, 10), highlightthickness=1, highlightbackground=LINE,
                 highlightcolor=ACCENT).grid(row=0, column=2, padx=(4, 20), ipady=6)

        box = tk.Frame(centre, bg=BG)
        box.grid(row=1, column=0, sticky="nsew", padx=14, pady=10)
        box.grid_rowconfigure(0, weight=1)
        box.grid_columnconfigure(0, weight=1)

        self.text = tk.Text(box, bg=BG, fg=TEXT, bd=0, wrap="word", state="disabled",
                            font=(FONT, 11), cursor="arrow", padx=10, pady=10,
                            highlightthickness=0, spacing1=2)
        sb = tk.Scrollbar(box, command=self.text.yview)
        self.text.config(yscrollcommand=sb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.configure_tags(self.text)

        # input
        inp = tk.Frame(centre, bg=BG)
        inp.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 4))
        inp.grid_columnconfigure(1, weight=1)

        wrap = tk.Frame(inp, bg=BG, highlightthickness=1, highlightbackground=LINE)
        wrap.pack(fill="x")
        wrap.grid_columnconfigure(1, weight=1)

        tk.Button(wrap, text="😊", command=self.emoji_popup, bg=BG, fg=CYAN, bd=0,
                  activebackground=BG, cursor="hand2", font=(FONT, 16)).grid(row=0, column=0, padx=10)
        self.entry = tk.Text(wrap, height=2, bg=BG, fg=TEXT, insertbackground=TEXT, bd=0,
                             font=(FONT, 11), wrap="word", highlightthickness=0)
        self.entry.grid(row=0, column=1, sticky="ew", pady=12)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<Shift-Return>", self.on_shift_enter)
        self.entry.bind("<KeyRelease>", self.on_key)
        self.entry.focus_set()

        flat_button(wrap, "SEND ➤", self.send, size=10, padx=20, pady=12).grid(row=0, column=2, padx=8)
        self.counter = tk.Label(wrap, text="0/1000", bg=BG, fg=MUTED, font=(FONT, 9))
        self.counter.grid(row=0, column=3, padx=8)

        tk.Label(centre, text="Enter → Send   •   Shift + Enter → New line   •   😊 Emoji",
                 bg=BG, fg=MUTED, font=(FONT, 8)).grid(row=3, column=0, sticky="w", padx=16, pady=(0, 6))

        # ---- online panel ----
        online = tk.Frame(body, bg=PANEL, width=230)
        online.grid(row=0, column=2, sticky="ns")
        online.grid_propagate(False)

        tk.Label(online, text="ONLINE", bg=PANEL, fg=TEXT, font=(FONT, 11, "bold")).pack(
            anchor="w", padx=14, pady=(18, 0))
        self.online_count = tk.Label(online, text="", bg=PANEL, fg=CYAN, font=(FONT, 10, "bold"))
        self.online_count.pack(anchor="w", padx=14, pady=(0, 8))
        self.online_list = tk.Frame(online, bg=PANEL)
        self.online_list.pack(fill="both", expand=True)

        # footer
        foot = tk.Frame(r, bg=BG, height=34)
        foot.grid(row=2, column=0, sticky="ew")
        tk.Label(foot, text=f"LOGIN CLIENT: {self.name.upper()}", bg=BG, fg=CYAN,
                 font=(FONT, 9, "bold")).pack(side="left", padx=20, pady=8)
        self.status = tk.Label(foot, text="● Connected", bg=BG, fg=GREEN, font=(FONT, 9, "bold"))
        self.status.pack(side="left", padx=20)
        tk.Label(foot, text="Real-Time Socket Communication", bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(side="right", padx=20)

    @staticmethod
    def configure_tags(t):
        """Plain text only – no blue boxes"""
        t.tag_config("date", justify="center", foreground=MUTED, background=CARD,
                     spacing1=10, spacing3=10)
        t.tag_config("meta_me", justify="right", foreground=CYAN, rmargin=20,
                     font=(FONT, 9, "bold"), spacing1=10)
        t.tag_config("meta_other", justify="left", foreground="#1de9b6", lmargin1=20,
                     lmargin2=20, font=(FONT, 9, "bold"), spacing1=10)
        t.tag_config("text_me", justify="right", foreground=TEXT, rmargin=20, spacing1=2)
        t.tag_config("text_other", justify="left", foreground=TEXT,
                     lmargin1=20, lmargin2=20, spacing1=2)
        t.tag_config("head", foreground=CYAN, font=(FONT, 12, "bold"), spacing1=14, spacing3=6)
        t.tag_config("session", foreground=ACCENT, font=(FONT, 11, "bold"), spacing1=16, spacing3=8)

    def avatar(self, parent, letter, color, dot=None):
        """Round avatar. dot = GREEN / RED colour for the status dot (optional)."""
        c = tk.Canvas(parent, width=38, height=38, bg=parent["bg"], highlightthickness=0)
        c.create_oval(2, 2, 36, 36, fill=color, outline="")
        c.create_text(19, 19, text=letter.upper(), fill="white", font=(FONT, 12, "bold"))
        if dot:
            c.create_oval(25, 25, 37, 37, fill=dot, outline=parent["bg"], width=2)
        return c

    def refresh_sidebar(self):
        for w in self.chat_list.winfo_children():
            w.destroy()
        q = self.side_search.get().strip().lower()

        def row(key, label, color, letter):
            if q and q not in label.lower():
                return
            sel = key == self.current
            bg = "#123a63" if sel else PANEL
            f = tk.Frame(self.chat_list, bg=bg, cursor="hand2")
            f.pack(fill="x", padx=4, pady=1)
            self.avatar(f, letter, color).pack(side="left", padx=10, pady=8)
            info = tk.Frame(f, bg=bg)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=label, bg=bg, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w")
            msgs = self.chats.get(key, [])
            if msgs:
                last = msgs[-1]
                who = "You" if last["from"] == self.name else last["from"]
                prev = f'{who}: {last["text"].splitlines()[0][:22]}'
            else:
                prev = "No messages yet"
            tk.Label(info, text=prev, bg=bg, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
            n = self.unread.get(key, 0)
            if n:
                tk.Label(f, text=str(n), bg=ACCENT, fg="white", font=(FONT, 8, "bold"),
                         padx=6).pack(side="right", padx=10)
            for w in [f, info] + list(f.winfo_children()) + list(info.winfo_children()):
                w.bind("<Button-1>", lambda e, k=key: self.open_chat(k))

        row(ALL, ALL, ACCENT, "A")
        tk.Label(self.chat_list, text="PRIVATE CHATS", bg=PANEL, fg=MUTED,
                 font=(FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        for key in sorted(self.chats):
            if key != ALL:
                row(key, key, "#00a389", key[0])

    def refresh_online(self):
        for w in self.online_list.winfo_children():
            w.destroy()
        self.online_count.config(text=f"{len(self.users)} / {self.max_clients} CLIENTS")
        for u in self.users:
            data = self.info.get(u, {})
            addr = data.get("addr", "")
            is_alive = data.get("alive", True)
            dot = GREEN if is_alive else RED

            f = tk.Frame(self.online_list, bg=PANEL, cursor="hand2")
            f.pack(fill="x", padx=6, pady=2)
            self.avatar(f, u[0], "#ff5722" if u == self.name else "#00a389", dot=dot).pack(
                side="left", padx=8, pady=6)

            col = tk.Frame(f, bg=PANEL)
            col.pack(side="left", fill="x", expand=True)
            label = f"{u} (You)" if u == self.name else u
            tk.Label(col, text=label, bg=PANEL, fg=TEXT, font=(FONT, 10, "bold")).pack(anchor="w")

            # typing indicator replaces the IP line while the person is typing
            if u in self.typing and u != self.name:
                tk.Label(col, text=f"{u} is typing…", bg=PANEL, fg=GREEN,
                         font=(FONT, 8, "italic")).pack(anchor="w")
            else:
                tk.Label(col, text=addr, bg=PANEL, fg=MUTED, font=(FONT, 8)).pack(anchor="w")

            if u != self.name:
                for w in [f, col] + list(f.winfo_children()) + list(col.winfo_children()):
                    w.bind("<Button-1>", lambda e, k=u: self.open_chat(k))

    def open_chat(self, key):
        self.current = key
        self.chats.setdefault(key, [])
        self.unread[key] = 0
        self.msg_search.set("")
        self.refresh_sidebar()
        self.render()

    def render(self):
        if self.current == ALL:
            self.chat_title.config(text="🌐  All Chat")
            self.chat_sub.config(text="Everyone in the server can see this chat")
        else:
            self.chat_title.config(text=f"👤  {self.current}")
            self.chat_sub.config(text="Private chat – only you two can see these messages")

        t = self.text
        t.config(state="normal")
        t.delete("1.0", "end")
        q = self.msg_search.get().strip().lower()
        t.insert("end", f" {self.session_start} \n", "date")

        for m in self.chats.get(self.current, []):
            if q and q not in m["text"].lower() and q not in m["from"].lower():
                continue
            side = "me" if m["from"] == self.name else "other"
            who = "You" if side == "me" else m["from"]
            t.insert("end", f'{who}   {m["time"]}\n', "meta_" + side)
            t.insert("end", f'{m["text"]}\n', "text_" + side)

        t.config(state="disabled")
        t.see("end")

    def add_msg(self, key, sender, text, tm):
        self.chats.setdefault(key, []).append({"from": sender, "text": text, "time": tm})
        if key == self.current:
            self.render()
        elif sender != self.name:
            self.unread[key] = self.unread.get(key, 0) + 1
        self.refresh_sidebar()

    def on_enter(self, e):
        self.send()
        return "break"

    def on_shift_enter(self, e):
        self.entry.insert("insert", "\n")
        return "break"

    def update_counter(self, e=None):
        n = len(self.entry.get("1.0", "end-1c"))
        self.counter.config(text=f"{n}/1000", fg=RED if n > 1000 else MUTED)

    def on_key(self, e):
        """Key released: update counter + send typing event (throttled)."""
        self.update_counter()
        ignore = ("Return", "Shift_L", "Shift_R", "Control_L", "Control_R",
                  "Alt_L", "Alt_R", "Caps_Lock", "Tab")
        if e.keysym in ignore:
            return
        if not self.entry.get("1.0", "end-1c").strip():
            return
        now = time.time()
        if now - self.last_typing_sent < TYPING_THROTTLE:
            return
        self.last_typing_sent = now
        try:
            if self.current == ALL:
                payload = {"type": "typing", "scope": "all"}
            else:
                payload = {"type": "typing", "scope": "private", "to": self.current}
            self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError:
            pass

    def send(self):
        text = self.entry.get("1.0", "end-1c").strip()
        if not text:
            return
        text = text[:1000]
        tm = datetime.datetime.now().strftime("%I:%M %p")
        try:
            if self.current == ALL:
                payload = {"type": "all", "text": text}
            else:
                payload = {"type": "private", "to": self.current, "text": text}
            self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError:
            self.status.config(text="● Disconnected", fg=RED)
            return
        # Local echo (so sender sees own message immediately)
        self.add_msg(self.current, self.name, text, tm)
        self.entry.delete("1.0", "end")
        self.last_typing_sent = 0
        self.update_counter()

    def emoji_popup(self):
        win = tk.Toplevel(self.root)
        win.title("")
        win.configure(bg=CARD)
        win.resizable(False, False)
        emojis = "😀 😂 😍 😎 😢 😡 👍 👎 🙏 🎉 ❤️ 🔥 😊 🤔 😴 👋".split()
        for i, em in enumerate(emojis):
            tk.Button(win, text=em, bd=0, bg=CARD, activebackground=LINE, font=(FONT, 16),
                      command=lambda e=em: (self.entry.insert("insert", e), win.destroy())).grid(
                row=i // 4, column=i % 4, padx=4, pady=4)

    # ---------- heartbeat (இதயத்துடிப்பு சோதனை) ----------
    def heartbeat(self):
        if not self.connected:
            return
        try:
            self.sock.sendall((json.dumps({"type": "ping"}) + "\n").encode("utf-8"))
        except OSError:
            self.status.config(text="● Disconnected", fg=RED)
            self.connected = False
            return
        if time.time() - self.last_pong > PONG_TIMEOUT:
            self.status.config(text="● Server not responding", fg=RED)
        else:
            self.status.config(text="● Connected", fg=GREEN)
        self.root.after(HEARTBEAT_EVERY, self.heartbeat)

    def listen(self):
        try:
            for line in self.rfile:
                self.q.put(json.loads(line))
        except Exception:
            pass
        self.q.put({"type": "disconnected"})

    def poll(self):
        redraw_online = False
        while not self.q.empty():
            m = self.q.get()
            t = m.get("type")
            if t == "users":
                self.users = m["list"]
                self.info = m.get("info", {})
                self.max_clients = m.get("max", self.max_clients)
                redraw_online = True
            elif t == "all":
                self.add_msg(ALL, m["from"], m["text"], m["time"])
                if self.typing.pop(m["from"], None) is not None:
                    redraw_online = True
            elif t == "private":
                # Only the selected person receives this
                other = m["from"]
                self.add_msg(other, other, m["text"], m["time"])
                if self.typing.pop(other, None) is not None:
                    redraw_online = True
            elif t == "typing":
                self.typing[m["from"]] = time.time()
                redraw_online = True
            elif t == "pong":
                self.last_pong = time.time()
            elif t == "disconnected":
                self.connected = False
                self.status.config(text="● Disconnected", fg=RED)

        # expire old "typing..." entries
        now = time.time()
        for n in [n for n, tm in self.typing.items() if now - tm > TYPING_EXPIRE]:
            del self.typing[n]
            redraw_online = True

        if redraw_online:
            self.refresh_online()
        self.root.after(100, self.poll)

    def archive_session(self):
        chats = {k: v for k, v in self.chats.items() if v}
        if not chats:
            return
        hist = load_history(self.name)
        hist.append({
            "started": self.session_start,
            "saved": datetime.datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "chats": chats,
        })
        save_history(self.name, hist)

    def new_chat(self):
        self.archive_session()
        self.chats = {ALL: []}
        self.unread = {}
        self.current = ALL
        self.session_start = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
        self.msg_search.set("")
        self.refresh_sidebar()
        self.render()

    def open_history(self):
        win = tk.Toplevel(self.root)
        win.title("Chat History")
        win.geometry("860x560")
        win.configure(bg=BG)
        win.grid_columnconfigure(1, weight=1)
        win.grid_rowconfigure(0, weight=1)

        hist = load_history(self.name)
        sessions = list(hist)

        left = tk.Frame(win, bg=PANEL, width=280)
        left.grid(row=0, column=0, sticky="ns")
        left.grid_propagate(False)

        tk.Label(left, text="🕘  CHAT HISTORY", bg=PANEL, fg=CYAN,
                 font=(FONT, 13, "bold")).pack(anchor="w", padx=14, pady=14)

        lb = tk.Listbox(left, bg=PANEL, fg=TEXT, bd=0, highlightthickness=0,
                        selectbackground="#123a63", selectforeground="white",
                        activestyle="none", font=(FONT, 10), height=20)
        lb.pack(fill="both", expand=True, padx=8)

        def count(s):
            return sum(len(v) for v in s["chats"].values())

        for s in reversed(sessions):
            lb.insert("end", f'{s["started"]}  ({count(s)} msgs)')

        viewer = tk.Text(win, bg=BG, fg=TEXT, bd=0, wrap="word", font=(FONT, 11),
                         state="disabled", padx=16, pady=12, highlightthickness=0)
        viewer.grid(row=0, column=1, sticky="nsew")
        self.configure_tags(viewer)

        def show(event=None):
            sel = lb.curselection()
            if not sel:
                return
            s = list(reversed(sessions))[sel[0]]
            viewer.config(state="normal")
            viewer.delete("1.0", "end")

            # Session header
            viewer.insert("end", f"Session started: {s['started']}\n", "session")
            viewer.insert("end", f"Saved at: {s['saved']}\n\n", "meta_other")

            for key, msgs in s["chats"].items():
                title = "🌐 All Chat" if key == ALL else f"👤 Private with {key}"
                viewer.insert("end", title + "\n", "head")
                for m in msgs:
                    side = "me" if m["from"] == self.name else "other"
                    who = "You" if side == "me" else m["from"]
                    viewer.insert("end", f'{who}   {m["time"]}\n', "meta_" + side)
                    viewer.insert("end", f'{m["text"]}\n\n', "text_" + side)
            viewer.config(state="disabled")

        lb.bind("<<ListboxSelect>>", show)

        def delete():
            sel = lb.curselection()
            if not sel:
                return
            idx = len(sessions) - 1 - sel[0]
            sessions.pop(idx)
            save_history(self.name, sessions)
            lb.delete(sel[0])
            viewer.config(state="normal")
            viewer.delete("1.0", "end")
            viewer.config(state="disabled")

        if not sessions:
            viewer.config(state="normal")
            viewer.insert("end", "\nNo saved chats yet.\n\n"
                                 "Click ＋ New Chat to save the current conversation into History.")
            viewer.config(state="disabled")

        flat_button(left, "🗑 Delete selected", delete, bg=CARD, fg=RED, size=9).pack(
            fill="x", padx=10, pady=12)

    def close(self):
        self.archive_session()
        self.connected = False
        try:
            self.sock.close()
        except OSError:
            pass
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    JoinScreen(root)
    root.mainloop()