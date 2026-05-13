# Azure Kinect 人体姿态检测与 QQ 监视系统

## 本版新增功能

1. QQ 发送其他未知指令时，机器人会回复：
   - 指令错误
   - 可用指令范本
2. QQ 发送 `截图` 时：
   - 程序截取当前左侧窗口画面，也就是正常 RGB 彩色图 + 骨架
   - 保存到 `screenshots` 文件夹
   - 通过 QQ 机器人把刚截的图片发送给你

## 文件结构

```text
azure_kinect_pose_qq_project_v2
├── main.py
├── app_window.py
├── pose_detector.py
├── qq_sender.py
├── requirements.txt
├── README.md
├── get_my_openid.py
└── .env
```

## .env 示例

```env
QQ_APP_ID=你的AppID
QQ_APP_SECRET=你的AppSecret
QQ_USER_OPENID=你的user_openid，可通过get_my_openid.py获取
```

## 安装依赖

```bash
pip install -r requirements.txt
```

如果你当前虚拟环境已经装过 `opencv-python`、`pykinect-azure`、`requests`、`websockets`、`python-dotenv`，一般只需要额外确认：

```bash
python -m pip install PyQt5
```

## 运行

```bash
python main.py
```

## QQ 指令

```text
开始监听
```

开启 QQ 姿态监视。开启后，只要任意一个人的姿态变化，就会发送当前检测时间、人数和每个人姿态。

```text
停止监听
```

关闭 QQ 姿态监视。程序不退出，只是停止发送姿态变化。

```text
截图
```

截取当前摄像机 RGB 图 + 骨架，并通过 QQ 发给你。

其他任何非空指令都会回复：

```text
指令错误。
可用指令范本：
1. 开始监听：开启 QQ 姿态监视
2. 停止监听：关闭 QQ 姿态监视
3. 截图：截取当前摄像机画面和骨架，并发送图片
```

## 可调参数

`app_window.py` 中：

```python
QQ_SEND_MIN_INTERVAL_SECONDS = 3.0
```

用于防止姿态抖动造成 QQ 刷屏。想每次变化都立刻发送，可以改成：

```python
QQ_SEND_MIN_INTERVAL_SECONDS = 0
```

`pose_detector.py` 默认使用 CPU 模式：

```python
tracker_config.tracker_processing_mode = pykinect.K4ABT_TRACKER_PROCESSING_MODE_CPU
```

如果你的 GPU 环境确认正常，可以改成：

```python
tracker_config.tracker_processing_mode = pykinect.K4ABT_TRACKER_PROCESSING_MODE_GPU
```
