# app/db.py
import psycopg2
import psycopg2.extras
import os
import sys

def get_db_connection():
    """
    Establishes a connection to the PostgreSQL database.
    Uses the DATABASE_URL environment variable.
    The cursor factory is set to DictCursor to return rows as dictionaries.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("FATAL: DATABASE_URL environment variable not set.", file=sys.stderr)
        raise ValueError("DATABASE_URL environment variable is not set. Application cannot connect to the database.")

    try:
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.DictCursor)
        return conn
    except psycopg2.Error as e:
        db_url_display = db_url[:db_url.find('@')] + "@..." if '@' in db_url else "URL (details hidden)"
        print(f"FATAL: Database connection failed. DB_URL might be incorrect or database not accessible.", file=sys.stderr)
        print(f"Used DB_URL: {db_url_display}", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
        raise

def delete_items_by_ids(item_ids):
    """ 複数の item_id に基づいてアイテムを削除する """
    if not item_ids:
        return 0
    
    conn = get_db_connection()
    # PostgreSQL用のプレースホルダ '%s' を使用
    placeholders = ','.join(['%s'] * len(item_ids))
    sql = f'DELETE FROM items WHERE id IN ({placeholders})'
    
    try:
        cursor = conn.cursor()
        # パラメータはタプルとして渡す
        cursor.execute(sql, tuple(item_ids))
        conn.commit()
        deleted_count = cursor.rowcount
    except Exception as e:
        conn.rollback()
        print(f"データベースエラー: {e}")
        deleted_count = 0
    finally:
        conn.close()
        
    return deleted_count