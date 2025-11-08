import json, time, logging
import threading
import paho.mqtt.client as mqtt

class MQTTRouter:
    def __init__(self, name: str, cfg: dict, on_cmd: callable):
        self.name = name
        self.cfg = cfg
        self.on_cmd = on_cmd
        # create client and register callbacks for better diagnostics
        self._client = mqtt.Client(client_id=cfg.get("client_id","wayfarer"))
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        # add on_connect and on_log to capture broker reason codes and debugging info
        self._client.on_connect = self._on_connect
        self._client.on_log = self._on_log
        self._lock = threading.Lock()
        self._run = False
        self._connected = False
        self._retry_backoff = 1.0  # seconds (could grow if desired)
        self._threads = []

    def start(self):
        self._run = True
        t = threading.Thread(target=self._connect_loop, daemon=False)
        t.start()
        self._threads.append(t)

    def _connect_loop(self):
        host = self.cfg["host"]
        port = int(self.cfg.get("port",1883))
        while self._run:
            if not self._connected:
                try:
                    logging.info(f"[mqtt:{self.name}] attempting connect_async {host}:{port}")
                    # Use connect_async + loop_start to avoid races and rely on on_connect callback
                    # Apply username/password if provided in cfg
                    username = self.cfg.get("username")
                    password = self.cfg.get("password")
                    if username:
                        try:
                            self._client.username_pw_set(username, password)
                        except Exception:
                            pass
                    # Preferred non-blocking connect
                    try:
                        self._client.connect_async(host, port)
                    except AttributeError:
                        # Older paho versions may not have connect_async; fallback to connect()
                        rc = self._client.connect(host, port)
                        if rc == 0:
                            logging.info(f"[mqtt:{self.name}] connect() returned rc=0; starting loop")
                        else:
                            logging.warning(f"[mqtt:{self.name}] connect rc={rc}; retry in {self._retry_backoff:.1f}s")
                            time.sleep(self._retry_backoff)
                            continue
                    # Start the network loop and wait for on_connect to set _connected
                    self._client.loop_start()
                    # wait a short period for connection to be established; on_connect will set _connected
                    wait_for = 5.0
                    start = time.time()
                    while self._run and not self._connected and (time.time() - start) < wait_for:
                        time.sleep(0.1)
                    if self._connected:
                        self._retry_backoff = 1.0
                        logging.info(f"[mqtt:{self.name}] connected (on_connect confirmed)")
                    else:
                        logging.warning(f"[mqtt:{self.name}] connect not confirmed within {wait_for}s; will retry in {self._retry_backoff:.1f}s")
                        try:
                            self._client.loop_stop()
                        except Exception:
                            pass
                        time.sleep(self._retry_backoff)
                except Exception as e:
                    logging.warning(f"[mqtt:{self.name}] connect error: {e}; retry in {self._retry_backoff:.1f}s")
                    time.sleep(self._retry_backoff)
            else:
                time.sleep(1.0)

    def _on_connect(self, client, userdata, flags, rc):
        # paho on_connect signature: client, userdata, flags, rc
        if rc == 0:
            logging.info(f"[mqtt:{self.name}] on_connect rc=0 (success)")
            self._connected = True
        else:
            logging.warning(f"[mqtt:{self.name}] on_connect rc={rc}")

    def _on_log(self, client, userdata, level, buf):
        # Emit paho debug logs to bridge logger when useful
        try:
            logging.debug(f"[mqtt:{self.name}] paho_log level={level} msg={buf}")
        except Exception:
            pass

    def _on_disconnect(self, client, userdata, rc):
        if not self._run:
            return
        if rc != 0:
            logging.warning(f"[mqtt:{self.name}] unexpected disconnect rc={rc}; will retry")
        else:
            logging.info(f"[mqtt:{self.name}] clean disconnect")
        self._connected = False
        try:
            self._client.loop_stop()
        except Exception:
            pass

    def stop(self):
        self._run = False
        try:
            self._client.disconnect()
        except Exception:
            pass
        try:
            self._client.loop_stop()
        except Exception:
            pass
        self._connected = False
        # Join internal threads
        for thr in getattr(self, "_threads", []):
            try:
                thr.join(timeout=2.0)
            except Exception:
                pass

    def publish_telem(self, topic: str, payload: dict, qos: int = 0, retain: bool = False):
        if not self._connected:
            # observable drop (not connected)
            logging.warning(f"[mqtt:{self.name}] drop publish (not connected) topic={topic}")
            return
        data = json.dumps(payload, separators=(",",":"))
        with self._lock:
            self._client.publish(topic, data, qos=qos, retain=retain)

    def subscribe_cmd(self, topic: str):
        if not self._connected:
            logging.debug(f"[mqtt:{self.name}] defer subscribe (not connected) topic={topic}")
            # Could queue subscriptions; minimal: retry when connected
            threading.Thread(target=self._deferred_sub, args=(topic,), daemon=True).start()
            return
        self._client.subscribe(topic)

    def _deferred_sub(self, topic: str):
        # wait until connected then subscribe
        while self._run and not self._connected:
            time.sleep(0.5)
        if self._run and self._connected:
            logging.info(f"[mqtt:{self.name}] deferred subscribe now active topic={topic}")
            self._client.subscribe(topic)

    def _on_message(self, _client, _userdata, msg):
        # delegate to core for routing to transports
        self.on_cmd(msg.topic, msg.payload)
