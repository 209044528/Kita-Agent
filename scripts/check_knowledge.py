import psycopg2
from app.core.config import settings
import json

def query_paper_tag():
    try:
        conn = psycopg2.connect(
            host=settings.PG_VECTOR_HOST,
            port=settings.PG_VECTOR_PORT,
            user=settings.PG_VECTOR_USER,
            password=settings.PG_VECTOR_PASSWORD,
            database=settings.PG_VECTOR_DB
        )
        cursor = conn.cursor()
        
        # 查询标签为 '论文' 的文档
        cursor.execute("""
            SELECT 
                id, 
                document, 
                cmetadata->>'source' as source,
                cmetadata->>'file_path' as file_path
            FROM langchain_pg_embedding 
            WHERE cmetadata->>'knowledge_tag' = %s
            LIMIT 20;
        """, ('论文',))
        
        rows = cursor.fetchall()
        if not rows:
            print("未找到标签为「论文」的文档。")
        else:
            print(f"查找到 {len(rows)} 条文档（显示前20条）：\n")
            for i, row in enumerate(rows):
                print(f"--- 文档 {i+1} ---")
                print(f"ID: {row[0]}")
                print(f"来源: {row[2]}")
                print(f"路径: {row[3]}")
                # 预览内容并处理换行
                preview = row[1][:200].replace('\n', ' ')
                print(f"内容预览: {preview}...")
                print("-" * 20)
                
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"查询失败: {str(e)}")

if __name__ == "__main__":
    query_paper_tag()
