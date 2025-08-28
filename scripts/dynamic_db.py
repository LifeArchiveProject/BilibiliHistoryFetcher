import os
import json
import sqlite3
from datetime import datetime
from typing import Iterable, Optional, Tuple, Dict, Any, List
from loguru import logger

from scripts.utils import get_database_path
from scripts.dynamic_media import collect_image_urls


def _get_db_path() -> str:
    """获取动态数据数据库路径"""
    return get_database_path('bilibili_dynamic.db')


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """确保动态相关表结构存在"""
    cursor = conn.cursor()



    # 规范化主表：核心信息
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dynamic_core (
            host_mid TEXT NOT NULL,
            id_str TEXT NOT NULL,
            type TEXT,
            visible INTEGER,
            publish_ts INTEGER,
            comment_id_str TEXT,
            comment_type INTEGER,
            rid_str TEXT,
            txt TEXT,
            author_name TEXT,
            bvid TEXT,
            title TEXT,
            cover TEXT,
            desc TEXT,
            article_title TEXT,
            article_covers TEXT,
            opus_title TEXT,
            opus_summary_text TEXT,
            media_locals TEXT,
            media_count INTEGER,
            live_media_locals TEXT,
            live_media_count INTEGER,
            fetch_time INTEGER NOT NULL,
            PRIMARY KEY (host_mid, id_str)
        )
        """
    )

    # media_urls 字段移除：不需要旧数据迁移
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dynamic_core_publish_ts
            ON dynamic_core(publish_ts)
        """
    )

    # 作者信息
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dynamic_author (
            host_mid TEXT NOT NULL,
            id_str TEXT NOT NULL,
            author_mid TEXT,
            author_name TEXT,
            face TEXT,
            PRIMARY KEY (host_mid, id_str)
        )
        """
    )

    # 统计信息
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dynamic_stat (
            host_mid TEXT NOT NULL,
            id_str TEXT NOT NULL,
            like_count INTEGER,
            comment_count INTEGER,
            repost_count INTEGER,
            view_count INTEGER,
            PRIMARY KEY (host_mid, id_str)
        )
        """
    )


    # 话题
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dynamic_topic (
            host_mid TEXT NOT NULL,
            id_str TEXT NOT NULL,
            topic_name TEXT,
            jump_url TEXT,
            PRIMARY KEY (host_mid, id_str)
        )
        """
    )




    # major: 图文（opus）
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS major_opus_pics (
            host_mid TEXT NOT NULL,
            id_str TEXT NOT NULL,
            idx INTEGER NOT NULL,
            url TEXT NOT NULL,
            PRIMARY KEY (host_mid, id_str, idx)
        )
        """
    )

    # major: archive 跳转URL列表（逐条展开）
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS major_archive_jump_urls (
            host_mid TEXT NOT NULL,
            id_str TEXT NOT NULL,
            idx INTEGER NOT NULL,
            url TEXT NOT NULL,
            PRIMARY KEY (host_mid, id_str, idx)
        )
        """
    )

    conn.commit()


def get_connection() -> sqlite3.Connection:
    """获取数据库连接（并自动创建表结构）"""
    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)
    return conn








def dynamic_core_exists(conn: sqlite3.Connection, host_mid: int, id_str: str) -> bool:
    """判断某条动态是否已存在于核心表中"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1 FROM dynamic_core WHERE host_mid = ? AND id_str = ? LIMIT 1
        """,
        (str(host_mid), str(id_str)),
    )
    return cursor.fetchone() is not None


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def save_normalized_dynamic_item(conn: sqlite3.Connection, host_mid: int, item: Dict[str, Any]) -> None:
    """将动态条目按多表结构保存/更新

    - 核心信息 dynamic_core
    - 作者 dynamic_author
    - 统计 dynamic_stat
    - 正文 dynamic_desc
    - 话题 dynamic_topic
    - major 分类型：archive / draw / article / opus
    """
    cursor = conn.cursor()
    fetch_time = int(datetime.now().timestamp())
    logger.debug(f"normalize.begin host_mid={host_mid}")

    basic = item.get("basic", {}) if isinstance(item, dict) else {}
    modules_raw = item.get("modules")
    # 兼容 modules 既可能为对象也可能为数组
    module_author = {}
    module_stat = {}
    module_dynamic = {}
    if isinstance(modules_raw, dict):
        module_author = modules_raw.get("module_author", {})
        module_stat = modules_raw.get("module_stat", {})
        module_dynamic = modules_raw.get("module_dynamic", {})
    elif isinstance(modules_raw, list):
        for mod in modules_raw:
            if not isinstance(mod, dict):
                continue
            mtype = mod.get("module_type")
            # 新版结构将内容放在同级键名里，例如 {"module_author": {...}, "module_type": "MODULE_TYPE_AUTHOR"}
            if mtype == "MODULE_TYPE_AUTHOR" and not module_author:
                module_author = mod.get("module_author", {})
            elif mtype == "MODULE_TYPE_STAT" and not module_stat:
                module_stat = mod.get("module_stat", {})
            elif mtype == "MODULE_TYPE_DYNAMIC" and not module_dynamic:
                module_dynamic = mod.get("module_dynamic", {})

    id_str = (
        item.get("id_str")
        or basic.get("id_str")
        or str(item.get("id"))
    )
    if not id_str:
        logger.warning("normalize.skip: missing id_str")
        return
    logger.debug(f"normalize.id id_str={id_str}")

    # 核心信息
    publish_ts = _to_int(module_author.get("pub_ts"))
    comment_id_str = basic.get("comment_id_str")
    comment_type = _to_int(basic.get("comment_type"))
    rid_str = basic.get("rid_str")
    visible = item.get("visible")

    # 作者名/头像URL
    author_name = module_author.get("name") or module_author.get("uname")
    avatar = module_author.get("avatar")
    if isinstance(avatar, dict):
        fl = avatar.get("fallback_layers", {})
        layers = fl.get("layers") if isinstance(fl, dict) else None
        if isinstance(layers, list):
            for layer in layers:
                if not isinstance(layer, dict):
                    continue
                res = layer.get("resource", {})
                if isinstance(res, dict):
                    res_img = res.get("res_image", {})
                    if isinstance(res_img, dict):
                        img_src = res_img.get("image_src", {})
                        if isinstance(img_src, dict):
                            remote = img_src.get("remote", {})
                            if isinstance(remote, dict) and remote.get("url"):
                                author_face_url = remote.get("url")
                                break

    # 文本
    txt = None
    desc_obj = module_dynamic.get("desc") if isinstance(module_dynamic, dict) else None
    if isinstance(desc_obj, dict):
        txt = desc_obj.get("text")
    elif isinstance(desc_obj, str):
        txt = desc_obj
    if not txt and isinstance(modules_raw, list):
        for mod in modules_raw:
            if isinstance(mod, dict) and isinstance(mod.get("module_desc"), dict):
                txt = mod.get("module_desc", {}).get("text")
                if txt:
                    break

    # 媒体信息不再从单独表中获取，直接设置为空
    media_locals_joined = None
    media_count = 0

    # 提取 archive、article 和 opus 信息到核心表
    archive_bvid = None
    archive_title = None
    archive_cover = None
    archive_desc = None
    article_title = None
    article_covers = None
    opus_title = None
    opus_summary_text = None
    major = module_dynamic.get("major") if isinstance(module_dynamic, dict) else None
    if isinstance(major, dict):
        if isinstance(major.get("archive"), dict):
            arc = major["archive"]
            archive_bvid = arc.get("bvid")
            archive_title = arc.get("title")
            archive_cover = arc.get("cover")
            archive_desc = arc.get("desc")
        if isinstance(major.get("article"), dict):
            ar = major["article"]
            article_title = ar.get("title")
            covers = ar.get("covers") if isinstance(ar, dict) else None
            if isinstance(covers, list) and covers:
                import json
                article_covers = json.dumps(covers)
        if isinstance(major.get("opus"), dict):
            opus = major["opus"]
            opus_title = opus.get("title")
            summary = opus.get("summary")
            if isinstance(summary, dict):
                opus_summary_text = summary.get("text")

    logger.info(f"normalize.core.upsert begin host_mid={host_mid} id_str={id_str} media_count={media_count}")
    cursor.execute(
        """
        INSERT INTO dynamic_core (host_mid, id_str, type, visible, publish_ts, comment_id_str, comment_type, rid_str,
                                  txt, author_name, bvid, title, cover, desc, article_title, article_covers,
                                  opus_title, opus_summary_text, media_locals, media_count, live_media_locals, live_media_count,
                                  fetch_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(host_mid, id_str) DO UPDATE SET
            type = excluded.type,
            visible = excluded.visible,
            publish_ts = excluded.publish_ts,
            comment_id_str = excluded.comment_id_str,
            comment_type = excluded.comment_type,
            rid_str = excluded.rid_str,
            txt = excluded.txt,
            author_name = excluded.author_name,
            bvid = excluded.bvid,
            title = excluded.title,
            cover = excluded.cover,
            desc = excluded.desc,
            article_title = excluded.article_title,
            article_covers = excluded.article_covers,
            opus_title = excluded.opus_title,
            opus_summary_text = excluded.opus_summary_text,
            media_locals = excluded.media_locals,
            media_count = excluded.media_count,
            live_media_locals = excluded.live_media_locals,
            live_media_count = excluded.live_media_count,
            fetch_time = excluded.fetch_time
        """,
        (
            str(host_mid),
            str(id_str),
            item.get("type"),
            1 if visible else 0 if visible is not None else None,
            publish_ts,
            comment_id_str,
            comment_type,
            rid_str,
            txt,
            author_name,
            archive_bvid,
            archive_title,
            archive_cover,
            archive_desc if isinstance(archive_desc, str) else None,
            article_title,
            article_covers,
            opus_title,
            opus_summary_text,
            media_locals_joined,
            media_count,
            None,  # live_media_locals - 暂时设为None，稍后在路由中处理
            0,     # live_media_count - 暂时设为0
            fetch_time,
        ),
    )
    logger.info(f"normalize.core.saved host_mid={host_mid} id_str={id_str}")

    # 作者
    author_mid = module_author.get("mid") or module_author.get("id")
    author_name = module_author.get("name") or module_author.get("uname")
    face = module_author.get("face")
    cursor.execute(
        """
        INSERT INTO dynamic_author (host_mid, id_str, author_mid, author_name, face)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(host_mid, id_str) DO UPDATE SET
            author_mid = excluded.author_mid,
            author_name = excluded.author_name,
            face = excluded.face
        """,
        (
            str(host_mid),
            str(id_str),
            str(author_mid) if author_mid is not None else None,
            author_name,
            face,
        ),
    )

    # 统计
    like_count = _to_int(
        module_stat.get("like") if isinstance(module_stat.get("like"), (int, str)) else (module_stat.get("like", {}).get("count") if isinstance(module_stat.get("like"), dict) else None)
    )
    comment_count = _to_int(
        module_stat.get("comment") if isinstance(module_stat.get("comment"), (int, str)) else (module_stat.get("comment", {}).get("count") if isinstance(module_stat.get("comment"), dict) else None)
    )
    repost_count = _to_int(
        module_stat.get("repost") if isinstance(module_stat.get("repost"), (int, str)) else (module_stat.get("forward", {}).get("count") if isinstance(module_stat.get("forward"), dict) else None)
    )
    view_count = _to_int(
        module_stat.get("view") if isinstance(module_stat.get("view"), (int, str)) else (module_stat.get("view", {}).get("count") if isinstance(module_stat.get("view"), dict) else None)
    )
    cursor.execute(
        """
        INSERT INTO dynamic_stat (host_mid, id_str, like_count, comment_count, repost_count, view_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(host_mid, id_str) DO UPDATE SET
            like_count = excluded.like_count,
            comment_count = excluded.comment_count,
            repost_count = excluded.repost_count,
            view_count = excluded.view_count
        """,
        (
            str(host_mid),
            str(id_str),
            like_count,
            comment_count,
            repost_count,
            view_count,
        ),
    )


    conn.commit()


def list_hosts_with_stats(
    conn: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """列出数据库中已有动态的UP（host_mid）及统计信息。

    返回字段：host_mid, item_count, core_count, last_publish_ts, last_fetch_time
    """
    cursor = conn.cursor()
    logger.debug(f"db.list_hosts_with_stats begin limit={limit} offset={offset}")
    rows = cursor.execute(
        (
            """
            SELECT dc.host_mid AS host_mid,
                   COUNT(*) AS item_count,
                   COUNT(*) AS core_count,
                   MAX(dc.publish_ts) AS last_publish_ts,
                   MAX(dc.fetch_time) AS last_fetch_time
            FROM dynamic_core AS dc
            GROUP BY dc.host_mid
            ORDER BY (MAX(dc.publish_ts) IS NULL) ASC, MAX(dc.publish_ts) DESC, COUNT(*) DESC
            LIMIT ? OFFSET ?
            """
        ),
        (limit, offset),
    ).fetchall()

    results: List[Dict[str, Any]] = []
    for r in rows:
        host_mid, item_count, core_count, last_publish_ts, last_fetch_time = r
        results.append(
            {
                "host_mid": str(host_mid) if host_mid is not None else None,
                "item_count": int(item_count) if item_count is not None else 0,
                "core_count": int(core_count) if core_count is not None else 0,
                "last_publish_ts": int(last_publish_ts) if last_publish_ts is not None else None,
                "last_fetch_time": int(last_fetch_time) if last_fetch_time is not None else None,
            }
        )
    logger.debug(f"db.list_hosts_with_stats done count={len(results)}")
    return results


def list_dynamics_for_host(
    conn: sqlite3.Connection,
    host_mid: int,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """列出指定UP的动态，优先从 dynamic_core 读取；若无则回退到 dynamic_items。

    返回：
        {
          "source": "core" | "items",
          "total": int,
          "items": [ { id_str, type, visible, publish_ts, txt, author_name, media_count, media_urls, media_locals, fetch_time } ]
        }
    """
    cursor = conn.cursor()
    host_mid_str = str(host_mid)

    # 统计 core 数量
    core_total_row = cursor.execute(
        "SELECT COUNT(*) FROM dynamic_core WHERE host_mid = ?",
        (host_mid_str,),
    ).fetchone()
    core_total = int(core_total_row[0]) if core_total_row and core_total_row[0] is not None else 0

    if core_total > 0:
        rows = cursor.execute(
            (
                """
                SELECT host_mid, id_str, type, visible, publish_ts, comment_id_str, comment_type, rid_str,
                       txt, author_name, bvid, title, cover, desc, article_title, article_covers, 
                       opus_title, opus_summary_text, media_locals, media_count, live_media_locals, live_media_count, fetch_time
                FROM dynamic_core
                WHERE host_mid = ?
                ORDER BY (publish_ts IS NULL) ASC, publish_ts DESC, fetch_time DESC
                LIMIT ? OFFSET ?
                """
            ),
            (host_mid_str, limit, offset),
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for r in rows:
            (
                _host_mid,
                id_str,
                dynamic_type,
                visible,
                publish_ts,
                comment_id_str,
                comment_type,
                rid_str,
                txt,
                author_name,
                bvid,
                title,
                cover,
                desc,
                article_title,
                article_covers,
                opus_title,
                opus_summary_text,
                media_locals,
                media_count,
                live_media_locals,
                live_media_count,
                fetch_time,
            ) = r
            items.append(
                {
                    "host_mid": str(_host_mid) if _host_mid is not None else host_mid_str,
                    "id_str": str(id_str) if id_str is not None else None,
                    "type": dynamic_type,
                    "visible": int(visible) if visible is not None else None,
                    "publish_ts": int(publish_ts) if publish_ts is not None else None,
                    "comment_id_str": comment_id_str,
                    "comment_type": int(comment_type) if comment_type is not None else None,
                    "rid_str": rid_str,
                    "txt": txt,
                    "author_name": author_name,
                    "bvid": bvid,
                    "title": title,
                    "cover": cover,
                    "desc": desc,
                    "article_title": article_title,
                    "article_covers": article_covers,
                    "opus_title": opus_title,
                    "opus_summary_text": opus_summary_text,
                    "media_locals": media_locals,
                    "media_count": int(media_count) if media_count is not None else None,
                    "live_media_locals": live_media_locals,
                    "live_media_count": int(live_media_count) if live_media_count is not None else None,
                    "fetch_time": int(fetch_time) if fetch_time is not None else None,
                }
            )
        return {"source": "core", "total": core_total, "items": items}

    # 如果没有core数据，返回空结果
    return {"source": "core", "total": 0, "items": []}


