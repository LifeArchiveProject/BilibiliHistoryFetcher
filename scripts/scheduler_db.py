import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

from scripts.utils import get_base_path

logger = logging.getLogger(__name__)

class SchedulerDB:
    """计划任务数据库管理类"""
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'SchedulerDB':
        """获取单例实例"""
        if not cls._instance:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """初始化数据库连接"""
        if SchedulerDB._instance is not None:
            return
            
        base_path = get_base_path()
        self.db_dir = os.path.join(base_path, 'output', 'database')
        os.makedirs(self.db_dir, exist_ok=True)
        
        self.db_path = os.path.join(self.db_dir, 'scheduler.db')
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        
        # 创建所需的表
        self._create_tables()
    
    def _create_tables(self):
        """创建所需的数据库表"""
        cursor = self.conn.cursor()
        
        # 任务状态表 - 存储每个任务的最新状态
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_status (
            task_id TEXT PRIMARY KEY,
            name TEXT,
            last_run_time TEXT,
            next_run_time TEXT,
            last_status TEXT,
            enabled INTEGER DEFAULT 1,
            total_runs INTEGER DEFAULT 0,
            success_runs INTEGER DEFAULT 0,
            fail_runs INTEGER DEFAULT 0,
            avg_duration REAL DEFAULT 0,
            last_error TEXT,
            last_modified TEXT,
            priority INTEGER DEFAULT 0,
            tags TEXT,
            extra_data TEXT
        )
        ''')
        
        # 任务执行历史表 - 存储每次执行的详细信息
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            start_time TEXT,
            end_time TEXT,
            duration REAL,
            status TEXT,
            error_message TEXT,
            triggered_by TEXT,
            output TEXT,
            FOREIGN KEY (task_id) REFERENCES task_status (task_id)
        )
        ''')
        
        # 依赖任务执行记录表 - 记录任务链的执行情况
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_chain_execution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id TEXT,
            start_task_id TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            tasks_executed TEXT,
            tasks_succeeded TEXT,
            tasks_failed TEXT
        )
        ''')
        
        self.conn.commit()
    
    def get_all_task_status(self) -> List[Dict]:
        """获取所有任务的状态"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT * FROM task_status
        ''')
        
        rows = cursor.fetchall()
        result = []
        
        for row in rows:
            task_data = dict(row)
            # 处理JSON字段
            if task_data.get('extra_data'):
                try:
                    task_data['extra_data'] = json.loads(task_data['extra_data'])
                except:
                    task_data['extra_data'] = {}
            
            if task_data.get('tags'):
                try:
                    task_data['tags'] = json.loads(task_data['tags'])
                except:
                    task_data['tags'] = []
            
            result.append(task_data)
        
        return result
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取特定任务的状态"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT * FROM task_status WHERE task_id = ?
        ''', (task_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        task_data = dict(row)
        # 处理JSON字段
        if task_data.get('extra_data'):
            try:
                task_data['extra_data'] = json.loads(task_data['extra_data'])
            except:
                task_data['extra_data'] = {}
        
        if task_data.get('tags'):
            try:
                task_data['tags'] = json.loads(task_data['tags'])
            except:
                task_data['tags'] = []
        
        return task_data
    
    def update_task_status(self, task_id: str, data: Dict) -> bool:
        """更新任务状态"""
        try:
            task_status = self.get_task_status(task_id)
            cursor = self.conn.cursor()
            
            # 检查task_status表是否有last_modified列
            cursor.execute("PRAGMA table_info(task_status)")
            columns = cursor.fetchall()
            has_last_modified = any(col[1] == 'last_modified' for col in columns)
            
            if task_status:
                # 任务存在，更新
                fields = []
                values = []
                
                for key, value in data.items():
                    # 确保列存在于表中
                    if key == 'last_modified' and not has_last_modified:
                        continue
                        
                    fields.append(f"{key} = ?")
                    
                    # 处理特殊字段
                    if key in ['extra_data', 'tags'] and value is not None:
                        values.append(json.dumps(value, ensure_ascii=False))
                    else:
                        values.append(value)
                
                # 如果表中有last_modified列，才添加最后修改时间
                if has_last_modified:
                    fields.append("last_modified = ?")
                    values.append(datetime.now().isoformat())
                
                # 添加任务ID
                values.append(task_id)
                
                query = f'''
                UPDATE task_status SET {", ".join(fields)} WHERE task_id = ?
                '''
                
                cursor.execute(query, values)
            else:
                # 任务不存在，创建新任务
                fields = ['task_id']
                placeholders = ['?']
                values = [task_id]
                
                for key, value in data.items():
                    # 确保列存在于表中
                    if key == 'last_modified' and not has_last_modified:
                        continue
                        
                    fields.append(key)
                    placeholders.append('?')
                    
                    # 处理特殊字段
                    if key in ['extra_data', 'tags'] and value is not None:
                        values.append(json.dumps(value, ensure_ascii=False))
                    else:
                        values.append(value)
                
                # 如果表中有last_modified列，才添加最后修改时间
                if has_last_modified:
                    fields.append("last_modified")
                    placeholders.append("?")
                    values.append(datetime.now().isoformat())
                
                query = f'''
                INSERT INTO task_status ({", ".join(fields)})
                VALUES ({", ".join(placeholders)})
                '''
                
                cursor.execute(query, values)
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"更新任务状态失败: {str(e)}")
            return False
    
    def record_task_execution(self, task_id: str, 
                             start_time: str, 
                             end_time: Optional[str] = None,
                             duration: Optional[float] = None,
                             status: str = "success",
                             error_message: Optional[str] = None,
                             triggered_by: Optional[str] = None,
                             output: Optional[str] = None) -> int:
        """记录任务执行"""
        try:
            cursor = self.conn.cursor()
            
            # 如果提供了开始时间和结束时间，但没有提供持续时间，尝试计算
            if start_time and end_time and duration is None:
                try:
                    # 尝试解析时间字符串为datetime对象
                    start_dt = datetime.fromisoformat(start_time)
                    end_dt = datetime.fromisoformat(end_time)
                    duration = (end_dt - start_dt).total_seconds()
                except Exception as e:
                    logger.warning(f"计算任务持续时间失败: {str(e)}")
            
            # 插入执行记录
            cursor.execute('''
            INSERT INTO task_history
            (task_id, start_time, end_time, duration, status, error_message, triggered_by, output)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_id,
                start_time,
                end_time,
                duration,
                status,
                error_message,
                triggered_by,
                output
            ))
            
            history_id = cursor.lastrowid
            
            # 更新任务状态
            task_status = self.get_task_status(task_id) or {}
            
            # 基本更新字段
            update_data = {
                'last_run_time': start_time,
                'last_status': status
            }
            
            # 计数更新
            total_runs = task_status.get('total_runs', 0) + 1
            update_data['total_runs'] = total_runs
            
            if status == 'success':
                success_runs = task_status.get('success_runs', 0) + 1
                update_data['success_runs'] = success_runs
            elif status == 'fail':
                fail_runs = task_status.get('fail_runs', 0) + 1
                update_data['fail_runs'] = fail_runs
                update_data['last_error'] = error_message
            
            # 更新平均执行时间
            if duration is not None:
                old_avg = float(task_status.get('avg_duration', 0))
                if old_avg == 0:
                    update_data['avg_duration'] = duration
                else:
                    # 使用移动平均值
                    update_data['avg_duration'] = (old_avg * (total_runs - 1) + duration) / total_runs
            
            # 应用更新
            self.update_task_status(task_id, update_data)
            
            self.conn.commit()
            return history_id
        except Exception as e:
            logger.error(f"记录任务执行失败: {str(e)}")
            return -1
    
    def get_task_execution_history(self, task_id: str, limit: int = 10) -> List[Dict]:
        """获取任务执行历史"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT * FROM task_history
        WHERE task_id = ?
        ORDER BY start_time DESC
        LIMIT ?
        ''', (task_id, limit))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def get_recent_task_executions(self, limit: int = 20) -> List[Dict]:
        """获取最近的任务执行记录"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT h.*, s.name
        FROM task_history h
        LEFT JOIN task_status s ON h.task_id = s.task_id
        ORDER BY h.start_time DESC
        LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def record_chain_execution(self, chain_id: str, start_task_id: str, 
                              tasks_executed: List[str], tasks_succeeded: List[str], 
                              tasks_failed: List[str], status: str,
                              start_time: datetime, end_time: Optional[datetime] = None) -> int:
        """记录任务链执行"""
        try:
            cursor = self.conn.cursor()
            
            cursor.execute('''
            INSERT INTO task_chain_execution
            (chain_id, start_task_id, start_time, end_time, status, tasks_executed, tasks_succeeded, tasks_failed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                chain_id,
                start_task_id,
                start_time.isoformat(),
                end_time.isoformat() if end_time else None,
                status,
                json.dumps(tasks_executed, ensure_ascii=False),
                json.dumps(tasks_succeeded, ensure_ascii=False),
                json.dumps(tasks_failed, ensure_ascii=False)
            ))
            
            chain_id = cursor.lastrowid
            self.conn.commit()
            return chain_id
        except Exception as e:
            logger.error(f"记录任务链执行失败: {str(e)}")
            return -1
    
    def get_chain_execution_history(self, limit: int = 10) -> List[Dict]:
        """获取任务链执行历史"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT * FROM task_chain_execution
        ORDER BY start_time DESC
        LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        result = []
        
        for row in rows:
            chain_data = dict(row)
            # 解析JSON字段
            for field in ['tasks_executed', 'tasks_succeeded', 'tasks_failed']:
                if chain_data.get(field):
                    try:
                        chain_data[field] = json.loads(chain_data[field])
                    except:
                        chain_data[field] = []
            
            result.append(chain_data)
        
        return result
    
    def set_task_next_run(self, task_id: str, next_run_time: datetime) -> bool:
        """设置任务的下次执行时间"""
        try:
            self.update_task_status(task_id, {
                'next_run_time': next_run_time.isoformat()
            })
            return True
        except Exception as e:
            logger.error(f"设置任务下次执行时间失败: {str(e)}")
            return False
    
    def enable_task(self, task_id: str, enabled: bool = True) -> bool:
        """启用或禁用任务"""
        try:
            self.update_task_status(task_id, {
                'enabled': 1 if enabled else 0
            })
            return True
        except Exception as e:
            logger.error(f"{'启用' if enabled else '禁用'}任务失败: {str(e)}")
            return False
    
    def set_task_priority(self, task_id: str, priority: int) -> bool:
        """设置任务优先级"""
        try:
            self.update_task_status(task_id, {
                'priority': priority
            })
            return True
        except Exception as e:
            logger.error(f"设置任务优先级失败: {str(e)}")
            return False
    
    def add_task_tags(self, task_id: str, tags: List[str]) -> bool:
        """添加任务标签"""
        try:
            task_status = self.get_task_status(task_id)
            if not task_status:
                return False
                
            current_tags = task_status.get('tags', [])
            if not isinstance(current_tags, list):
                current_tags = []
            
            # 添加新标签
            for tag in tags:
                if tag not in current_tags:
                    current_tags.append(tag)
            
            self.update_task_status(task_id, {
                'tags': current_tags
            })
            return True
        except Exception as e:
            logger.error(f"添加任务标签失败: {str(e)}")
            return False
    
    def remove_task_tags(self, task_id: str, tags: List[str]) -> bool:
        """移除任务标签"""
        try:
            task_status = self.get_task_status(task_id)
            if not task_status:
                return False
                
            current_tags = task_status.get('tags', [])
            if not isinstance(current_tags, list):
                current_tags = []
            
            # 移除标签
            current_tags = [tag for tag in current_tags if tag not in tags]
            
            self.update_task_status(task_id, {
                'tags': current_tags
            })
            return True
        except Exception as e:
            logger.error(f"移除任务标签失败: {str(e)}")
            return False
    
    def record_chain_execution_start(self, chain_id: str, start_task_id: str, start_time: str) -> int:
        """记录任务链开始执行"""
        try:
            cursor = self.conn.cursor()
            
            cursor.execute('''
            INSERT INTO task_chain_execution
            (chain_id, start_task_id, start_time, status)
            VALUES (?, ?, ?, ?)
            ''', (
                chain_id,
                start_task_id,
                start_time,
                'running'
            ))
            
            execution_id = cursor.lastrowid
            self.conn.commit()
            return execution_id
        except Exception as e:
            logger.error(f"记录任务链开始执行失败: {str(e)}")
            return -1
    
    def record_chain_execution_end(self, chain_id: str, end_time: str, status: str,
                                  tasks_executed: int, tasks_succeeded: int, tasks_failed: int) -> bool:
        """记录任务链执行完成"""
        try:
            cursor = self.conn.cursor()
            
            cursor.execute('''
            UPDATE task_chain_execution
            SET end_time = ?, status = ?, 
                tasks_executed = ?, tasks_succeeded = ?, tasks_failed = ?
            WHERE chain_id = ?
            ''', (
                end_time,
                status,
                tasks_executed,
                tasks_succeeded,
                tasks_failed,
                chain_id
            ))
            
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"记录任务链执行完成失败: {str(e)}")
            return False
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close() 