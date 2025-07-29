# tests/conftest.py
import pytest
from dotenv import load_dotenv
import os

@pytest.fixture(scope='session', autouse=True)
def load_test_env():
    """
    テストセッションの開始時に一度だけ.flaskenvファイルを読み込むためのfixture
    """
    # プロジェクトのルートディレクトリにある .flaskenv ファイルのパスを指定
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.flaskenv')

    # .flaskenv ファイルが存在すれば読み込む
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path)
    else:
        print(f"Warning: .flaskenv file not found at {dotenv_path}")

# tests/conftest.py の末尾に追記

from app import create_app
from app.db import get_db_connection

@pytest.fixture
def app():
    """
    テスト用のFlaskアプリケーションインスタンスを作成するfixture。
    """
    # create_appを呼び出して、テスト用の設定でアプリを作成
    app = create_app({
        'TESTING': True,
    })
    yield app

@pytest.fixture
def db_session(app):
    """
    テスト用のデータベース接続と、テスト後の自動ロールバックを提供するfixture。
    これにより、データベースの状態がテスト間でクリーンに保たれる。
    """
    # アプリケーションのコンテキスト内でデータベース接続を取得
    with app.app_context():
        conn = get_db_connection()
        try:
            # 接続をテスト関数に提供
            yield conn
        finally:
            # テストが終わったら、すべての変更を元に戻す（ロールバック）
            conn.rollback()
            conn.close()

# tests/conftest.py の末尾に追記

@pytest.fixture
def client(app):
    """
    テスト用のWebクライアント（仮想ブラウザ）を作成するfixture。
    これを使って、テストコードからアプリケーションにリクエストを送ることができる。
    """
    return app.test_client()