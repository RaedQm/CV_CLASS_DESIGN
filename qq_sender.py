import os
import time
import json
import asyncio
import threading

import requests
import websockets
from dotenv import load_dotenv


load_dotenv()


class QQController:
    """
    QQ 官方机器人控制器。

    功能：
    1. send_text(text)：给 .env 中 QQ_USER_OPENID 对应的用户发送单聊消息
    2. start_command_listener()：后台监听 QQ 私聊消息
       - 收到“开始指令”：调用 on_start 回调
       - 收到“结束指令”：调用 on_stop 回调

    .env 需要：
    QQ_APP_ID=你的AppID
    QQ_APP_SECRET=你的AppSecret
    QQ_USER_OPENID=你的user_openid
    """

    def __init__(self, on_start=None, on_stop=None, on_log=None):
        self.app_id = os.getenv("QQ_APP_ID")
        self.app_secret = os.getenv("QQ_APP_SECRET")
        self.user_openid = os.getenv("QQ_USER_OPENID")

        if not self.app_id:
            raise ValueError("请在 .env 文件中填写 QQ_APP_ID")

        if not self.app_secret:
            raise ValueError("请在 .env 文件中填写 QQ_APP_SECRET")

        if not self.user_openid:
            raise ValueError("请在 .env 文件中填写 QQ_USER_OPENID")

        self.on_start = on_start
        self.on_stop = on_stop
        self.on_log = on_log

        self.access_token = None
        self.expire_time = 0
        self.latest_seq = None
        self.running = False

        self._token_lock = threading.Lock()

    def log(self, text):
        if self.on_log:
            self.on_log(text)
        else:
            print(text)

    def get_access_token(self):
        with self._token_lock:
            now = time.time()

            if self.access_token and now < self.expire_time - 60:
                return self.access_token

            url = "https://bots.qq.com/app/getAppAccessToken"
            payload = {
                "appId": self.app_id,
                "clientSecret": self.app_secret
            }

            response = requests.post(url, json=payload, timeout=10)

            try:
                result = response.json()
            except Exception:
                raise RuntimeError(
                    f"获取 AccessToken 失败，HTTP状态码: {response.status_code}, 返回内容: {response.text}"
                )

            if "access_token" not in result:
                raise RuntimeError(f"获取 AccessToken 失败: {result}")

            self.access_token = result["access_token"]
            expires_in = int(result.get("expires_in", 7200))
            self.expire_time = now + expires_in
            return self.access_token

    def get_headers(self):
        access_token = self.get_access_token()
        return {
            "Authorization": f"QQBot {access_token}",
            "Content-Type": "application/json"
        }

    def send_text(self, text):
        """
        给指定 user_openid 发送文本消息。
        """
        url = f"https://api.sgroup.qq.com/v2/users/{self.user_openid}/messages"

        payload = {
            "content": text,
            "msg_type": 0
        }

        response = requests.post(
            url,
            headers=self.get_headers(),
            json=payload,
            timeout=10
        )

        try:
            result = response.json()
        except Exception:
            result = {
                "http_status": response.status_code,
                "text": response.text
            }

        return response.status_code, result

    async def get_gateway_url(self):
        url = "https://api.sgroup.qq.com/gateway"

        response = requests.get(
            url,
            headers=self.get_headers(),
            timeout=10
        )

        result = response.json()

        if "url" not in result:
            raise RuntimeError(f"获取 WebSocket 网关地址失败: {result}")

        return result["url"]

    async def heartbeat(self, websocket, interval_ms):
        while self.running:
            await asyncio.sleep(interval_ms / 1000)
            payload = {
                "op": 1,
                "d": self.latest_seq
            }
            await websocket.send(json.dumps(payload))

    def find_user_openid(self, obj):
        if isinstance(obj, dict):
            if "user_openid" in obj and obj["user_openid"]:
                return obj["user_openid"]

            if "openid" in obj and obj["openid"]:
                return obj["openid"]

            for value in obj.values():
                result = self.find_user_openid(value)
                if result:
                    return result

        elif isinstance(obj, list):
            for item in obj:
                result = self.find_user_openid(item)
                if result:
                    return result

        return None

    async def listen_commands(self):
        while self.running:
            try:
                gateway_url = await self.get_gateway_url()

                async with websockets.connect(gateway_url) as websocket:
                    hello_text = await websocket.recv()
                    hello = json.loads(hello_text)
                    heartbeat_interval = hello["d"]["heartbeat_interval"]

                    asyncio.create_task(
                        self.heartbeat(websocket, heartbeat_interval)
                    )

                    access_token = self.get_access_token()

                    identify_payload = {
                        "op": 2,
                        "d": {
                            "token": f"QQBot {access_token}",
                            "intents": 1 << 25,
                            "shard": [0, 1],
                            "properties": {
                                "$os": "windows",
                                "$browser": "azure-kinect-pose",
                                "$device": "azure-kinect-pose"
                            }
                        }
                    }

                    await websocket.send(json.dumps(identify_payload))
                    self.log("QQ 指令监听已连接。")

                    while self.running:
                        message = await websocket.recv()
                        data = json.loads(message)

                        if data.get("s") is not None:
                            self.latest_seq = data["s"]

                        event_type = data.get("t")
                        event_data = data.get("d", {})

                        if event_type != "C2C_MESSAGE_CREATE":
                            continue

                        user_openid = self.find_user_openid(event_data)
                        content = str(event_data.get("content", "")).strip()

                        # 只响应 .env 里绑定的这个用户，避免其他人控制
                        if user_openid != self.user_openid:
                            continue

                        if content == "开始监听":
                            self.log("收到 QQ 开始指令。")
                            if self.on_start:
                                self.on_start()

                        elif content == "停止监听":
                            self.log("收到 QQ 停止指令。")
                            if self.on_stop:
                                self.on_stop()

            except Exception as e:
                self.log(f"QQ 指令监听异常，3 秒后重连：{e}")
                await asyncio.sleep(3)

    def start_command_listener(self):
        """
        在后台线程启动 QQ 指令监听。
        """
        if self.running:
            return

        self.running = True

        def runner():
            asyncio.run(self.listen_commands())

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()

    def stop_command_listener(self):
        self.running = False
