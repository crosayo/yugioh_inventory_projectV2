# normalize_items.py
import os
import sys
from dotenv import load_dotenv
import psycopg2

# 'app'ディレクトリ内のモジュールをインポート可能にする
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))
from utils import normalize_for_search

def load_environment():
    """
    .envまたは.flaskenvファイルから環境変数を読み込む。
    """
    # .env ファイルを先に試す
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path)
        print("INFO: .env ファイルから環境変数を読み込みました。")
        return

    # .flaskenv ファイルを次に試す (Flaskの標準)
    flaskenv_path = os.path.join(os.path.dirname(__file__), '.flaskenv')
    if os.path.exists(flaskenv_path):
        load_dotenv(dotenv_path=flaskenv_path)
        print("INFO: .flaskenv ファイルから環境変数を読み込みました。")
        return
    
    print("WARNING: .env または .flaskenv が見つかりませんでした。システムの環境変数を参照します。")


def backfill_normalized_columns():
    """
    itemsテーブルの既存レコードに対して、
    正規化されたnameとcard_idを新しい列に書き込む。
    """
    load_environment() # =====> ここで環境変数を読み込む
    conn = None
    try:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            print("エラー: 環境変数 DATABASE_URL が設定されていません。", file=sys.stderr)
            return

        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        print("正規化が必要なアイテムを取得しています...")
        # まだ正規化されていないレコードのみを対象にする
        cur.execute("SELECT id, name, card_id FROM items WHERE name_normalized IS NULL OR card_id_normalized IS NULL")
        items_to_update = cur.fetchall()

        if not items_to_update:
            print("全てのアイテムは既に正規化済みのようです。処理をスキップしました。")
            return

        print(f"{len(items_to_update)} 件のアイテムを更新します。")
        
        updated_count = 0
        for item in items_to_update:
            item_id, name, card_id = item
            
            name_norm = normalize_for_search(name)
            card_id_norm = normalize_for_search(card_id)
            
            cur.execute(
                "UPDATE items SET name_normalized = %s, card_id_normalized = %s WHERE id = %s",
                (name_norm, card_id_norm, item_id)
            )
            updated_count += 1
            if updated_count % 500 == 0:
                print(f"  ... {updated_count} 件処理完了 ...")

        conn.commit()
        print(f"\n成功: {updated_count} 件のアイテムを正規化しました。")

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"エラーが発生しました: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == '__main__':
    print("--- 既存アイテムの検索用データ正規化スクリプト ---")
    print("警告: このスクリプトはデータベースの 'items' テーブルを更新します。")
    proceed = input("処理を続行しますか？ (yes/no): ").strip().lower()
    if proceed == 'yes':
        backfill_normalized_columns()
    else:
        print("処理を中止しました。")
    print("--- スクリプト終了 ---")