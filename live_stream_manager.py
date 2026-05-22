import os
import time
import json
import qrcode
import socket
import secrets
import string
import threading
import subprocess
from pathlib import Path

import requests

from h264_streamer import H264Streamer


class LiveStreamManager:
    """
    直播管理器：
    1. 自动检查 / 启动 MediaMTX。
    2. 启动 FFmpeg，将当前画面推到 MediaMTX。
    3. 启动 ngrok，将 MediaMTX 的 HLS 端口暴露到公网。
    4. 临时生成 Basic Auth 用户名和密码。
    5. 停止直播时关闭 FFmpeg、ngrok，以及本管理器自动启动的 MediaMTX。

    默认端口：
    - MediaMTX RTMP: 1935
    - MediaMTX HLS : 8888

    可在 .env 里配置：
    MEDIAMTX_PATH=D:/tools/mediamtx/mediamtx.exe
    LIVE_AUTO_START_MEDIAMTX=1
    LIVE_RTMP_URL=rtmp://127.0.0.1/live/kinect
    LIVE_HLS_PATH=/live/kinect
    LIVE_NGROK_HTTP_PORT=8888
    LIVE_WIDTH=960
    LIVE_HEIGHT=540
    LIVE_FPS=10
    LIVE_BITRATE=600k
    FFMPEG_PATH=ffmpeg
    NGROK_PATH=ngrok
    """

    def __init__(
        self,
        rtmp_url=None,
        hls_path=None,
        ngrok_http_port=None,
        width=None,
        height=None,
        fps=None,
        bitrate=None,
        ffmpeg_path=None,
        ngrok_path=None,
        mediamtx_path=None,
        auto_start_mediamtx=None,
        work_dir=None,
        on_log=None,
    ):
        self.rtmp_url = rtmp_url or os.getenv("LIVE_RTMP_URL", "rtmp://127.0.0.1/live/kinect")
        self.hls_path = hls_path or os.getenv("LIVE_HLS_PATH", "/live/kinect")
        self.ngrok_http_port = int(ngrok_http_port or os.getenv("LIVE_NGROK_HTTP_PORT", "8888"))

        self.width = int(width or os.getenv("LIVE_WIDTH", "960"))
        self.height = int(height or os.getenv("LIVE_HEIGHT", "540"))
        self.fps = int(fps or os.getenv("LIVE_FPS", "10"))
        self.bitrate = bitrate or os.getenv("LIVE_BITRATE", "600k")

        self.ffmpeg_path = ffmpeg_path or os.getenv("FFMPEG_PATH", "ffmpeg")
        self.ngrok_path = ngrok_path or os.getenv("NGROK_PATH", "ngrok")
        self.mediamtx_path = mediamtx_path or os.getenv("MEDIAMTX_PATH", "mediamtx")

        if auto_start_mediamtx is None:
            auto_start_text = os.getenv("LIVE_AUTO_START_MEDIAMTX", "1").strip().lower()
            self.auto_start_mediamtx = auto_start_text not in {"0", "false", "no", "off"}
        else:
            self.auto_start_mediamtx = bool(auto_start_mediamtx)

        base_dir = Path(__file__).resolve().parent
        self.work_dir = Path(work_dir or base_dir / "live_runtime")
        self.work_dir.mkdir(exist_ok=True)

        self.on_log = on_log

        self.streamer = None
        self.ngrok_process = None
        self.mediamtx_process = None
        self.mediamtx_started_by_me = False

        self.ngrok_stderr_lines = []
        self.ngrok_stderr_thread = None
        self.mediamtx_output_lines = []
        self.mediamtx_output_thread = None

        self.public_base_url = None
        self.watch_url = None
        self.auth_username = None
        self.auth_password = None
        self.policy_path = None
        self.live_qrcode_path = None

        self.running = False
        self.lock = threading.RLock()

    def log(self, text):
        if self.on_log:
            self.on_log(text)
        else:
            print(text)

    def _generate_password(self, length=18):
        # Basic Auth 密码放在 YAML 的 user:password 中。这里避免冒号和空格，减少转义问题。
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def _is_tcp_port_open(self, host, port, timeout=0.5):
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            return False

    def _wait_for_port(self, host, port, timeout=15):
        start = time.time()
        while time.time() - start < timeout:
            if self._is_tcp_port_open(host, port):
                return True

            if self.mediamtx_process and self.mediamtx_process.poll() is not None:
                raise RuntimeError(
                    "MediaMTX 进程已退出，无法启动直播。\n"
                    f"MediaMTX 最近输出：\n{self.get_mediamtx_recent_output()}"
                )

            time.sleep(0.3)

        return False

    def _start_mediamtx_if_needed(self):
        """
        如果 MediaMTX 已经在运行，则直接复用。
        如果没有运行，并且 LIVE_AUTO_START_MEDIAMTX=1，则自动启动 mediamtx.exe。
        """
        rtmp_ready = self._is_tcp_port_open("127.0.0.1", 1935)
        hls_ready = self._is_tcp_port_open("127.0.0.1", self.ngrok_http_port)

        if rtmp_ready and hls_ready:
            self.log("检测到 MediaMTX 已经在运行，复用现有服务。")
            self.mediamtx_started_by_me = False
            return

        if not self.auto_start_mediamtx:
            raise RuntimeError(
                "MediaMTX 没有运行。请先手动启动 mediamtx.exe，或在 .env 中设置 LIVE_AUTO_START_MEDIAMTX=1。"
            )

        self.log("未检测到 MediaMTX 服务，正在自动启动 MediaMTX...")

        mediamtx_cmd = self.mediamtx_path
        cwd = None
        try:
            mediamtx_file = Path(mediamtx_cmd)
            if mediamtx_file.exists():
                cwd = str(mediamtx_file.resolve().parent)
        except Exception:
            cwd = None

        startupinfo = None
        if os.name == "nt":
            # Windows 下尽量不弹出额外控制台窗口。
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        self.mediamtx_process = subprocess.Popen(
            [mediamtx_cmd],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            startupinfo=startupinfo,
        )
        self.mediamtx_started_by_me = True

        self.mediamtx_output_lines.clear()
        self.mediamtx_output_thread = threading.Thread(
            target=self._read_mediamtx_output_loop,
            daemon=True,
        )
        self.mediamtx_output_thread.start()

        if not self._wait_for_port("127.0.0.1", 1935, timeout=15):
            raise RuntimeError(
                "等待 MediaMTX RTMP 端口 1935 超时。\n"
                f"MediaMTX 最近输出：\n{self.get_mediamtx_recent_output()}"
            )

        if not self._wait_for_port("127.0.0.1", self.ngrok_http_port, timeout=15):
            raise RuntimeError(
                f"等待 MediaMTX HLS 端口 {self.ngrok_http_port} 超时。\n"
                f"MediaMTX 最近输出：\n{self.get_mediamtx_recent_output()}"
            )

        self.log("MediaMTX 已自动启动。")

    def _read_mediamtx_output_loop(self):
        if not self.mediamtx_process or not self.mediamtx_process.stdout:
            return

        for line in self.mediamtx_process.stdout:
            line = line.strip()
            if line:
                self.mediamtx_output_lines.append(line)
                self.mediamtx_output_lines[:] = self.mediamtx_output_lines[-40:]

    def _write_ngrok_policy(self):
        self.auth_username = "viewer"
        self.auth_password = self._generate_password()

        self.policy_path = self.work_dir / "ngrok-basic-auth-policy.yml"

        # 这里生成临时 Basic Auth 凭据。
        # 观看者需要同时拥有 ngrok 网址、用户名和密码。
        policy = (
            "on_http_request:\n"
            "  - actions:\n"
            "      - type: basic-auth\n"
            "        config:\n"
            "          credentials:\n"
            f"            - {self.auth_username}:{self.auth_password}\n"
        )

        self.policy_path.write_text(policy, encoding="utf-8")

    def _start_ngrok(self):
        self._write_ngrok_policy()

        command = [
            self.ngrok_path,
            "http",
            str(self.ngrok_http_port),
            "--traffic-policy-file",
            str(self.policy_path),
        ]

        self.ngrok_process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
        )

        self.ngrok_stderr_lines.clear()
        self.ngrok_stderr_thread = threading.Thread(
            target=self._read_ngrok_stderr_loop,
            daemon=True,
        )
        self.ngrok_stderr_thread.start()

        self.public_base_url = self._wait_for_ngrok_public_url()
        self.watch_url = self.public_base_url.rstrip("/") + self.hls_path

    def _read_ngrok_stderr_loop(self):
        if not self.ngrok_process or not self.ngrok_process.stderr:
            return

        for line in self.ngrok_process.stderr:
            line = line.strip()
            if line:
                self.ngrok_stderr_lines.append(line)
                self.ngrok_stderr_lines[:] = self.ngrok_stderr_lines[-30:]

    def _wait_for_ngrok_public_url(self, timeout=20):
        api_url = "http://127.0.0.1:4040/api/tunnels"
        start = time.time()

        last_error = None

        while time.time() - start < timeout:
            if self.ngrok_process and self.ngrok_process.poll() is not None:
                raise RuntimeError(
                    "ngrok 进程已退出。请确认 ngrok 已登录，并且当前版本支持 --traffic-policy-file。\n"
                    f"ngrok 最近输出：\n{self.get_ngrok_recent_stderr()}"
                )

            try:
                response = requests.get(api_url, timeout=2)
                data = response.json()

                for tunnel in data.get("tunnels", []):
                    public_url = tunnel.get("public_url", "")
                    config = tunnel.get("config", {})
                    addr = str(config.get("addr", ""))

                    # 优先找指向 8888 的 https 隧道。
                    if public_url.startswith("https://") and str(self.ngrok_http_port) in addr:
                        return public_url

                # 兜底：取第一个 https 隧道
                for tunnel in data.get("tunnels", []):
                    public_url = tunnel.get("public_url", "")
                    if public_url.startswith("https://"):
                        return public_url

            except Exception as e:
                last_error = e

            time.sleep(0.5)

        raise RuntimeError(
            "等待 ngrok 公网地址超时。\n"
            f"最后错误：{last_error}\n"
            f"ngrok 最近输出：\n{self.get_ngrok_recent_stderr()}"
        )

    def start(self):
        with self.lock:
            if self.running:
                return {
                    "already_running": True,
                    "watch_url": self.watch_url,
                    "username": self.auth_username,
                    "password": self.auth_password,
                }

            self.log("正在启动直播服务...")

            try:
                self._start_mediamtx_if_needed()

                self.log("正在启动 H.264 FFmpeg 推流...")
                self.streamer = H264Streamer(
                    rtmp_url=self.rtmp_url,
                    width=self.width,
                    height=self.height,
                    fps=self.fps,
                    bitrate=self.bitrate,
                    ffmpeg_path=self.ffmpeg_path,
                )
                self.streamer.start()

                self.log("FFmpeg 推流已启动，正在启动 ngrok 公网隧道...")
                self._start_ngrok()

                self.running = True

                self.log(f"直播已启动：{self.watch_url}")

                return {
                    "already_running": False,
                    "watch_url": self.watch_url,
                    "username": self.auth_username,
                    "password": self.auth_password,
                }

            except Exception:
                # 任何一步失败都要清理已启动的 MediaMTX / FFmpeg / ngrok，避免后台残留进程。
                self.stop()
                raise

    def generate_live_qrcode(self, live_url):
        """
        生成直播观看地址二维码。
        二维码只包含观看地址，不包含用户名和临时密钥。
        """
        qr_dir = self.work_dir / "live_qrcode"
        qr_dir.mkdir(exist_ok=True)

        filename = time.strftime("live_qrcode_%Y%m%d_%H%M%S.png")
        qr_path = qr_dir / filename

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=3
        )

        qr.add_data(live_url)
        qr.make(fit=True)

        img = qr.make_image(
            fill_color="black",
            back_color="white"
        )

        img.save(str(qr_path))

        self.live_qrcode_path = qr_path
        return qr_path


    def delete_live_qrcode(self):
        """
        删除本次直播生成的二维码图片。
        """
        qr_path = getattr(self, "live_qrcode_path", None)

        if qr_path and Path(qr_path).exists():
            try:
                Path(qr_path).unlink()
                self.log(f"直播二维码已删除：{qr_path}")
            except Exception as e:
                self.log(f"删除直播二维码失败：{e}")

        self.live_qrcode_path = None

    def write_frame(self, frame):
        if self.running and self.streamer:
            self.streamer.write_frame(frame)

    def stop(self):
        with self.lock:
            if (
                not self.running
                and self.streamer is None
                and self.ngrok_process is None
                and self.mediamtx_process is None
            ):
                return False

            was_running = self.running or self.streamer is not None or self.ngrok_process is not None
            self.running = False

            if self.streamer:
                try:
                    self.streamer.stop()
                except Exception as e:
                    self.log(f"停止 FFmpeg 推流时发生错误：{e}")
                self.streamer = None

            if self.ngrok_process:
                try:
                    self.ngrok_process.terminate()
                except Exception:
                    pass

                try:
                    self.ngrok_process.wait(timeout=3)
                except Exception:
                    try:
                        self.ngrok_process.kill()
                    except Exception:
                        pass

                self.ngrok_process = None

            # 只有本管理器自动启动的 MediaMTX 才会在结束直播时关闭。
            # 如果用户本来已经手动启动了 MediaMTX，则不会关掉用户的进程。
            if self.mediamtx_process:
                try:
                    self.mediamtx_process.terminate()
                except Exception:
                    pass

                try:
                    self.mediamtx_process.wait(timeout=3)
                except Exception:
                    try:
                        self.mediamtx_process.kill()
                    except Exception:
                        pass

                self.mediamtx_process = None
                self.mediamtx_started_by_me = False
                self.log("自动启动的 MediaMTX 已停止。")

            self.delete_live_qrcode()

            self.log("直播已停止。")
            return bool(was_running)

    def get_ngrok_recent_stderr(self):
        if not self.ngrok_stderr_lines:
            return "暂无 ngrok stderr 输出。"
        return "\n".join(self.ngrok_stderr_lines)

    def get_mediamtx_recent_output(self):
        if not self.mediamtx_output_lines:
            return "暂无 MediaMTX 输出。"
        return "\n".join(self.mediamtx_output_lines)

    def close(self):
        self.stop()
