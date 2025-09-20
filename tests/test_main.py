# tests/test_main.py

def test_index_page_logged_out(client):
    """
    ログインしていない状態でホームページにアクセスした際の動作をテストする。
    """
    # clientを使ってホームページ('/')にGETリクエストを送る
    response = client.get('/')
    
    # 1. 検証: レスポンスは成功したか？ (ステータスコード 200 OK)
    assert response.status_code == 200
    
    # 2. 検証: レスポンスのHTMLに「ログイン」という文字が含まれているか？
    # ▼▼▼ ここの行を修正しました ▼▼▼
    assert 'ログイン'.encode('utf-8') in response.data
    # ▲▲▲ ここまで修正 ▲▲▲

def test_index_page_logged_in(client, db_session):
    """
    ログインした状態でホームページにアクセスした際の動作をテストする。
    （これは将来のログイン機能のテストに向けた準備です）
    """
    # このテストは、ログイン機能を実装した後に完成させます。
    # 今は、このファイルが正しく動作することを確認するためのプレースホルダーです。
    pass