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
        finally:
            conn.close()

    def load_all_faces(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, name, embedding, dim FROM faces")
            rows = cursor.fetchall()
        finally:
            conn.close()

        faces = []
        for user_id, name, blob, dim in rows:
            embedding = np.frombuffer(blob, dtype=np.float32, count=int(dim)).copy()
            embedding = self._normalize_embedding(embedding)
            faces.append(
                {
                    "user_id": user_id,
                    "name": name,
                    "embedding": embedding,
                }
            )

        return faces

    def count(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM faces")
            return int(cursor.fetchone()[0])
        finally:
            conn.close()
