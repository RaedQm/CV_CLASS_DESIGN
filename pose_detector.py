import math
from datetime import datetime

import pykinect_azure as pykinect


def make_tracker_config():
    """
    Body Tracking 配置。
    默认使用 CPU 模式，最容易跑通。
    """
    tracker_config = pykinect.default_tracker_configuration
    tracker_config.sensor_orientation = pykinect.K4ABT_SENSOR_ORIENTATION_DEFAULT
    # tracker_config.tracker_processing_mode = pykinect.K4ABT_TRACKER_PROCESSING_MODE_CPU
    tracker_config.tracker_processing_mode = pykinect.K4ABT_TRACKER_PROCESSING_MODE_GPU
    tracker_config.gpu_device_id = 0
    return tracker_config


def get_joint_id(name, fallback_id):
    return getattr(pykinect, name, fallback_id)


JOINT = {
    "PELVIS": get_joint_id("K4ABT_JOINT_PELVIS", 0),
    "SPINE_CHEST": get_joint_id("K4ABT_JOINT_SPINE_CHEST", 2),
    "NECK": get_joint_id("K4ABT_JOINT_NECK", 3),

    "SHOULDER_LEFT": get_joint_id("K4ABT_JOINT_SHOULDER_LEFT", 5),
    "ELBOW_LEFT": get_joint_id("K4ABT_JOINT_ELBOW_LEFT", 6),
    "WRIST_LEFT": get_joint_id("K4ABT_JOINT_WRIST_LEFT", 7),
    "HAND_LEFT": get_joint_id("K4ABT_JOINT_HAND_LEFT", 8),

    "SHOULDER_RIGHT": get_joint_id("K4ABT_JOINT_SHOULDER_RIGHT", 12),
    "ELBOW_RIGHT": get_joint_id("K4ABT_JOINT_ELBOW_RIGHT", 13),
    "WRIST_RIGHT": get_joint_id("K4ABT_JOINT_WRIST_RIGHT", 14),
    "HAND_RIGHT": get_joint_id("K4ABT_JOINT_HAND_RIGHT", 15),

    "HIP_LEFT": get_joint_id("K4ABT_JOINT_HIP_LEFT", 18),
    "KNEE_LEFT": get_joint_id("K4ABT_JOINT_KNEE_LEFT", 19),
    "ANKLE_LEFT": get_joint_id("K4ABT_JOINT_ANKLE_LEFT", 20),

    "HIP_RIGHT": get_joint_id("K4ABT_JOINT_HIP_RIGHT", 22),
    "KNEE_RIGHT": get_joint_id("K4ABT_JOINT_KNEE_RIGHT", 23),
    "ANKLE_RIGHT": get_joint_id("K4ABT_JOINT_ANKLE_RIGHT", 24),

    "HEAD": get_joint_id("K4ABT_JOINT_HEAD", 26),
}


def get_xyz_from_joint(joint):
    """
    读取关节点 3D 坐标，单位：毫米。
    """
    pos = joint.position

    if hasattr(pos, "v"):
        return float(pos.v[0]), float(pos.v[1]), float(pos.v[2])

    if hasattr(pos, "xyz"):
        return float(pos.xyz.x), float(pos.xyz.y), float(pos.xyz.z)

    if hasattr(pos, "x"):
        return float(pos.x), float(pos.y), float(pos.z)

    raise RuntimeError("无法读取关节点坐标，请检查 pykinect_azure 的 joint.position 结构。")


def get_joint_position(skeleton, joint_name):
    joint_index = JOINT[joint_name]
    joint = skeleton.joints[joint_index]
    return get_xyz_from_joint(joint)


def recognize_pose(skeleton):
    """
    简单姿态识别。
    坐标说明：
    x：左右方向
    y：上下方向，向下为正
    z：前后方向，远离相机为正
    """
    head = get_joint_position(skeleton, "HEAD")
    neck = get_joint_position(skeleton, "NECK")
    pelvis = get_joint_position(skeleton, "PELVIS")

    left_wrist = get_joint_position(skeleton, "WRIST_LEFT")
    right_wrist = get_joint_position(skeleton, "WRIST_RIGHT")

    left_ankle = get_joint_position(skeleton, "ANKLE_LEFT")
    right_ankle = get_joint_position(skeleton, "ANKLE_RIGHT")

    ankle_y = (left_ankle[1] + right_ankle[1]) / 2.0
    body_height_y = ankle_y - head[1]
    pelvis_to_ankle_y = ankle_y - pelvis[1]
    head_to_pelvis_y = pelvis[1] - head[1]

    neck_pelvis_horizontal = math.sqrt(
        (neck[0] - pelvis[0]) ** 2 +
        (neck[2] - pelvis[2]) ** 2
    )
    neck_pelvis_vertical = abs(neck[1] - pelvis[1])
    tilt_ratio = neck_pelvis_horizontal / max(neck_pelvis_vertical, 1.0)

    # y 越小表示越高，所以手腕 y < 头部 y 表示举手
    left_hand_up = left_wrist[1] < head[1] - 80
    right_hand_up = right_wrist[1] < head[1] - 80

    squat = pelvis_to_ankle_y < head_to_pelvis_y * 0.70
    bend_over = tilt_ratio > 0.55
    fall = body_height_y < 650

    if fall:
        return "疑似跌倒"

    if left_hand_up and right_hand_up:
        return "双手举起"

    if left_hand_up:
        return "举左手"

    if right_hand_up:
        return "举右手"

    if squat:
        return "下蹲"

    if bend_over:
        return "弯腰"

    return "站立"


def make_pose_state(pose_items):
    """
    用于判断姿态是否变化。
    只要任意一个人的姿态变化，整体 state 就会变化。
    """
    return tuple((item["person_index"], item["body_id"], item["pose"]) for item in pose_items)


class BodyPoseDetector:
    """
    Azure Kinect 人体姿态检测器。
    read_frame() 每次返回：
    - display_image：RGB 摄像头图像 + 骨架
    - info：人数、每个人姿态、时间、整体姿态状态
    """

    def __init__(self):
        pykinect.initialize_libraries(track_body=True)

        device_config = pykinect.default_configuration
        device_config.color_resolution = pykinect.K4A_COLOR_RESOLUTION_720P
        device_config.depth_mode = pykinect.K4A_DEPTH_MODE_WFOV_2X2BINNED
        device_config.camera_fps = pykinect.K4A_FRAMES_PER_SECOND_15

        self.device = pykinect.start_device(config=device_config)
        self.body_tracker = pykinect.start_body_tracker(
            tracker_configuration=make_tracker_config()
        )

        if hasattr(self.body_tracker, "set_temporal_smoothing"):
            self.body_tracker.set_temporal_smoothing(0.3)

    def read_frame(self):
        capture = self.device.update()

        try:
            body_frame = self.body_tracker.update(capture)
        except TypeError:
            body_frame = self.body_tracker.update()

        ret_color, color_image = capture.get_color_image()
        if not ret_color:
            return None, None

        display_image = color_image.copy()
        num_bodies = body_frame.get_num_bodies()
        pose_items = []

        if num_bodies > 0:
            for body_index in range(num_bodies):
                skeleton = body_frame.get_body_skeleton(body_index)
                pose_text = recognize_pose(skeleton)

                try:
                    body_id = body_frame.get_body_id(body_index)
                except Exception:
                    body_id = body_index

                pose_items.append({
                    "person_index": body_index + 1,
                    "body_id": body_id,
                    "pose": pose_text,
                })

            # 画骨架到 RGB 彩色相机坐标系，避免深度图坐标和 RGB 图错位
            color_camera_type = getattr(pykinect, "K4A_CALIBRATION_TYPE_COLOR", 1)
            display_image = body_frame.draw_bodies(display_image, color_camera_type)

        timestamp = datetime.now()

        info = {
            "timestamp": timestamp,
            "num_bodies": num_bodies,
            "poses": pose_items,
            "pose_state": make_pose_state(pose_items),
        }

        return display_image, info

    def close(self):
        try:
            if hasattr(self.device, "stop_cameras"):
                self.device.stop_cameras()
        except Exception:
            pass

        try:
            if hasattr(self.device, "close"):
                self.device.close()
        except Exception:
            pass
