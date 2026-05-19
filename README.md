# Azure Kinect 人体姿态检测与 QQ 监视系统 v6

本版本在 v5 基础上新增 **自动启动 MediaMTX**：

- QQ 发送 `直播`：程序会自动检查 MediaMTX 是否运行；如果没有运行，会自动启动 `mediamtx.exe`。
- 然后程序启动 FFmpeg H.264 推流、启动 ngrok 公网隧道、临时生成 Basic Auth 用户名和密钥，并把观看地址回复给你。
- QQ 发送 `结束直播`：程序停止 FFmpeg 推流和 ngrok 隧道；如果 MediaMTX 是本程序自动启动的，也会一并关闭。
- 如果你已经手动启动了 MediaMTX，本程序会复用现有服务，不会在停止直播时关闭你手动启动的 MediaMTX。

直播内容为当前窗口里的 **Azure Kinect 彩色图 + 人体骨架叠加图**。观看者不需要安装软件，只需要浏览器打开链接，并输入你收到的用户名和临时密钥。

---

## 文件结构

```text
azure_kinect_pose_qq_project_v6
├── main.py
├── app_window.py
├── pose_detector.py
├── qq_sender.py
├── h264_streamer.py
├── live_stream_manager.py
├── get_my_openid.py
├── requirements.txt
├── README.md
└── .env
```

---

## 原有功能

1. 左侧窗口实时显示 Azure Kinect 正常 RGB 彩色图 + 骨架。
2. 右侧文字栏显示时间、检测人数、每个人的姿态、QQ 监视状态、直播状态、跌倒报警状态。
3. 本地按钮：
   - 截图
   - 退出
   - 开始QQ监视
   - 关闭QQ监视
4. QQ 指令：
   - `开始监听`：开启 QQ 姿态监视
   - `停止监听`：关闭 QQ 姿态监视
   - `截图`：保存当前画面并发送图片
   - `直播`：自动启动 MediaMTX、开启公网直播并返回观看地址、用户名、临时密钥
   - `结束直播`：停止公网直播
5. 未知 QQ 指令会回复指令范本。
6. 疑似跌倒会自动截图并通过 QQ 报警，不需要开启 QQ 监视。

---

## .env 示例

你的 `.env` 仍然放在项目同目录下：

```env
QQ_APP_ID=你的AppID
QQ_APP_SECRET=你的AppSecret
QQ_USER_OPENID=你的user_openid
```

可选直播参数：

```env
FFMPEG_PATH=ffmpeg
NGROK_PATH=ngrok

# 如果 mediamtx 已加入 Path，可以写 mediamtx；否则建议写完整路径。
MEDIAMTX_PATH=D:/tools/mediamtx/mediamtx.exe

# 1 表示直播启动时自动启动 MediaMTX；0 表示仍然要求你手动启动。
LIVE_AUTO_START_MEDIAMTX=1

LIVE_RTMP_URL=rtmp://127.0.0.1/live/kinect
LIVE_HLS_PATH=/live/kinect
LIVE_NGROK_HTTP_PORT=8888
LIVE_WIDTH=960
LIVE_HEIGHT=540
LIVE_FPS=10
LIVE_BITRATE=600k
```

如果 `ffmpeg`、`ngrok`、`mediamtx` 都已经加入系统 Path，可选路径参数可以不写。更稳妥的做法是写完整路径：

```env
MEDIAMTX_PATH=D:/tools/mediamtx/mediamtx.exe
```

注意路径建议使用 `/`，不要写成单个反斜杠 `\`。

---

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

系统软件需要你已经安装好：

```text
FFmpeg
MediaMTX
ngrok
```

并且至少满足：

```bat
ffmpeg -version
ngrok version
```

能在终端正常输出。MediaMTX 如果没有加入 Path，就需要在 `.env` 里填写 `MEDIAMTX_PATH`。

ngrok 还需要提前执行：

```bat
ngrok config add-authtoken 你的ngrok_token
```

---

## 启动方式

### 1. 启动项目

```bat
cd D:\codes_yuanma\vscode\CV_EXP
python main.py
```

现在不需要你手动启动 `mediamtx.exe`。当你发送 `直播` 时，程序会自动启动它。

### 2. 在 QQ 给机器人发送

```text
直播
```

如果成功，机器人会回复类似：

```text
【Azure Kinect 直播】
开始直播。
观看地址：https://xxxx.ngrok-free.app/live/kinect
用户名：viewer
临时密钥：xxxxxxxxxxxxxxxxxx

说明：浏览器打开观看地址后，会弹出登录框；输入上面的用户名和临时密钥即可观看。
```

### 3. 停止直播

在 QQ 给机器人发送：

```text
结束直播
```

机器人会回复：

```text
【Azure Kinect 直播】
直播已停止。
```

如果 MediaMTX 是本程序自动启动的，它也会被关闭。

---

## 观看方式

观看者打开机器人发来的 `观看地址`，浏览器会弹出 Basic Auth 登录框：

```text
用户名：viewer
密码：机器人发来的临时密钥
```

输入正确后即可观看。

注意：HLS 直播通常会有几秒延迟，刚打开页面时出现加载圈是正常的，等待 5 到 20 秒。

---

## 安全说明

本项目使用 ngrok Traffic Policy 的 Basic Auth。含义是：

```text
只有同时拥有：
1. 观看地址
2. 用户名
3. 临时密钥

的人才能观看。
```

每次你发送 `直播` 启动直播时，程序都会临时生成新的密钥。发送 `结束直播` 后，ngrok 隧道关闭，原来的公网链接随之失效。

---

## 常见问题

### 1. 直播启动失败：找不到 MediaMTX

在 `.env` 里填写完整路径：

```env
MEDIAMTX_PATH=D:/tools/mediamtx/mediamtx.exe
LIVE_AUTO_START_MEDIAMTX=1
```

然后重新运行 `python main.py`。

### 2. 直播启动失败：等待 MediaMTX RTMP 端口 1935 超时

可能是：

```text
1. MEDIAMTX_PATH 写错
2. mediamtx.yml 配置有问题
3. 1935 端口被其他程序占用
4. MediaMTX 启动后立即退出
```

可以在终端手动验证：

```bat
D:\tools\mediamtx\mediamtx.exe
```

### 3. 直播启动失败：等待 ngrok 公网地址超时

检查：

```bat
ngrok version
ngrok config add-authtoken 你的token
```

并确认没有其他 ngrok 进程占用本地 API 端口。

### 4. 页面一直加载圈

直播启动后，本机也可以测试：

```text
http://127.0.0.1:8888/live/kinect
```

如果本机也看不到，说明 FFmpeg 到 MediaMTX 的推流链路有问题。

### 5. 画面卡顿

降低码率和分辨率：

```env
LIVE_WIDTH=640
LIVE_HEIGHT=360
LIVE_FPS=8
LIVE_BITRATE=300k
```

---

## 调试：手动测试 MediaMTX 和 FFmpeg

如果自动直播失败，可以手动测试链路。

先启动 MediaMTX：

```bat
cd D:\tools\mediamtx
mediamtx.exe
```

再打开另一个终端推测试源：

```bat
ffmpeg -re -f lavfi -i testsrc=size=960x540:rate=10 ^
-c:v libx264 -preset veryfast -tune zerolatency ^
-b:v 600k -maxrate 600k -bufsize 1200k ^
-g 20 -keyint_min 20 -sc_threshold 0 ^
-pix_fmt yuv420p ^
-f flv rtmp://127.0.0.1/live/kinect
```

本机浏览器访问：

```text
http://127.0.0.1:8888/live/kinect
```
