import argparse
import sys

from face_db import FaceDatabase


def format_table(rows, headers):
    if not rows:
        return ""

    widths = []
    for key, title in headers:
        max_width = len(str(title))
        for row in rows:
            max_width = max(max_width, len(str(row.get(key, ""))))
        widths.append(max_width)

    header_line = "  ".join(str(title).ljust(widths[i]) for i, (_, title) in enumerate(headers))
    sep_line = "  ".join("-" * widths[i] for i in range(len(headers)))
    body_lines = []

    for row in rows:
        body_lines.append(
            "  ".join(str(row.get(key, "")).ljust(widths[i]) for i, (key, _) in enumerate(headers))
        )

    return "\n".join([header_line, sep_line] + body_lines)


def ask_confirm(message, yes=False):
    if yes:
        return True
    answer = input(f"{message}\n确认执行？输入 yes 确认：").strip().lower()
    return answer == "yes"


def print_people(db):
    people = db.list_people()
    print(f"人脸数据库：{db.db_path}")
    print(f"总特征数：{db.count()}")
    print()

    if not people:
        print("当前没有录入任何人脸。")
        return

    print("按人员汇总：")
    print(
        format_table(
            people,
            [
                ("user_id", "用户ID"),
                ("name", "姓名"),
                ("feature_count", "特征数"),
                ("first_created_at", "首次录入"),
                ("last_created_at", "最近录入"),
            ],
        )
    )



def delete_user(db, user_id, yes):
    targets = db.list_faces(user_id=user_id)
    if not targets:
        print(f"没有找到 user_id={user_id} 的记录。")
        return 0

    print(f"即将删除 user_id={user_id} 的全部 {len(targets)} 条记录。")
    if not ask_confirm("删除后不可恢复。", yes=yes):
        print("已取消。")
        return 0

    deleted = db.delete_by_user_id(user_id)
    print(f"已删除 {deleted} 条记录。")
    return deleted


def delete_name(db, name, yes):
    targets = db.list_faces(name=name)
    if not targets:
        print(f"没有找到 name={name} 的记录。")
        return 0

    print(f"即将删除 name={name} 的全部 {len(targets)} 条记录。")
    if not ask_confirm("删除后不可恢复。", yes=yes):
        print("已取消。")
        return 0

    deleted = db.delete_by_name(name)
    print(f"已删除 {deleted} 条记录。")
    return deleted



def parse_args():
    parser = argparse.ArgumentParser(description="查看人脸库人员汇总，并按用户ID或姓名删除全部人脸记录。")
    parser.add_argument("--db", default="data/faces.db", help="人脸数据库路径，默认 data/faces.db。")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("people", help="按人员汇总查看。")

    delete_user_parser = subparsers.add_parser("delete-user", help="按用户 ID 删除该用户全部人脸特征。")
    delete_user_parser.add_argument("user_id", help="用户 ID。")
    delete_user_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认。")

    delete_name_parser = subparsers.add_parser("delete-name", help="按姓名删除该姓名全部人脸特征。")
    delete_name_parser.add_argument("name", help="姓名。")
    delete_name_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认。")

    return parser.parse_args()


def main():
    args = parse_args()
    db = FaceDatabase(args.db)

    command = args.command or "people"

    if command == "people":
        print_people(db)
    elif command == "delete-user":
        delete_user(db, args.user_id, args.yes)
    elif command == "delete-name":
        delete_name(db, args.name, args.yes)
    else:
        print(f"未知命令：{command}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
