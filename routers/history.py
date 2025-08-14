import json
import os
import hashlib
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from scripts.utils import get_output_path, load_config
from scripts.image_downloader import ImageDownloader

router = APIRouter()
config = load_config()
downloader = ImageDownloader()

def get_db():
    """获取数据库连接，并确保数据库版本兼容性"""
    db_path = get_output_path(config['db_file'])

    # 检查数据库文件是否存在
    db_exists = os.path.exists(db_path)

    try:
        # 连接数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 设置数据库兼容性参数
        pragmas = [
            ('legacy_file_format', 1),
            ('journal_mode', 'DELETE'),
            ('synchronous', 'NORMAL'),
            ('user_version', 317)  # 使用固定的用户版本号
        ]

        for pragma, value in pragmas:
            cursor.execute(f'PRAGMA {pragma}={value}')
        conn.commit()

        if not db_exists:
            print("数据库文件不存在，将创建新数据库")
            print("已配置数据库兼容性设置")

        return conn

    except sqlite3.Error as e:
        print(f"数据库连接错误: {str(e)}")
        if 'conn' in locals() and conn:
            conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"数据库连接失败: {str(e)}"
        )

def get_available_years():
    """获取数据库中所有可用的年份"""
    print("开始获取可用年份列表")
    conn = None
    try:
        # 获取数据库连接
        conn = get_db()
        if conn is None:
            print("无法连接到数据库")
            return [datetime.now().year]  # 返回当前年份作为默认值

        cursor = conn.cursor()

        # 查询所有历史记录表
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name LIKE 'bilibili_history_%'
            ORDER BY name DESC
        """)

        tables = cursor.fetchall()
        print(f"找到的表: {tables}")

        years = []
        for (table_name,) in tables:
            try:
                year = int(table_name.split('_')[-1])
                years.append(year)
                print(f"添加年份: {year} (来自表 {table_name})")
            except (ValueError, IndexError) as e:
                print(f"处理表名 {table_name} 时出错: {e}")
                continue

        sorted_years = sorted(years, reverse=True)
        print(f"最终年份列表: {sorted_years}")

        # 如果没有找到年份，返回当前年份
        if not sorted_years:
            current_year = datetime.now().year
            print(f"未找到年份，返回当前年份: {current_year}")
            return [current_year]

        return sorted_years
    except sqlite3.Error as e:
        print(f"获取年份列表时发生数据库错误: {e}")
        return [datetime.now().year]  # 返回当前年份作为默认值
    except Exception as e:
        print(f"获取年份列表时发生未知错误: {e}")
        return [datetime.now().year]  # 返回当前年份作为默认值
    finally:
        if conn:
            try:
                conn.close()
                print("数据库连接已关闭")
            except Exception as e:
                print(f"关闭数据库连接时出错: {e}")

@router.get("/available-years", summary="获取可用的年份列表")
async def get_years():
    """获取所有可用的年份列表"""
    years = get_available_years()
    if not years:
        return {
            "status": "error",
            "message": "未找到任何历史记录数据"
        }

    return {
        "status": "success",
        "data": years
    }

def _process_image_url(url: str, image_type: str, use_local: bool, use_sessdata: bool = True) -> str:
    """处理图片URL，根据需要返回本地路径或原始URL

    Args:
        url: 原始图片URL
        image_type: 图片类型 (covers 或 avatars)
        use_local: 是否使用本地图片
        use_sessdata: 是否在下载图片时使用SESSDATA（对于公开内容如视频封面和头像，可以不使用SESSDATA）

    Returns:
        str: 处理后的URL
    """

    # 如果不使用本地图片或URL为空,直接返回原始URL
    if not use_local or not url:
        # 如果不使用SESSDATA，移除URL中可能包含的SESSDATA参数
        if not use_sessdata and '?' in url:
            # 移除URL中的所有参数，保留纯净的图片URL
            url = url.split('?')[0]
        return url

    try:
        # 计算URL的哈希值（只使用基本URL部分，不包含参数）
        base_url = url.split('?')[0] if '?' in url else url
        file_hash = hashlib.md5(base_url.encode()).hexdigest()

        # 检查图片类型是否有效
        if image_type not in ('covers', 'avatars'):
            print(f"无效的图片类型: {image_type}")
            return url

        # 构建本地图片URL（返回相对路径，前端自行拼接域名）
        base_url = "/images/local"
        local_url = f"{base_url}/{image_type}/{file_hash}"

        return local_url

    except Exception as e:
        print(f"处理图片URL时出错: {str(e)}")
        return url

def _process_record(record: dict, use_local: bool, use_sessdata: bool = True) -> dict:
    """处理单条记录，转换图片URL

    Args:
        record: 原始记录
        use_local: 是否使用本地图片
        use_sessdata: 是否在下载图片时使用SESSDATA

    Returns:
        dict: 处理后的记录
    """
    # 处理封面图片
    if 'cover' in record and record['cover']:
        record['cover'] = _process_image_url(record['cover'], 'covers', use_local, use_sessdata)

    # 处理作者头像
    if 'author_face' in record and record['author_face']:
        record['author_face'] = _process_image_url(record['author_face'], 'avatars', use_local, use_sessdata)

    # 解析 covers 字段的 JSON 字符串
    if 'covers' in record and record['covers']:
        try:
            # 如果是字符串，尝试解析为 JSON
            if isinstance(record['covers'], str):
                covers = json.loads(record['covers'])
                # 处理每个封面URL
                if isinstance(covers, list):
                    record['covers'] = [_process_image_url(url, 'covers', use_local, use_sessdata) for url in covers]
                else:
                    record['covers'] = []
            else:
                record['covers'] = []
        except json.JSONDecodeError:
            print(f"解析 covers JSON 失败: {record['covers']}")
            record['covers'] = []
    else:
        record['covers'] = []

    return record

@router.get("/all", summary="分页查询历史记录")
async def get_history_page(
    page: int = Query(1, description="当前页码"),
    size: int = Query(10, description="每页记录数"),
    sort_order: int = Query(0, description="排序顺序，0为降序，1为升序"),
    tag_name: Optional[str] = Query(None, description="视频子分区名称"),
    main_category: Optional[str] = Query(None, description="主分区名称"),
    date_range: Optional[str] = Query(None, description="日期范围，格式为yyyyMMdd-yyyyMMdd"),
    use_local_images: bool = Query(False, description="是否使用本地图片"),
    use_sessdata: bool = Query(True, description="是否在图片URL中使用SESSDATA"),
    business: Optional[str] = Query(None, description="业务类型，如archive(普通视频)、pgc(番剧)、live(直播)、article-list(文集)、article(文章)")
):
    """分页查询历史记录，支持跨年份查询"""
    print("\n=== 接收到的请求参数 ===")
    print(f"页码(page): {page}")
    print(f"每页记录数(size): {size}")
    print(f"排序顺序(sort_order): {'升序' if sort_order == 1 else '降序'}")
    print(f"子分区名称(tag_name): {tag_name if tag_name else '无'}")
    print(f"主分区名称(main_category): {main_category if main_category else '无'}")
    print(f"日期范围(date_range): {date_range if date_range else '无'}")
    print(f"是否使用本地图片(use_local_images): {use_local_images}")
    print(f"是否使用SESSDATA(use_sessdata): {use_sessdata}")
    print(f"业务类型(business): {business if business else '全部'}")
    print("=====================\n")

    try:
        conn = get_db()
        cursor = conn.cursor()

        # 获取可用年份列表
        available_years = get_available_years()
        if not available_years:
            return {
                "status": "error",
                "message": "未找到任何历史记录数据"
            }

        # 构建UNION ALL查询
        queries = []
        params = []

        # 处理日期范围
        start_timestamp = None
        end_timestamp = None
        if date_range:
            try:
                start_date, end_date = date_range.split('-')
                start_timestamp = int(datetime.strptime(start_date, '%Y%m%d').timestamp())
                end_timestamp = int(datetime.strptime(end_date, '%Y%m%d').timestamp()) + 86400
            except ValueError:
                return {"status": "error", "message": "日期格式无效，应为yyyyMMdd-yyyyMMdd"}

        # 为每个年份构建查询
        for year in available_years:
            table_name = f"bilibili_history_{year}"
            query = f"SELECT * FROM {table_name} WHERE 1=1"

            # 添加日期范围条件
            if start_timestamp is not None and end_timestamp is not None:
                query += " AND view_at >= ? AND view_at < ?"
                params.extend([start_timestamp, end_timestamp])

            # 添加分类筛选
            if main_category:
                query += " AND main_category = ?"
                params.append(main_category)
            elif tag_name:
                query += " AND tag_name = ?"
                params.append(tag_name)

            # 添加业务类型筛选
            if business:
                query += " AND business = ?"
                params.append(business)

            queries.append(query)

        # 组合所有查询
        base_query = " UNION ALL ".join(queries)

        # 获取总记录数
        count_query = f"SELECT COUNT(*) FROM ({base_query})"
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        # 添加排序和分页
        final_query = f"""
            SELECT * FROM ({base_query})
            ORDER BY view_at {('ASC' if sort_order == 1 else 'DESC')}
            LIMIT ? OFFSET ?
        """
        params.extend([size, (page - 1) * size])

        print("=== SQL查询构建 ===")
        print(f"最终SQL: {final_query}")
        print(f"参数: {params}")
        print("==================\n")

        # 执行查询
        cursor.execute(final_query, params)
        columns = [description[0] for description in cursor.description]
        records = []

        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            record = _process_record(record, use_local_images, use_sessdata)
            records.append(record)

        print("=== 响应结果 ===")
        print(f"返回记录数: {len(records)}")
        print(f"第一条记录: {records[0] if records else '无记录'}")
        print("================\n")

        return {
            "status": "success",
            "data": {
                "records": records,
                "total": total,
                "size": size,
                "current": page,
                "available_years": available_years
            }
        }

    except sqlite3.Error as e:
        error_msg = f"数据库错误: {str(e)}"
        print(f"=== 错误 ===\n{error_msg}\n===========")
        return {"status": "error", "message": error_msg}
    finally:
        if conn:
            conn.close()

def process_search_keyword(keyword: str) -> str:
    """处理搜索关键词，返回处理后的关键词

    Args:
        keyword: 搜索关键词

    Returns:
        str: 处理后的关键词
    """
    if not keyword:
        return ""

    # 移除多余的空格，但保留单个空格
    keyword = ' '.join(keyword.split())
    return keyword

def create_fts_table(conn, table_name: str):
    """创建全文搜索虚拟表"""
    cursor = conn.cursor()

    try:
        # 检查原表是否存在
        cursor.execute(f"""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='bilibili_history_{table_name}'
        """)
        if not cursor.fetchone():
            return False

        # 创建FTS5虚拟表
        fts_table = f"bilibili_history_{table_name}_fts"
        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {fts_table} USING fts5(
                title,
                author_name,
                tag_name,
                main_category,
                remark,
                title_pinyin,
                content='bilibili_history_{table_name}',
                content_rowid='id'
            )
        """)

        # 创建触发器以保持FTS表同步
        cursor.execute(f"""
            CREATE TRIGGER IF NOT EXISTS history_{table_name}_ai AFTER INSERT ON bilibili_history_{table_name} BEGIN
                INSERT INTO {fts_table}(
                    rowid, title, author_name, tag_name, main_category, remark, title_pinyin
                )
                VALUES (
                    new.id, new.title, new.author_name, new.tag_name, new.main_category,
                    new.remark, new.title
                );
            END;
        """)

        cursor.execute(f"""
            CREATE TRIGGER IF NOT EXISTS history_{table_name}_ad AFTER DELETE ON bilibili_history_{table_name} BEGIN
                INSERT INTO {fts_table}({fts_table}, rowid, title, author_name, tag_name, main_category, remark)
                VALUES('delete', old.id, old.title, old.author_name, old.tag_name, old.main_category, old.remark);
            END;
        """)

        cursor.execute(f"""
            CREATE TRIGGER IF NOT EXISTS history_{table_name}_au AFTER UPDATE ON bilibili_history_{table_name} BEGIN
                INSERT INTO {fts_table}({fts_table}, rowid, title, author_name, tag_name, main_category, remark)
                VALUES('delete', old.id, old.title, old.author_name, old.tag_name, old.main_category, old.remark);
                INSERT INTO {fts_table}(rowid, title, author_name, tag_name, main_category, remark)
                VALUES (new.id, new.title, new.author_name, new.tag_name, new.main_category, new.remark);
            END;
        """)

        # 初始化FTS表数据
        cursor.execute(f"""
            INSERT OR REPLACE INTO {fts_table}(
                rowid, title, author_name, tag_name, main_category, remark, title_pinyin
            )
            SELECT
                id, title, author_name, tag_name, main_category, remark, title
            FROM bilibili_history_{table_name}
        """)

        conn.commit()
        return True

    except sqlite3.Error as e:
        print(f"创建FTS表时出错: {str(e)}")
        conn.rollback()
        return False

def build_field_search_conditions(field: str, search: str, exact_match: bool) -> tuple:
    """构建字段搜索条件"""
    params = []
    conditions = []

    if exact_match:
        # 精确匹配
        conditions.append(f"{field} = ?")
        params.append(search)
    else:
        # 模糊匹配
        conditions.append(f"{field} LIKE ?")
        params.append(f"%{search}%")

    # 使用 OR 连接所有条件
    condition = "(" + " OR ".join(conditions) + ")"

    print(f"\n=== 字段条件构建 [{field}] ===")
    print(f"条件: {condition}")
    print(f"参数: {params}")
    print("===================")
    return condition, params

@router.get("/search", summary="搜索历史记录")
async def search_history(
    page: int = Query(1, description="当前页码"),
    size: int = Query(30, description="每页记录数"),
    sortOrder: int = Query(0, description="排序顺序，0为降序，1为升序"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    search_type: Optional[str] = Query("all", description="搜索类型：all-全部, title-标题, author-作者, tag-分区, remark-备注"),
    use_sessdata: bool = Query(True, description="是否在图片URL中使用SESSDATA"),
    use_local_images: bool = Query(False, description="是否使用本地图片")
):
    """高级搜索历史记录，按观看时间排序，使用模糊匹配"""
    try:
        print("\n=== 搜索开始 ===")
        print(f"关键词: {search}")
        print(f"类型: {search_type}")
        print(f"匹配方式: 模糊匹配")
        print(f"排序顺序: {'升序' if sortOrder == 1 else '降序'}")
        print(f"是否使用SESSDATA: {use_sessdata}")
        print(f"是否使用本地图片: {use_local_images}")
        print("==============\n")

        conn = get_db()
        cursor = conn.cursor()

        # 获取可用年份列表
        available_years = get_available_years()
        if not available_years:
            return {
                "status": "error",
                "message": "未找到任何历史记录数据"
            }

        # 构建每个年份的子查询
        sub_queries = []
        base_params = []

        # 处理搜索关键词
        field_map = {
            "title": "title",
            "author": "author_name",
            "tag": "tag_name",
            "remark": "remark"
        }

        where_clause = ""
        search_params = []
        if search:
            search = process_search_keyword(search)
            print(f"\n处理后的搜索关键词: {search}\n")

            print("\n=== 开始构建查询条件 ===")

            # 构建WHERE子句（强制使用模糊匹配）
            exact_match = False
            if search_type == "all":
                field_conditions = []
                for field_name, field in field_map.items():
                    print(f"\n处理字段: {field_name}")
                    condition, params = build_field_search_conditions(field, search, exact_match)
                    field_conditions.append(condition)
                    search_params.extend(params)
                    print(f"当前参数数量: {len(search_params)}")

                if field_conditions:
                    where_clause = f"WHERE ({' OR '.join(field_conditions)})"
            else:
                field = field_map.get(search_type)
                if field:
                    condition, params = build_field_search_conditions(field, search, exact_match)
                    where_clause = f"WHERE {condition}"
                    search_params.extend(params)

        # 构建基础查询
        for year in available_years:
            table_name = f"bilibili_history_{year}"
            sub_query = f"SELECT * FROM {table_name} {where_clause}"
            sub_queries.append(sub_query)
            # 为每个子查询添加一组参数
            base_params.extend(search_params)

        base_query = f"{' UNION ALL '.join(sub_queries)}"

        print("\n=== 基础查询 ===")
        print(f"SQL: {base_query}")
        print(f"参数: {base_params}")
        print(f"参数数量: {len(base_params)}")
        print("================\n")

        # 获取总记录数
        count_query = f"SELECT COUNT(*) FROM ({base_query})"
        print("\n=== 计数查询 ===")
        print(f"SQL: {count_query}")
        print(f"参数: {base_params}")
        print("================\n")

        cursor.execute(count_query, base_params)
        total = cursor.fetchone()[0]

        # 构建最终查询，按观看时间排序和分页
        params = base_params.copy()
        query = f"""
            SELECT * FROM ({base_query})
            ORDER BY view_at {('ASC' if sortOrder == 1 else 'DESC')}
        """

        # 添加分页
        query += " LIMIT ? OFFSET ?"
        params.extend([size, (page - 1) * size])

        print("\n=== 最终查询 ===")
        print(f"SQL: {query}")
        print(f"参数: {params}")
        print(f"参数数量: {len(params)}")
        print("================\n")

        # 执行查询
        cursor.execute(query, params)
        columns = [description[0] for description in cursor.description]
        records = []

        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            record = _process_record(record, use_local_images, use_sessdata)
            records.append(record)

        return {
            "status": "success",
            "data": {
                "records": records,
                "total": total,
                "size": size,
                "current": page,
                "available_years": available_years,
                "search_info": {
                    "keyword": search,
                    "type": search_type,
                    "exact_match": False,
                    "sort_by": "view_at"
                }
            }
        }

    except sqlite3.Error as e:
        error_msg = f"数据库错误: {str(e)}"
        print(f"\n=== 数据库错误 ===\n{error_msg}\n=================\n")
        return {"status": "error", "message": error_msg}
    finally:
        if conn:
            conn.close()

@router.get("/remarks", summary="获取所有备注")
async def get_all_remarks(
    page: int = Query(1, description="当前页码"),
    size: int = Query(10, description="每页记录数"),
    sort_order: int = Query(0, description="排序顺序，0为降序，1为升序")
):
    """获取所有带有备注的视频记录

    Args:
        page: 当前页码
        size: 每页记录数
        sort_order: 排序顺序，0为降序，1为升序

    Returns:
        dict: 包含分页的备注记录列表
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # 获取所有年份的表
        years = get_available_years()
        if not years:
            return {
                "status": "error",
                "message": "未找到任何历史记录数据"
            }

        # 构建UNION ALL查询，只查询有备注的记录
        queries = []
        for year in years:
            table_name = f"bilibili_history_{year}"
            queries.append(f"""
                SELECT *
                FROM {table_name}
                WHERE remark != ''
            """)

        # 组合所有查询，添加排序和分页
        base_query = " UNION ALL ".join(queries)
        count_query = f"SELECT COUNT(*) FROM ({base_query})"

        # 添加排序和分页（按备注时间排序）
        final_query = f"""
            SELECT * FROM ({base_query})
            ORDER BY remark_time {('ASC' if sort_order == 1 else 'DESC')}
            LIMIT ? OFFSET ?
        """

        # 获取总记录数
        cursor.execute(count_query)
        total = cursor.fetchone()[0]

        # 执行分页查询
        cursor.execute(final_query, [size, (page - 1) * size])

        # 获取列名
        columns = [description[0] for description in cursor.description]
        records = []

        # 构建记录
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            # 解析JSON字符串
            if 'covers' in record and record['covers']:
                try:
                    record['covers'] = json.loads(record['covers'])
                except json.JSONDecodeError:
                    record['covers'] = []
            records.append(record)

        return {
            "status": "success",
            "data": {
                "records": records,
                "total": total,
                "size": size,
                "current": page
            }
        }

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=500,
            detail=f"数据库操作失败: {str(e)}"
        )
    finally:
        if conn:
            conn.close()

class UpdateRemarkRequest(BaseModel):
    bvid: str
    view_at: int
    remark: str

@router.post("/update-remark", summary="更新视频备注")
async def update_video_remark(request: UpdateRemarkRequest):
    """更新视频备注

    Args:
        request: 包含bvid、view_at和remark的请求体

    Returns:
        dict: 更新操作的结果
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # 从时间戳获取年份
        year = datetime.fromtimestamp(request.view_at).year
        table_name = f"bilibili_history_{year}"

        # 检查表是否存在
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name=?
        """, (table_name,))

        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"未找到 {year} 年的历史记录数据"
            )

        # 更新备注和备注时间
        current_time = int(datetime.now().timestamp())
        query = f"""
            UPDATE {table_name}
            SET remark = ?, remark_time = ?
            WHERE bvid = ? AND view_at = ?
        """
        cursor.execute(query, (request.remark, current_time, request.bvid, request.view_at))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="未找到指定的视频记录"
            )

        return {
            "status": "success",
            "message": "备注更新成功",
            "data": {
                "bvid": request.bvid,
                "view_at": request.view_at,
                "remark": request.remark,
                "remark_time": current_time
            }
        }

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=500,
            detail=f"数据库操作失败: {str(e)}"
        )
    finally:
        if conn:
            conn.close()

@router.post("/reset-database", summary="重置数据库")
async def reset_database():
    """重置数据库

    删除现有的数据库文件和last_import.json文件，用于重新导入数据

    Returns:
        dict: 操作结果
    """
    try:
        # 获取文件路径
        db_path = get_output_path(config['db_file'])
        last_import_path = get_output_path('last_import.json')

        # 删除数据库文件
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"删除数据库文件失败: {str(e)}"
                )

        # 删除last_import.json文件
        if os.path.exists(last_import_path):
            try:
                os.remove(last_import_path)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"删除last_import.json文件失败: {str(e)}"
                )

        return {
            "status": "success",
            "message": "数据库已重置",
            "data": {
                "deleted_files": [
                    os.path.basename(db_path),
                    os.path.basename(last_import_path)
                ]
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"重置数据库失败: {str(e)}"
        )

@router.get("/sqlite-version", summary="获取SQLite版本")
async def get_sqlite_version():
    """获取 SQLite 版本信息"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        version_info = {
            "sqlite_version": None,
            "user_version": None,
            "database_settings": {
                "journal_mode": None,
                "synchronous": None,
                "legacy_format": None,
                "page_size": None,
                "cache_size": None,
                "encoding": None
            }
        }

        # 获取 SQLite 版本信息
        try:
            cursor.execute('SELECT sqlite_version()')
            result = cursor.fetchone()
            version_info["sqlite_version"] = result[0] if result else "未知"
        except sqlite3.Error as e:
            print(f"获取 SQLite 版本失败: {e}")

        # 获取所有 PRAGMA 设置
        pragmas = {
            "user_version": None,
            "journal_mode": "journal_mode",
            "synchronous": "synchronous",
            "legacy_file_format": "legacy_format",
            "page_size": "page_size",
            "cache_size": "cache_size",
            "encoding": "encoding"
        }

        # 获取用户版本
        try:
            cursor.execute('PRAGMA user_version')
            result = cursor.fetchone()
            version_info["user_version"] = result[0] if result else 0
        except sqlite3.Error as e:
            print(f"获取用户版本失败: {e}")

        # 获取其他 PRAGMA 设置
        for pragma_name, setting_name in pragmas.items():
            if setting_name:  # 跳过已经处理的 user_version
                try:
                    cursor.execute(f'PRAGMA {pragma_name}')
                    result = cursor.fetchone()
                    if result is not None:
                        value = result[0]
                        # 特殊处理某些值
                        if pragma_name == "legacy_file_format":
                            value = bool(int(value)) if value is not None else False
                        elif pragma_name == "synchronous":
                            value = {0: "OFF", 1: "NORMAL", 2: "FULL"}.get(value, value)
                        version_info["database_settings"][setting_name] = value
                except sqlite3.Error as e:
                    print(f"获取 {pragma_name} 设置失败: {e}")

        # 获取数据库文件信息
        db_path = get_output_path(config['db_file'])
        db_exists = os.path.exists(db_path)
        db_size = os.path.getsize(db_path) if db_exists else 0

        # 添加数据库文件信息
        version_info["database_file"] = {
            "exists": db_exists,
            "size_bytes": db_size,
            "size_mb": round(db_size / (1024 * 1024), 2) if db_exists else 0,
            "path": db_path
        }

        return {
            "status": "success",
            "data": version_info
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"获取版本信息失败: {str(e)}"
        }
    finally:
        if conn:
            conn.close()

class BatchRemarksRequest(BaseModel):
    items: list[dict]

@router.post("/batch-remarks", summary="批量获取视频备注")
async def get_video_remarks(request: BatchRemarksRequest):
    """批量获取视频备注

    Args:
        request: 包含 items 列表的请求体，每个 item 包含 bvid 和 view_at

    Returns:
        dict: 包含所有视频备注信息的响应
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # 按年份分组记录
        records_by_year = {}
        for record in request.items:
            year = datetime.fromtimestamp(record['view_at']).year
            if year not in records_by_year:
                records_by_year[year] = []
            records_by_year[year].append((record['bvid'], record['view_at']))

        # 存储所有查询结果
        results = {}

        # 处理每个年份的数据
        for year, year_records in records_by_year.items():
            table_name = f"bilibili_history_{year}"

            # 检查表是否存在
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """, (table_name,))

            if not cursor.fetchone():
                print(f"未找到 {year} 年的历史记录数据")
                continue

            # 为每个(bvid, view_at)对执行单独的查询
            for bvid, view_at in year_records:
                query = f"""
                    SELECT bvid, view_at, title, remark, remark_time
                    FROM {table_name}
                    WHERE bvid = ? AND view_at = ?
                """

                cursor.execute(query, (bvid, view_at))
                row = cursor.fetchone()

                if row:
                    bvid, view_at, title, remark, remark_time = row
                    results[f"{bvid}_{view_at}"] = {
                        "bvid": bvid,
                        "view_at": view_at,
                        "title": title,
                        "remark": remark,
                        "remark_time": remark_time
                    }

        return {
            "status": "success",
            "data": results
        }

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=500,
            detail=f"数据库操作失败: {str(e)}"
        )
    finally:
        if conn:
            conn.close()

@router.get("/by_cid/{cid}", summary="根据CID查询视频详情")
async def get_video_by_cid(
    cid: int,
    use_local_images: bool = Query(False, description="是否使用本地图片"),
    use_sessdata: bool = Query(True, description="是否在图片URL中使用SESSDATA")
):
    """
    根据视频CID查询详细信息

    Args:
        cid: 视频的CID
        use_local_images: 是否使用本地图片
        use_sessdata: 是否在图片URL中使用SESSDATA

    Returns:
        视频的详细信息，包括标题、封面和作者信息
    """
    print(f"【调试】开始根据CID={cid}查询视频信息")
    try:
        conn = get_db()
        cursor = conn.cursor()

        # 获取所有年份表
        years = get_available_years()
        if not years:
            print(f"【调试】未找到任何历史记录数据表")
            return {
                "status": "error",
                "message": "未找到任何历史记录数据"
            }

        print(f"【调试】找到以下年份表: {years}")

        # 构建UNION ALL查询
        queries = []
        for year in years:
            table_name = f"bilibili_history_{year}"
            # 选择与视频相关的所有字段
            queries.append(f"""
                SELECT
                    id, title, long_title, cover, covers, uri, oid, epid, bvid, page,
                    cid, part, business, dt, videos, author_name, author_face, author_mid,
                    view_at, progress, badge, show_title, duration, current, total,
                    new_desc, is_finish, is_fav, kid, tag_name, live_status, main_category
                FROM {table_name}
                WHERE cid = {cid}
            """)

        # 组合所有查询，LIMIT放在最后，不使用括号
        union_query = f"{' UNION ALL '.join(queries)} LIMIT 1"
        print(f"【调试】CID查询SQL: {union_query}")

        # 执行查询
        cursor.execute(union_query)
        columns = [description[0] for description in cursor.description]

        record = cursor.fetchone()
        if not record:
            print(f"【调试】未找到CID为{cid}的视频记录")
            return {
                "status": "error",
                "message": f"未找到CID为{cid}的视频记录"
            }

        print(f"【调试】找到CID={cid}的记录，开始处理")

        # 构建记录字典
        record_dict = dict(zip(columns, record))

        # 打印记录内容以便调试
        print(f"【调试】原始记录: {record_dict}")

        # 处理图片URL
        record_dict = _process_record(record_dict, use_local_images, use_sessdata)

        # 添加视频的播放时间（人类可读格式）
        if 'view_at' in record_dict and record_dict['view_at']:
            record_dict['view_time'] = datetime.fromtimestamp(record_dict['view_at']).strftime("%Y-%m-%d %H:%M:%S")

        print(f"【调试】处理后的记录: {record_dict}")

        conn.close()

        return {
            "status": "success",
            "data": record_dict
        }
    except Exception as e:
        print(f"查询CID时出错: {str(e)}")
        if 'conn' in locals() and conn:
            conn.close()
        return {
            "status": "error",
            "message": f"查询视频详情时出错: {str(e)}"
        }