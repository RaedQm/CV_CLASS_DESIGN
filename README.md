# Azure Kinect 家庭摔倒检测系统

## 项目简介

本项目是一个基于 **Azure Kinect** 的家庭场景摔倒检测系统，主要面向家中老人、小孩等需要看护的人群。系统通过 Azure Kinect 实时采集人体骨架信息，对人体姿态进行分析，识别站立、弯腰、下蹲、坐姿以及疑似跌倒等状态。当检测到疑似跌倒时，系统可以自动保存现场截图，并通过 QQ 机器人向监护人发送远程提醒。

除摔倒检测外，系统还集成了人脸识别、人脸库管理、远程 QQ 指令交互和视频直播功能。监护人可以通过 QQ 远程开启监听、获取截图、启动直播并查看现场画面，从而提高家庭安全看护的及时性和便利性。

## 主要功能

### 1. 实时人体姿态检测

- 使用 Azure Kinect 采集彩色图像和人体骨架数据。
- 在主界面实时显示摄像头画面和人体骨架叠加效果。
- 根据关节点空间位置判断人体姿态。
- 支持识别站立、弯腰、下蹲、坐姿、举手、平举、疑似跌倒等状态。
- 对姿态识别结果进行多帧平滑，减少单帧抖动导致的误判。

### 2. 摔倒检测与报警

- 系统重点识别“疑似跌倒”状态。
- 跌倒判断采用多条件评分机制，综合考虑：
  - 躯干倾斜角度；
  - 人体竖直高度变化；
  - 身体水平展开程度；
  - 头部与骨盆高度关系。
- 针对约 1.1m 的相机安装高度，项目中已适当放宽疑似跌倒判断条件，以提高侧倒、半躺、低位倒地等情况的识别能力。
- 检测到疑似跌倒后，系统会进入报警冷却时间，避免同一次跌倒连续多帧重复发送报警。

### 3. 人脸识别与截图标注

- 使用 OpenCV YuNet 进行人脸检测。
- 使用 OpenCV SFace 提取人脸特征并进行相似度匹配。
- 截图时自动对画面中的人脸进行识别。
- 识别结果会绘制到截图中，方便监护人判断现场人员身份。
- 当人脸识别模块初始化失败时，系统的姿态检测、摔倒报警、QQ 控制和直播功能仍可继续使用。

### 4. 人脸库管理

- 支持在主界面中添加人脸信息。
- 添加人脸时自动分配从 1 开始的最小空闲用户 ID。
- 每个人至少录入 5 张人脸样本，提高识别稳定性。
- 支持查看人脸库，界面只显示“按人员汇总”信息。
- 支持删除人脸记录：
  - 删除某个用户 ID 的全部记录；
  - 删除某个姓名的全部记录。
- 人脸数据保存在本地 SQLite 数据库中。

### 5. 远程 QQ 交互

系统集成 QQ 官方机器人能力，监护人可以通过 QQ 私聊发送指令控制本地程序。

支持的 QQ 指令如下：

| 指令 | 功能 |
| --- | --- |
| `开始监听` | 开启 QQ 姿态监视 |
| `停止监听` | 关闭 QQ 姿态监视 |
| `截图` | 截取当前画面并发送图片 |
| `直播` | 开启远程视频直播，并返回观看地址、用户名和临时密钥 |
| `结束直播` | 停止当前直播 |

当检测到疑似跌倒时，系统可以通过 QQ 向监护人发送报警文本和现场截图。

### 6. 视频直播

- 支持通过 QQ 指令远程开启直播。
- 使用 FFmpeg 将本地画面编码为 H.264 视频流。
- 使用 MediaMTX 提供本地 RTMP/HLS 流媒体服务。
- 使用 ngrok 将本地直播服务临时映射到公网。
- 系统会生成临时用户名和密钥，并通过 QQ 发送给监护人。
- 系统会生成直播二维码，方便手机扫码查看。

### 7. 图形化界面

- 基于 PyQt5 开发本地桌面端界面。
- 主界面采用深色科技感风格。
- 左侧显示实时视频画面、系统状态和人脸管理按钮。
- 右侧显示姿态信息、运行日志和主要控制按钮。
- 人脸录入、删除、提示确认等弹窗均使用与主界面一致的紫色主题风格。

## 系统架构

系统整体采用模块化设计，主要由以下模块组成：

```text
Azure Kinect 摄像头
        │
        ▼
人体采集与姿态识别模块
        │
        ├── PyQt5 主界面显示
        ├── 摔倒检测与报警逻辑
        ├── 截图保存与人脸识别
        ├── QQ 机器人远程交互
        └── 视频直播推流模块
```

核心模块说明：

| 文件 | 说明 |
| --- | --- |
| `main.py` | 程序入口，启动 PyQt5 主窗口 |
| `app_window.py` | 主界面、按钮事件、报警逻辑、人脸管理、QQ 与直播调度 |
| `pose_detector.py` | Azure Kinect 数据采集、骨架解析、姿态识别和跌倒判断 |
| `face_engine.py` | 人脸检测、人脸特征提取、人脸识别和截图标注 |
| `face_db.py` | SQLite 人脸数据库封装 |
| `manage_faces.py` | 命令行方式查看和管理人脸库 |
| `enroll_face.py` | 命令行方式录入人脸 |
| `qq_sender.py` | QQ 机器人文本、图片发送和指令监听 |
| `get_my_openid.py` | 获取并保存 QQ 用户 openid |
| `live_stream_manager.py` | MediaMTX、ngrok、直播地址和二维码管理 |
| `h264_streamer.py` | 调用 FFmpeg 进行 H.264 编码和 RTMP 推流 |
| `download_face_models.py` | 下载 YuNet 与 SFace 人脸模型 |

## 目录结构

建议项目目录如下：

```text
modified_face_project/
├── main.py
├── app_window.py
├── pose_detector.py
├── face_engine.py
├── face_db.py
├── manage_faces.py
├── enroll_face.py
├── qq_sender.py
├── get_my_openid.py
├── live_stream_manager.py
├── h264_streamer.py
├── download_face_models.py
├── README.md
├── .env                  # 本地配置文件，需要自行创建
├── data/                 # 人脸数据库目录，运行后自动生成
│   └── faces.db
├── models/               # 人脸识别模型目录，需要下载或手动放入
│   ├── face_detection_yunet_2023mar.onnx
│   └── face_recognition_sface_2021dec.onnx
├── screenshots/          # 截图保存目录，运行后自动生成
└── live_runtime/          # 直播运行文件目录，运行后自动生成
```

## 运行环境

### 硬件环境

- Azure Kinect DK 摄像头；
- 支持运行 Azure Kinect Body Tracking 的 Windows 电脑；
- 建议具备可用 GPU，以提高骨架检测性能；
- 摄像头建议安装在约 1.1m 至 1.6m 高度，尽量保证能看到头部、躯干、髋部、膝盖和脚踝。

### 软件环境

- Windows 操作系统；
- Python 3.10 或以上版本；
- Azure Kinect Sensor SDK；
- Azure Kinect Body Tracking SDK；
- FFmpeg；
- MediaMTX；
- ngrok；
- QQ 官方机器人应用配置。

### Python 依赖

项目主要使用以下 Python 库：

```text
PyQt5
opencv-contrib-python
numpy
Pillow
requests
python-dotenv
websockets
qrcode
pykinect_azure
```

可参考以下命令安装常用依赖：

```bash
pip install PyQt5 opencv-contrib-python numpy Pillow requests python-dotenv websockets qrcode pykinect_azure
```

> 注意：`pykinect_azure` 依赖本机已正确安装 Azure Kinect SDK 和 Body Tracking SDK。若 Body Tracking 初始化失败，需要优先检查 SDK、驱动、设备连接和 GPU 环境。

## 配置说明

在项目根目录下创建 `.env` 文件，用于保存 QQ 机器人和直播相关配置。

示例：

```env
QQ_APP_ID=你的QQ机器人AppID
QQ_APP_SECRET=你的QQ机器人AppSecret
QQ_USER_OPENID=你的QQ用户openid,可通过get_my_openid.py获取

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

配置说明：

| 配置项 | 说明 |
| --- | --- |
| `QQ_APP_ID` | QQ 机器人应用 ID |
| `QQ_APP_SECRET` | QQ 机器人应用密钥 |
| `QQ_USER_OPENID` | 接收消息的用户 openid |
| `MEDIAMTX_PATH` | MediaMTX 可执行文件路径 |
| `LIVE_AUTO_START_MEDIAMTX` | 是否由程序自动启动 MediaMTX，`1` 表示自动启动 |
| `LIVE_RTMP_URL` | 本地 RTMP 推流地址 |
| `LIVE_HLS_PATH` | HLS 直播路径 |
| `LIVE_NGROK_HTTP_PORT` | HLS 本地端口，默认 `8888`，建议 `8889`因为延迟更低 |
| `LIVE_WIDTH` | 直播画面宽度 |
| `LIVE_HEIGHT` | 直播画面高度 |
| `LIVE_FPS` | 直播帧率 |
| `LIVE_BITRATE` | 直播码率 |
| `FFMPEG_PATH` | FFmpeg 可执行文件路径或命令名 |
| `NGROK_PATH` | ngrok 可执行文件路径或命令名 |

## 人脸模型准备

人脸识别依赖两个 ONNX 模型文件：

- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`

可以运行以下命令自动下载：

```bash
python download_face_models.py
```

如果网络访问 GitHub 不稳定，可以使用代理：

```bash
python download_face_models.py --proxy http://127.0.0.1:7890
```

下载完成后，模型文件应位于项目根目录的 `models/` 目录下。

## QQ openid 获取

首次使用 QQ 机器人前，需要获取接收消息用户的 openid。

1. 在 `.env` 中填写 `QQ_APP_ID` 和 `QQ_APP_SECRET`。
2. 运行：

```bash
python get_my_openid.py
```

3. 按终端提示向机器人发送消息。
4. 程序会自动识别用户 openid，并写入 `.env` 文件中的 `QQ_USER_OPENID`。

## 启动项目

在项目根目录执行：

```bash
python main.py
```

程序启动后会打开桌面端主界面。主界面包括：

- Azure Kinect 实时画面；
- 系统状态：时间、人数、QQ 监视状态、直播状态；
- 姿态信息显示；
- 运行日志；
- 截图、退出、QQ 监视控制按钮；
- 查看人脸库、删除人脸记录、添加人脸信息按钮。

## 使用说明

### 1. 添加人脸信息

1. 启动主程序，并确保摄像头画面正常。
2. 点击左侧视频下方的“添加人脸信息”。
3. 系统自动分配用户 ID。
4. 输入姓名。
5. 在录入窗口中点击“拍摄”，建议录入正脸、轻微左转、轻微右转、不同距离等多张样本。
6. 至少录入 5 张后，点击“完成”。

### 2. 查看人脸库

点击“查看人脸库”，系统会显示当前数据库路径、总人脸特征数以及按人员汇总的信息。

显示内容包括：

- 用户 ID；
- 姓名；
- 特征数；
- 首次录入时间；
- 最近录入时间。

### 3. 删除人脸记录

点击“删除人脸记录”，可选择：

- 删除某个用户 ID 全部记录；
- 删除某个姓名全部记录。

系统会先统计匹配记录数量，并弹出确认框。确认后删除不可恢复。

### 4. 截图识别

点击“截图”，系统会保存当前画面。如果人脸识别模块可用，会自动识别人脸并将识别结果画到截图上。

截图默认保存在：

```text
screenshots/
```

### 5. QQ 远程控制

点击“开始QQ监视”后，系统开始监听 QQ 私聊指令。监护人可通过 QQ 发送：

```text
开始监听
停止监听
截图
直播
结束直播
```

### 6. 直播查看

发送 `直播` 指令后，系统会：

1. 启动或复用 MediaMTX；
2. 使用 FFmpeg 推送当前画面；
3. 使用 ngrok 生成公网访问地址；
4. 生成直播二维码；
5. 通过 QQ 发送二维码、观看地址、用户名和临时密钥。

发送 `结束直播` 后，系统会停止直播并清理二维码文件。

## 命令行人脸库管理

除主界面外，也可以使用 `manage_faces.py` 管理人脸库。

查看人员汇总：

```bash
python manage_faces.py people
```

按用户 ID 删除全部记录：

```bash
python manage_faces.py delete-user 1
```

跳过确认：

```bash
python manage_faces.py delete-user 1 -y
```

按姓名删除全部记录：

```bash
python manage_faces.py delete-name 张三
```

## 命令行录入人脸

从摄像头录入：

```bash
python enroll_face.py --user-id 1 --name 张三 --camera 0
```

从图片录入：

```bash
python enroll_face.py --user-id 1 --name 张三 --image path/to/image.jpg
```

## 常见问题

### 1. 程序启动后没有摄像头画面

请检查：

- Azure Kinect 是否连接正常；
- Azure Kinect Sensor SDK 是否安装；
- 摄像头是否被其他程序占用；
- USB 和电源连接是否稳定。

### 2. 姿态识别显示“无法判断”

可能原因：

- 人体不在摄像头视野范围内；
- 头部、躯干、髋部、膝盖或脚踝被遮挡；
- 光照或距离影响骨架跟踪；
- Body Tracking SDK 初始化异常。

### 3. 坐在椅子上被识别为下蹲

在低机位家庭场景中，坐姿和下蹲的骨盆高度、膝盖角度比较接近，可能出现分类相近的情况。本项目重点关注“疑似跌倒”状态，普通低姿态识别为下蹲或坐姿不会触发跌倒报警。

### 4. 人脸识别初始化失败

请检查：

- 是否已安装 `opencv-contrib-python`；
- `models/` 目录下是否存在 YuNet 和 SFace 模型；
- 模型文件是否下载完整；
- Python 环境是否使用了正确的 OpenCV 版本。

### 5. QQ 消息发送失败

请检查：

- `.env` 中 `QQ_APP_ID`、`QQ_APP_SECRET`、`QQ_USER_OPENID` 是否正确；
- QQ 机器人是否已正常配置和启用；
- 当前网络是否可以访问 QQ 机器人接口。

### 6. 直播启动失败

请检查：

- `ffmpeg -version` 是否可用；
- MediaMTX 路径是否正确；
- ngrok 是否已登录并可以正常运行；
- 1935 和 8888 端口是否被占用；
- 防火墙是否阻止本地服务或 ngrok 访问。

## 数据说明

人脸数据库默认路径为：

```text
data/faces.db
```

数据库表 `faces` 主要字段如下：

| 字段 | 说明 |
| --- | --- |
| `id` | 人脸记录 ID，自增主键 |
| `user_id` | 用户 ID |
| `name` | 姓名 |
| `embedding` | 人脸特征向量，二进制存储 |
| `dim` | 特征维度 |
| `created_at` | 录入时间 |

## 注意事项

- 本项目适用于课程设计、实验演示和家庭看护原型验证。
- 实际部署时应根据房间布局、摄像头安装高度和人员活动范围调整姿态判断阈值。
- 跌倒检测存在一定误报和漏报可能，不能完全替代人工看护或专业医疗报警设备。
- QQ 机器人密钥、ngrok 账号、直播访问密钥等敏感信息不要上传到公开仓库。
- 人脸数据属于敏感生物特征信息，请妥善保管本地数据库文件。

## 项目特点

- 将 Azure Kinect 骨架检测与家庭摔倒监护场景结合；
- 支持疑似跌倒自动报警和远程查看；
- 集成人脸识别，增强截图信息量；
- 提供本地可视化界面和 QQ 远程交互双重操作方式；
- 使用 SQLite 存储人脸特征，部署简单，适合课程设计和原型系统演示；
- UI 风格统一，便于展示和汇报。
