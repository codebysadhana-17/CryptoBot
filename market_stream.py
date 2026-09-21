"""Public WebSocket market-data layer.

The execution engine remains REST/order-book based for executable depth and
exchange-specific validation. WebSocket BBO data is used as a low-latency
trigger/cache, with REST depth validation before any real order.
"""
import json
import threading
import time
from typing import Dict

import config

try:
    import websocket
except ImportError:  # pragma: no cover
    websocket = None


class PublicBBOStream:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[str, dict] = {}
        self._threads = {}
        self._started = False

    def start(self):
        if websocket is None or self._started:
            return False
        self._started = True
        targets = {
            "Binance": self._binance_loop,
            "Bybit": self._bybit_loop,
            "KuCoin": self._kucoin_loop,
        }
        for name, target in targets.items():
            if name in config.SUPPORTED_EXCHANGES:
                t = threading.Thread(target=target, name=f"ws-{name.lower()}", daemon=True)
                self._threads[name] = t
                t.start()
        return True

    def snapshot(self) -> Dict[str, dict]:
        with self._lock:
            now = time.time()
            out = {}
            for name, item in self._data.items():
                x = dict(item)
                x["age_ms"] = max(0.0, (now - x["received_at"]) * 1000.0)
                out[name] = x
            return out

    def _set(self, name, bid, ask, source):
        try:
            bid, ask = float(bid), float(ask)
            if bid <= 0 or ask <= 0 or ask < bid:
                return
        except Exception:
            return
        with self._lock:
            self._data[name] = {
                "bid": bid,
                "ask": ask,
                "last": (bid + ask) / 2.0,
                "received_at": time.time(),
                "source": source,
            }

    def _connect_loop(self, name, url, on_message, ping_interval=20):
        while True:
            try:
                ws = websocket.create_connection(
                    url,
                    timeout=max(5, int(config.REQUEST_TIMEOUT_MS / 1000)),
                    enable_multithread=True,
                    origin=None,
                )
                ws.settimeout(max(5, int(config.REQUEST_TIMEOUT_MS / 1000)))
                while True:
                    raw = ws.recv()
                    if raw is None:
                        raise RuntimeError("WebSocket closed")
                    on_message(raw)
            except Exception as exc:
                print(f"[WS {name}] reconnecting: {str(exc)[:160]}", flush=True)
                time.sleep(2.0)

    def _binance_loop(self):
        if websocket is None:
            return
        url = "wss://stream.binance.com:9443/ws/ethusdt@bookTicker"
        def handle(raw):
            data = json.loads(raw)
            self._set("Binance", data.get("b"), data.get("a"), "binance-bookTicker")
        self._connect_loop("Binance", url, handle)

    def _bybit_loop(self):
        if websocket is None:
            return
        url = "wss://stream.bybit.com/v5/public/spot"
        def handle(raw):
            data = json.loads(raw)
            if data.get("op") == "pong":
                return
            if data.get("topic") != "orderbook.1.ETHUSDT":
                return
            result = data.get("data") or {}
            bids = result.get("b") or []
            asks = result.get("a") or []
            if bids and asks:
                self._set("Bybit", bids[0][0], asks[0][0], "bybit-orderbook")
        while True:
            try:
                ws = websocket.create_connection(url, timeout=10, origin=None)
                ws.send(json.dumps({"op": "subscribe", "args": ["orderbook.1.ETHUSDT"]}))
                last_ping = time.time()
                while True:
                    if time.time() - last_ping > 15:
                        ws.send(json.dumps({"op": "ping"}))
                        last_ping = time.time()
                    raw = ws.recv()
                    if raw is not None:
                        handle(raw)
            except Exception as exc:
                print(f"[WS Bybit] reconnecting: {str(exc)[:160]}", flush=True)
                time.sleep(2.0)

    def _kucoin_loop(self):
        # KuCoin requires a short-lived public token before opening its socket.
        # REST is used only for connection bootstrap; live quotes then arrive
        # through the WebSocket channel.
        if websocket is None:
            return
        import requests
        while True:
            try:
                r = requests.post("https://api.kucoin.com/api/v1/bullet-public", timeout=10)
                r.raise_for_status()
                payload = r.json().get("data") or {}
                token = payload["token"]
                server = payload["instanceServers"][0]
                endpoint = server["endpoint"]
                connect_id = str(int(time.time() * 1000))
                url = f"{endpoint}?token={token}&connectId={connect_id}"
                ws = websocket.create_connection(url, timeout=15, origin=None)
                ws.send(json.dumps({
                    "id": connect_id,
                    "type": "subscribe",
                    "topic": "/market/ticker:ETH-USDT",
                    "privateChannel": False,
                    "response": True,
                }))
                last_ping = time.time()
                while True:
                    if time.time() - last_ping > 15:
                        ws.send(json.dumps({"id": str(int(time.time()*1000)), "type": "ping"}))
                        last_ping = time.time()
                    raw = ws.recv()
                    if not raw:
                        continue
                    data = json.loads(raw)
                    if data.get("type") != "message":
                        continue
                    subject = data.get("subject")
                    if subject != "trade.ticker":
                        continue
                    change = data.get("data") or {}
                    self._set("KuCoin", change.get("bestBid"), change.get("bestAsk"), "kucoin-ticker")
            except Exception as exc:
                print(f"[WS KuCoin] reconnecting: {str(exc)[:160]}", flush=True)
                time.sleep(2.0)


public_bbo_stream = PublicBBOStream()
