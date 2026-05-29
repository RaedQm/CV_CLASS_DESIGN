"""
下载 OpenCV YuNet + SFace ONNX 模型。

如果你的网络访问 GitHub 不稳定，可以用：
    python download_face_models.py --proxy http://127.0.0.1:7890

如果校园网/代理做了 HTTPS 证书拦截，且你确认当前网络可信，可以临时用：
    python download_face_models.py --no-verify

如果脚本仍失败，请按脚本最后打印的地址用浏览器手动下载，放到 models/ 目录。
"""

from pathlib import Path
import argparse
import sys
import time

import requests


MODELS = {
    "face_detection_yunet_2023mar.onnx": {
        "url": "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "page": "https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "min_size": 100_000,
    },
    "face_recognition_sface_2021dec.onnx": {
        "url": "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "page": "https://github.com/opencv/opencv_zoo/blob/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "min_size": 30_000_000,
    },
}


def is_git_lfs_pointer(path: Path) -> bool:
    try:
        head = path.read_bytes()[:128]
        return head.startswith(b"version https://git-lfs.github.com/spec/v1")
    except Exception:
        return False


def download_file(filename: str, meta: dict, model_dir: Path, proxy: str | None, verify: bool):
    url = meta["url"]
    path = model_dir / filename
    temp_path = model_dir / f".{filename}.part"

    if path.exists() and path.stat().st_size >= meta["min_size"] and not is_git_lfs_pointer(path):
        print(f"已存在，跳过：{path}")
        return

    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    headers = {
        "User-Agent": "Mozilla/5.0 model-downloader",
        "Accept": "application/octet-stream,*/*",
    }

    last_error = None
    for attempt in range(1, 4):
        try:
            print(f"正在下载：{filename}，第 {attempt}/3 次")
            with requests.get(
                url,
                stream=True,
                timeout=(15, 90),
                headers=headers,
                proxies=proxies,
                verify=verify,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()

                total = int(response.headers.get("Content-Length", "0") or 0)
                downloaded = 0
                last_print = time.time()

                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.time()
                        if now - last_print > 0.8:
                            if total > 0:
                                percent = downloaded * 100 / total
                                print(f"  已下载 {downloaded / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB ({percent:.1f}%)")
                            else:
                                print(f"  已下载 {downloaded / 1024 / 1024:.1f} MB")
                            last_print = now

            if temp_path.stat().st_size < meta["min_size"]:
                raise RuntimeError(
                    f"下载文件过小：{temp_path.stat().st_size} bytes，可能下载到了错误页面或 Git LFS 指针。"
                )

            if is_git_lfs_pointer(temp_path):
                raise RuntimeError("下载到的是 Git LFS 指针文件，不是真正的 ONNX 模型。")

            temp_path.replace(path)
            print(f"已保存：{path}，大小 {path.stat().st_size / 1024 / 1024:.1f} MB")
            return

        except Exception as e:
            last_error = e
            print(f"下载失败：{e}")
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            time.sleep(1.5)

    raise RuntimeError(f"{filename} 下载失败：{last_error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", default=None, help="代理地址，例如 http://127.0.0.1:7890")
    parser.add_argument("--no-verify", action="store_true", help="关闭 HTTPS 证书校验，仅在可信网络下临时使用")
    args = parser.parse_args()

    model_dir = Path(__file__).resolve().parent / "models"
    model_dir.mkdir(exist_ok=True)

    if args.no_verify:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print("警告：已关闭 HTTPS 证书校验。仅建议在可信网络中临时使用。")

    errors = []
    for filename, meta in MODELS.items():
        try:
            download_file(filename, meta, model_dir, args.proxy, verify=not args.no_verify)
        except Exception as e:
            errors.append((filename, str(e)))

    if errors:
        print("\n有模型下载失败：")
        for filename, error in errors:
            print(f"- {filename}: {error}")

        print("\n手动下载办法：")
        print("1. 用浏览器打开下面两个官方 GitHub 页面。")
        print("2. 点击页面里的 Download raw file。")
        print("3. 把下载后的文件放到项目的 models/ 目录。")
        for filename, meta in MODELS.items():
            print(f"- {filename}: {meta['page']}")

        print("\n也可以尝试代理：")
        print("python download_face_models.py --proxy http://127.0.0.1:7890")
        print("\n如果是校园网/公司网 HTTPS 拦截导致，可临时尝试：")
        print("python download_face_models.py --no-verify")
        sys.exit(1)

    print("\n模型下载完成。")


if __name__ == "__main__":
    main()
