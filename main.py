import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

from app_window import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    
    def lock_window_size():
        window.setFixedSize(window.size())

    QTimer.singleShot(300, lock_window_size)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
