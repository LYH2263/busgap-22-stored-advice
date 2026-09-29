import os

# 必须在任何 app.* 模块导入前生效：避免 app.database 按默认 postgres URL 拉 psycopg2
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_ON_EMPTY", "false")
