import json
import sqlite3
from datetime import datetime
from typing import Optional, List
import os

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from scripts.utils import get_output_path, load_config

router = APIRouter()
config = load_config()

def get_db():
    """获取数据库连接"""
    db_path = get_output_path(config['db_file'])
    return sqlite3.connect(db_path)

def get_available_years():
    """获取数据库中所有可用的年份"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name LIKE 'bilibili_history_%'
            ORDER BY name DESC
        """)
        
        years = []
        for (table_name,) in cursor.fetchall():
            try:
                year = int(table_name.split('_')[-1])
                years.append(year)
            except (ValueError, IndexError):
                continue
                
        return sorted(years, reverse=True)
    except sqlite3.Error as e:
        print(f"获取年份列表时发生错误: {e}")
        return []
    finally:
        if conn:
            conn.close()

@router.get("/available-years")
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

@router.get("/all")
async def get_history_page(
    page: int = Query(1, description="当前页码"),
    size: int = Query(10, description="每页记录数"),
    sort_order: int = Query(0, description="排序顺序，0为降序，1为升序"),
    tag_name: Optional[str] = Query(None, description="视频子分区名称"),
    main_category: Optional[str] = Query(None, description="主分区名称"),
    date_range: Optional[str] = Query(None, description="日期范围，格式为yyyyMMdd-yyyyMMdd")
):
    """分页查询历史记录，支持跨年份查询"""
    print("\n=== 接收到的请求参数 ===")
    print(f"页码(page): {page}")
    print(f"每页记录数(size): {size}")
    print(f"排序顺序(sort_order): {'升序' if sort_order == 1 else '降序'}")
    print(f"子分区名称(tag_name): {tag_name if tag_name else '无'}")
    print(f"主分区名称(main_category): {main_category if main_category else '无'}")
    print(f"日期范围(date_range): {date_range if date_range else '无'}")
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
            if 'covers' in record and record['covers']:
                try:
                    record['covers'] = json.loads(record['covers'])
                except json.JSONDecodeError:
                    record['covers'] = []
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

@router.get("/search")
async def search_history(
    page: int = Query(1, description="当前页码"),
    size: int = Query(10, description="每页记录数"),
    sortOrder: int = Query(0, description="排序顺序，0为降序，1为升序"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    year: Optional[int] = Query(None, description="要查询的年份，不传则使用当前年份")
):
    """搜索历史记录"""
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
        
        # 如果未指定年份，使用最新的年份
        target_year = year if year is not None else available_years[0]
        
        # 检查指定的年份是否可用
        if year is not None and year not in available_years:
            return {
                "status": "error",
                "message": f"未找到 {year} 年的历史记录数据。可用的年份有：{', '.join(map(str, available_years))}"
            }
        
        table_name = f"bilibili_history_{target_year}"
        query = f"SELECT * FROM {table_name} WHERE 1=1"
        params = []

        if search:
            search = search.strip()
            if search.isdigit():
                # 按 oid 精确搜索
                query += " AND oid = ?"
                params.append(int(search))
            else:
                # 按标题模糊搜索
                query += " AND title LIKE ?"
                params.append(f"%{search}%")

        # 添加排序
        query += " ORDER BY view_at " + ("ASC" if sortOrder == 1 else "DESC")

        # 获取总记录数
        count_query = f"SELECT COUNT(*) FROM ({query})"
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        # 添加分页
        query += " LIMIT ? OFFSET ?"
        params.extend([size, (page - 1) * size])

        # 执行查询
        cursor.execute(query, params)
        columns = [description[0] for description in cursor.description]
        records = []
        
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
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
                "current": page,
                "year": target_year,
                "available_years": available_years
            }
        }

    except sqlite3.Error as e:
        return {"status": "error", "message": f"数据库错误: {str(e)}"}
    finally:
        if conn:
            conn.close()

@router.get("/search_author")
async def search_author(
    page: int = Query(1, description="当前页码"),
    size: int = Query(10, description="每页记录数"),
    sortOrder: int = Query(0, description="排序顺序，0为降序，1为升序"),
    author: Optional[str] = Query(None, description="作者名称，支持模糊搜索"),
    year: Optional[int] = Query(None, description="要查询的年份，不传则使用当前年份")
):
    """搜索作者的历史记录"""
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
        
        # 如果未指定年份，使用最新的年份
        target_year = year if year is not None else available_years[0]
        
        # 检查指定的年份是否可用
        if year is not None and year not in available_years:
            return {
                "status": "error",
                "message": f"未找到 {year} 年的历史记录数据。可用的年份有：{', '.join(map(str, available_years))}"
            }
        
        table_name = f"bilibili_history_{target_year}"
        query = f"SELECT * FROM {table_name} WHERE 1=1"
        params = []

        if author:
            author = author.strip()
            # 使用LIKE进行模糊搜索
            query += " AND author_name LIKE ?"
            params.append(f"%{author}%")

        # 添加排序
        query += " ORDER BY view_at " + ("ASC" if sortOrder == 1 else "DESC")

        # 获取总记录数
        count_query = f"SELECT COUNT(*) FROM ({query})"
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        # 添加分页
        query += " LIMIT ? OFFSET ?"
        params.extend([size, (page - 1) * size])

        # 执行查询
        cursor.execute(query, params)
        columns = [description[0] for description in cursor.description]
        records = []
        
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
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
                "current": page,
                "year": target_year,
                "available_years": available_years
            }
        }

    except sqlite3.Error as e:
        return {"status": "error", "message": f"数据库错误: {str(e)}"}
    finally:
        if conn:
            conn.close()

class UpdateRemarkRequest(BaseModel):
    bvid: str
    view_at: int
    remark: str

@router.post("/update-remark")
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

@router.get("/remark")
async def get_video_remark(bvid: str, view_at: int):
    """获取视频备注
    
    Args:
        bvid: 视频的BV号
        view_at: 观看时间戳
        
    Returns:
        dict: 包含视频备注信息的响应
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 从时间戳获取年份
        year = datetime.fromtimestamp(view_at).year
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
        
        # 查询备注
        query = f"""
            SELECT title, remark, remark_time
            FROM {table_name}
            WHERE bvid = ? AND view_at = ?
        """
        cursor.execute(query, (bvid, view_at))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(
                status_code=404,
                detail="未找到指定的视频记录"
            )
        
        return {
            "status": "success",
            "data": {
                "bvid": bvid,
                "view_at": view_at,
                "title": result[0],
                "remark": result[1],
                "remark_time": result[2]
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

@router.post("/reset-database")
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

@router.get("/remarks")
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