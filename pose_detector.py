import math
from collections import Counter, deque
from datetime import datetime

import pykinect_azure as pykinect


# =========================
# Azure Kinect / BodyTrack 配置
# =========================

def make_tracker_config():
    """
    Body Tracking 配置。
    默认使用 GPU 模式；如果你的电脑 GPU 模式报错，可以把 GPU 改成 CPU。
    """
    tracker_config = pykinect.default_tracker_configuration
    tracker_config.sensor_orientation = pykinect.K4ABT_SENSOR_ORIENTATION_DEFAULT

    # 如果 GPU 模式不稳定，把下面这一行改为：
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


# =========================
# 关节点读取与几何计算
# =========================

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


def is_invalid_point(point):
    """
    简单过滤无效点。
    Body Tracking 偶尔会返回接近 (0,0,0) 的异常点。
    """
    return abs(point[0]) < 1e-3 and abs(point[1]) < 1e-3 and abs(point[2]) < 1e-3


def distance_3d(p1, p2):
    return math.sqrt(
        (p1[0] - p2[0]) ** 2 +
        (p1[1] - p2[1]) ** 2 +
        (p1[2] - p2[2]) ** 2
    )


def vec_from_to(p1, p2):
    return (
        p2[0] - p1[0],
        p2[1] - p1[1],
        p2[2] - p1[2],
    )


def vector_norm(vector):
    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def angle_between_vectors(v1, v2):
    """
    计算两个三维向量夹角，单位：度。
    """
    n1 = vector_norm(v1)
    n2 = vector_norm(v2)

    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0

    cos_value = (
        v1[0] * v2[0] +
        v1[1] * v2[1] +
        v1[2] * v2[2]
    ) / (n1 * n2)

    cos_value = max(-1.0, min(1.0, cos_value))
    return math.degrees(math.acos(cos_value))


def angle_at_b(point_a, point_b, point_c):
    """
    计算 A-B-C 中 B 点处的夹角。
    用于计算膝盖角度、肘部角度。
    """
    ba = vec_from_to(point_b, point_a)
    bc = vec_from_to(point_b, point_c)
    return angle_between_vectors(ba, bc)


# =========================
# 姿态识别逻辑
# =========================

def recognize_pose(skeleton):
    """
    强化版人体姿态识别。

    1. 使用躯干长度、肩宽等人体比例做动态阈值，减少远近距离影响。
    2. 使用膝盖角度判断下蹲/坐姿，减少站立误判。
    3. 使用躯干与竖直方向夹角判断弯腰和跌倒。
    4. 跌倒采用多条件评分，而不是单独用人体高度判断。
    5. 支持“举手 + 下蹲/弯腰”的组合姿态。

    坐标说明：
    x：左右方向
    y：上下方向，向下为正
    z：前后方向，远离相机为正
    """
    try:
        head = get_joint_position(skeleton, "HEAD")
        neck = get_joint_position(skeleton, "NECK")
        pelvis = get_joint_position(skeleton, "PELVIS")

        left_shoulder = get_joint_position(skeleton, "SHOULDER_LEFT")
        right_shoulder = get_joint_position(skeleton, "SHOULDER_RIGHT")

        left_elbow = get_joint_position(skeleton, "ELBOW_LEFT")
        right_elbow = get_joint_position(skeleton, "ELBOW_RIGHT")

        left_wrist = get_joint_position(skeleton, "WRIST_LEFT")
        right_wrist = get_joint_position(skeleton, "WRIST_RIGHT")

        left_hip = get_joint_position(skeleton, "HIP_LEFT")
        right_hip = get_joint_position(skeleton, "HIP_RIGHT")

        left_knee = get_joint_position(skeleton, "KNEE_LEFT")
        right_knee = get_joint_position(skeleton, "KNEE_RIGHT")

        left_ankle = get_joint_position(skeleton, "ANKLE_LEFT")
        right_ankle = get_joint_position(skeleton, "ANKLE_RIGHT")

    except Exception:
        return "无法判断"

    core_points = [
        head, neck, pelvis,
        left_shoulder, right_shoulder,
        left_hip, right_hip,
        left_knee, right_knee,
        left_ankle, right_ankle,
    ]

    valid_core_points = [point for point in core_points if not is_invalid_point(point)]
    if len(valid_core_points) < 7:
        return "无法判断"

    # -------- 人体尺度：用于动态阈值 --------
    shoulder_width = max(distance_3d(left_shoulder, right_shoulder), 250.0)
    torso_length = max(distance_3d(neck, pelvis), 350.0)

    all_points = [
        head, neck, pelvis,
        left_shoulder, right_shoulder,
        left_elbow, right_elbow,
        left_wrist, right_wrist,
        left_hip, right_hip,
        left_knee, right_knee,
        left_ankle, right_ankle,
    ]
    all_points = [point for point in all_points if not is_invalid_point(point)]

    ys = [point[1] for point in all_points]
    xs = [point[0] for point in all_points]
    zs = [point[2] for point in all_points]

    body_height_y = max(ys) - min(ys)
    body_width_x = max(xs) - min(xs)
    body_depth_z = max(zs) - min(zs)
    body_horizontal_extent = max(body_width_x, body_depth_z)

    avg_ankle_y = (left_ankle[1] + right_ankle[1]) / 2.0
    pelvis_to_ankle_y = avg_ankle_y - pelvis[1]

    # pelvis -> neck 接近竖直向上时，躯干角度小。
    # y 轴向下，所以竖直向上是 (0, -1, 0)。
    torso_vector = vec_from_to(pelvis, neck)
    vertical_up = (0.0, -1.0, 0.0)
    torso_angle = angle_between_vectors(torso_vector, vertical_up)

    left_knee_angle = angle_at_b(left_hip, left_knee, left_ankle)
    right_knee_angle = angle_at_b(right_hip, right_knee, right_ankle)
    avg_knee_angle = (left_knee_angle + right_knee_angle) / 2.0

    left_elbow_angle = angle_at_b(left_shoulder, left_elbow, left_wrist)
    right_elbow_angle = angle_at_b(right_shoulder, right_elbow, right_wrist)

    # -------- 手部动作：举手 / 平举 --------
    hand_up_margin = max(80.0, torso_length * 0.18)
    elbow_raise_margin = max(80.0, torso_length * 0.20)

    left_hand_up = (
        left_wrist[1] < head[1] - hand_up_margin and
        left_elbow[1] < left_shoulder[1] + elbow_raise_margin
    )

    right_hand_up = (
        right_wrist[1] < head[1] - hand_up_margin and
        right_elbow[1] < right_shoulder[1] + elbow_raise_margin
    )

    side_margin_y = max(100.0, torso_length * 0.25)

    left_arm_side = (
        abs(left_wrist[1] - left_shoulder[1]) < side_margin_y and
        abs(left_wrist[0] - left_shoulder[0]) > shoulder_width * 0.55 and
        left_elbow_angle > 120
    )

    right_arm_side = (
        abs(right_wrist[1] - right_shoulder[1]) < side_margin_y and
        abs(right_wrist[0] - right_shoulder[0]) > shoulder_width * 0.55 and
        right_elbow_angle > 120
    )

    hand_pose = None
    if left_hand_up and right_hand_up:
        hand_pose = "双手举起"
    elif left_hand_up:
        hand_pose = "举左手"
    elif right_hand_up:
        hand_pose = "举右手"
    elif left_arm_side and right_arm_side:
        hand_pose = "双手平举"
    elif left_arm_side:
        hand_pose = "左手平举"
    elif right_arm_side:
        hand_pose = "右手平举"

    # -------- 跌倒：多条件评分，减少弯腰/坐姿误判 --------
    # 当前项目相机安装高度约 1.1m，低机位会让侧倒、半躺、低位倒地时的
    # 骨架竖直高度和水平展开不如高机位明显，因此这里适度放宽阈值。
    # 仍然保留 fall_score >= 3，避免把普通坐姿、下蹲直接误报为跌倒。
    fall_score = 0

    # 躯干接近水平：由 65° 放宽到 60°，更容易识别侧倒/半躺。
    if torso_angle > 60:
        fall_score += 1

    # 竖直高度明显降低：由 700 / 1.45 放宽到 780 / 1.55。
    if body_height_y < max(780.0, torso_length * 1.55):
        fall_score += 1

    # 水平方向展开明显大于竖直高度：由 0.9 放宽到 0.8。
    if body_horizontal_extent > body_height_y * 0.8:
        fall_score += 1

    # 头部和骨盆高度接近，常见于躺倒：由 280 / 0.55 放宽到 330 / 0.65。
    if abs(head[1] - pelvis[1]) < max(330.0, torso_length * 0.65):
        fall_score += 1

    if fall_score >= 3:
        return "疑似跌倒"

    # -------- 下蹲 / 坐姿 --------
    pelvis_ankle_ratio = pelvis_to_ankle_y / max(body_height_y, 1.0)

    deep_squat_or_sit = (
        pelvis_ankle_ratio < 0.40 and
        avg_knee_angle < 125 and
        torso_angle < 35
    )

    squat = (
        pelvis_ankle_ratio < 0.48 and
        avg_knee_angle < 150 and
        torso_angle < 40
    )

    if deep_squat_or_sit:
        return f"下蹲/坐姿+{hand_pose}" if hand_pose else "下蹲/坐姿"

    if squat:
        return f"下蹲+{hand_pose}" if hand_pose else "下蹲"

    # -------- 弯腰 --------
    bend_over = (
        35 <= torso_angle < 70 and
        head[1] < pelvis[1]
    )

    if bend_over:
        return f"弯腰+{hand_pose}" if hand_pose else "弯腰"

    # -------- 站立 / 手部动作 --------
    if hand_pose:
        return hand_pose

    if torso_angle < 25 and avg_knee_angle > 145:
        return "站立"

    return "其他姿态"


class PoseSmoother:
    """
    多帧投票平滑。
    作用：减少单帧骨骼点抖动导致的姿态频繁跳变。
    """

    def __init__(self, window_size=5, min_count=3):
        self.window_size = window_size
        self.min_count = min_count
        self.history = {}

    def update(self, body_key, raw_pose):
        if body_key not in self.history:
            self.history[body_key] = deque(maxlen=self.window_size)

        self.history[body_key].append(raw_pose)
        counter = Counter(self.history[body_key])
        most_common_pose, count = counter.most_common(1)[0]

        if count >= self.min_count:
            return most_common_pose

        return raw_pose

    def clear_missing_bodies(self, current_body_keys):
        current_body_keys = set(current_body_keys)
        for body_key in list(self.history.keys()):
            if body_key not in current_body_keys:
                del self.history[body_key]


def make_pose_state(pose_items):
    """
    用于判断姿态是否变化。
    只要任意一个人的姿态变化，整体 state 就会变化。
    """
    return tuple((item["person_index"], item["body_id"], item["pose"]) for item in pose_items)


# =========================
# 检测器类
# =========================

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

        # 姿态平滑窗口：5 帧中至少 3 帧一致才稳定输出。
        self.pose_smoother = PoseSmoother(window_size=5, min_count=3)

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
        current_body_keys = []

        if num_bodies > 0:
            for body_index in range(num_bodies):
                skeleton = body_frame.get_body_skeleton(body_index)
                raw_pose_text = recognize_pose(skeleton)

                try:
                    body_id = body_frame.get_body_id(body_index)
                except Exception:
                    body_id = body_index

                # 用 body_id 做平滑键；如果 body_id 不可哈希，退回字符串。
                try:
                    hash(body_id)
                    body_key = body_id
                except Exception:
                    body_key = str(body_id)

                pose_text = self.pose_smoother.update(body_key, raw_pose_text)
                current_body_keys.append(body_key)

                pose_items.append({
                    "person_index": body_index + 1,
                    "body_id": body_id,
                    "pose": pose_text,
                    "raw_pose": raw_pose_text,
                })

            self.pose_smoother.clear_missing_bodies(current_body_keys)

            # 画骨架到 RGB 彩色相机坐标系，避免深度图坐标和 RGB 图错位。
            color_camera_type = getattr(pykinect, "K4A_CALIBRATION_TYPE_COLOR", 1)
            display_image = body_frame.draw_bodies(display_image, color_camera_type)
        else:
            self.pose_smoother.clear_missing_bodies([])

        timestamp = datetime.now()

        info = {
            "timestamp": timestamp,
            "num_bodies": num_bodies,
            "poses": pose_items,
            "pose_state": make_pose_state(pose_items),
            # 给人脸识别使用的原始彩色图，不叠加骨架，避免骨架线影响人脸特征。
            "color_frame": color_image.copy(),
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
