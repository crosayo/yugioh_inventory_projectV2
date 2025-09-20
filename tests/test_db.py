# tests/test_db.py
import psycopg2
from app.db import get_db_connection

def test_db_connection():
    """
    データベースへの接続をテストする。
    """
    conn = None
    try:
        # 実際にデータベースに接続を試みる
        conn = get_db_connection()
        
        # connオブジェクトがNoneでないこと、つまり接続が成功したことを確認
        assert conn is not None
        
        # 接続がアクティブであることを確認
        assert not conn.closed
        
    except psycopg2.Error as e:
        # もし接続エラーが発生したら、テストは失敗したとみなす
        assert False, f"データベース接続に失敗しました: {e}"
        
    finally:
        # テストが終わったら、必ず接続を閉じる
        if conn:
            conn.close()

# tests/test_db.py の末尾に追記

def test_add_and_get_item(db_session):
    """
    itemsテーブルに新しいレコードを追加し、正しく取得できるかをテストする。
    db_session fixtureのおかげで、テスト後のデータは自動的にロールバックされる。
    """
    # db_sessionからカーソルを取得
    cursor = db_session.cursor()
    
    # テスト用のカードデータ
    test_card = {
        'name': 'テスト・カード',
        'card_id': 'TEST-JP001',
        'rare': 'Test Rare',
        'stock': 10,
        'category': 'テストカテゴリ'
    }
    
    # 1. データの挿入
    cursor.execute(
        """
        INSERT INTO items (name, card_id, rare, stock, category)
        VALUES (%(name)s, %(card_id)s, %(rare)s, %(stock)s, %(category)s)
        """,
        test_card
    )
    
    # 2. 挿入したデータをIDで取得
    cursor.execute("SELECT * FROM items WHERE card_id = 'TEST-JP001'")
    inserted_item = cursor.fetchone()
    
    # 3. 検証 (assert)
    # 挿入したデータがちゃんと存在するか？
    assert inserted_item is not None
    # 挿入したデータの内容は正しいか？
    assert inserted_item['name'] == test_card['name']
    assert inserted_item['stock'] == test_card['stock']
    
    # テストが終わると、db_sessionが自動的にこのINSERTをロールバック（取り消し）してくれます。