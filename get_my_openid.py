import os
import json
import asyncio
import requests
import websockets
from dotenv import load_dotenv


load_dotenv()

APP_ID = os.getenv("QQ_APP_ID")
APP_SECRET = os.getenv("QQ_APP_SECRET")


def get_access_token():
    url = "https://bots.qq.com/app/getAppAccessToken"

    payload = {
        "appId": APP_ID,
        "clientSecret": APP_SECRET
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

    return result["access_token"]


def get_gateway_url(access_token):
    url = "https://api.sgroup.qq.com/gateway"

    headers = {
        "Authorization": f"QQBot {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers, timeout=10)

    try:
        result = response.json()
    except Exception:
        raise RuntimeError(
            f"获取 WebSocket 网关失败，HTTP状态码: {response.status_code}, 返回内容: {response.text}"
        )

    if "url" not in result:
        raise RuntimeError(f"获取 WebSocket 网关失败: {result}")

    return result["url"]


async def send_heartbeat(websocket, interval_ms, get_latest_seq):
    while True:
        await asyncio.sleep(interval_ms / 1000)

        payload = {
            "op": 1,
            "d": get_latest_seq()
        }

        await websocket.send(json.dumps(payload))


def find_user_openid(obj):
    """
    从事件 JSON 里递归查找 user_openid。
    优先找 user_openid，其次找 openid。
    """
    if isinstance(obj, dict):
        # 优先直接找 user_openid
        if "user_openid" in obj and obj["user_openid"]:
            return obj["user_openid"]

        # 兼容旧字段 openid
        if "openid" in obj and obj["openid"]:
            return obj["openid"]

        # 递归查找子内容
        for value in obj.values():
            result = find_user_openid(value)
            if result:
                return result

    elif isinstance(obj, list):
        for item in obj:
            result = find_user_openid(item)
            if result:
                return result

    return None


def save_openid_to_env(openid):
    """
    把 openid 保存到当前 Python 文件同目录下的 .env 文件第三行。

    如果 .env 中已经有 QQ_USER_OPENID，则先删除旧的，再写入新的。
    """
    env_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        ".env"
    )

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
        lines = []

    # 删除旧的 QQ_USER_OPENID，避免重复写入
    lines = [
        line for line in lines
        if not line.strip().startswith("QQ_USER_OPENID=")
    ]

    # 保证至少有前两行
    while len(lines) < 2:
        lines.append("")

    # 第三行写入 QQ_USER_OPENID
    lines.insert(2, f"QQ_USER_OPENID={openid}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def main():
    if not APP_ID or not APP_SECRET:
        raise ValueError("请先在 .env 文件中填写 QQ_APP_ID 和 QQ_APP_SECRET")

    access_token = get_access_token()
    gateway_url = get_gateway_url(access_token)

    print("AccessToken 获取成功。")
    print("正在连接 QQ 机器人 WebSocket...")

    latest_seq = None

    def get_latest_seq():
        return latest_seq

    async with websockets.connect(gateway_url) as websocket:
        hello_text = await websocket.recv()
        hello = json.loads(hello_text)

        #print("WebSocket 已连接。")
        #print("收到 Hello：")
        #print(json.dumps(hello, ensure_ascii=False, indent=2))

        heartbeat_interval = hello["d"]["heartbeat_interval"]

        asyncio.create_task(
            send_heartbeat(websocket, heartbeat_interval, get_latest_seq)
        )

        identify_payload = {
            "op": 2,
            "d": {
                "token": f"QQBot {access_token}",
                "intents": 1 << 25,
                "shard": [0, 1],
                "properties": {
                    "$os": "windows",
                    "$browser": "cvclass",
                    "$device": "cvclass"
                }
            }
        }

        await websocket.send(json.dumps(identify_payload))

        print("-" * 60)
        print("现在请打开 QQ，给你的机器人发送一句话，例如：hello")
        print("收到事件后，程序会自动查找并打印你的 openid。")
        print("-" * 60)

        while True:
            message = await websocket.recv()
            data = json.loads(message)

            if data.get("s") is not None:
                latest_seq = data["s"]

            event_type = data.get("t")

            #print("\n收到事件类型：", event_type)
            #print(json.dumps(data, ensure_ascii=False, indent=2))

            openid = find_user_openid(data)

            if openid:
                print("\n" + "=" * 60)
                print("找到 openid：")
                print(openid)
                print("已保存到 .env 文件")
                save_openid_to_env(openid)
                print("=" * 60)
                break


if __name__ == "__main__":
    asyncio.run(main())