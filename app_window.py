import time
import threading
from pathlib import Path

import cv2
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QTextEdit,
    QHBoxLayout, QVBoxLayout, QMessageBox
)

from pose_detector import BodyPoseDetector
from qq_sender import QQController
from live_stream_manager import LiveStreamManager


QQ_SEND_MIN_INTERVAL_SECONDS = 3.0

# 跌倒报警冷却时间，避免同一次跌倒持续多帧时疯狂截图和发 QQ。
FALL_ALERT_COOLDOWN_SECONDS = 30.0

# 跌倒报警提示语。注意：这不会自动开启监听。
FALL_ALERT_TEXT = "检测到人物摔倒，请打开监听查看详细情况。"


class CameraWorker(QThread):
    frame_ready = pyqtSignal(object, dict)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.detector = None

    def run(self):
        try:
            self.detector = BodyPoseDetector()

            while self.running:
                frame, info = self.detector.read_frame()

                if frame is None or info is None:
                    continue

                self.frame_ready.emit(frame, info)

        except Exception as e:
            self.error.emit(str(e))

        finally:
            if self.detector:
                self.detector.close()

    def stop(self):
        self.running = False


class CommandBridge(QObject):
    start_monitor_signal = pyqtSignal()
    stop_monitor_signal = pyqtSignal()
    screenshot_signal = pyqtSignal()
    live_start_signal = pyqtSignal()
    live_stop_signal = pyqtSignal()
    log_signal = pyqtSignal(str)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Azure Kinect 人体姿态检测与 QQ 监视系统")
        self.resize(1200, 720)

        self.current_frame = None
        self.current_info = None

        self.qq_monitor_enabled = False
        self.last_qq_pose_state = None
        self.last_qq_send_time = 0

        # 跌倒报警状态。
        # fall_alert_active=True 表示当前已经处在一段跌倒报警状态中；
        # 只有检测结果恢复为非跌倒后，才会允许下一次跌倒重新触发。
        self.fall_alert_active = False
        self.last_fall_alert_time = 0

        self.qq_controller = None

        # 直播管理器：QQ 发送“直播”后启动，发送“结束直播”后停止。
        self.live_stream_running = False
        self.live_stream_info = None
        self.live_manager = LiveStreamManager(
            on_log=lambda text: self.bridge.log_signal.emit(text)
            if hasattr(self, "bridge") else print(text)
        )

        self.bridge = CommandBridge()
        self.bridge.start_monitor_signal.connect(lambda: self.enable_qq_monitor("QQ指令"))
        self.bridge.stop_monitor_signal.connect(lambda: self.disable_qq_monitor("QQ指令"))
        self.bridge.screenshot_signal.connect(self.handle_qq_screenshot_request)
        self.bridge.live_start_signal.connect(lambda: self.start_live_stream("QQ指令"))
        self.bridge.live_stop_signal.connect(lambda: self.stop_live_stream("QQ指令"))
        self.bridge.log_signal.connect(self.append_log)

        self.init_ui()
        self.init_qq()
        self.start_camera()

    def init_ui(self):
        self.image_label = QLabel("正在启动 Azure Kinect...")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(820, 620)
        self.image_label.setStyleSheet("background-color: #111; color: white; border: 1px solid #444;")

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setFont(QFont("Consolas", 11))
        self.info_text.setMinimumWidth(320)

        self.btn_screenshot = QPushButton("截图")
        self.btn_exit = QPushButton("退出")
        self.btn_start_qq = QPushButton("开始QQ监视")
        self.btn_stop_qq = QPushButton("关闭QQ监视")

        for btn in [self.btn_screenshot, self.btn_exit, self.btn_start_qq, self.btn_stop_qq]:
            btn.setMinimumHeight(46)
            btn.setStyleSheet("font-size: 16px;")

        self.btn_screenshot.clicked.connect(self.save_screenshot_by_button)
        self.btn_exit.clicked.connect(self.close)
        self.btn_start_qq.clicked.connect(lambda: self.enable_qq_monitor("按钮"))
        self.btn_stop_qq.clicked.connect(lambda: self.disable_qq_monitor("按钮"))

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.info_text, stretch=1)
        right_layout.addWidget(self.btn_screenshot)
        right_layout.addWidget(self.btn_exit)
        right_layout.addWidget(self.btn_start_qq)
        right_layout.addWidget(self.btn_stop_qq)

        main_layout = QHBoxLayout()
        main_layout.addWidget(self.image_label, stretch=3)
        main_layout.addLayout(right_layout, stretch=1)

        self.setLayout(main_layout)

    def init_qq(self):
        try:
            self.qq_controller = QQController(
                on_start=lambda: self.bridge.start_monitor_signal.emit(),
                on_stop=lambda: self.bridge.stop_monitor_signal.emit(),
                on_screenshot=lambda: self.bridge.screenshot_signal.emit(),
                on_live_start=lambda: self.bridge.live_start_signal.emit(),
                on_live_stop=lambda: self.bridge.live_stop_signal.emit(),
                on_log=lambda text: self.bridge.log_signal.emit(text)
            )
            self.qq_controller.start_command_listener()
            self.append_log("QQ 功能初始化成功。")
            self.append_log("QQ 可用指令：开始监听 / 停止监听 / 截图 / 直播 / 结束直播。")
            self.append_log("跌倒报警已启用：即使未开启监听，检测到疑似跌倒也会自动截图并发送 QQ。")
        except Exception as e:
            self.qq_controller = None
            self.append_log(f"QQ 功能初始化失败：{e}")
            self.append_log("如果暂时不使用 QQ，摄像头检测和截图功能仍可正常使用。")

    def start_camera(self):
        self.camera_worker = CameraWorker()
        self.camera_worker.frame_ready.connect(self.on_frame_ready)
        self.camera_worker.error.connect(self.on_camera_error)
        self.camera_worker.start()

    def on_camera_error(self, error_text):
        QMessageBox.critical(self, "Azure Kinect 错误", error_text)
        self.append_log(f"Azure Kinect 错误：{error_text}")

    def cv_image_to_qpixmap(self, image):
        """
        OpenCV 图像转 Qt Pixmap。
        Azure Kinect 的彩色图常见为 BGRA，普通 OpenCV 图常见为 BGR。
        """
        if image.ndim == 2:
            qimage = QImage(
                image.data,
                image.shape[1],
                image.shape[0],
                image.strides[0],
                QImage.Format_Grayscale8
            ).copy()
        elif image.shape[2] == 4:
            rgba = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
            qimage = QImage(
                rgba.data,
                rgba.shape[1],
                rgba.shape[0],
                rgba.strides[0],
                QImage.Format_RGBA8888
            ).copy()
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            qimage = QImage(
                rgb.data,
                rgb.shape[1],
                rgb.shape[0],
                rgb.strides[0],
                QImage.Format_RGB888
            ).copy()

        pixmap = QPixmap.fromImage(qimage)
        return pixmap.scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

    def on_frame_ready(self, frame, info):
        self.current_frame = frame.copy()
        self.current_info = info

        # 如果直播已启动，则把当前“彩色图 + 骨架”帧写入 FFmpeg。
        if self.live_manager:
            self.live_manager.write_frame(frame)

        pixmap = self.cv_image_to_qpixmap(frame)
        self.image_label.setPixmap(pixmap)

        self.update_info_text(info)

        # 普通姿态变化发送：只有开启 QQ 监视后才发送。
        self.handle_qq_pose_sending(info)

        # 跌倒报警：即使没开启 QQ 监视，也会自动截图并发送。
        # 但它不会自动开启 QQ 监视。
        self.handle_fall_alert(info)

    def update_info_text(self, info):
        timestamp = info["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"时间：{timestamp}",
            f"人数：{info['num_bodies']}",
            "",
            "每个人的姿态："
        ]

        if info["num_bodies"] == 0:
            lines.append("未检测到人体")
        else:
            for item in info["poses"]:
                lines.append(
                    f"人物{item['person_index']}（ID:{item['body_id']}）：{item['pose']}"
                )

        lines.append("")
        lines.append(f"QQ监视状态：{'开启' if self.qq_monitor_enabled else '关闭'}")
        lines.append(f"直播状态：{'开启' if self.live_stream_running else '关闭'}")
        if self.live_stream_info:
            lines.append(f"直播地址：{self.live_stream_info.get('watch_url', '')}")
        lines.append(f"跌倒报警状态：{'已触发，等待恢复' if self.fall_alert_active else '待命'}")
        lines.append("")
        lines.append("QQ控制指令：")
        lines.append("开始监听：开启 QQ 姿态监视")
        lines.append("停止监听：关闭 QQ 姿态监视")
        lines.append("截图：保存当前画面并发送到 QQ")
        lines.append("直播：开启 H.264 直播并返回公网观看地址")
        lines.append("结束直播：停止 H.264 直播")
        lines.append("")
        lines.append("说明：疑似跌倒会自动报警，但不会自动开启 QQ 监视。")

        self.info_text.setPlainText("\n".join(lines))

    def build_pose_message(self, info):
        timestamp = info["timestamp"].strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "【Azure Kinect 人体姿态检测】",
            f"检测时间：{timestamp}",
            f"检测人数：{info['num_bodies']}",
            "人物姿态："
        ]

        if info["num_bodies"] == 0:
            lines.append("未检测到人体")
        else:
            for item in info["poses"]:
                lines.append(
                    f"人物{item['person_index']}（ID:{item['body_id']}）：{item['pose']}"
                )

        return "\n".join(lines)

    def build_fall_alert_message(self, info):
        timestamp = info["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        fall_people = [
            item for item in info["poses"]
            if item["pose"] == "疑似跌倒"
        ]

        lines = [
            "【Azure Kinect 跌倒报警】",
            FALL_ALERT_TEXT,
            f"检测时间：{timestamp}",
            f"检测人数：{info['num_bodies']}",
            "疑似跌倒对象："
        ]

        if not fall_people:
            lines.append("未知")
        else:
            for item in fall_people:
                lines.append(
                    f"人物{item['person_index']}：{item['pose']}"
                )

        lines.append("")
        lines.append("注意：本报警不会自动开启监听。")
        lines.append("你可以发送“开始监听”来查看后续详细姿态变化。")

        return "\n".join(lines)

    def handle_qq_pose_sending(self, info):
        if not self.qq_monitor_enabled:
            return

        if not self.qq_controller:
            return

        # 没有人时不发送，避免刷屏
        if info["num_bodies"] == 0:
            return

        current_state = info["pose_state"]

        # 只要有一个人的姿态变化，整体 pose_state 就会变化
        if current_state == self.last_qq_pose_state:
            return

        now = time.time()

        # 防止姿态抖动造成 QQ 刷屏。想立刻发送每次变化，可把 QQ_SEND_MIN_INTERVAL_SECONDS 改成 0。
        if now - self.last_qq_send_time < QQ_SEND_MIN_INTERVAL_SECONDS:
            return

        self.last_qq_pose_state = current_state
        self.last_qq_send_time = now

        message = self.build_pose_message(info)

        thread = threading.Thread(
            target=self.send_qq_message_background,
            args=(message,),
            daemon=True
        )
        thread.start()

    def handle_fall_alert(self, info):
        """
        跌倒自动报警逻辑。

        关键点：
        1. 不管 QQ 监视是否开启，只要检测到“疑似跌倒”就报警。
        2. 报警会自动截图并通过 QQ 发送截图。
        3. 报警不会自动开启监听。
        4. 同一段连续跌倒只报警一次；恢复正常后才允许下次报警。
        5. 额外加入冷却时间，避免误识别抖动导致频繁报警。
        """
        if not self.qq_controller:
            return

        poses = info.get("poses", [])
        any_fall = any(item["pose"] == "疑似跌倒" for item in poses)

        if not any_fall:
            self.fall_alert_active = False
            return

        now = time.time()

        # 已经在一段连续跌倒报警状态中，不重复报警。
        if self.fall_alert_active:
            return

        # 冷却时间内，不重复报警。
        if now - self.last_fall_alert_time < FALL_ALERT_COOLDOWN_SECONDS:
            return

        self.fall_alert_active = True
        self.last_fall_alert_time = now

        path = self.save_screenshot_to_file()
        message = self.build_fall_alert_message(info)

        thread = threading.Thread(
            target=self.send_fall_alert_background,
            args=(message, path),
            daemon=True
        )
        thread.start()

    def send_fall_alert_background(self, message, image_path):
        try:
            self.qq_controller.send_text(message)

            if image_path is not None:
                status_code, result = self.qq_controller.send_image(image_path)
                self.bridge.log_signal.emit(
                    f"跌倒报警截图发送完成，HTTP状态码：{status_code}，返回：{result}"
                )
            else:
                self.qq_controller.send_text("跌倒报警截图失败：当前没有可保存的摄像头画面。")

            self.bridge.log_signal.emit("跌倒报警已发送。")
        except Exception as e:
            self.bridge.log_signal.emit(f"跌倒报警发送失败：{e}")
            try:
                self.qq_controller.send_text(f"检测到疑似跌倒，但报警截图发送失败：{e}")
            except Exception:
                pass

    def send_qq_message_background(self, message):
        try:
            status_code, result = self.qq_controller.send_text(message)
            self.bridge.log_signal.emit(f"QQ发送完成，HTTP状态码：{status_code}，返回：{result}")
        except Exception as e:
            self.bridge.log_signal.emit(f"QQ发送失败：{e}")

    def send_qq_feedback(self, text):
        """
        给 QQ 发送反馈消息。
        QQ 指令触发和窗口按钮触发都会走这里，避免重复逻辑。
        """
        if not self.qq_controller:
            return

        thread = threading.Thread(
            target=self.send_qq_feedback_background,
            args=(text,),
            daemon=True
        )
        thread.start()

    def send_qq_feedback_background(self, text):
        try:
            status_code, result = self.qq_controller.send_text(text)
            self.bridge.log_signal.emit(
                f"QQ反馈发送完成，HTTP状态码：{status_code}，返回：{result}"
            )
        except Exception as e:
            self.bridge.log_signal.emit(f"QQ反馈发送失败：{e}")

    def enable_qq_monitor(self, source="按钮"):
        already_open = self.qq_monitor_enabled

        self.qq_monitor_enabled = True
        self.last_qq_pose_state = None
        self.last_qq_send_time = 0

        self.append_log(f"QQ监视已开启，来源：{source}")

        if already_open:
            self.send_qq_feedback("QQ监视已经是开启状态。")
        else:
            self.send_qq_feedback("QQ监视已开启。")

    def disable_qq_monitor(self, source="按钮"):
        already_closed = not self.qq_monitor_enabled

        self.qq_monitor_enabled = False
        self.append_log(f"QQ监视已关闭，来源：{source}")

        if already_closed:
            self.send_qq_feedback("QQ监视本来就是关闭状态。")
        else:
            self.send_qq_feedback("QQ监视已关闭。")

    def append_log(self, text):
        print(text)

    def save_screenshot_to_file(self):
        """
        保存当前彩色图 + 骨架截图，返回 Path。
        """
        if self.current_frame is None:
            return None

        screenshots_dir = Path(__file__).resolve().parent / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        filename = time.strftime("screenshot_%Y%m%d_%H%M%S.png")
        path = screenshots_dir / filename

        ok = cv2.imwrite(str(path), self.current_frame)

        if not ok:
            return None

        return path

    def save_screenshot_by_button(self):
        path = self.save_screenshot_to_file()

        if path is None:
            QMessageBox.warning(self, "截图失败", "当前还没有可保存的摄像头画面，或保存失败。")
            return

        QMessageBox.information(self, "截图成功", f"截图已保存：\n{path}")
        self.append_log(f"截图已保存：{path}")

    def handle_qq_screenshot_request(self):
        """
        QQ 收到“截图”指令后触发。
        注意：这个函数在 Qt 主线程执行，可以安全访问 current_frame。
        """
        if not self.qq_controller:
            return

        path = self.save_screenshot_to_file()

        if path is None:
            self.send_qq_feedback("截图失败：当前还没有可保存的摄像头画面。")
            return

        self.append_log(f"QQ 截图已保存：{path}")

        thread = threading.Thread(
            target=self.send_qq_screenshot_background,
            args=(path,),
            daemon=True
        )
        thread.start()

    def send_qq_screenshot_background(self, path):
        try:
            self.qq_controller.send_text(f"截图成功，正在发送图片：{path.name}")
            status_code, result = self.qq_controller.send_image(path)
            self.bridge.log_signal.emit(f"QQ截图发送完成，HTTP状态码：{status_code}，返回：{result}")
        except Exception as e:
            self.bridge.log_signal.emit(f"QQ截图发送失败：{e}")
            try:
                self.qq_controller.send_text(f"截图已保存，但图片发送失败：{e}")
            except Exception:
                pass

    def build_live_started_message(self, result):
        """
        生成直播启动成功后发送给 QQ 的消息。
        """
        if result.get("already_running"):
            title = "【Azure Kinect 直播】\n直播已经在运行。"
        else:
            title = "【Azure Kinect 直播】\n开始直播。"

        return (
            f"{title}\n"
            f"观看地址：{result.get('watch_url')}\n"
            f"用户名：{result.get('username')}\n"
            f"临时密钥：{result.get('password')}\n\n"
            "说明：浏览器打开观看地址后，会弹出登录框；输入上面的用户名和临时密钥即可观看。"
        )

    def start_live_stream(self, source="QQ指令"):
        """
        开启直播。
        QQ 发送“直播”会触发这里。
        """
        if not self.qq_controller:
            self.append_log("QQ 未初始化，无法发送直播地址。")
            return

        thread = threading.Thread(
            target=self.start_live_stream_background,
            args=(source,),
            daemon=True
        )
        thread.start()

    def start_live_stream_background(self, source):
        try:
            result = self.live_manager.start()
            self.live_stream_running = True
            self.live_stream_info = result

            message = self.build_live_started_message(result)
            self.qq_controller.send_text(message)

            self.bridge.log_signal.emit(
                f"直播启动完成，来源：{source}，地址：{result.get('watch_url')}"
            )
        except Exception as e:
            self.live_stream_running = False
            self.live_stream_info = None
            error_msg = (
                "【Azure Kinect 直播】\n"
                f"直播启动失败：{e}\n\n"
                "请检查：\n"
                "1. MEDIAMTX_PATH 是否正确，或 mediamtx 是否已加入 Path。\n"
                "2. ffmpeg -version 是否可用。\n"
                "3. ngrok 是否已登录并可运行。\n"
                "4. MediaMTX 的 8888 和 1935 端口是否被占用。"
            )
            self.bridge.log_signal.emit(f"直播启动失败：{e}")
            try:
                self.qq_controller.send_text(error_msg)
            except Exception:
                pass

    def stop_live_stream(self, source="QQ指令"):
        """
        停止直播。
        QQ 发送“结束直播”会触发这里。
        """
        if not self.qq_controller:
            self.append_log("QQ 未初始化，无法发送直播停止反馈。")
            return

        thread = threading.Thread(
            target=self.stop_live_stream_background,
            args=(source,),
            daemon=True
        )
        thread.start()

    def stop_live_stream_background(self, source):
        try:
            was_running = self.live_manager.stop()
            self.live_stream_running = False
            self.live_stream_info = None

            if was_running:
                message = "【Azure Kinect 直播】\n直播已停止。"
            else:
                message = "【Azure Kinect 直播】\n直播本来就是停止状态。"

            self.qq_controller.send_text(message)
            self.bridge.log_signal.emit(f"直播停止完成，来源：{source}")
        except Exception as e:
            self.bridge.log_signal.emit(f"直播停止失败：{e}")
            try:
                self.qq_controller.send_text(f"【Azure Kinect 直播】\n直播停止失败：{e}")
            except Exception:
                pass


    def closeEvent(self, event):
        try:
            if hasattr(self, "camera_worker") and self.camera_worker:
                self.camera_worker.stop()
                self.camera_worker.wait(2000)
        except Exception:
            pass

        try:
            if self.qq_controller:
                self.qq_controller.stop_command_listener()
        except Exception:
            pass

        try:
            if self.live_manager:
                self.live_manager.close()
        except Exception:
            pass

        event.accept()
