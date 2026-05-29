import time
import threading
from pathlib import Path

import cv2
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer
from PyQt5.QtGui import QImage, QPixmap, QFont, QTextCursor
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QTextEdit,
    QHBoxLayout, QVBoxLayout, QMessageBox, QFrame,
    QGridLayout, QSizePolicy, QInputDialog, QDialog
)

from pose_detector import BodyPoseDetector
from qq_sender import QQController
from live_stream_manager import LiveStreamManager
from face_engine import FaceEngine
from face_db import FaceDatabase


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


class FaceEnrollDialog(QDialog):
    """
    主界面内嵌式人脸录入窗口。

    只复用 MainWindow 已经采集到的 Azure Kinect 当前帧，不会再单独打开一套摄像头，
    避免和 Body Tracking 采集线程抢占设备。
    """

    def __init__(self, parent_window, user_id, name, min_samples=5):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.user_id = str(user_id)
        self.name = str(name)
        self.min_samples = int(min_samples)
        self.saved_record_ids = []
        self.completed = False

        self.setWindowTitle("添加人脸信息")
        self.resize(900, 650)
        self.setModal(True)

        self.title_label = QLabel(
            f"正在录入：编号 {self.user_id}，姓名 {self.name}\n"
            f"请至少拍摄 {self.min_samples} 张清晰人脸。建议正脸、轻微左转、轻微右转、不同距离各拍几张。"
        )
        self.title_label.setObjectName("PanelSubTitle")
        self.title_label.setWordWrap(True)

        self.preview_label = QLabel("等待摄像头画面...")
        self.preview_label.setObjectName("VideoView")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(760, 460)

        self.status_label = QLabel()
        self.status_label.setObjectName("PanelSubTitle")
        self.status_label.setWordWrap(True)

        self.btn_capture = QPushButton("拍摄")
        self.btn_done = QPushButton("完成")
        self.btn_capture.setObjectName("PurpleButton3")
        self.btn_done.setObjectName("PurpleButton1")

        for btn in [self.btn_capture, self.btn_done]:
            btn.setMinimumHeight(38)
            btn.setCursor(Qt.PointingHandCursor)

        self.btn_capture.clicked.connect(self.capture_face)
        self.btn_done.clicked.connect(self.finish_enroll)

        button_row = QHBoxLayout()
        button_row.addWidget(self.btn_capture)
        button_row.addWidget(self.btn_done)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.title_label)
        layout.addWidget(self.preview_label, stretch=1)
        layout.addWidget(self.status_label)
        layout.addLayout(button_row)

        # 复用主窗口主题。
        try:
            self.setStyleSheet(parent_window.styleSheet())
        except Exception:
            pass

        self.update_status()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_preview)
        self.timer.start(80)

    def _get_current_frame(self):
        if self.parent_window.current_face_frame is not None:
            return self.parent_window.current_face_frame.copy()
        if self.parent_window.current_frame is not None:
            return self.parent_window.current_frame.copy()
        return None

    def _frame_to_pixmap(self, frame):
        if frame is None:
            return None

        image = frame
        if image.ndim == 2:
            qimage = QImage(
                image.data,
                image.shape[1],
                image.shape[0],
                image.strides[0],
                QImage.Format_Grayscale8,
            ).copy()
        elif image.shape[2] == 4:
            rgba = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
            qimage = QImage(
                rgba.data,
                rgba.shape[1],
                rgba.shape[0],
                rgba.strides[0],
                QImage.Format_RGBA8888,
            ).copy()
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            qimage = QImage(
                rgb.data,
                rgb.shape[1],
                rgb.shape[0],
                rgb.strides[0],
                QImage.Format_RGB888,
            ).copy()

        return QPixmap.fromImage(qimage).scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

    def update_preview(self):
        frame = self._get_current_frame()
        if frame is None:
            self.preview_label.setText("等待摄像头画面...")
            return

        pixmap = self._frame_to_pixmap(frame)
        if pixmap is not None:
            self.preview_label.setPixmap(pixmap)

    def update_status(self, message=None):
        saved = len(self.saved_record_ids)
        remaining = max(0, self.min_samples - saved)
        base = f"已拍摄并录入 {saved} 张，至少还需 {remaining} 张。"
        if saved >= self.min_samples:
            base = f"已拍摄并录入 {saved} 张，可以点击“完成”。也可以继续拍摄更多样本。"
        if message:
            base += f"\n{message}"
        self.status_label.setText(base)

    def capture_face(self):
        frame = self._get_current_frame()
        if frame is None:
            QMessageBox.warning(self, "无法拍摄", "当前还没有可用的摄像头画面。")
            return

        face_engine = self.parent_window.face_engine
        if face_engine is None:
            QMessageBox.warning(self, "无法拍摄", "人脸识别模块不可用，无法提取人脸特征。")
            return

        try:
            faces = face_engine.detect_faces(frame)
        except Exception as e:
            self.parent_window.append_log(f"添加人脸时检测失败：{e}")
            QMessageBox.warning(self, "检测失败", f"人脸检测失败：\n{e}")
            return

        if len(faces) == 0:
            QMessageBox.warning(self, "未检测到人脸", "当前画面中没有检测到人脸，请面向摄像头后重试。")
            return

        if len(faces) > 1:
            QMessageBox.warning(
                self,
                "人脸数量过多",
                f"当前画面中检测到 {len(faces)} 张人脸。\n录入时请保证画面中只有一个人。",
            )
            return

        try:
            feature = face_engine.get_feature(frame, faces[0])
            db = self.parent_window.get_face_database()
            record_id = db.add_face(self.user_id, self.name, feature)
            self.saved_record_ids.append(record_id)
            known_count = self.parent_window.refresh_face_database_cache()
            self.parent_window.append_log(
                f"已拍摄人脸样本：记录ID={record_id}，编号={self.user_id}，姓名={self.name}；"
                f"人脸库已自动刷新，当前 {known_count} 条人脸特征。"
            )
            self.update_status(f"本次拍摄成功：记录ID={record_id}。")
        except Exception as e:
            self.parent_window.append_log(f"添加人脸记录失败：{e}")
            QMessageBox.warning(self, "添加失败", f"添加人脸记录失败：\n{e}")

    def finish_enroll(self):
        saved = len(self.saved_record_ids)
        if saved < self.min_samples:
            QMessageBox.warning(
                self,
                "样本不足",
                f"当前只录入了 {saved} 张，至少需要 {self.min_samples} 张。\n请继续点击“拍摄”。",
            )
            return

        self.completed = True
        self.parent_window.refresh_face_database_cache()
        QMessageBox.information(
            self,
            "录入完成",
            f"编号：{self.user_id}\n姓名：{self.name}\n本次共录入：{saved} 张人脸样本。",
        )
        self.accept()

    def reject(self):
        if self.completed:
            return super().reject()

        saved = len(self.saved_record_ids)
        if saved == 0:
            return super().reject()

        reply = QMessageBox.question(
            self,
            "放弃录入？",
            f"当前已拍摄 {saved} 张，但尚未点击“完成”。\n是否放弃本次录入并删除这些已保存样本？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                db = self.parent_window.get_face_database()
                deleted = db.delete_by_ids(self.saved_record_ids)
                known_count = self.parent_window.refresh_face_database_cache()
                self.parent_window.append_log(
                    f"已放弃本次人脸录入，删除 {deleted} 条临时样本；"
                    f"人脸库已自动刷新，当前 {known_count} 条人脸特征。"
                )
            except Exception as e:
                self.parent_window.append_log(f"放弃录入时删除临时样本失败：{e}")
            return super().reject()

    def closeEvent(self, event):
        before = self.result()
        self.reject()
        if self.result() != before or len(self.saved_record_ids) == 0 or self.completed:
            event.accept()
        else:
            event.ignore()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Azure Kinect人体姿态检测系统本地端")
        self.resize(1280, 760)

        self.current_frame = None
        # 保存一份尽量干净的彩色帧给人脸识别使用。
        # 如果 pose_detector 提供 color_frame，就使用未叠加骨架的原始彩色图；
        # 否则退回使用当前显示帧。
        self.current_face_frame = None
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

        # 人脸识别器：只在截图时调用，避免影响平时实时检测延迟。
        self.face_engine = None
        self.face_db = None
        self.last_screenshot_face_results = []
        self.last_screenshot_face_error = None

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
        self.init_face_engine()
        self.init_qq()
        self.start_camera()

    def init_ui(self):
        self.setMinimumSize(1024, 640)
        self.setObjectName("MainWindow")
        self.apply_theme()

        # ===== 左侧视频区域 =====
        self.video_title = QLabel("Azure Kinect 实时画面")
        self.video_title.setObjectName("PanelTitle")

        self.video_subtitle = QLabel("RGB 彩色图像 + 人体骨架叠加")
        self.video_subtitle.setObjectName("PanelSubTitle")

        video_header_text = QVBoxLayout()
        video_header_text.setContentsMargins(0, 0, 0, 0)
        video_header_text.setSpacing(2)
        video_header_text.addWidget(self.video_title)
        video_header_text.addWidget(self.video_subtitle)

        video_header = QHBoxLayout()
        video_header.setContentsMargins(0, 0, 0, 0)
        video_header.setSpacing(12)
        video_header.addLayout(video_header_text, stretch=1)

        # 系统状态四个框移动到视频画面正上方，不再单独显示“系统状态”标题
        self.time_value_label = QLabel("--")
        self.body_count_label = QLabel("0")
        self.qq_state_label = QLabel("关闭")
        self.live_state_label = QLabel("关闭")

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(10)
        status_row.addWidget(self.create_status_card("时间", self.time_value_label), stretch=1)
        status_row.addWidget(self.create_status_card("人数", self.body_count_label), stretch=1)
        status_row.addWidget(self.create_status_card("QQ监视", self.qq_state_label), stretch=1)
        status_row.addWidget(self.create_status_card("直播", self.live_state_label), stretch=1)

        self.image_label = QLabel("正在启动 Azure Kinect...")
        self.image_label.setObjectName("VideoView")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(700, 430)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        video_card = QFrame()
        video_card.setObjectName("VideoCard")
        video_layout = QVBoxLayout(video_card)
        video_layout.setContentsMargins(18, 16, 18, 18)
        video_layout.setSpacing(12)
        video_layout.addLayout(video_header)
        video_layout.addLayout(status_row)
        video_layout.addWidget(self.image_label, stretch=1)

        # ===== 右侧信息与控制区域 =====
        self.info_text = QTextEdit()
        self.info_text.setObjectName("InfoText")
        self.info_text.setReadOnly(True)
        self.info_text.setFont(QFont("Microsoft YaHei UI", 7))
        self.info_text.setMinimumHeight(210)
        self.info_text.setMaximumHeight(360)
        self.info_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.log_text = QTextEdit()
        self.log_text.setObjectName("LogText")
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 6))
        self.log_text.setMinimumHeight(100)
        self.log_text.setMaximumHeight(135)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.btn_screenshot = QPushButton("截图")
        self.btn_exit = QPushButton("退出")
        self.btn_start_qq = QPushButton("开始QQ监视")
        self.btn_stop_qq = QPushButton("关闭QQ监视")
        self.btn_show_faces = QPushButton("查看人脸库")
        self.btn_delete_faces = QPushButton("删除人脸记录")
        self.btn_add_face = QPushButton("添加人脸信息")

        self.btn_screenshot.setObjectName("PurpleButton1")
        self.btn_exit.setObjectName("PurpleButton2")
        self.btn_start_qq.setObjectName("PurpleButton3")
        self.btn_stop_qq.setObjectName("PurpleButton4")
        self.btn_show_faces.setObjectName("PurpleButton1")
        self.btn_delete_faces.setObjectName("PurpleButton2")
        self.btn_add_face.setObjectName("PurpleButton3")

        for btn in [
            self.btn_screenshot, self.btn_exit,
            self.btn_start_qq, self.btn_stop_qq,
            self.btn_show_faces, self.btn_delete_faces, self.btn_add_face
        ]:
            btn.setMinimumHeight(34)
            btn.setMaximumHeight(38)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.btn_screenshot.clicked.connect(self.save_screenshot_by_button)
        self.btn_exit.clicked.connect(self.close)
        self.btn_start_qq.clicked.connect(lambda: self.enable_qq_monitor("按钮"))
        self.btn_stop_qq.clicked.connect(lambda: self.disable_qq_monitor("按钮"))
        self.btn_show_faces.clicked.connect(self.show_face_database)
        self.btn_delete_faces.clicked.connect(self.delete_face_records_dialog)
        self.btn_add_face.clicked.connect(self.add_face_record_dialog)

        buttons_layout = QVBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)
        buttons_layout.addWidget(self.btn_screenshot)
        buttons_layout.addWidget(self.btn_exit)
        buttons_layout.addWidget(self.btn_start_qq)
        buttons_layout.addWidget(self.btn_stop_qq)
        buttons_layout.addWidget(self.btn_show_faces)
        buttons_layout.addWidget(self.btn_delete_faces)
        buttons_layout.addWidget(self.btn_add_face)

        right_card = QFrame()
        right_card.setObjectName("SideCard")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(10)
        right_layout.addWidget(self.make_section_title("姿态信息"))
        right_layout.addWidget(self.info_text, stretch=0)
        right_layout.addSpacing(8)
        right_layout.addWidget(self.make_section_title("运行日志"))
        right_layout.addWidget(self.log_text, stretch=0)
        right_layout.addSpacing(8)
        right_layout.addWidget(self.make_section_title("控制面板"))
        right_layout.addLayout(buttons_layout)
        right_layout.addStretch(1)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        main_layout.addWidget(video_card, stretch=7)
        main_layout.addWidget(right_card, stretch=3)

        self.setLayout(main_layout)
        self.update_status_badges()

    def make_section_title(self, text):
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def create_status_card(self, title, value_label):
        card = QFrame()
        card.setObjectName("StatusCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(1)

        title_label = QLabel(title)
        title_label.setObjectName("StatusCardTitle")

        value_label.setObjectName("StatusCardValue")
        value_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return card

    def apply_theme(self):
        self.setStyleSheet("""
        QWidget#MainWindow {
            background: #17112b;
            color: #f3e8ff;
            font-family: 'Microsoft YaHei UI', 'Segoe UI', Arial;
        }
        QFrame#VideoCard, QFrame#SideCard {
            background: #1e1637;
            border: 1px solid #3b2b63;
            border-radius: 18px;
        }
        QLabel#VideoView {
            background: #06030f;
            color: #c4b5fd;
            border: 1px solid #4c3a75;
            border-radius: 14px;
            font-size: 16px;
        }
        QLabel#PanelTitle {
            color: #faf5ff;
            font-size: 19px;
            font-weight: 700;
        }
        QLabel#PanelSubTitle {
            color: #c4b5fd;
            font-size: 11px;
        }
        QLabel#SectionTitle {
            color: #f3e8ff;
            font-size: 12px;
            font-weight: 700;
            padding-top: 1px;
        }
        QFrame#StatusCard {
            background: #2a1f49;
            border: 1px solid #5b3f8f;
            border-radius: 13px;
        }
        QLabel#StatusCardTitle {
            color: #d8b4fe;
            font-size: 10px;
        }
        QLabel#StatusCardValue {
            color: #ffffff;
            font-size: 13px;
            font-weight: 700;
        }
        QTextEdit#InfoText, QTextEdit#LogText {
            background: #35285f;
            color: #f5f3ff;
            border: 1px solid #6d4aa3;
            border-radius: 14px;
            padding: 6px;
            selection-background-color: #7c3aed;
            selection-color: #ffffff;
        }
        QTextEdit#InfoText:focus, QTextEdit#LogText:focus {
            border: 1px solid #a78bfa;
            background: #3c2d68;
        }
        QTextEdit#LogText {
            color: #ddd6fe;
        }
        QTextEdit#InfoText QScrollBar:vertical,
        QTextEdit#LogText QScrollBar:vertical {
            background: #24193f;
            width: 12px;
            margin: 10px 3px 10px 3px;
            border-radius: 6px;
        }
        QTextEdit#InfoText QScrollBar::handle:vertical,
        QTextEdit#LogText QScrollBar::handle:vertical {
            background: #7c3aed;
            min-height: 28px;
            border-radius: 6px;
        }
        QTextEdit#InfoText QScrollBar::handle:vertical:hover,
        QTextEdit#LogText QScrollBar::handle:vertical:hover {
            background: #a78bfa;
        }
        QTextEdit#InfoText QScrollBar::add-line:vertical,
        QTextEdit#InfoText QScrollBar::sub-line:vertical,
        QTextEdit#LogText QScrollBar::add-line:vertical,
        QTextEdit#LogText QScrollBar::sub-line:vertical {
            height: 0px;
            background: transparent;
        }
        QTextEdit#InfoText QScrollBar::add-page:vertical,
        QTextEdit#InfoText QScrollBar::sub-page:vertical,
        QTextEdit#LogText QScrollBar::add-page:vertical,
        QTextEdit#LogText QScrollBar::sub-page:vertical {
            background: transparent;
        }
        QPushButton {
            border: none;
            border-radius: 13px;
            padding: 6px 10px;
            color: white;
            font-size: 11px;
            font-weight: 700;
        }
        QPushButton#PurpleButton1 {
            background: #a78bfa;
        }
        QPushButton#PurpleButton1:hover {
            background: #b99cff;
        }
        QPushButton#PurpleButton1:pressed {
            background: #8b5cf6;
        }
        QPushButton#PurpleButton2 {
            background: #8b5cf6;
        }
        QPushButton#PurpleButton2:hover {
            background: #9f7aea;
        }
        QPushButton#PurpleButton2:pressed {
            background: #7c3aed;
        }
        QPushButton#PurpleButton3 {
            background: #7c3aed;
        }
        QPushButton#PurpleButton3:hover {
            background: #8b5cf6;
        }
        QPushButton#PurpleButton3:pressed {
            background: #6d28d9;
        }
        QPushButton#PurpleButton4 {
            background: #5b21b6;
        }
        QPushButton#PurpleButton4:hover {
            background: #6d28d9;
        }
        QPushButton#PurpleButton4:pressed {
            background: #4c1d95;
        }
        QMessageBox {
            background: #1e1637;
            color: #f3e8ff;
        }
        QMessageBox QLabel {
            color: #ffffff;
            background: transparent;
            font-family: 'Microsoft YaHei UI', 'Segoe UI', Arial;
            font-size: 12px;
        }
        QMessageBox QPushButton {
            background: #7c3aed;
            color: #ffffff;
            border-radius: 10px;
            padding: 6px 14px;
            min-width: 72px;
        }
        QMessageBox QPushButton:hover {
            background: #8b5cf6;
        }
        """)

    def update_status_badges(self):
        qq_on = self.qq_monitor_enabled
        live_on = self.live_stream_running

        self.qq_state_label.setText('开启' if qq_on else '关闭')
        self.live_state_label.setText('开启' if live_on else '关闭')

        self.qq_state_label.setStyleSheet(
            "color:#bbf7d0;" if qq_on else "color:#e9d5ff;"
        )
        self.live_state_label.setStyleSheet(
            "color:#dbeafe;" if live_on else "color:#e9d5ff;"
        )

    def init_face_engine(self):
        """
        初始化本地人脸识别模块。

        如果模型文件或 OpenCV contrib 组件缺失，这里只记录日志，不影响原有姿态检测、QQ 和直播功能。
        人脸数据库查看/删除只依赖 SQLite，因此即使模型缺失也可以管理数据库。
        """
        try:
            self.face_db = FaceDatabase()
        except Exception as e:
            self.face_db = None
            self.append_log(f"人脸数据库初始化失败：{e}")

        try:
            self.face_engine = FaceEngine()
            known_count = len(self.face_engine.known_faces)
            self.face_db = self.face_engine.db
            self.append_log(f"人脸识别模块初始化成功，已加载 {known_count} 条人脸特征。")
            if known_count == 0:
                self.append_log("人脸数据库为空：请先运行 enroll_face.py 录入人脸。")
        except Exception as e:
            self.face_engine = None
            self.append_log(f"人脸识别模块初始化失败：{e}")
            self.append_log("截图和跌倒报警仍会正常工作，但截图不会附加人脸识别结果。")

    def get_face_database(self):
        if self.face_db is None:
            self.face_db = FaceDatabase()
        return self.face_db

    def refresh_face_database_cache(self):
        """刷新内存中的人脸特征缓存，供添加/删除后自动调用。"""
        if self.face_engine is not None:
            self.face_engine.reload_database()
            return len(self.face_engine.known_faces)

        db = self.get_face_database()
        return db.count()

    def reload_face_database(self):
        """保留给内部调用或后续扩展：手动刷新内存中的人脸特征缓存。"""
        try:
            known_count = self.refresh_face_database_cache()
            self.append_log(f"人脸库已刷新，当前 {known_count} 条人脸特征。")
            QMessageBox.information(self, "刷新成功", f"人脸库已刷新。\n当前共有 {known_count} 条人脸特征。")
        except Exception as e:
            self.append_log(f"刷新人脸库失败：{e}")
            QMessageBox.warning(self, "刷新失败", f"刷新人脸库失败：\n{e}")

    def add_face_record_dialog(self):
        """打开多样本人脸录入窗口，自动分配从 1 开始的最小空闲编号。"""
        if self.face_engine is None:
            reply = QMessageBox.question(
                self,
                "人脸识别未初始化",
                "人脸识别模块当前不可用，可能是模型文件缺失或 OpenCV contrib 未正确安装。\n是否尝试重新初始化？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.init_face_engine()

            if self.face_engine is None:
                QMessageBox.warning(self, "无法添加", "人脸识别模块仍不可用，无法从画面中提取人脸特征。")
                return

        if self.current_face_frame is None and self.current_frame is None:
            QMessageBox.warning(self, "无法添加", "当前还没有可用的摄像头画面。")
            return

        try:
            db = self.get_face_database()
            user_id = str(db.get_next_available_user_id())
        except Exception as e:
            self.append_log(f"自动分配人脸编号失败：{e}")
            QMessageBox.warning(self, "无法添加", f"自动分配人脸编号失败：\n{e}")
            return

        name, ok = QInputDialog.getText(
            self,
            "添加人脸信息",
            f"系统将自动分配编号：{user_id}\n请输入姓名："
        )
        if not ok:
            return

        name = name.strip()
        if not name:
            QMessageBox.warning(self, "输入无效", "姓名不能为空。")
            return

        dialog = FaceEnrollDialog(
            parent_window=self,
            user_id=user_id,
            name=name,
            min_samples=5,
        )
        result = dialog.exec_()

        if result == QDialog.Accepted:
            known_count = self.refresh_face_database_cache()
            self.append_log(
                f"人脸信息录入完成：编号={user_id}，姓名={name}，"
                f"本次录入 {len(dialog.saved_record_ids)} 张；当前 {known_count} 条人脸特征。"
            )

    def build_face_database_text(self, max_records=80):
        db = self.get_face_database()
        people = db.list_people()
        records = db.list_faces(limit=max_records)
        total = db.count()

        lines = [
            f"数据库路径：{db.db_path}",
            f"总人脸特征数：{total}",
            "",
            "【按人员汇总】",
        ]

        if not people:
            lines.append("当前没有录入任何人脸。")
        else:
            for item in people:
                lines.append(
                    f"用户ID：{item['user_id']} | 姓名：{item['name']} | "
                    f"特征数：{item['feature_count']} | 最近录入：{item['last_created_at']}"
                )

        lines.extend(["", f"【记录列表，最多显示 {max_records} 条】"])

        if not records:
            lines.append("无记录。")
        else:
            for row in records:
                lines.append(
                    f"ID={row['id']} | 用户ID={row['user_id']} | 姓名={row['name']} | "
                    f"维度={row['dim']} | 录入时间={row['created_at']}"
                )

            if total > max_records:
                lines.append(f"……还有 {total - max_records} 条未显示，可用 manage_faces.py list 查看全部。")

        lines.extend([
            "",
            "删除说明：",
            "1. 可在本窗口点击“删除人脸记录”。",
            "2. 也可命令行执行：python manage_faces.py list",
            "3. 在主界面添加或删除人脸记录后，系统会自动刷新主程序中的人脸特征缓存。",
        ])

        return "\n".join(lines)

    def show_face_database(self):
        try:
            text = self.build_face_database_text()
            dialog = QMessageBox(self)
            dialog.setWindowTitle("人脸库")
            dialog.setText(text)
            dialog.setIcon(QMessageBox.Information)
            dialog.exec_()
        except Exception as e:
            self.append_log(f"查看人脸库失败：{e}")
            QMessageBox.warning(self, "查看失败", f"查看人脸库失败：\n{e}")

    def delete_face_records_dialog(self):
        help_text = (
            "请输入删除目标：\n"
            "1. 删除指定记录ID：1,2,3\n"
            "2. 删除某个用户ID全部记录：user:001\n"
            "3. 删除某个姓名全部记录：name:张三\n"
            "4. 清空全部记录：all\n"
        )

        text, ok = QInputDialog.getText(self, "删除人脸记录", help_text)
        if not ok:
            return

        command = text.strip()
        if not command:
            return

        try:
            db = self.get_face_database()

            if command.lower() == "all":
                target_desc = f"全部 {db.count()} 条人脸特征"
                delete_func = db.clear
            elif command.lower().startswith("user:"):
                user_id = command.split(":", 1)[1].strip()
                target_count = len(db.list_faces(user_id=user_id))
                target_desc = f"用户ID={user_id} 的 {target_count} 条人脸特征"
                delete_func = lambda: db.delete_by_user_id(user_id)
            elif command.lower().startswith("name:"):
                name = command.split(":", 1)[1].strip()
                target_count = len(db.list_faces(name=name))
                target_desc = f"姓名={name} 的 {target_count} 条人脸特征"
                delete_func = lambda: db.delete_by_name(name)
            else:
                ids = [item.strip() for item in command.replace("，", ",").split(",") if item.strip()]
                ids = [int(item) for item in ids]
                target_count = len([row for row in db.list_faces() if row["id"] in ids])
                target_desc = f"记录ID={ids} 的 {target_count} 条人脸特征"
                delete_func = lambda: db.delete_by_ids(ids)

            reply = QMessageBox.question(
                self,
                "确认删除",
                f"即将删除：{target_desc}。\n删除后不可恢复，是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if reply != QMessageBox.Yes:
                return

            deleted = delete_func()
            known_count = self.refresh_face_database_cache()

            self.append_log(f"已删除 {deleted} 条人脸特征，人脸库已自动刷新，当前 {known_count} 条人脸特征。")
            QMessageBox.information(
                self,
                "删除完成",
                f"已删除 {deleted} 条人脸特征。\n人脸库已自动刷新，当前共有 {known_count} 条人脸特征。"
            )

        except Exception as e:
            self.append_log(f"删除人脸记录失败：{e}")
            QMessageBox.warning(self, "删除失败", f"删除人脸记录失败：\n{e}")

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

        raw_color_frame = None
        if isinstance(info, dict):
            raw_color_frame = info.get("color_frame")

        if raw_color_frame is not None:
            self.current_face_frame = raw_color_frame.copy()
        else:
            self.current_face_frame = frame.copy()

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
        short_time = info["timestamp"].strftime("%H:%M:%S")

        self.time_value_label.setText(short_time)
        self.body_count_label.setText(str(info["num_bodies"]))
        self.update_status_badges()

        pose_html = []

        if info["num_bodies"] == 0:
            pose_html.append("""
            <div style='padding:5px 0;color:#c4b5fd;font-size:11px;'>
                未检测到人体
            </div>
            """)
        else:
            for item in info["poses"]:
                pose = item["pose"]
                if pose == "疑似跌倒":
                    color = "#fecaca"
                    bg = "#7f1d1d"
                    border = "#ef4444"
                elif "举" in pose or "平举" in pose:
                    color = "#dbeafe"
                    bg = "#1d4ed8"
                    border = "#60a5fa"
                elif pose in {"下蹲", "弯腰"}:
                    color = "#fef3c7"
                    bg = "#92400e"
                    border = "#f59e0b"
                else:
                    color = "#dcfce7"
                    bg = "#14532d"
                    border = "#22c55e"

                pose_html.append(f"""
                <div style='margin:4px 0;padding:6px;border-radius:10px;
                            background:#281e48;border:1px solid #6d4aa3;'>
                    <div style='color:#ddd6fe;font-size:10px;font-weight:700;'>人物{item['person_index']}：</div>
                    <div style='margin-top:3px;'>
                        <span style='display:inline-block;padding:3px 8px;border-radius:999px;
                                     background:{bg};color:{color};border:1px solid {border};
                                     font-weight:700;font-size:11px;'>
                            {pose}
                        </span>
                    </div>
                </div>
                """)

        html = f"""
        <div style='font-family:Microsoft YaHei UI, Segoe UI, Arial;color:#f5f3ff;font-size:11px;'>
            <div style='font-size:9px;color:#d8b4fe;'>当前时间</div>
            <div style='font-size:12px;font-weight:700;color:#f8fafc;margin-bottom:4px;'>{timestamp}</div>

            <div style='font-size:9px;color:#d8b4fe;margin-top:6px;'>检测结果</div>
            <div style='margin-bottom:8px;'>
                <b>人数：</b>{info['num_bodies']}
            </div>

            <div style='font-size:9px;color:#d8b4fe;margin-top:8px;'>每个人的姿态</div>
            {''.join(pose_html)}

            <div style='margin-top:6px;padding:6px;border-radius:10px;background:#281e48;border:1px solid #6d4aa3;color:#e9d5ff;font-size:10px;'>
                <div><b>QQ 指令：</b>开始监听 / 停止监听 / 截图 / 直播 / 结束直播</div>
                <div style='margin-top:3px;color:#c4b5fd;'>疑似跌倒会自动报警，但不会自动开启 QQ 监视。</div>
            </div>
        </div>
        """

        self.info_text.setHtml(html)

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
                    f"人物{item['person_index']}：{item['pose']}"
                )

        return "\n".join(lines)

    def build_face_results_lines(self, face_results=None, face_error=None):
        """
        把最近一次截图的人脸识别结果格式化成文本行。
        普通截图、QQ截图、跌倒报警都复用这段逻辑。
        """
        lines = ["人脸识别结果："]

        if face_error:
            lines.append(f"人脸识别失败：{face_error}")
        elif self.face_engine is None:
            lines.append("人脸识别模块未启用或初始化失败。")
        elif not face_results:
            lines.append("未检测到可识别的人脸。")
        else:
            for index, face in enumerate(face_results, start=1):
                name = face.get("name", "Unknown")
                score = float(face.get("score", -1.0))

                if name == "Unknown":
                    lines.append(f"人脸{index}：未知人员，相似度 {score:.2f}")
                else:
                    lines.append(f"人脸{index}：{name}，相似度 {score:.2f}")

        return lines

    def _scale_face_results_for_frame(self, face_results, source_frame, target_frame):
        """
        人脸检测通常在未叠加骨架的原始彩色帧上做，截图保存的是当前显示帧。
        正常情况下两者尺寸一致；如果尺寸不同，这里把人脸框缩放到截图尺寸。
        """
        if not face_results or source_frame is None or target_frame is None:
            return face_results

        source_h, source_w = source_frame.shape[:2]
        target_h, target_w = target_frame.shape[:2]

        if source_w == target_w and source_h == target_h:
            return face_results

        if source_w <= 0 or source_h <= 0:
            return face_results

        scale_x = target_w / source_w
        scale_y = target_h / source_h

        scaled_results = []
        for item in face_results:
            copied = dict(item)
            x, y, w, h = copied.get("box", (0, 0, 0, 0))
            copied["box"] = (
                int(x * scale_x),
                int(y * scale_y),
                int(w * scale_x),
                int(h * scale_y),
            )
            scaled_results.append(copied)

        return scaled_results

    def build_fall_alert_message(self, info, face_results=None, face_error=None):
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
        lines.extend(self.build_face_results_lines(face_results, face_error))

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
        2. 跌倒报警不再单独做人脸识别；它复用截图流程中的人脸识别结果。
        3. 报警截图会通过 save_screenshot_to_file() 自动标注人脸框和姓名。
        4. 报警不会自动开启监听。
        5. 同一段连续跌倒只报警一次；恢复正常后才允许下一次报警。
        6. 额外加入冷却时间，避免误识别抖动导致频繁报警。
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

        # 跌倒会自动截图；截图函数内部会统一做人脸识别和标注。
        path = self.save_screenshot_to_file(prefix="fall_alert")
        face_results = list(self.last_screenshot_face_results or [])
        face_error = self.last_screenshot_face_error

        message = self.build_fall_alert_message(info, face_results, face_error)

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
        self.update_status_badges()

        if already_open:
            self.send_qq_feedback("QQ监视已经是开启状态。")
        else:
            self.send_qq_feedback("QQ监视已开启。")

    def disable_qq_monitor(self, source="按钮"):
        already_closed = not self.qq_monitor_enabled

        self.qq_monitor_enabled = False
        self.append_log(f"QQ监视已关闭，来源：{source}")
        self.update_status_badges()

        if already_closed:
            self.send_qq_feedback("QQ监视本来就是关闭状态。")
        else:
            self.send_qq_feedback("QQ监视已关闭。")

    def append_log(self, text):
        print(text)
        if hasattr(self, "log_text") and self.log_text is not None:
            now = time.strftime("%H:%M:%S")
            self.log_text.append(f"[{now}] {text}")
            self.log_text.moveCursor(QTextCursor.End)

    def save_screenshot_to_file(self, frame=None, prefix="screenshot"):
        """
        保存截图，返回 Path。

        每次截图都会统一做人脸识别：
        - 优先用未叠加骨架的 current_face_frame 做识别，减少骨架线对人脸特征的影响；
        - 在最终截图上画出人脸框和姓名；
        - 识别结果保存到 self.last_screenshot_face_results / self.last_screenshot_face_error，
          供按钮截图、QQ截图和跌倒报警文本复用。
        """
        self.last_screenshot_face_results = []
        self.last_screenshot_face_error = None

        if frame is None:
            if self.current_frame is None:
                return None
            screenshot_frame = self.current_frame.copy()
            recognition_frame = (
                self.current_face_frame.copy()
                if self.current_face_frame is not None
                else screenshot_frame.copy()
            )
        else:
            screenshot_frame = frame.copy()
            recognition_frame = (
                self.current_face_frame.copy()
                if self.current_face_frame is not None
                else screenshot_frame.copy()
            )

        # 统一在截图前做人脸识别，并把结果画到截图上。
        if self.face_engine is not None and recognition_frame is not None:
            try:
                face_results = self.face_engine.recognize_faces(recognition_frame)
                self.last_screenshot_face_results = face_results

                if face_results:
                    draw_results = self._scale_face_results_for_frame(
                        face_results,
                        recognition_frame,
                        screenshot_frame,
                    )
                    screenshot_frame = self.face_engine.draw_results(
                        screenshot_frame,
                        draw_results,
                    )

                self.append_log(f"截图人脸识别完成，检测到 {len(face_results)} 张人脸。")
            except Exception as e:
                self.last_screenshot_face_results = []
                self.last_screenshot_face_error = str(e)
                self.append_log(f"截图人脸识别失败：{e}")

        screenshots_dir = Path(__file__).resolve().parent / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        millisecond = int((time.time() % 1) * 1000)
        filename = f"{prefix}_{timestamp}_{millisecond:03d}.png"
        path = screenshots_dir / filename

        image = screenshot_frame
        if image is None:
            return None

        # OpenCV imwrite 对 BGR/GRAY 最稳定；BGRA 也能写 PNG，但这里统一转成 BGR。
        if len(image.shape) == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        ok = cv2.imwrite(str(path), image)

        if not ok:
            return None

        return path

    def save_screenshot_by_button(self):
        path = self.save_screenshot_to_file()

        if path is None:
            QMessageBox.warning(self, "截图失败", "当前还没有可保存的摄像头画面，或保存失败。")
            return

        face_text = "\n".join(
            self.build_face_results_lines(
                self.last_screenshot_face_results,
                self.last_screenshot_face_error,
            )
        )
        QMessageBox.information(self, "截图成功", f"截图已保存：\n{path}\n\n{face_text}")
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

        face_results = list(self.last_screenshot_face_results or [])
        face_error = self.last_screenshot_face_error

        thread = threading.Thread(
            target=self.send_qq_screenshot_background,
            args=(path, face_results, face_error),
            daemon=True
        )
        thread.start()

    def send_qq_screenshot_background(self, path, face_results=None, face_error=None):
        try:
            face_text = "\n".join(self.build_face_results_lines(face_results, face_error))
            self.qq_controller.send_text(f"截图成功，正在发送图片：{path.name}\n\n{face_text}")
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
            "说明：\n"
            "1. 可以点击观看地址，也可以扫描二维码打开直播页面。\n"
            "2. 二维码只包含观看地址，不包含用户名和临时密钥。\n"
            "3. 浏览器弹出登录框后，请输入上面的用户名和临时密钥。"
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
            self.bridge.log_signal.emit("UI状态：直播已开启。")

            watch_url = result.get("watch_url")

            # 只有本次新启动直播时才重新生成二维码；
            # 如果直播已经在运行，则直接复用已有直播地址，不重复生成文件也可以。
            qr_path = None
            if watch_url:
                try:
                    qr_path = self.live_manager.generate_live_qrcode(watch_url)
                    self.bridge.log_signal.emit(f"直播二维码已生成：{qr_path}")
                except Exception as e:
                    self.bridge.log_signal.emit(f"直播二维码生成失败：{e}")

            # 先发送二维码图片，再发送文字说明
            if qr_path:
                try:
                    status_code, send_result = self.qq_controller.send_image(qr_path)
                    self.bridge.log_signal.emit(
                        f"直播二维码发送完成，HTTP状态码：{status_code}，返回：{send_result}"
                    )
                except Exception as e:
                    self.bridge.log_signal.emit(f"直播二维码发送失败：{e}")
                    try:
                        self.qq_controller.send_text(f"直播已启动，但二维码发送失败：{e}")
                    except Exception:
                        pass    

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
            self.bridge.log_signal.emit("UI状态：直播已关闭。")

            if was_running:
                message = "【Azure Kinect 直播】\n直播已停止，二维码图片已删除。"
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
