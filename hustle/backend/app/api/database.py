from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.database import get_db, engine, Base
import json

router = APIRouter(prefix="/database", tags=["database"])

@router.get("/tables")
def get_tables():
    """获取数据库表列表"""
    try:
        # 获取所有表名
        inspector = engine.raw_connection().cursor()
        inspector.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        tables = inspector.fetchall()
        inspector.close()
        
        table_list = []
        for table in tables:
            table_name = table[0]
            
            # 获取表的列数
            inspector = engine.raw_connection().cursor()
            inspector.execute(f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'")
            columns_count = inspector.fetchone()[0]
            
            # 获取表的行数
            try:
                inspector.execute(f"SELECT COUNT(*) FROM {table_name}")
                rows_count = inspector.fetchone()[0]
            except:
                rows_count = 0
            
            inspector.close()
            
            table_list.append({
                "name": table_name,
                "columns": columns_count,
                "rows": rows_count
            })
        
        return {"data": table_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取表列表失败: {str(e)}")

@router.get("/tables/{table_name}/data")
def get_table_data(table_name: str, skip: int = 0, limit: int = 100):
    """获取表数据"""
    try:
        # 获取表的列名
        inspector = engine.raw_connection().cursor()
        inspector.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}' ORDER BY ordinal_position")
        columns = [col[0] for col in inspector.fetchall()]
        
        # 获取表数据
        inspector.execute(f"SELECT * FROM {table_name} LIMIT {limit} OFFSET {skip}")
        rows = inspector.fetchall()
        inspector.close()
        
        # 构建结果
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                # 处理JSON类型的数据
                value = row[i]
                if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                    try:
                        value = json.loads(value)
                    except:
                        pass
                row_dict[col] = value
            data.append(row_dict)
        
        return {"columns": columns, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取表数据失败: {str(e)}")

@router.post("/tables/{table_name}/data")
def add_table_row(table_name: str, row: dict):
    """添加表数据行"""
    try:
        # 构建SQL插入语句
        columns = list(row.keys())
        values = list(row.values())
        
        # 处理值的格式化
        formatted_values = []
        for value in values:
            if value is None:
                formatted_values.append('NULL')
            elif isinstance(value, (int, float)):
                formatted_values.append(str(value))
            elif isinstance(value, bool):
                formatted_values.append('true' if value else 'false')
            elif isinstance(value, (dict, list)):
                formatted_values.append(f"'{json.dumps(value)}'")
            else:
                formatted_values.append(f"'{str(value)}'")
        
        sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(formatted_values)}) RETURNING *"
        
        inspector = engine.raw_connection().cursor()
        inspector.execute(sql)
        result = inspector.fetchone()
        inspector.connection.commit()
        inspector.close()
        
        # 构建返回结果
        if result:
            result_dict = {}
            for i, col in enumerate(columns):
                result_dict[col] = result[i]
            return {"data": result_dict}
        else:
            return {"data": row}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加数据失败: {str(e)}")

@router.put("/tables/{table_name}/data/{primary_key}")
def update_table_row(table_name: str, primary_key: str, row: dict):
    """更新表数据行"""
    try:
        # 获取表的主键
        inspector = engine.raw_connection().cursor()
        inspector.execute(f"SELECT column_name FROM information_schema.key_column_usage WHERE table_name = '{table_name}' AND constraint_name LIKE '%_pkey'")
        primary_key_column = inspector.fetchone()
        
        if not primary_key_column:
            raise HTTPException(status_code=400, detail="表没有主键")
        
        primary_key_column = primary_key_column[0]
        
        # 构建SQL更新语句
        set_clauses = []
        for key, value in row.items():
            if key == primary_key_column:
                continue
            
            if value is None:
                set_clauses.append(f"{key} = NULL")
            elif isinstance(value, (int, float)):
                set_clauses.append(f"{key} = {str(value)}")
            elif isinstance(value, bool):
                set_clauses.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (dict, list)):
                set_clauses.append(f"{key} = '{json.dumps(value)}'")
            else:
                set_clauses.append(f"{key} = '{str(value)}'")
        
        sql = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {primary_key_column} = '{primary_key}' RETURNING *"
        
        inspector.execute(sql)
        result = inspector.fetchone()
        inspector.connection.commit()
        inspector.close()
        
        # 构建返回结果
        if result:
            columns = list(row.keys())
            result_dict = {}
            for i, col in enumerate(columns):
                result_dict[col] = result[i]
            return {"data": result_dict}
        else:
            return {"data": row}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新数据失败: {str(e)}")

@router.delete("/tables/{table_name}/data/{primary_key}")
def delete_table_row(table_name: str, primary_key: str):
    """删除表数据行"""
    try:
        # 获取表的主键
        inspector = engine.raw_connection().cursor()
        inspector.execute(f"SELECT column_name FROM information_schema.key_column_usage WHERE table_name = '{table_name}' AND constraint_name LIKE '%_pkey'")
        primary_key_column = inspector.fetchone()
        
        if not primary_key_column:
            raise HTTPException(status_code=400, detail="表没有主键")
        
        primary_key_column = primary_key_column[0]
        
        # 执行删除操作
        sql = f"DELETE FROM {table_name} WHERE {primary_key_column} = '{primary_key}'"
        inspector.execute(sql)
        affected_rows = inspector.rowcount
        inspector.connection.commit()
        inspector.close()
        
        if affected_rows == 0:
            raise HTTPException(status_code=404, detail="数据行不存在")
        
        return {"message": "数据删除成功", "affected_rows": affected_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除数据失败: {str(e)}")

@router.post("/query")
def execute_sql_query(sql: dict):
    """执行SQL查询"""
    try:
        sql_text = sql.get("sql", "")
        
        if not sql_text:
            raise HTTPException(status_code=400, detail="SQL语句不能为空")
        
        # 禁止危险操作
        dangerous_commands = ["DROP", "ALTER", "TRUNCATE", "CREATE", "INSERT", "UPDATE", "DELETE"]
        for cmd in dangerous_commands:
            if cmd in sql_text.upper():
                raise HTTPException(status_code=400, detail="禁止执行危险操作")
        
        # 执行查询
        inspector = engine.raw_connection().cursor()
        inspector.execute(sql_text)
        
        # 获取列名
        columns = [desc[0] for desc in inspector.description] if inspector.description else []
        
        # 获取结果
        rows = inspector.fetchall()
        inspector.close()
        
        # 构建结果
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                row_dict[col] = row[i]
            data.append(row_dict)
        
        return {"columns": columns, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行查询失败: {str(e)}")

@router.get("/metrics")
def get_database_metrics():
    """获取数据库性能指标"""
    try:
        # 获取连接数
        inspector = engine.raw_connection().cursor()
        inspector.execute("SELECT COUNT(*) FROM pg_stat_activity")
        connections = inspector.fetchone()[0]
        
        # 获取最大连接数
        inspector.execute("SHOW max_connections")
        max_connections = inspector.fetchone()[0]
        
        # 获取缓存命中率
        inspector.execute("SELECT sum(blks_hit) as hit, sum(blks_read) as read FROM pg_stat_database")
        cache_stats = inspector.fetchone()
        if cache_stats[0] and (cache_stats[0] + cache_stats[1]) > 0:
            cache_hit_rate = round((cache_stats[0] / (cache_stats[0] + cache_stats[1])) * 100, 2)
        else:
            cache_hit_rate = 0
        
        # 获取数据库版本
        inspector.execute("SELECT version()")
        version = inspector.fetchone()[0]
        
        inspector.close()
        
        return {
            "connections": connections,
            "max_connections": max_connections,
            "cache_hit_rate": cache_hit_rate,
            "version": version
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取性能指标失败: {str(e)}")
