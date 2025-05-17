# wsgi.py
from app import create_app
import os

# 環境変数から設定ファイル名を読み込む (オプション)
# config_name = os.getenv('FLASK_CONFIG') or 'default'
# app = create_app(config_name)

app = create_app()

if __name__ == "__main__":
    # このファイルが直接実行された場合 (例: python wsgi.py)、
    # Flaskの開発サーバーを起動します。
    # 本番環境ではGunicornなどのWSGIサーバーがこの `app` オブジェクトを使用します。
    app.run(debug=True) # debug=True は開発時のみ。本番ではFalseまたは削除
