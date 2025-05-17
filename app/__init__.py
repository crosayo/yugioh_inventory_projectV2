# app/__init__.py
import os
from flask import Flask, render_template, session
from pykakasi import kakasi
import datetime # For context_processor

# グローバル変数としてpykakasiのインスタンスを保持（アプリケーションコンテキスト外で初期化）
# これらは create_app 内で app オブジェクトにアタッチすることも検討できます。
# 今回は元の app.py のグローバルスコープでの初期化を踏襲しつつ、
# create_app 内で app.kks_hira_converter などとして設定します。
_kks_hira_converter = kakasi()
_kks_hira_converter.setMode("J", "H") #
_kks_hira_converter.setMode("K", "H") #
_kks_hira_converter.setMode("s", False) # Don't split
_kks_hira_converter.setMode("C", False) # No Romaji conversion

_kks_kata_converter = kakasi()
_kks_kata_converter.setMode("J", "K") #
_kks_kata_converter.setMode("H", "K") #
_kks_kata_converter.setMode("s", False) # Don't split
_kks_kata_converter.setMode("C", False) # No Romaji conversion


def create_app(test_config=None):
    """
    Flaskアプリケーションインスタンスを作成し、設定を読み込み、Blueprintを登録します。
    アプリケーションファクトリパターンを使用します。
    """
    app = Flask(__name__, instance_relative_config=True)

    # --- アプリケーション設定 ---
    # SECRET_KEY: セッション管理などに使われる秘密鍵。本番環境では必ず推測困難な値を設定。
    # 環境変数から読み込むか、インスタンスフォルダのconfig.pyから読み込むのが一般的。
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev_secret_key_should_be_changed_in_production'),
        # ↓↓↓ この行を修正します ↓↓↓
        USER_FILE='users.json', # プロジェクトルートに users.json を配置
        # ↑↑↑ この行を修正します ↑↑↑
        UPLOAD_FOLDER=os.path.join(app.root_path, 'uploads')
    )

    if test_config is None:
        # インスタンスフォルダのconfig.pyが存在すれば、それで設定を上書き
        # (例: DATABASE_URL や本番用SECRET_KEYなどを記述)
        app.config.from_pyfile('config.py', silent=True)
    else:
        # テスト用の設定を読み込む
        app.config.from_mapping(test_config)

    # --- ディレクトリ作成 ---
    # インスタンスフォルダの存在を確認・作成
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass # instance_path がルートディレクトリと同じ場合など

    # アップロードフォルダの存在を確認・作成
    # UPLOAD_FOLDER は app/uploads を指すようにする
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        try:
            os.makedirs(app.config['UPLOAD_FOLDER'])
            print(f"INFO: Created upload folder at {app.config['UPLOAD_FOLDER']}")
        except OSError as e:
            app.logger.error(f"Error creating upload folder {app.config['UPLOAD_FOLDER']}: {e}")


    # --- pykakasiコンバーターをappオブジェクトに設定 ---
    # これにより、Blueprint内などから current_app.kks_hira_converter のようにアクセス可能
    app.kks_hira_converter = _kks_hira_converter
    app.kks_kata_converter = _kks_kata_converter

    # --- データベース初期化関数の登録 (オプション) ---
    # from . import db
    # db.init_app(app) # もしdbモジュールにinit_app関数などがあれば

    # --- Blueprintの登録 ---
    from . import auth
    app.register_blueprint(auth.bp)

    from . import main
    app.register_blueprint(main.bp)
    app.add_url_rule('/', endpoint='index') # メインBlueprintのindexをルートURLにマッピング

    from . import admin
    app.register_blueprint(admin.bp)


    # --- コンテキストプロセッサの登録 ---
    @app.context_processor
    def inject_global_vars():
        """
        テンプレート全体で利用可能な変数を注入します。
        """
        return {
            'logged_in': session.get('logged_in'),
            'username': session.get('username'),
            'now': datetime.datetime.now(datetime.timezone.utc) # タイムゾーン対応の現在時刻
        }

    # --- カスタムエラーページの登録 (例) ---
    # @app.errorhandler(404)
    # def page_not_found(e):
    #     return render_template('errors/404.html'), 404

    # @app.errorhandler(500)
    # def internal_server_error(e):
    #     return render_template('errors/500.html'), 500

    # --- リクエストフック (例: データベース接続の管理) ---
    # @app.before_request
    # def before_request_func():
    #     # 例: gオブジェクトにDB接続を格納
    #     # from .db import get_db_connection
    #     # g.db = get_db_connection()
    #     pass

    # @app.teardown_appcontext
    # def teardown_db(exception=None):
    #     # 例: gオブジェクトからDB接続を取得してクローズ
    #     # db = g.pop('db', None)
    #     # if db is not None:
    #     #     db.close()
    #     pass
    
    app.logger.info("Flask app created successfully.")
    return app
