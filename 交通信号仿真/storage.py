"""数据持久化。

设计目标：**无 MySQL 服务器也能一条命令跑通，配了环境变量则无缝切换 MySQL。**

* 默认使用 Python 标准库 sqlite3，数据落在 data/traffic_sim.db；
* 设置环境变量 MYSQL_HOST 后改用 PyMySQL 连 MySQL；
* 两者共享同一套表结构与写入接口（StrategyRepository 抽象）。

表结构
------
runs(id, created_at, strategy, demand_vph, arrivals, departed,
     throughput_vph, mean_wait, p95_wait, max_wait, max_queue, mean_queue,
     mean_green, mean_cycle, service_ratio, config_json, metrics_json)

每次仿真完成后写入一行，保留 config_json / metrics_json 便于回看完整参数，
其余高频指标拆成独立列方便直接 SQL 查询与对比。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time

from config import SimConfig, database_config_from_env, project_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    strategy        TEXT    NOT NULL,
    demand_vph      REAL    NOT NULL,
    arrivals        INTEGER,
    departed        INTEGER,
    throughput_vph  REAL,
    mean_wait       REAL,
    p95_wait        REAL,
    max_wait        REAL,
    max_queue       INTEGER,
    mean_queue      REAL,
    mean_green      REAL,
    mean_cycle      REAL,
    service_ratio   REAL,
    config_json     TEXT,
    metrics_json    TEXT
);
"""

_MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    created_at      VARCHAR(32) NOT NULL,
    strategy        VARCHAR(32) NOT NULL,
    demand_vph      DOUBLE NOT NULL,
    arrivals        BIGINT,
    departed        BIGINT,
    throughput_vph  DOUBLE,
    mean_wait       DOUBLE,
    p95_wait        DOUBLE,
    max_wait        DOUBLE,
    max_queue       BIGINT,
    mean_queue      DOUBLE,
    mean_green      DOUBLE,
    mean_cycle      DOUBLE,
    service_ratio   DOUBLE,
    config_json     TEXT,
    metrics_json    TEXT
) DEFAULT CHARSET=utf8mb4;
"""

_COLS = "id, created_at, strategy, demand_vph, arrivals, departed, throughput_vph, mean_wait, p95_wait, max_wait, max_queue, mean_queue, mean_green, mean_cycle, service_ratio"


class StrategyRepository:
    """统一的仿真结果仓库。"""

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or database_config_from_env()
        self.backend = self.cfg.get("backend", "sqlite")
        self.conn = None
        self._connect()

    # ------------------------------------------------------------------
    def _connect(self) -> None:
        if self.backend == "sqlite":
            path = self.cfg.get("path", "data/traffic_sim.db")
            path = project_path(path) if not os.path.isabs(path) else path
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.conn = sqlite3.connect(path)
            self.conn.execute(_SCHEMA)
            self.conn.commit()
        elif self.backend == "mysql":
            import pymysql

            self.conn = pymysql.connect(
                host=self.cfg["host"],
                port=self.cfg.get("port", 3306),
                user=self.cfg["user"],
                password=self.cfg.get("password", ""),
                database=self.cfg["database"],
                charset="utf8mb4",
                autocommit=True,
            )
            with self.conn.cursor() as cur:
                cur.execute(_MYSQL_SCHEMA)
        else:
            raise ValueError(f"未知存储后端: {self.backend}")

    # ------------------------------------------------------------------
    def insert_run(self, strategy: str, cfg: SimConfig, metrics: dict, controller_stats: dict | None = None) -> int:
        m = dict(metrics)
        ctrl = controller_stats or {}
        created = time.strftime("%Y-%m-%d %H:%M:%S")
        merged = {**m, "config": cfg.to_dict(), "controller": ctrl}
        row = (
            created, strategy,
            cfg.demand_vph,
            m.get("arrivals"), m.get("departed"),
            m.get("throughput_vph"), m.get("mean_wait"), m.get("p95_wait"), m.get("max_wait"),
            m.get("max_queue"), m.get("mean_queue"),
            m.get("mean_green"), m.get("mean_cycle"), m.get("service_ratio"),
            json.dumps(cfg.to_dict(), ensure_ascii=False),
            json.dumps(merged, ensure_ascii=False),
        )
        if self.backend == "sqlite":
            cur = self.conn.execute(
                """INSERT INTO runs
                   (created_at, strategy, demand_vph, arrivals, departed,
                    throughput_vph, mean_wait, p95_wait, max_wait, max_queue, mean_queue,
                    mean_green, mean_cycle, service_ratio, config_json, metrics_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                row,
            )
            self.conn.commit()
            return cur.lastrowid
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO runs
                   (created_at, strategy, demand_vph, arrivals, departed,
                    throughput_vph, mean_wait, p95_wait, max_wait, max_queue, mean_queue,
                    mean_green, mean_cycle, service_ratio, config_json, metrics_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                row,
            )
            return cur.lastrowid

    # ------------------------------------------------------------------
    def list_runs(self, strategy: str | None = None, limit: int = 200) -> list[dict]:
        keys = [k.strip() for k in _COLS.split(",")]
        if self.backend == "sqlite":
            if strategy:
                rows = self.conn.execute(
                    f"SELECT {_COLS} FROM runs WHERE strategy=? ORDER BY id DESC LIMIT ?",
                    (strategy, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(f"SELECT {_COLS} FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(zip(keys, r)) for r in rows]
        with self.conn.cursor() as cur:
            if strategy:
                cur.execute(f"SELECT {_COLS} FROM runs WHERE strategy=%s ORDER BY id DESC LIMIT %s", (strategy, limit))
            else:
                cur.execute(f"SELECT {_COLS} FROM runs ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(zip(keys, r)) for r in cur.fetchall()]

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
