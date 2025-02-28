import sqlite3
from fastapi import APIRouter
from scripts.init_categories import init_categories
from scripts.utils import get_output_path, load_config

router = APIRouter()

def get_db():
    """获取数据库连接"""
    config = load_config()
    db_path = get_output_path(config['db_file'])
    return sqlite3.connect(db_path)

def ensure_table_exists():
    """确保分类表存在，如果不存在则初始化"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='video_categories'
        ''')
        
        if not cursor.fetchone():
            print("分类表不存在，正在初始化...")
            init_categories()
            print("分类表初始化完成")
            
    except sqlite3.Error as e:
        print(f"检查表存在时发生错误: {e}")
    finally:
        if conn:
            conn.close()

@router.post("/init", summary="初始化视频分类数据")
async def initialize_categories():
    """初始化视频分类数据"""
    try:
        init_categories()
        return {
            "status": "success",
            "message": "视频分类表初始化成功"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"初始化失败: {str(e)}"
        }

@router.get("/categories", summary="获取所有分类信息")
async def get_categories():
    """获取所有分类信息"""
    try:
        # 确保表存在
        ensure_table_exists()
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 查询所有分类
        cursor.execute('''
        SELECT main_category, sub_category, alias, tid, image 
        FROM video_categories 
        ORDER BY main_category, sub_category
        ''')
        
        # 构建分类树
        categories = {}
        for row in cursor.fetchall():
            main_cat, sub_cat, alias, tid, image = row
            
            if main_cat not in categories:
                categories[main_cat] = {
                    "name": main_cat,
                    "image": image,
                    "sub_categories": []
                }
            
            # 只有当子分类名称不等于主分类名称时才添加
            if sub_cat != main_cat:
                categories[main_cat]["sub_categories"].append({
                    "name": sub_cat,
                    "alias": alias,
                    "tid": tid
                })
        
        # 打印结果
        print("\n=== 分类数据 ===")
        print(f"主分类数量: {len(categories)}")
        for main_cat, data in categories.items():
            print(f"{main_cat}: {len(data['sub_categories'])} 个子分类")
        print("===============\n")
        
        return {
            "status": "success",
            "data": list(categories.values())
        }
        
    except sqlite3.Error as e:
        error_msg = f"数据库错误: {str(e)}"
        print(f"=== 错误 ===\n{error_msg}\n===========")
        return {"status": "error", "message": error_msg}
    finally:
        if conn:
            conn.close()

@router.get("/main-categories", summary="获取所有主分类")
async def get_main_categories():
    """获取所有主分类"""
    try:
        # 确保表存在
        ensure_table_exists()
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT DISTINCT main_category, image 
        FROM video_categories 
        ORDER BY main_category
        ''')
        
        categories = []
        for row in cursor.fetchall():
            categories.append({
                "name": row[0],
                "image": row[1]
            })
            
        return {
            "status": "success",
            "data": categories
        }
        
    except sqlite3.Error as e:
        return {"status": "error", "message": f"数据库错误: {str(e)}"}
    finally:
        if conn:
            conn.close()

@router.get("/sub-categories/{main_category}", summary="获取指定主分类下的所有子分类")
async def get_sub_categories(main_category: str):
    """获取指定主分类下的所有子分类"""
    try:
        # 确保表存在
        ensure_table_exists()
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT sub_category, alias, tid 
        FROM video_categories 
        WHERE main_category = ? AND sub_category != main_category
        ORDER BY sub_category
        ''', (main_category,))
        
        categories = []
        for row in cursor.fetchall():
            categories.append({
                "name": row[0],
                "alias": row[1],
                "tid": row[2]
            })
            
        return {
            "status": "success",
            "data": categories
        }
        
    except sqlite3.Error as e:
        return {"status": "error", "message": f"数据库错误: {str(e)}"}
    finally:
        if conn:
            conn.close() 