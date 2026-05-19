import subprocess
import threading
import queue
import time
from collections import deque

import cv2
import numpy as np


class H264Streamer:
    """
    将 OpenCV 帧写入 FFmpeg，由 FFmpeg 编码为 H.264 并推送到 MediaMTX 的 RTMP 地址。

    默认推流地址：
        rtmp://127.0.0.1/live/kinect

    注意：
        1. MediaMTX 必须先启动。
        2. ffmpeg 必须已经加入系统 Path，或者通过 ffmpeg_path 指定完整路径。
    """

    def __init__(
        self,
        rtmp_url="rtmp://127.0.0.1/live/kinect",
        width=960,
        height=540,
        fps=10,
        bitrate="600k",
        ffmpeg_path="ffmpeg",
    ):
        self.rtmp_url = rtmp_url
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.bitrate = str(bitrate)
        self.ffmpeg_path = ffmpeg_path

        self.process = None
        self.running = False
        self.frame_queue = queue.Queue(maxsize=2)
        self.writer_thread = None
        self.stderr_thread = None
        self.stderr_lines = deque(maxlen=30)

    def start(self):
        if self.running:
            return

        command = [
            self.ffmpeg_path,

            # 输入：Python 通过 stdin 传入原始 BGR 帧
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "-",

            # 编码：H.264
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-b:v", self.bitrate,
            "-maxrate", self.bitrate,
            "-bufsize", "1200k",
            "-pix_fmt", "yuv420p",

            # GOP 约 2 秒，利于 HLS 生成可播放片段
            "-g", str(self.fps * 2),
            "-keyint_min", str(self.fps * 2),
            "-sc_threshold", "0",

            # 输出：RTMP 使用 FLV 封装
            "-f", "flv",
            self.rtmp_url,
        ]

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
            text=False,
        )

        self.running = True

        self.stderr_thread = threading.Thread(
            target=self._stderr_loop,
            daemon=True,
        )
        self.stderr_thread.start()

        self.writer_thread = threading.Thread(
            target=self._writer_loop,
            daemon=True,
        )
        self.writer_thread.start()

        # 给 FFmpeg 一点时间连接 MediaMTX。如果 MediaMTX 没启动，通常会很快退出。
        time.sleep(0.8)
        if self.process.poll() is not None:
            self.running = False
            raise RuntimeError(
                "FFmpeg 推流进程已退出。请确认 MediaMTX 已启动，并且 RTMP 端口 1935 可用。\n"
                f"最近 FFmpeg 输出：\n{self.get_recent_stderr()}"
            )

    def write_frame(self, frame):
        if not self.running or self.process is None:
            return

        if frame is None:
            return

        # Azure Kinect 彩色图常见是 BGRA，FFmpeg 输入这里要求 BGR24。
        if len(frame.shape) == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height))

        frame = np.ascontiguousarray(frame, dtype=np.uint8)

        try:
            if self.frame_queue.full():
                self.frame_queue.get_nowait()
            self.frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    def _writer_loop(self):
        while self.running:
            try:
                frame = self.frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                if self.process is None or self.process.stdin is None:
                    self.running = False
                    break
                self.process.stdin.write(frame.tobytes())
            except Exception:
                self.running = False
                break

    def _stderr_loop(self):
        if not self.process or not self.process.stderr:
            return

        while True:
            try:
                line = self.process.stderr.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="ignore").strip()
                except Exception:
                    text = str(line)
                if text:
                    self.stderr_lines.append(text)
            except Exception:
                break

    def get_recent_stderr(self):
        if not self.stderr_lines:
            return "暂无 FFmpeg stderr 输出。"
        return "\n".join(self.stderr_lines)

    def stop(self):
        self.running = False

        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
            except Exception:
                pass

            try:
                self.process.terminate()
            except Exception:
                pass

            try:
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

            self.process = None
