# app/__init__.py
import os
from flask import Flask, render_template, session, current_app
from pykakasi import kakasi
import datetime
import psycopg2
from collections import defaultdict

# データベース接続関数とデータ定義をインポート
from .db import get_db_connection
from .data_definitions import ERA_DISPLAY_ORDER, ERA_DISPLAY_NAMES

_kks_hira_converter = kakasi()
_kks_hira_converter.setMode("J", "H")
_kks_hira_converter.setMode("K", "H")
_kks_hira_converter.setMode("s", False)
_kks_hira_converter.setMode("C", False)

_kks_kata_converter = kakasi()
_kks_kata_converter.setMode("J", "K")
_kks_kata_converter.setMode("H", "K")
_kks_kata_converter.setMode("s", False)
_kks_kata_converter.setMode("C", False)


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev_secret_key_should_be_changed_in_production'),
        USER_FILE='users.json',
        UPLOAD_FOLDER=os.path.join(app.root_path, 'uploads')
    )

    if test_config is None:
        app.config.from_pyfile('config.py', silent=True)
    else:
        app.config.from_mapping(test_config)

    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        try:
            os.makedirs(app.config['UPLOAD_FOLDER'])
            print(f"INFO: Created upload folder at {app.config['UPLOAD_FOLDER']}")
        except OSError as e:
            app.logger.error(f"Error creating upload folder {app.config['UPLOAD_FOLDER']}: {e}")

    app.kks_hira_converter = _kks_hira_converter
    app.kks_kata_converter = _kks_kata_converter

    from . import auth
    app.register_blueprint(auth.bp)

    from . import main
    app.register_blueprint(main.bp)
    app.add_url_rule('/', endpoint='index')

    from . import admin
    app.register_blueprint(admin.bp)

    @app.context_processor
    def inject_global_vars():
        """
        テンプレート全体で利用可能な変数を注入します。
        サイドバー用のデータ取得もここで行います。
        """
        conn = None
        grouped_by_era = defaultdict(list)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT name, display_name, era, release_date FROM products 
                WHERE show_in_sidebar = TRUE 
                ORDER BY era DESC NULLS LAST, release_date DESC, name ASC
                """
            )
            sidebar_products = cur.fetchall()
            for product in sidebar_products:
                era = product['era']
                if era:
                    grouped_by_era[era].append(product)
        except (Exception, psycopg2.Error) as e:
            current_app.logger.error(f"Sidebar data fetching failed: {e}")
        finally:
            if conn:
                if 'cur' in locals() and not cur.closed:
                    cur.close()
                conn.close()

        return {
            'logged_in': session.get('logged_in'),
            'username': session.get('username'),
            'now': datetime.datetime.now(datetime.timezone.utc),
            'sidebar_data': grouped_by_era,
            'sidebar_era_order': ERA_DISPLAY_ORDER,
            'sidebar_era_names': ERA_DISPLAY_NAMES
        }

    app.logger.info("Flask app created successfully.")
    return app