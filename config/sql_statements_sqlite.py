CREATE_TABLE_DEFAULT = """
CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    long_title TEXT,
    cover TEXT,
    covers JSON,
    uri TEXT,
    oid INTEGER NOT NULL,
    epid INTEGER DEFAULT 0,
    bvid TEXT NOT NULL,
    page INTEGER DEFAULT 1,
    cid INTEGER,
    part TEXT,
    business TEXT,
    dt INTEGER NOT NULL,
    videos INTEGER DEFAULT 1,
    author_name TEXT NOT NULL,
    author_face TEXT,
    author_mid INTEGER NOT NULL,
    view_at INTEGER NOT NULL,
    progress INTEGER DEFAULT 0,
    badge TEXT,
    show_title TEXT,
    duration INTEGER NOT NULL,
    current TEXT,
    total INTEGER DEFAULT 0,
    new_desc TEXT,
    is_finish INTEGER DEFAULT 0,
    is_fav INTEGER DEFAULT 0,
    kid INTEGER,
    tag_name TEXT,
    live_status INTEGER DEFAULT 0,
    main_category TEXT,
    remark TEXT DEFAULT '',
    remark_time INTEGER DEFAULT 0
);
"""

# 视频摘要表创建语句
CREATE_TABLE_VIDEO_SUMMARY = """
CREATE TABLE IF NOT EXISTS video_summary (
    id INTEGER PRIMARY KEY,
    bvid TEXT NOT NULL,
    cid INTEGER NOT NULL,
    up_mid INTEGER NOT NULL,
    stid TEXT,
    summary TEXT,
    outline JSON,
    result_type INTEGER DEFAULT 0,
    fetch_time INTEGER NOT NULL,
    update_time INTEGER DEFAULT 0
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_{table}_author_mid ON {table} (author_mid);",
    "CREATE INDEX IF NOT EXISTS idx_{table}_view_at ON {table} (view_at);",
    "CREATE INDEX IF NOT EXISTS idx_{table}_remark_time ON {table} (remark_time);",
    "CREATE INDEX IF NOT EXISTS idx_{table}_covers ON {table} (json_valid(covers));"
]

# 视频摘要表索引
CREATE_INDEXES_VIDEO_SUMMARY = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_video_summary_bvid_cid ON video_summary (bvid, cid);",
    "CREATE INDEX IF NOT EXISTS idx_video_summary_up_mid ON video_summary (up_mid);",
    "CREATE INDEX IF NOT EXISTS idx_video_summary_fetch_time ON video_summary (fetch_time);",
    "CREATE INDEX IF NOT EXISTS idx_video_summary_update_time ON video_summary (update_time);"
]

INSERT_DATA = """
INSERT INTO {table} (
    id, title, long_title, cover, covers, uri, oid, epid, bvid, page, cid, part, 
    business, dt, videos, author_name, author_face, author_mid, view_at, progress, 
    badge, show_title, duration, current, total, new_desc, is_finish, is_fav, kid, 
    tag_name, live_status, main_category, remark, remark_time
) VALUES ({placeholders})
"""

# 视频摘要表插入语句
INSERT_VIDEO_SUMMARY = """
INSERT INTO video_summary (
    id, bvid, cid, up_mid, stid, summary, outline, result_type, fetch_time, update_time
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# 视频摘要表更新语句
UPDATE_VIDEO_SUMMARY = """
UPDATE video_summary SET 
    stid = ?, summary = ?, outline = ?, result_type = ?, update_time = ?
WHERE bvid = ? AND cid = ?
"""
