import os
import time
import json
import asyncio
import threading
import base64
from pathlib import Path

import requests
import websockets
from dotenv import load_dotenv


load_dotenv()


# 主指令
START_COMMANDS = {"开始监听"}
STOP_COMMANDS = {"停止监听"}
SCREENSHOT_COMMANDS = {"截图"}

COMMAND_TEMPLATE = (
    "指令错误。\n"
    "可用指令范本：\n"
    "1. 开始监听：开启 QQ 姿态监视\n"
    "2. 停止监听：关闭 QQ 姿态监视\n"
    "3. 截图：截取当前摄像机画面和骨架，并发送图片"
)


class QQController:
    """
    QQ 官方机器人控制器。

    功能：
    1. send_text(text)：给 .env 中 QQ_USER_OPENID 对应的用户发送单聊文本
    2. send_image(image_path)：给 .env 中 QQ_USER_OPENID 对应的用户发送本地图片
    3. start_command_listener()：后台监听 QQ 私聊指令
       - 开始监听 / 开始指令：调用 on_start
       - 停止监听 / 结束指令：调用 on_stop
       - 截图：调用 on_screenshot
       - 其他指令：回复指令错误和指令范本

    .env 需要：
    QQ_APP_ID=你的AppID
    QQ_APP_SECRET=你的AppSecret
    QQ_USER_OPENID=你的user_openid
    """

    def __init__(self, on_start=None, on_stop=None, on_screenshot=None, on_log=None):
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
        self.on_screenshot = on_screenshot
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

    def upload_image(self, image_path):
        """
        上传/注册本地图片，返回 file_info。
        QQ 官方机器人单聊图片接口使用 /v2/users/{openid}/files。
        """
        image_path = Path(image_path)

        if not image_path.exists():
            raise FileNotFoundError(f"图片不存在：{image_path}")

        with open(image_path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode("utf-8")

        url = f"https://api.sgroup.qq.com/v2/users/{self.user_openid}/files"

        payload = {
            "file_type": 1,
            "file_data": file_data,
            "srv_send_msg": False
        }

        response = requests.post(
            url,
            headers=self.get_headers(),
            json=payload,
            timeout=30
        )

        try:
            result = response.json()
        except Exception:
            raise RuntimeError(
                f"上传图片失败，HTTP状态码: {response.status_code}, 返回内容: {response.text}"
            )

        if "file_info" not in result:
            raise RuntimeError(f"上传图片失败: {result}")

        return result["file_info"], result

    def send_image(self, image_path):
        """
        发送本地图片给 QQ_USER_OPENID。

        过程：
        1. 上传/注册图片，拿到 file_info
        2. 使用 msg_type=7 发送富媒体消息
        """
        file_info, upload_result = self.upload_image(image_path)

        url = f"https://api.sgroup.qq.com/v2/users/{self.user_openid}/messages"

        payload = {
            "msg_type": 7,
            "media": {
                "file_info": file_info
            }
        }

        response = requests.post(
            url,
            headers=self.get_headers(),
            json=payload,
            timeout=20
        )

        try:
            result = response.json()
        except Exception:
            result = {
                "http_status": response.status_code,
                "text": response.text
            }

        # 兼容性兜底：如果某些环境不接受 media 对象，就再尝试 media 直接传 file_info。
        if response.status_code != 200 or (
            isinstance(result, dict)
            and result.get("code")
            and result.get("code") != 0
        ):
            fallback_payload = {
                "msg_type": 7,
                "media": file_info
            }

            fallback_response = requests.post(
                url,
                headers=self.get_headers(),
                json=fallback_payload,
                timeout=20
            )

            try:
                fallback_result = fallback_response.json()
            except Exception:
                fallback_result = {
                    "http_status": fallback_response.status_code,
                    "text": fallback_response.text
                }

            return fallback_response.status_code, {
                "upload": upload_result,
                "send": fallback_result,
                "fallback_used": True
            }

        return response.status_code, {
            "upload": upload_result,
            "send": result,
            "fallback_used": False
        }

    async def reply_text(self, text):
        """
        在异步监听里发送文本，避免同步 requests 长时间阻塞事件循环。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.send_text, text)

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

    async def handle_user_command(self, content):
        """
        处理用户发来的 QQ 指令。
        """
        if content in START_COMMANDS:
            self.log("收到 QQ 开始监听指令。")
            if self.on_start:
                self.on_start()
            return

        if content in STOP_COMMANDS:
            self.log("收到 QQ 停止监听指令。")
            if self.on_stop:
                self.on_stop()
            return

        if content in SCREENSHOT_COMMANDS:
            self.log("收到 QQ 截图指令。")
            if self.on_screenshot:
                self.on_screenshot()
            else:
                await self.reply_text("截图功能未连接到窗口。")
            return

        # 其他任何非空内容，都回复指令错误和范本。
        if content:
            self.log(f"收到未知 QQ 指令：{content}")
            await self.reply_text(COMMAND_TEMPLATE)

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

                        await self.handle_user_command(content)

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
