from pathlib import Path

import cv2
import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None

from face_db import FaceDatabase


class FaceEngine:
    """
    YuNet + SFace 本地人脸识别引擎。

    用法：
    - recognize_faces(frame)：检测并识别一帧里的所有人脸。
    - draw_results(frame, face_results)：把识别结果画到截图上。
    """

    def __init__(
        self,
        detector_model="models/face_detection_yunet_2023mar.onnx",
        recognizer_model="models/face_recognition_sface_2021dec.onnx",
        db_path="data/faces.db",
        score_threshold=0.9,
        similarity_threshold=0.36,
        min_face_size=60,
    ):
        self.detector_model = Path(detector_model)
        self.recognizer_model = Path(recognizer_model)
        self.db_path = db_path
        self.score_threshold = float(score_threshold)
        self.similarity_threshold = float(similarity_threshold)
        self.min_face_size = int(min_face_size)

        if not self.detector_model.exists():
            raise FileNotFoundError(
                f"未找到 YuNet 模型：{self.detector_model}\n"
                "请先运行 download_face_models.py，或把模型放到 models/ 目录。"
            )

        if not self.recognizer_model.exists():
            raise FileNotFoundError(
                f"未找到 SFace 模型：{self.recognizer_model}\n"
                "请先运行 download_face_models.py，或把模型放到 models/ 目录。"
            )

        self.detector = self._create_detector()
        self.recognizer = self._create_recognizer()

        self.db = FaceDatabase(db_path)
        self.known_faces = self.db.load_all_faces()

    def _create_detector(self):
        # 兼容不同 OpenCV 版本的 Python API 命名。
        if hasattr(cv2, "FaceDetectorYN"):
            return cv2.FaceDetectorYN.create(
                str(self.detector_model),
                "",
                (320, 320),
                self.score_threshold,
                0.3,
                5000,
            )

        if hasattr(cv2, "FaceDetectorYN_create"):
            return cv2.FaceDetectorYN_create(
                str(self.detector_model),
                "",
                (320, 320),
                self.score_threshold,
                0.3,
                5000,
            )

        raise RuntimeError(
            "当前 cv2 不支持 FaceDetectorYN。请安装 opencv-contrib-python==4.10.0.84。"
        )

    def _create_recognizer(self):
        if hasattr(cv2, "FaceRecognizerSF"):
            return cv2.FaceRecognizerSF.create(str(self.recognizer_model), "")

        if hasattr(cv2, "FaceRecognizerSF_create"):
            return cv2.FaceRecognizerSF_create(str(self.recognizer_model), "")

        raise RuntimeError(
            "当前 cv2 不支持 FaceRecognizerSF。请安装 opencv-contrib-python==4.10.0.84。"
        )

    def reload_database(self):
        self.known_faces = self.db.load_all_faces()
        return len(self.known_faces)

    @staticmethod
    def to_bgr(frame):
        if frame is None:
            return None

        if len(frame.shape) == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        if len(frame.shape) == 3 and frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        return frame

    @staticmethod
    def normalize_feature(feature):
        feature = np.asarray(feature, dtype=np.float32).flatten()
        norm = np.linalg.norm(feature)
        if norm > 0:
            feature = feature / norm
        return feature.astype(np.float32)

    def detect_faces(self, frame):
        frame = self.to_bgr(frame)
        if frame is None:
            return []

        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)

        if faces is None:
            return []

        return faces

    def get_feature(self, frame, face):
        frame = self.to_bgr(frame)
        aligned_face = self.recognizer.alignCrop(frame, face)
        feature = self.recognizer.feature(aligned_face)
        return self.normalize_feature(feature)

    @staticmethod
    def cosine_similarity(a, b):
        a = np.asarray(a, dtype=np.float32).flatten()
        b = np.asarray(b, dtype=np.float32).flatten()
        if a.shape != b.shape:
            return -1.0
        return float(np.dot(a, b))

    def recognize_one(self, feature):
        if not self.known_faces:
            return "Unknown", -1.0, None

        best_name = "Unknown"
        best_user_id = None
        best_score = -1.0

        for item in self.known_faces:
            score = self.cosine_similarity(feature, item["embedding"])
            if score > best_score:
                best_score = score
                best_name = item["name"]
                best_user_id = item["user_id"]

        if best_score >= self.similarity_threshold:
            return best_name, best_score, best_user_id

        return "Unknown", best_score, None

    def recognize_faces(self, frame):
        frame = self.to_bgr(frame)
        if frame is None:
            return []

        faces = self.detect_faces(frame)
        results = []

        for face in faces:
            x, y, w, h = face[:4].astype(int)

            # 太小的人脸通常识别不稳定，直接过滤。
            if w < self.min_face_size or h < self.min_face_size:
                continue

            feature = self.get_feature(frame, face)
            name, score, user_id = self.recognize_one(feature)

            results.append(
                {
                    "name": name,
                    "score": float(score),
                    "user_id": user_id,
                    "box": (int(x), int(y), int(w), int(h)),
                }
            )

        return results

    @staticmethod
    def _load_unicode_font(font_size=28):
        """
        加载支持中文的系统字体。

        OpenCV 的 cv2.putText 不支持中文，中文姓名会显示成问号。
        这里优先使用 Windows 常见中文字体；如果 Pillow 或字体不可用，
        后续会自动回退到 cv2.putText。
        """
        if ImageFont is None:
            return None

        candidate_paths = [
            "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
            "C:/Windows/Fonts/msyhbd.ttc",    # 微软雅黑粗体
            "C:/Windows/Fonts/simhei.ttf",    # 黑体
            "C:/Windows/Fonts/simsun.ttc",    # 宋体
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        ]

        for font_path in candidate_paths:
            try:
                path = Path(font_path)
                if path.exists():
                    return ImageFont.truetype(str(path), font_size)
            except Exception:
                continue

        for font_name in ["msyh.ttc", "simhei.ttf", "simsun.ttc", "arial.ttf"]:
            try:
                return ImageFont.truetype(font_name, font_size)
            except Exception:
                continue

        return None

    @classmethod
    def _draw_unicode_label(cls, image_bgr, text, x, y, font_size=28):
        """
        在 BGR 图像上绘制 Unicode 文本。
        文本颜色固定为白色，并加深色背景，保证应用窗口和截图里都清晰可见。
        """
        if Image is None or ImageDraw is None:
            return False

        font = cls._load_unicode_font(font_size)
        if font is None:
            return False

        try:
            image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(image_rgb)
            draw = ImageDraw.Draw(pil_image)

            # Pillow 新旧版本兼容：优先 textbbox，失败则用 textsize。
            try:
                left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
                text_w = right - left
                text_h = bottom - top
            except Exception:
                text_w, text_h = draw.textsize(text, font=font)

            padding_x = 8
            padding_y = 5
            img_h, img_w = image_bgr.shape[:2]

            x = max(0, min(int(x), max(0, img_w - text_w - padding_x * 2)))
            y = int(y)
            if y < 0:
                y = 0
            if y + text_h + padding_y * 2 > img_h:
                y = max(0, img_h - text_h - padding_y * 2)

            # 深色底 + 白字，避免“应用窗口中识别结果文字发黑/看不清”。
            draw.rectangle(
                [x, y, x + text_w + padding_x * 2, y + text_h + padding_y * 2],
                fill=(17, 24, 39),
                outline=(34, 197, 94),
                width=2,
            )
            draw.text(
                (x + padding_x, y + padding_y),
                text,
                font=font,
                fill=(255, 255, 255),
            )

            image_bgr[:, :] = cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2BGR)
            return True
        except Exception:
            return False

    def draw_results(self, frame, face_results):
        image = self.to_bgr(frame).copy()

        for item in face_results:
            x, y, w, h = item["box"]
            name = item.get("name", "Unknown")
            score = float(item.get("score", -1.0))

            if name == "Unknown":
                label = f"未知人员 {score:.2f}"
            else:
                label = f"{name} {score:.2f}"

            x, y, w, h = int(x), int(y), int(w), int(h)
            cv2.rectangle(image, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # 使用 Pillow 画 Unicode 中文；如果 Pillow/字体不可用，再回退到 OpenCV 英文。
            label_y = y - 38
            ok = self._draw_unicode_label(image, label, x, label_y, font_size=28)

            if not ok:
                fallback_label = f"{name if name.isascii() else 'Known'} {score:.2f}"
                cv2.rectangle(
                    image,
                    (x, max(0, y - 32)),
                    (x + min(260, max(120, len(fallback_label) * 16)), max(30, y)),
                    (17, 24, 39),
                    -1,
                )
                cv2.putText(
                    image,
                    fallback_label,
                    (x + 6, max(24, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.75,
                    (255, 255, 255),
                    2,
                )

        return image
