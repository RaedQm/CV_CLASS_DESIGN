# Azure Kinect 人体姿态检测与 QQ 监视系统 v3

## 功能

1. 左侧窗口实时显示 Azure Kinect 正常 RGB 彩色图 + 骨架。
2. 右侧文字栏显示：
   - 时间
   - 检测人数
   - 每个人的姿态
   - QQ 监视状态
3. 四个按钮：
   - 截图
   - 退出
   - 开始QQ监视
   - 关闭QQ监视
4. 点击“截图”会保存当前彩色图 + 骨架到 `screenshots` 文件夹。
5. QQ 发送 `截图` 会触发截图，并通过 QQ 机器人发送刚截的图片。
6. QQ 发送未知指令时，机器人会回复指令错误和指令范本。
7. QQ 监视开启后，只要任意一个人的姿态变化，就会通过 QQ 机器人发送：
   - 检测时间
   - 检测人数
   - 每个人的姿态
8. 无论是 QQ 发 `停止监听`，还是窗口点击“关闭QQ监视”，机器人都会发送反馈消息。
9. 无论是 QQ 发 `开始监听`，还是窗口点击“开始QQ监视”，机器人都会发送反馈消息。

## 文件结构

```text
azure_kinect_pose_qq_project_v3
├── main.py
├── app_window.py
├── pose_detector.py
├── qq_sender.py
├── requirements.txt
├── .env.example
└── README.md
```

实际运行时，你需要自己创建或保留 `.env` 文件。

## .env 示例

```env
QQ_APP_ID=你的AppID
QQ_APP_SECRET=你的AppSecret
QQ_USER_OPENID=你的user_openid
```

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

如果你的虚拟环境已经装好了 `opencv-python`、`pykinect-azure`、`requests`、`websockets`、`python-dotenv`，通常只需要：

```bash
python -m pip install PyQt5
```

## 运行

```bash
python main.py
```

## QQ 指令

推荐使用：

```text
开始监听
停止监听
截图
```

兼容旧指令：

```text
开始指令
结束指令
```

未知指令会回复：

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
