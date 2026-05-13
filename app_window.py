import os
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


QQ_SEND_MIN_INTERVAL_SECONDS = 3.0


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

        self.qq_controller = None

        self.bridge = CommandBridge()
        self.bridge.start_monitor_signal.connect(lambda: self.enable_qq_monitor("QQ指令"))
        self.bridge.stop_monitor_signal.connect(lambda: self.disable_qq_monitor("QQ指令"))
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

        self.btn_screenshot.clicked.connect(self.save_screenshot)
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
                on_log=lambda text: self.bridge.log_signal.emit(text)
            )
            self.qq_controller.start_command_listener()
            self.append_log("QQ 功能初始化成功。发送“开始指令”或“结束指令”可控制监视。")
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

        pixmap = self.cv_image_to_qpixmap(frame)
        self.image_label.setPixmap(pixmap)

        self.update_info_text(info)
        self.handle_qq_sending(info)

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
        lines.append("")
        lines.append("QQ控制指令：")
        lines.append("开始指令")
        lines.append("结束指令")

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

    def handle_qq_sending(self, info):
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

    def send_qq_message_background(self, message):
        try:
            status_code, result = self.qq_controller.send_text(message)
            self.bridge.log_signal.emit(f"QQ发送完成，HTTP状态码：{status_code}，返回：{result}")
        except Exception as e:
            self.bridge.log_signal.emit(f"QQ发送失败：{e}")

    def enable_qq_monitor(self, source="按钮"):
        self.qq_monitor_enabled = True

        # 设为 None：开启监视后，下一帧检测到人体就会发送一次当前姿态。
        self.last_qq_pose_state = None
        self.last_qq_send_time = 0

        self.append_log(f"QQ监视已开启，来源：{source}")

        if self.qq_controller and source == "QQ指令":
            threading.Thread(
                target=lambda: self.qq_controller.send_text("QQ监视已开启。"),
                daemon=True
            ).start()

    def disable_qq_monitor(self, source="按钮"):
        self.qq_monitor_enabled = False
        self.append_log(f"QQ监视已关闭，来源：{source}")

        if self.qq_controller and source == "QQ指令":
            threading.Thread(
                target=lambda: self.qq_controller.send_text("QQ监视已关闭。"),
                daemon=True
            ).start()

    def append_log(self, text):
        print(text)

    def save_screenshot(self):
        if self.current_frame is None:
            QMessageBox.warning(self, "截图失败", "当前还没有可保存的摄像头画面。")
            return

        screenshots_dir = Path(__file__).resolve().parent / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        filename = time.strftime("screenshot_%Y%m%d_%H%M%S.png")
        path = screenshots_dir / filename

        ok = cv2.imwrite(str(path), self.current_frame)

        if ok:
            QMessageBox.information(self, "截图成功", f"截图已保存：\n{path}")
            self.append_log(f"截图已保存：{path}")
        else:
            QMessageBox.warning(self, "截图失败", "cv2.imwrite 保存失败。")

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

        event.accept()
