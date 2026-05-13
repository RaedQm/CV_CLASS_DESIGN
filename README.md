# Azure Kinect 人体姿态检测与 QQ 监视系统

## 功能

1. 使用 Azure Kinect 检测人体姿态。
2. 左侧窗口实时显示正常 RGB 彩色图和骨架。
3. 右侧文字栏显示：
   - 时间
   - 人数
   - 每个人的姿态
   - QQ 监视状态
4. 四个按钮：
   - 截图
   - 退出
   - 开始QQ监视
   - 关闭QQ监视
5. 点击“截图”会保存当前彩色图 + 骨架到 `screenshots` 文件夹。
6. QQ 监视开启后，只要任意一个人的姿态变化，就会通过 QQ 机器人发送：
   - 检测时间
   - 检测人数
   - 每个人的姿态
7. QQ 指令控制：
   - 对机器人发送 `开始指令`：开启 QQ 监视
   - 对机器人发送 `结束指令`：关闭 QQ 监视

## 文件结构

```text
azure_kinect_pose_qq_project
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

如果你已经从 GitHub 安装新版 pyKinectAzure，可以保留你的安装方式。

## 运行

```bash
python main.py
```

## 说明

`pose_detector.py` 使用 CPU 模式：

```python
tracker_config.tracker_processing_mode = pykinect.K4ABT_TRACKER_PROCESSING_MODE_CPU
```

如果你的 GPU 环境正常，可以改成：

```python
tracker_config.tracker_processing_mode = pykinect.K4ABT_TRACKER_PROCESSING_MODE_GPU
```

`app_window.py` 里有防刷屏间隔：

```python
QQ_SEND_MIN_INTERVAL_SECONDS = 3.0
```

如果想每次姿态变化都立即发送，可以改成：

```python
QQ_SEND_MIN_INTERVAL_SECONDS = 0
```
