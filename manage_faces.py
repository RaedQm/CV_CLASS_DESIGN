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


def print_records(db, args):
    rows = db.list_faces(user_id=args.user_id, name=args.name, limit=args.limit)
    print(f"人脸数据库：{db.db_path}")
    print(f"匹配记录数：{len(rows)}")
    print()

    if not rows:
        print("没有找到符合条件的人脸记录。")
        return

    print(
        format_table(
            rows,
            [
                ("id", "记录ID"),
                ("user_id", "用户ID"),
                ("name", "姓名"),
                ("dim", "维度"),
                ("created_at", "录入时间"),
            ],
        )
    )


def delete_ids(db, ids, yes):
    preview = db.list_faces()
    id_set = {int(item) for item in ids}
    targets = [row for row in preview if int(row["id"]) in id_set]

    if not targets:
        print("没有找到要删除的记录。")
        return 0

    print("即将删除以下记录：")
    print(
        format_table(
            targets,
            [
                ("id", "记录ID"),
                ("user_id", "用户ID"),
                ("name", "姓名"),
                ("created_at", "录入时间"),
            ],
        )
    )

    if not ask_confirm("删除后不可恢复。", yes=yes):
        print("已取消。")
        return 0

    deleted = db.delete_by_ids(ids)
    print(f"已删除 {deleted} 条记录。")
    return deleted


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


def clear_all(db, yes):
    total = db.count()
    if total <= 0:
        print("数据库已经为空。")
        return 0

    print(f"即将清空全部 {total} 条人脸特征记录。")
    if not ask_confirm("这是危险操作，删除后不可恢复。", yes=yes):
        print("已取消。")
        return 0

    deleted = db.clear()
    print(f"已删除 {deleted} 条记录。")
    return deleted


def parse_args():
    parser = argparse.ArgumentParser(description="查看和删除本地人脸数据库记录。")
    parser.add_argument("--db", default="data/faces.db", help="人脸数据库路径，默认 data/faces.db。")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("people", help="按人员汇总查看。")

    list_parser = subparsers.add_parser("list", help="查看每条人脸特征记录。")
    list_parser.add_argument("--user-id", default=None, help="只查看指定用户 ID。")
    list_parser.add_argument("--name", default=None, help="只查看指定姓名。")
    list_parser.add_argument("--limit", type=int, default=None, help="限制显示记录数。")

    delete_id_parser = subparsers.add_parser("delete-id", help="按记录 ID 删除。")
    delete_id_parser.add_argument("ids", nargs="+", help="一个或多个记录 ID。")
    delete_id_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认。")

    delete_user_parser = subparsers.add_parser("delete-user", help="按用户 ID 删除该用户全部人脸特征。")
    delete_user_parser.add_argument("user_id", help="用户 ID。")
    delete_user_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认。")

    delete_name_parser = subparsers.add_parser("delete-name", help="按姓名删除该姓名全部人脸特征。")
    delete_name_parser.add_argument("name", help="姓名。")
    delete_name_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认。")

    clear_parser = subparsers.add_parser("clear", help="清空全部人脸特征。")
    clear_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认。")

    return parser.parse_args()


def main():
    args = parse_args()
    db = FaceDatabase(args.db)

    command = args.command or "people"

    if command == "people":
        print_people(db)
    elif command == "list":
        print_records(db, args)
    elif command == "delete-id":
        delete_ids(db, args.ids, args.yes)
    elif command == "delete-user":
        delete_user(db, args.user_id, args.yes)
    elif command == "delete-name":
        delete_name(db, args.name, args.yes)
    elif command == "clear":
        clear_all(db, args.yes)
    else:
        print(f"未知命令：{command}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
