import argparse
from pathlib import Path

import cv2

from face_db import FaceDatabase
from face_engine import FaceEngine


def parse_args():
    parser = argparse.ArgumentParser(description="录入人脸到 SQLite 数据库。")
    parser.add_argument("--user-id", default=None, help="用户 ID。")
    parser.add_argument("--name", default=None, help="用户名/姓名。")
    parser.add_argument("--camera", type=int, default=0, help="摄像头编号，默认 0。")
    parser.add_argument("--image", default=None, help="从单张图片录入，而不是打开摄像头。")
    parser.add_argument("--db", default="data/faces.db", help="人脸数据库路径。")
    return parser.parse_args()


def draw_faces(frame, faces):
    image = frame.copy()
    for face in faces:
        x, y, w, h = face[:4].astype(int)
        cv2.rectangle(image, (x, y), (x + w, y + h), (0, 255, 0), 2)
    return image


def enroll_from_image(engine, db, user_id, name, image_path):
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"无法读取图片：{image_path}")

    faces = engine.detect_faces(image)
    if len(faces) != 1:
        raise RuntimeError(f"图片中需要恰好 1 张人脸，当前检测到 {len(faces)} 张。")

    feature = engine.get_feature(image, faces[0])
    db.add_face(user_id, name, feature)
    print(f"已从图片录入：{name} / {user_id} / {image_path}")


def enroll_from_camera(engine, db, user_id, name, camera_index):
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开摄像头：{camera_index}")

    saved_count = 0
    print("按空格保存当前人脸，按 ESC 退出。")
    print("建议每个人录入 5 到 10 张：正脸、轻微左转、轻微右转、不同光照。")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                continue

            faces = engine.detect_faces(frame)
            preview = draw_faces(frame, faces)

            cv2.putText(
                preview,
                f"User: {name}  Saved: {saved_count}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 0),
                2,
            )

            cv2.imshow("Enroll Face", preview)
            key = cv2.waitKey(1) & 0xFF

            if key == 27:
                break

            if key == 32:
                if len(faces) != 1:
                    print(f"请保证画面中只有一张人脸，当前检测到 {len(faces)} 张。")
                    continue

                feature = engine.get_feature(frame, faces[0])
                db.add_face(user_id, name, feature)
                saved_count += 1
                print(f"已保存 {name} 的第 {saved_count} 张人脸。")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main():
    args = parse_args()

    user_id = args.user_id or input("请输入用户ID：").strip()
    name = args.name or input("请输入姓名：").strip()

    if not user_id or not name:
        raise ValueError("用户ID和姓名不能为空。")

    engine = FaceEngine(db_path=args.db)
    db = FaceDatabase(args.db)

    if args.image:
        enroll_from_image(engine, db, user_id, name, Path(args.image))
    else:
        enroll_from_camera(engine, db, user_id, name, args.camera)

    print(f"当前数据库总人脸特征数：{db.count()}")


if __name__ == "__main__":
    main()
