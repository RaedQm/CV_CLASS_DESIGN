# Azure Kinect 人体姿态检测与跌倒报警系统

本项目是一个基于 **Azure Kinect DK** 的本地端监测系统，主要功能包括人体姿态检测、疑似跌倒报警、QQ 机器人远程控制、截图发送、低延迟直播，以及截图时的人脸识别。

系统使用 Python 开发，界面基于 PyQt5，人体姿态检测基于 Azure Kinect Body Tracking，人脸识别基于 OpenCV YuNet + SFace，数据存储使用 SQLite。

---

## 1. 项目功能

### 1.1 实时人体姿态检测

系统会持续读取 Azure Kinect DK 的彩色图像和人体骨架信息，并在界面中显示：

- Azure Kinect 实时画面
- 人体骨架叠加结果
- 当前检测人数
- 每个人的姿态状态
- 当前系统时间
- QQ 监视状态
- 直播状态

当前支持的姿态包括但不限于：

- 站立
- 举左手
- 举右手
- 双手举起
- 左手平举
- 右手平举
- 双手平举
- 下蹲
- 下蹲/坐姿
- 弯腰
- 疑似跌倒

---

### 1.2 疑似跌倒自动报警

当系统检测到有人处于“疑似跌倒”状态时，会自动触发跌倒报警。

报警逻辑包括：

- 自动截图
- 截图时进行人脸识别
- 将人脸识别结果画到截图上
- 通过 QQ 机器人发送报警文本
- 通过 QQ 机器人发送报警截图
- 同一段连续跌倒只报警一次
- 设置冷却时间，避免误判时频繁报警

默认跌倒报警冷却时间为：

```python
FALL_ALERT_COOLDOWN_SECONDS = 30.0
```

需要注意：跌倒报警不会自动开启 QQ 姿态监听，它只是自动发送一次报警提醒。

---

### 1.3 截图与人脸识别

当前项目中，所有截图都会自动进行人脸识别，包括：

- 点击界面上的“截图”按钮
- QQ 发送“截图”指令
- 检测到疑似跌倒后自动截图

截图时系统会：

1. 获取当前画面
2. 使用 YuNet 检测人脸
3. 使用 SFace 提取人脸特征
4. 与 SQLite 数据库中的已录入人脸进行比对
5. 在图片上画出人脸框、姓名和相似度
6. 保存截图
7. 根据触发来源决定是否通过 QQ 发送

如果数据库中没有匹配的人脸，会显示为：

```text
Unknown
```

---

### 1.4 本地人脸识别

人脸识别完全在本地完成，不依赖云服务。

使用组件：

- OpenCV YuNet：人脸检测
- OpenCV SFace：人脸特征提取
- SQLite：保存已录入人脸特征

人脸录入后，数据默认保存在：

```text
data/faces.db
```

数据库中保存的是人脸特征向量，不是原始人脸图片。

同一个人可以录入多张脸，例如正脸、侧脸、不同光照和不同距离。数据库中会为每次录入保存一条特征记录。

---

### 1.5 QQ 机器人控制

系统支持通过 QQ 机器人接收远程指令。

可用指令：

```text
开始监听
停止监听
截图
直播
结束直播
```

指令说明：

| 指令 | 功能 |
|---|---|
| 开始监听 | 开启 QQ 姿态变化推送 |
| 停止监听 | 关闭 QQ 姿态变化推送 |
| 截图 | 截取当前画面，做人脸识别，并通过 QQ 发送截图 |
| 直播 | 开启实时直播，并返回观看地址 |
| 结束直播 | 停止当前直播 |

QQ 相关配置写在 `.env` 文件中。

---

### 1.6 实时直播

系统支持将当前画面推流到 MediaMTX，并通过浏览器观看。

直播链路大致为：

```text
OpenCV 当前画面
→ FFmpeg 编码 H.264
→ RTMP 推送到 MediaMTX
→ MediaMTX 转为 HLS 或 WebRTC
→ 浏览器观看
```

项目中默认推流地址为：

```text
rtmp://127.0.0.1/live/kinect
```

如果使用 HLS，默认端口通常是：

```text
8888
```

如果使用 WebRTC，默认端口通常是：

```text
8889
```

WebRTC 延迟更低，但需要额外注意局域网、防火墙、UDP 端口和 MediaMTX 配置。

---

## 2. 项目结构

项目主要文件如下：

```text
CV_CLASS_DESIGN/
├─ main.py
├─ app_window.py
├─ pose_detector.py
├─ qq_sender.py
├─ live_stream_manager.py
├─ h264_streamer.py
├─ get_my_openid.py
├─ face_engine.py
├─ face_db.py
├─ enroll_face.py
├─ download_face_models.py
├─ requirements_face.txt
├─ README.md
├─ .env
│
├─ models/
│  ├─ face_detection_yunet_2023mar.onnx
│  └─ face_recognition_sface_2021dec.onnx
│
├─ data/
│  └─ faces.db
│
├─ screenshots/
│  └─ screenshot_xxx.jpg
│
└─ live_runtime/
```

---

## 3. 主要文件说明

### main.py

程序入口文件，负责启动 PyQt5 应用窗口。

运行主程序时执行：

```bash
python main.py
```

---

### app_window.py

主界面文件，负责：

- 显示实时画面
- 显示姿态信息
- 显示运行日志
- 响应按钮操作
- 启动摄像头线程
- 管理 QQ 控制器
- 管理直播功能
- 处理截图
- 处理跌倒报警
- 在截图时调用人脸识别

这是项目的主要业务调度文件。

---

### pose_detector.py

Azure Kinect 姿态检测模块，负责：

- 初始化 Azure Kinect
- 初始化 Body Tracking
- 读取彩色图像
- 读取人体骨架
- 判断人体姿态
- 生成叠加骨架后的显示画面
- 返回姿态检测信息

---

### face_engine.py

人脸识别核心模块，负责：

- 加载 YuNet 人脸检测模型
- 加载 SFace 人脸识别模型
- 检测画面中的人脸
- 提取人脸特征向量
- 与数据库中的人脸特征进行比对
- 在截图上绘制人脸框、姓名和相似度

当前图像中文绘制使用 Pillow，因此中文姓名不会显示成问号。

---

### face_db.py

人脸数据库模块，负责：

- 创建 SQLite 数据库
- 保存人脸特征
- 读取所有已录入人脸
- 将 NumPy 特征向量保存为 SQLite BLOB

默认数据库文件：

```text
data/faces.db
```

---

### enroll_face.py

人脸录入脚本。

用于提前录入用户人脸。

示例：

```bash
python enroll_face.py --user-id 001 --name 张三 --camera 0
```

运行后：

- 按空格保存当前检测到的人脸
- 按 ESC 退出
- 建议每个人录入 5 到 10 张不同角度、光照、距离的人脸

---

### qq_sender.py

QQ 机器人控制模块，负责：

- 获取 QQ Bot AccessToken
- 监听 QQ 私聊指令
- 发送文本消息
- 上传并发送图片
- 调用主窗口中的功能回调

---

### get_my_openid.py

用于获取自己的 QQ `user_openid`。

首次配置 QQ 机器人时，需要运行该脚本获取 openid，然后写入 `.env`。

---

### live_stream_manager.py

直播管理模块，负责：

- 检查或启动 MediaMTX
- 启动 FFmpeg 推流
- 启动 ngrok 隧道
- 生成观看地址
- 生成临时访问凭据
- 停止直播相关进程

---

### h264_streamer.py

H.264 推流模块，负责：

- 接收 OpenCV 图像帧
- 调用 FFmpeg
- 将原始 BGR 图像编码为 H.264
- 通过 RTMP 推送到 MediaMTX

---

## 4. 环境要求

推荐环境：

```text
Windows 10 / Windows 11
Python 3.9 - 3.11
Azure Kinect DK
Azure Kinect Sensor SDK
Azure Kinect Body Tracking SDK
FFmpeg
MediaMTX
```

Python 依赖包括：

```text
PyQt5
opencv-contrib-python
numpy
pykinect-azure
requests
websockets
python-dotenv
qrcode
Pillow
```

---

## 5. 安装依赖

建议在 Conda 环境或 venv 虚拟环境中运行。

### 5.1 创建环境

```bash
conda create -n CVClass python=3.11
conda activate CVClass
```

### 5.2 安装依赖

为了兼容 `pykinect-azure`，建议固定 NumPy 版本，不要使用 NumPy 2.x：

```bash
pip uninstall opencv-python opencv-contrib-python numpy -y
pip install numpy==1.26.4
pip install opencv-contrib-python==4.10.0.84
pip install PyQt5 requests websockets python-dotenv qrcode Pillow
pip install pykinect-azure==0.1.0
```

如果项目中提供了 `requirements_face.txt`，也可以使用：

```bash
pip install -r requirements_face.txt
```

---

## 6. 下载人脸识别模型

需要两个 ONNX 模型：

```text
face_detection_yunet_2023mar.onnx
face_recognition_sface_2021dec.onnx
```

放到：

```text
models/
```

最终目录应为：

```text
models/
├─ face_detection_yunet_2023mar.onnx
└─ face_recognition_sface_2021dec.onnx
```

可以运行脚本下载：

```bash
python download_face_models.py
```

如果脚本下载失败，也可以手动下载。

GitHub 地址：

```text
https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
https://github.com/opencv/opencv_zoo/blob/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
```

下载时需要点击 GitHub 页面中的 Download raw file。

---

## 7. 配置 .env

项目根目录下需要创建 `.env` 文件。

示例：

```env
QQ_APP_ID=你的QQ机器人AppID
QQ_APP_SECRET=你的QQ机器人AppSecret
QQ_USER_OPENID=你的user_openid

MEDIAMTX_PATH=D:/tools/mediamtx/mediamtx.exe
LIVE_AUTO_START_MEDIAMTX=1
LIVE_RTMP_URL=rtmp://127.0.0.1/live/kinect
LIVE_HLS_PATH=/live/kinect
LIVE_NGROK_HTTP_PORT=8889
LIVE_WIDTH=960
LIVE_HEIGHT=540
LIVE_FPS=10
LIVE_BITRATE=600k
FFMPEG_PATH=ffmpeg
NGROK_PATH=ngrok
```

其中 QQ 相关配置是发送消息和接收指令必须的。

如果暂时不使用 QQ 功能，主程序仍可进行本地姿态检测、界面显示和截图，但 QQ 报警和远程指令不可用。

---

## 8. 获取 QQ_USER_OPENID

首次使用 QQ 机器人时，需要获取自己的 `QQ_USER_OPENID`。

运行：

```bash
python get_my_openid.py
```

然后给机器人发送一条消息，例如：

```text
hello
```

程序收到事件后会打印 openid，并自动写入 `.env`。

---

## 9. 录入人脸

在运行主程序前，建议先录入人脸。

示例：

```bash
python enroll_face.py --user-id 001 --name 张三 --camera 0
```

操作方式：

- 摄像头打开后，保持画面中只有一个人脸
- 按空格保存当前人脸
- 按 ESC 退出

建议每个人录入：

```text
正脸 2 张
轻微左侧脸 2 张
轻微右侧脸 2 张
不同光照 2 张
不同距离 2 张
```

录入后数据会保存到：

```text
data/faces.db
```

---

## 10. 运行主程序

确保 Azure Kinect DK 已连接，并且官方 Viewer 可以正常打开相机后，运行：

```bash
python main.py
```

程序启动后会显示主界面。

界面中包括：

- 实时画面区域
- 姿态信息区域
- 运行日志区域
- 控制按钮区域

可用按钮：

| 按钮 | 功能 |
|---|---|
| 截图 | 保存当前画面并进行人脸识别 |
| 退出 | 关闭程序 |
| 开始QQ监视 | 开始向 QQ 推送姿态变化 |
| 关闭QQ监视 | 停止 QQ 姿态变化推送 |

---

## 11. 截图保存位置

截图默认保存在：

```text
screenshots/
```

截图文件名通常包含时间戳，例如：

```text
screenshots/screenshot_20260529_193000.jpg
```

截图会包含：

- 当前画面
- 骨架叠加结果
- 人脸检测框
- 姓名
- 相似度

---

## 12. 人脸识别数据库说明

所有录入的人脸都保存在同一个 SQLite 文件中：

```text
data/faces.db
```

数据库表为：

```text
faces
```

主要字段：

| 字段 | 说明 |
|---|---|
| id | 自增主键 |
| user_id | 用户 ID |
| name | 用户姓名 |
| embedding | 人脸特征向量，BLOB 格式 |
| dim | 特征维度 |
| created_at | 创建时间 |

同一个人可以有多条记录。

例如：

```text
user_id=001, name=张三, embedding=第1张人脸特征
user_id=001, name=张三, embedding=第2张人脸特征
user_id=001, name=张三, embedding=第3张人脸特征
```

识别时，系统会将当前截图中的人脸与数据库中的所有特征进行比对，选择相似度最高的一条。如果相似度超过阈值，则显示对应姓名；否则显示 `Unknown`。

---

## 13. 直播使用说明

### 13.1 本机或局域网观看

如果使用 WebRTC 低延迟观看，通常访问：

```text
http://电脑局域网IP:8889/live/kinect
```

例如：

```text
http://172.18.44.59:8889/live/kinect
```

如果使用 HLS 观看，通常访问：

```text
http://电脑局域网IP:8888/live/kinect
```

HLS 延迟更高，但兼容性更好。

---

### 13.2 WebRTC 注意事项

WebRTC 低延迟，但需要确保：

- MediaMTX 的 8889 TCP 端口可访问
- MediaMTX 的 8189 UDP 端口可访问
- Windows 防火墙放行相关端口
- 手机和电脑在同一局域网
- 路由器没有开启客户端隔离
- `mediamtx.yml` 中配置了正确的 `webrtcAdditionalHosts`

Windows 防火墙可执行：

```powershell
New-NetFirewallRule -DisplayName "MediaMTX WebRTC HTTP 8889" -Direction Inbound -Protocol TCP -LocalPort 8889 -Action Allow
New-NetFirewallRule -DisplayName "MediaMTX WebRTC UDP 8189" -Direction Inbound -Protocol UDP -LocalPort 8189 -Action Allow
```

MediaMTX 配置示例：

```yaml
webrtc: true
webrtcAddress: :8889
webrtcLocalUDPAddress: :8189
webrtcLocalTCPAddress: ''
webrtcAdditionalHosts:
  - 你的电脑局域网IP
```

---

## 14. 常见问题

### 14.1 安装 opencv-contrib-python 后 Kinect 代码报错

通常是 NumPy 被自动升级到了 2.x。

修复方式：

```bash
pip uninstall opencv-python opencv-contrib-python numpy -y
pip install numpy==1.26.4
pip install opencv-contrib-python==4.10.0.84
```

然后测试：

```bash
python -c "import cv2, numpy; import pykinect_azure; print(cv2.__version__, numpy.__version__)"
```

---

### 14.2 中文姓名在图片上显示为问号

当前项目已经使用 Pillow 绘制中文文字。

如果仍然显示异常，检查系统中是否存在中文字体，例如：

```text
Microsoft YaHei
SimHei
SimSun
```

Windows 正常情况下无需额外配置字体。

---

### 14.3 截图时识别不到人脸

可能原因：

- 人脸太小
- 角度过大
- 光线太暗
- 人脸被遮挡
- 骨架线或画面叠加影响检测
- 数据库没有录入该人员
- 相似度阈值设置过高

建议：

- 每个人录入 5 到 10 张
- 尽量包含不同角度和光照
- 截图时保证人脸朝向摄像头
- 必要时调整相似度阈值

---

### 14.4 手机打不开直播地址

先确认电脑 IP 是否正确：

```powershell
ipconfig
```

然后在电脑本机测试：

```powershell
curl.exe -v http://电脑局域网IP:8889/live/kinect
```

如果本机能访问但手机不能访问，可能是：

- Windows 防火墙拦截
- 手机和电脑不在同一网络
- 校园网或公司网开启了客户端隔离
- 手机连了访客 Wi-Fi
- 电脑开启了 VPN 或代理

可以用临时 HTTP 服务测试局域网互通：

```bash
python -m http.server 8000
```

手机访问：

```text
http://电脑局域网IP:8000
```

如果这个也打不开，说明不是 MediaMTX 问题，而是局域网设备互访被阻止。

---

### 14.5 QQ 指令没有反应

检查：

- `.env` 中 `QQ_APP_ID` 是否正确
- `.env` 中 `QQ_APP_SECRET` 是否正确
- `.env` 中 `QQ_USER_OPENID` 是否正确
- QQ 机器人是否已发布或配置可用
- 当前网络是否能访问 QQ Bot API
- 程序日志中是否有 AccessToken 或 WebSocket 报错

---

## 15. 推荐使用流程

完整使用流程如下：

```text
1. 安装 Azure Kinect Sensor SDK 和 Body Tracking SDK
2. 确认 Azure Kinect Viewer 能正常打开相机
3. 安装 Python 依赖
4. 下载 YuNet 和 SFace 模型到 models/
5. 配置 .env
6. 运行 get_my_openid.py 获取 QQ_USER_OPENID
7. 运行 enroll_face.py 录入人员人脸
8. 运行 python main.py 启动主程序
9. 点击截图或通过 QQ 发送“截图”测试截图与人脸识别
10. 测试疑似跌倒报警
11. 根据需要开启直播
```

---

## 16. 说明

本项目定位为课程设计、实验演示或原型系统。实际用于安全监护、医疗看护、门禁识别等场景时，还需要进一步增强稳定性、误报处理、权限管理、隐私保护和异常恢复能力。
