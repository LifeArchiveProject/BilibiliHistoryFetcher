CREATE_TABLE_DEFAULT = """
CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    long_title TEXT,
    cover TEXT,
    covers TEXT,
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
    remark TEXT DEFAULT ''
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_{table}_author_mid ON {table} (author_mid);",
    "CREATE INDEX IF NOT EXISTS idx_{table}_view_at ON {table} (view_at);"
]

INSERT_DATA = """
INSERT INTO {table} (
    id, title, long_title, cover, covers, uri, oid, epid, bvid, page, cid, part, 
    business, dt, videos, author_name, author_face, author_mid, view_at, progress, 
    badge, show_title, duration, current, total, new_desc, is_finish, is_fav, kid, 
    tag_name, live_status, main_category, remark
) VALUES ({placeholders})
"""
