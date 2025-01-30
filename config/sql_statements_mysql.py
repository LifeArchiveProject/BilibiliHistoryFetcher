SHOW_DATABASES = "SHOW DATABASES LIKE %s"
CREATE_DATABASE = "CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
SHOW_TABLES = """
    SELECT COUNT(*)
    FROM information_schema.tables 
    WHERE table_schema = %s 
    AND table_name = %s
"""
CREATE_TABLE_DEFAULT = """
    CREATE TABLE {table} (
        id BIGINT PRIMARY KEY COMMENT '主键，使用雪花算法等库生成的唯一ID',
        title VARCHAR(255) NOT NULL COMMENT '条目标题，字符串，最大255字符',
        long_title VARCHAR(255) COMMENT '条目副标题（有时为空），最大255字符',
        cover VARCHAR(255) COMMENT '条目封面图url，用于专栏以外的条目',
        covers JSON COMMENT '条目封面图组，有效时array无效时null，仅用于专栏',
        uri VARCHAR(255) COMMENT '重定向url仅用于剧集和直播',
        oid BIGINT NOT NULL COMMENT '目标id稿件视频&剧集（当business=archive或business=pgc时）：稿件avid直播（当business=live时）：直播间id文章（当business=article时）：文章cvid文集（当business=article-list时）：文集rlid',
        epid BIGINT DEFAULT 0 COMMENT '剧集epid 仅用于剧集',
        bvid VARCHAR(50) NOT NULL COMMENT '稿件bvid 仅用于稿件视频',
        page INT DEFAULT 1 COMMENT '观看到的视频分P数 仅用于稿件视频',
        cid BIGINT COMMENT '观看到的对象id 稿件视频&剧集（当business=archive或business=pgc时）：视频cid文集（当business=article-list时）：文章cvid',
        part VARCHAR(255) COMMENT '观看到的视频分 P 标题 仅用于稿件视频',
        business VARCHAR(50) COMMENT '视频业务类型（如archive代表普通视频），最大50字符',
        dt INT NOT NULL COMMENT '记录查看的平台代码 1 3 5 7 手机端，2 web端，4 6 pad端，33TV端，0其他',
        videos INT DEFAULT 1 COMMENT '视频分 P 数目 仅用于稿件视频，整数型，默认为1',
        author_name VARCHAR(100) NOT NULL COMMENT 'UP 主昵称',
        author_face VARCHAR(255) COMMENT 'UP 主头像 url',
        author_mid BIGINT NOT NULL COMMENT 'UP 主 mid',
        view_at BIGINT NOT NULL COMMENT '查看时间 时间戳',
        progress INT DEFAULT 0 COMMENT '视频观看进度，单位为秒，用于稿件视频或剧集',
        badge VARCHAR(50) COMMENT '角标文案 稿件视频 / 剧集 / 笔记',
        show_title VARCHAR(255) COMMENT '分 P 标题 用于稿件视频或剧集',
        duration INT NOT NULL COMMENT '视频总时长 用于稿件视频或剧集',
        current VARCHAR(255) COMMENT '未知字段',
        total INT DEFAULT 0 COMMENT '总计分集数 仅用于剧集',
        new_desc VARCHAR(255) COMMENT '最新一话 / 最新一 P 标识 用于稿件视频或剧集',
        is_finish TINYINT(1) DEFAULT 0 COMMENT '是否观看完，布尔值，0为否，1为是',
        is_fav TINYINT(1) DEFAULT 0 COMMENT '是否收藏，布尔值，0为否，1为是',
        kid BIGINT COMMENT '条目目标 id',
        tag_name VARCHAR(100) COMMENT '子分区名 用于稿件视频和直播',
        live_status TINYINT(1) DEFAULT 0 COMMENT '直播状态 仅用于直播0未开播1已开播',
        main_category VARCHAR(100) COMMENT '主分区名称',
        remark TEXT COMMENT '用户添加的备注信息',
        INDEX (author_mid) COMMENT '建立作者MID的索引，用于快速查询',
        INDEX (view_at) COMMENT '建立观看时间的索引'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""
CREATE_TABLE_LIKE = "CREATE TABLE {new_table} LIKE {reference_table};"
SELECT_DATABASE = "SELECT DATABASE() AS current_db;"

INSERT_DATA = """
    INSERT INTO {table} (
        id, title, long_title, cover, covers, uri, oid, epid, bvid, page, cid, part, 
        business, dt, videos, author_name, author_face, author_mid, view_at, progress, 
        badge, show_title, duration, current, total, new_desc, is_finish, is_fav, kid, 
        tag_name, live_status, main_category, remark
    ) VALUES (
        %(id)s, %(title)s, %(long_title)s, %(cover)s, %(covers)s, %(uri)s, %(oid)s, 
        %(epid)s, %(bvid)s, %(page)s, %(cid)s, %(part)s, %(business)s, %(dt)s, 
        %(videos)s, %(author_name)s, %(author_face)s, %(author_mid)s, %(view_at)s, 
        %(progress)s, %(badge)s, %(show_title)s, %(duration)s, %(current)s, %(total)s, 
        %(new_desc)s, %(is_finish)s, %(is_fav)s, %(kid)s, %(tag_name)s, %(live_status)s, 
        %(main_category)s, %(remark)s
    )
"""
