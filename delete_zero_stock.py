# delete_zero_stock.py
import os
import psycopg2
import psycopg2.extras
import sys
from dotenv import load_dotenv

def get_db_connection_local():
    """
    ローカル環境変数ファイル (.env) からデータベースURLを読み込み接続を確立します。
    """
    # プロジェクトルートの .env ファイルを読み込む
    # このスクリプトをプロジェクトルートに置いて実行することを想定
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
        print(f"INFO: Loaded environment variables from {dotenv_path}")
    else:
        # .flaskenv も試す (Flask標準)
        flaskenv_path = os.path.join(os.path.dirname(__file__), '.flaskenv')
        if os.path.exists(flaskenv_path):
            load_dotenv(flaskenv_path)
            print(f"INFO: Loaded environment variables from {flaskenv_path}")
        else:
            print("WARNING: .env or .flaskenv file not found in the script's directory. DATABASE_URL must be set in the system environment.")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("CRITICAL: DATABASE_URL environment variable not set. Cannot connect to the database.", file=sys.stderr)
        sys.exit(1) # エラーで終了

    try:
        conn = psycopg2.connect(db_url) # DictCursorはここでは不要な場合が多い
        print("INFO: Successfully connected to the database.")
        return conn
    except psycopg2.Error as e:
        print(f"CRITICAL: Database connection failed.", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
        sys.exit(1) # エラーで終了

def delete_zero_stock_items():
    """
    データベース内の在庫数が0のアイテムを全て削除します。
    削除前に確認を求め、削除件数を報告します。
    """
    conn = None
    deleted_count = 0
    try:
        conn = get_db_connection_local()
        cur = conn.cursor()

        # まず、在庫数0のアイテムが何件あるか確認
        cur.execute("SELECT COUNT(*) FROM items WHERE stock = 0")
        count_result = cur.fetchone()
        zero_stock_count = count_result[0] if count_result else 0

        if zero_stock_count == 0:
            print("INFO: 在庫数0のアイテムは見つかりませんでした。削除処理は行いません。")
            return

        print(f"INFO: 現在、在庫数0のアイテムが {zero_stock_count} 件見つかりました。")
        
        # ユーザーに最終確認
        confirm = input(f"本当にこれらのアイテム {zero_stock_count} 件を全て削除しますか？ この操作は元に戻せません。 (yes/no): ").strip().lower()

        if confirm == 'yes':
            print("INFO: 削除処理を開始します...")
            cur.execute("DELETE FROM items WHERE stock = 0")
            deleted_count = cur.rowcount # 削除された行数を取得
            conn.commit() # 変更をデータベースに永続化
            print(f"SUCCESS: {deleted_count} 件の在庫数0のアイテムを削除しました。")
        else:
            print("INFO: 削除処理はキャンセルされました。")

    except (Exception, psycopg2.Error) as error:
        if conn:
            conn.rollback() # エラーが発生した場合はロールバック
        print(f"ERROR: 在庫数0のアイテム削除中にエラーが発生しました: {error}", file=sys.stderr)
        traceback.print_exc()
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()
            print("INFO: Database connection closed.")

if __name__ == '__main__':
    print("--- 在庫数0のカード一括削除スクリプト ---")
    print("警告: このスクリプトはデータベースの内容を直接変更します。")
    print("実行前に必ずデータベースのバックアップを取得してください。")
    
    # 環境変数ファイルがスクリプトと同じディレクトリにあることを確認
    print(f"スクリプトの場所: {os.path.abspath(__file__)}")
    print(f"想定される.envファイルの場所: {os.path.abspath(os.path.join(os.path.dirname(__file__), '.env'))}")
    
    # ユーザーに実行意思を再確認
    proceed = input("スクリプトを実行しますか？ (yes/no): ").strip().lower()
    if proceed == 'yes':
        delete_zero_stock_items()
    else:
        print("スクリプトの実行を中止しました。")
    print("--- スクリプト終了 ---")
