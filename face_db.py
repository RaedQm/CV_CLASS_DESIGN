import sqlite3
from pathlib import Path

import numpy as np


class FaceDatabase:
    """SQLite 人脸特征库。"""

    def __init__(self, db_path="data/faces.db"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS faces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    dim INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _normalize_embedding(embedding):
        embedding = np.asarray(embedding, dtype=np.float32).flatten()
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding.astype(np.float32)

    def add_face(self, user_id, name, embedding):
        embedding = self._normalize_embedding(embedding)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO faces(user_id, name, embedding, dim)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(user_id),
                    str(name),
                    embedding.tobytes(),
                    int(embedding.shape[0]),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def load_all_faces(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_id, name, embedding, dim, created_at FROM faces ORDER BY id")
            rows = cursor.fetchall()
        finally:
            conn.close()

        faces = []
        for row_id, user_id, name, blob, dim, created_at in rows:
            embedding = np.frombuffer(blob, dtype=np.float32, count=int(dim)).copy()
            embedding = self._normalize_embedding(embedding)
            faces.append(
                {
                    "id": int(row_id),
                    "user_id": user_id,
                    "name": name,
                    "embedding": embedding,
                    "dim": int(dim),
                    "created_at": created_at,
                }
            )

        return faces

    def list_faces(self, user_id=None, name=None, limit=None):
        """返回人脸记录元数据，不返回 embedding，适合查看/管理。"""
        sql = "SELECT id, user_id, name, dim, created_at FROM faces"
        conditions = []
        params = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(str(user_id))

        if name:
            conditions.append("name = ?")
            params.append(str(name))

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY id"

        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        finally:
            conn.close()

        return [
            {
                "id": int(row_id),
                "user_id": user_id,
                "name": name,
                "dim": int(dim),
                "created_at": created_at,
            }
            for row_id, user_id, name, dim, created_at in rows
        ]

    def list_people(self):
        """按 user_id + name 汇总每个人的录入数量。"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_id, name, COUNT(*) AS feature_count,
                       MIN(created_at) AS first_created_at,
                       MAX(created_at) AS last_created_at
                FROM faces
                GROUP BY user_id, name
                ORDER BY user_id, name
                """
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        return [
            {
                "user_id": user_id,
                "name": name,
                "feature_count": int(feature_count),
                "first_created_at": first_created_at,
                "last_created_at": last_created_at,
            }
            for user_id, name, feature_count, first_created_at, last_created_at in rows
        ]

    def count(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM faces")
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    def delete_by_ids(self, ids):
        """按记录 ID 删除。返回实际删除数量。"""
        clean_ids = []
        for item in ids:
            try:
                clean_ids.append(int(item))
            except Exception:
                continue

        clean_ids = sorted(set(clean_ids))
        if not clean_ids:
            return 0

        placeholders = ",".join("?" for _ in clean_ids)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM faces WHERE id IN ({placeholders})", clean_ids)
            deleted = int(cursor.rowcount)
            conn.commit()
            return deleted
        finally:
            conn.close()

    def delete_by_user_id(self, user_id):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM faces WHERE user_id = ?", (str(user_id),))
            deleted = int(cursor.rowcount)
            conn.commit()
            return deleted
        finally:
            conn.close()

    def delete_by_name(self, name):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM faces WHERE name = ?", (str(name),))
            deleted = int(cursor.rowcount)
            conn.commit()
            return deleted
        finally:
            conn.close()

    def clear(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM faces")
            deleted = int(cursor.rowcount)
            conn.commit()
            return deleted
        finally:
            conn.close()
