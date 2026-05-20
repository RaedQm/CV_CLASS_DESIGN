import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

from app_window import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()

    # 启动后默认最大化，并在最大化尺寸下锁定窗口大小，禁止用户手动拖拽缩放。
    # 延迟执行是为了等待系统完成最大化布局计算。
    def lock_window_size():
        window.setFixedSize(window.size())

    QTimer.singleShot(300, lock_window_size)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
