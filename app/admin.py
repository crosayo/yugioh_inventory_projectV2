# app/admin.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, current_app, session
)
import psycopg2
import psycopg2.extras
import traceback
import csv
import io
import os
import re # 正規表現モジュールをインポート
from werkzeug.utils import secure_filename

from app.db import get_db_connection
from app.auth import login_required
from app.data_definitions import DEFINED_RARITIES, RARITY_CONVERSION_MAP

ALLOWED_EXTENSIONS = {'csv'}
bp = Blueprint('admin', __name__, url_prefix='/admin')

# --- ヘッダーマッピングの定義 ---
CSV_HEADER_MAP = {
    'name': ['name', '名前', '名称'],
    'card_id': ['card_id', 'カードid', 'カードID', '型番'],
    'rare': ['rare', 'レアリティ', 'レア度'],
    'stock': ['stock', '在庫', '在庫数'],
    'category': ['category', 'カテゴリ', '分類']
}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route('/unify_rarities', methods=('GET', 'POST'))
@login_required
def admin_unify_rarities():
    if request.method == 'POST':
        conn = None
        updated_count_total = 0
        current_app.logger.info(f"Rarity unification process started by user '{session.get('username', 'unknown_user')}'.")
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            for old_rare, new_rare in RARITY_CONVERSION_MAP.items():
                cur.execute("""
                    UPDATE items SET rare = %s
                    WHERE LOWER(rare) = LOWER(%s) AND rare != %s
                """, (new_rare, old_rare, new_rare))
                if cur.rowcount > 0:
                    current_app.logger.debug(f"Unified '{old_rare}' to '{new_rare}': {cur.rowcount} items affected.")
                updated_count_total += cur.rowcount
            conn.commit()
            if updated_count_total > 0:
                flash(f'{updated_count_total}件のレアリティ表記をデータベース内で更新/確認しました。', 'success')
                current_app.logger.info(f"{updated_count_total} rarities unified successfully.")
            else:
                flash('レアリティ表記の更新対象はありませんでした。または、既に統一済みか、変換ルールに該当しませんでした。', 'info')
                current_app.logger.info("No rarities needed unification.")
        except (psycopg2.Error, Exception) as e:
            if conn: conn.rollback()
            error_message = f"レアリティ統一中にデータベースエラーが発生しました: {e}"
            current_app.logger.error(f"Error during rarity unification: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn:
                if 'cur' in locals() and cur and not cur.closed: cur.close()
                conn.close()
        return redirect(url_for('admin.admin_unify_rarities'))

    conn_get = None
    current_db_rarities = []
    try:
        conn_get = get_db_connection()
        cur_get = conn_get.cursor()
        cur_get.execute("SELECT DISTINCT rare FROM items WHERE rare IS NOT NULL AND rare != '' ORDER BY rare")
        current_db_rarities_tuples = cur_get.fetchall()
        current_db_rarities = [row['rare'] for row in current_db_rarities_tuples]
    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Error fetching current DB rarities for unification page: {e}\n{traceback.format_exc()}")
        flash("現在のレアリティ情報の取得中にエラーが発生しました。", "danger")
    finally:
        if conn_get:
            if 'cur_get' in locals() and cur_get and not cur_get.closed: cur_get.close()
            conn_get.close()
    return render_template('admin/admin_unify_rarities.html',
                           rarity_map=RARITY_CONVERSION_MAP,
                           defined_rarities=DEFINED_RARITIES,
                           current_db_rarities=current_db_rarities)

def get_items_by_category_for_batch(category_keyword=None, page=1, per_page=20, sort_by="name", sort_order="asc"):
    if not category_keyword: return [], 0
    conn = None; items = []; total_items = 0
    try:
        conn = get_db_connection(); cur = conn.cursor()
        base_query = "SELECT id, name, card_id, rare, stock, category FROM items WHERE LOWER(category) LIKE %s"
        count_query = "SELECT COUNT(*) FROM items WHERE LOWER(category) LIKE %s"
        search_term = f"%{category_keyword.lower()}%"
        cur.execute(count_query, (search_term,))
        total_items_result = cur.fetchone()
        total_items = total_items_result['count'] if total_items_result else 0
        valid_sort_keys_batch = ["name", "card_id", "rare", "stock", "id", "category"]
        if sort_by not in valid_sort_keys_batch: sort_by = "name"
        if sort_order.lower() not in ["asc", "desc"]: sort_order = "asc"
        offset = (page - 1) * per_page
        query_with_order_limit = f"{base_query} ORDER BY {sort_by} {sort_order.upper()} LIMIT %s OFFSET %s"
        cur.execute(query_with_order_limit, (search_term, per_page, offset))
        items = cur.fetchall()
    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Error in get_items_by_category_for_batch (category: '{category_keyword}'): {e}\n{traceback.format_exc()}")
        flash("カテゴリ別商品取得中にデータベースエラーが発生しました。", "danger")
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed: cur.close()
            conn.close()
    return items, total_items

@bp.route('/batch_register', methods=('GET', 'POST'))
@login_required
def admin_batch_register():
    if request.method == 'POST':
        conn = None; updated_count = 0; error_messages_for_flash = []
        category_keyword_hidden = request.form.get('category_keyword_hidden', '').strip()
        current_page_hidden = request.form.get('current_page', '1')
        current_app.logger.info(f"Batch stock update started by user '{session.get('username', 'unknown_user')}' for category '{category_keyword_hidden}'.")
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                for key, value in request.form.items():
                    if key.startswith('stock_item_'):
                        try:
                            item_id_str = key.split('_')[-1]
                            if not item_id_str.isdigit():
                                current_app.logger.warning(f"Batch update: Invalid item_id format in key '{key}'. Skipping.")
                                error_messages_for_flash.append(f"キー '{key}' から有効な商品IDを取得できませんでした。")
                                continue
                            item_id = int(item_id_str)
                            stock_count_str = value.strip()
                            stock_count = 0
                            if not stock_count_str: stock_count = 0
                            elif not stock_count_str.isdigit():
                                current_app.logger.warning(f"Batch update: Invalid stock value '{stock_count_str}' for item_id {item_id}. Using 0.")
                                error_messages_for_flash.append(f"ID {item_id} の在庫数に不正な値「{stock_count_str}」が入力されました。0として扱います。")
                            else: stock_count = int(stock_count_str)
                            if stock_count < 0:
                                stock_count = 0
                                error_messages_for_flash.append(f"ID {item_id} の在庫数に負の値が入力されました。0として扱います。")
                            cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
                            current_item_db_stock = cur.fetchone()
                            if current_item_db_stock:
                                if current_item_db_stock['stock'] != stock_count:
                                    cur.execute("UPDATE items SET stock = %s WHERE id = %s", (stock_count, item_id))
                                    updated_count += 1
                                    current_app.logger.debug(f"Batch update: Item ID {item_id} stock changed from {current_item_db_stock['stock']} to {stock_count}")
                            else:
                                current_app.logger.warning(f"Batch update: Item ID {item_id} not found in database during update attempt.")
                                error_messages_for_flash.append(f"ID {item_id} の商品がデータベースに見つかりませんでした（更新スキップ）。")
                        except ValueError as ve:
                            current_app.logger.warning(f"Batch update: ValueError for key '{key}', value '{value}': {ve}. Skipping this item.")
                            error_messages_for_flash.append(f"処理中に値のエラーが発生しました (ID関連キー: {key}, 値: {value})。この項目はスキップされました。")
                        except Exception as e_inner:
                            current_app.logger.error(f"Batch update: Unexpected error for item_id derived from '{key}': {e_inner}\n{traceback.format_exc()}")
                            error_messages_for_flash.append(f"ID {key.split('_')[-1]} の更新中に予期せぬエラーが発生しました。この項目はスキップされました。")
                if updated_count > 0:
                    conn.commit()
                    flash(f"{updated_count}件のカードの在庫を一括更新しました。", "success")
                    current_app.logger.info(f"Batch stock update committed: {updated_count} items updated.")
                elif not error_messages_for_flash:
                    flash("在庫が変更されたカードはありませんでした。", "info")
                    current_app.logger.info("Batch stock update: No items had their stock changed.")
                for err_msg in error_messages_for_flash: flash(err_msg, 'warning')
        except (psycopg2.Error, Exception) as e_db:
            if conn: conn.rollback()
            error_message = f"一括在庫更新中にデータベースエラーが発生しました: {e_db}"
            current_app.logger.error(f"Error during batch stock update (DB transaction): {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn and not conn.closed: conn.close()
        return redirect(url_for('admin.admin_batch_register', category_keyword=category_keyword_hidden, page=current_page_hidden))

    category_keyword = request.args.get('category_keyword', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page_batch = 20
    items_for_batch, total_items_batch = [], 0
    if category_keyword:
        items_for_batch, total_items_batch = get_items_by_category_for_batch(category_keyword, page, per_page_batch)
        if not items_for_batch and page == 1 and total_items_batch == 0:
            flash(f"カテゴリ「{category_keyword}」に該当するカードは見つかりませんでした。", "info")
    total_pages_batch = (total_items_batch + per_page_batch - 1) // per_page_batch if per_page_batch > 0 else 1
    if page > total_pages_batch and total_pages_batch > 0:
        page = total_pages_batch
        items_for_batch, _ = get_items_by_category_for_batch(category_keyword, page, per_page_batch)
    return render_template('admin/admin_batch_register.html',
                           items=items_for_batch, category_keyword=category_keyword, page=page,
                           per_page=per_page_batch, total_pages=total_pages_batch, total_items=total_items_batch)

@bp.route('/import_csv', methods=('GET', 'POST'))
@login_required
def admin_import_csv():
    if request.method == 'POST':
        if 'csv_files' not in request.files:
            flash('ファイルが選択されていません。', 'warning')
            return redirect(request.url)

        files = request.files.getlist('csv_files')
        if not files or all(f.filename == '' for f in files):
            flash('ファイルが選択されていません。', 'warning')
            return redirect(request.url)

        total_files_processed_count = 0
        overall_summary_stats = {'added': 0, 'updated_info': 0, 'skipped_no_change': 0, 'skipped_error_row': 0, 'rows_processed_total':0}
        error_file_messages = {}

        current_app.logger.info(f"CSV import process started by user '{session.get('username', 'unknown_user')}'. Uploaded {len(files)} file(s).")
        conn_outer = None
        made_committable_changes_in_any_file = False
        try:
            conn_outer = get_db_connection()
            for file_idx, file_obj in enumerate(files):
                if file_obj and allowed_file(file_obj.filename):
                    original_filename_for_display = file_obj.filename
                    base_fn, _ = os.path.splitext(original_filename_for_display)
                    safe_base_fn = re.sub(r'[^a-zA-Z0-9_]', '_', base_fn)
                    savepoint_name = f"sp_file_{file_idx}_{secure_filename(safe_base_fn)[:20]}"
                    category_name_from_filename = os.path.splitext(original_filename_for_display)[0] 

                    total_files_processed_count += 1
                    file_processing_summary = {'added': 0, 'updated_info': 0, 'skipped_no_change': 0, 'skipped_error_row': 0, 'rows_processed_in_file':0}
                    current_csv_row_num_for_log = 0
                    file_had_db_error_preventing_commit = False
                    file_had_committable_change_this_file = False
                    num_total_rows_in_file = 0 # 初期化

                    current_app.logger.info(f"--- Processing CSV file #{file_idx + 1}/{len(files)}: '{original_filename_for_display}' (Savepoint: {savepoint_name}) ---")
                    current_app.logger.info(f"Derived category name for this file (fallback): '{category_name_from_filename}'")

                    try:
                        with conn_outer.cursor() as cur:
                            try:
                                cur.execute(f"SAVEPOINT {savepoint_name}")
                                current_app.logger.debug(f"Successfully created savepoint {savepoint_name}")
                            except psycopg2.Error as e_sp_create:
                                current_app.logger.error(f"Failed to create savepoint {savepoint_name} for file '{original_filename_for_display}': {e_sp_create}")
                                if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                error_file_messages[original_filename_for_display].append(f"セーブポイント作成失敗: {e_sp_create}。このファイルはスキップされました。")
                                overall_summary_stats['skipped_error_row'] += 1
                                continue

                            try:
                                # --- ▼▼▼ 総行数を事前に取得 ▼▼▼ ---
                                # file_obj.stream はTextIOWrapperでラップされている可能性があるため、
                                # バイトストリーム (file_obj.stream.buffer) を使うか、
                                # TextIOWrapperを再作成する
                                # ここでは、再度TextIOWrapperを作成するアプローチを取る
                                file_content_for_count = file_obj.read() # 全て読み込む
                                file_obj.seek(0) # ストリームを先頭に戻す
                                
                                temp_file_like_object_for_count = io.StringIO(file_content_for_count.decode('utf-8-sig'))
                                temp_reader_for_count = csv.reader(temp_file_like_object_for_count)
                                try:
                                    header_for_count = next(temp_reader_for_count) 
                                    num_total_rows_in_file = sum(1 for row in temp_reader_for_count)
                                    current_app.logger.info(f"File '{original_filename_for_display}' has approx. {num_total_rows_in_file} data rows.")
                                except StopIteration: 
                                    num_total_rows_in_file = 0
                                    current_app.logger.info(f"File '{original_filename_for_display}' appears to be empty or header-only.")
                                # file_streamの作成はDictReaderの前で行う
                                file_stream = io.StringIO(file_content_for_count.decode('utf-8-sig')) # デコードしたコンテンツでStringIOを再作成
                                # --- ▲▲▲ 総行数を事前に取得 ▲▲▲ ---
                                
                                csv_reader = csv.DictReader(file_stream)
                                csv_headers_original = csv_reader.fieldnames or []

                                normalized_header_map = {} 
                                csv_headers_lower_stripped = [h.strip().lower() for h in csv_headers_original if h]

                                for internal_key, possible_headers in CSV_HEADER_MAP.items():
                                    found_header = None
                                    for p_header in possible_headers:
                                        if p_header.lower() in csv_headers_lower_stripped:
                                            original_idx = csv_headers_lower_stripped.index(p_header.lower())
                                            found_header = csv_headers_original[original_idx]
                                            break
                                    if found_header:
                                        normalized_header_map[internal_key] = found_header
                                
                                required_internal_keys = ['name', 'rare'] 
                                missing_headers = [
                                    key for key in required_internal_keys if key not in normalized_header_map
                                ]

                                if missing_headers:
                                    missing_headers_display = []
                                    for key in missing_headers:
                                        expected_options = CSV_HEADER_MAP.get(key, [key])
                                        missing_headers_display.append(f"'{key}' (例: {', '.join(expected_options)})")
                                    err_msg = (f"ヘッダー不正。必須列 ({', '.join(missing_headers_display)}) "
                                               f"が見つかりません。検出されたヘッダー: {csv_headers_original}")
                                    raise ValueError(err_msg)

                                def get_val_from_row(row_dict, internal_key, default_val=''):
                                    original_header_name = normalized_header_map.get(internal_key)
                                    if original_header_name:
                                        val = row_dict.get(original_header_name, default_val)
                                        return val.strip() if isinstance(val, str) else val
                                    return default_val
                                
                                # --- ▼▼▼ 進捗表示のための設定 ▼▼▼ ---
                                report_interval = 1000 
                                if num_total_rows_in_file > 0 and num_total_rows_in_file < report_interval * 5: 
                                    report_interval = max(100, num_total_rows_in_file // 10) 
                                if report_interval == 0 and num_total_rows_in_file > 0 : # 総行数が非常に少ない場合の対策
                                     report_interval = 1
                                # --- ▲▲▲ 進捗表示のための設定 ▲▲▲ ---

                                for row_idx_in_file, row_data_dict in enumerate(csv_reader):
                                    current_csv_row_num_for_log = row_idx_in_file + 1 # データ行のインデックスは0からなので+1
                                    file_processing_summary['rows_processed_in_file'] += 1
                                    
                                    # --- ▼▼▼ 定期的な進捗ログ出力 ▼▼▼ ---
                                    if num_total_rows_in_file > 0 and report_interval > 0 and \
                                       (current_csv_row_num_for_log % report_interval == 0 or current_csv_row_num_for_log == num_total_rows_in_file):
                                        progress_percent = (current_csv_row_num_for_log / num_total_rows_in_file * 100)
                                        current_app.logger.info(
                                            f"  File '{original_filename_for_display}': Processing row {current_csv_row_num_for_log}/{num_total_rows_in_file} "
                                            f"({progress_percent:.2f}%)"
                                        )
                                    elif num_total_rows_in_file == 0 and (row_idx_in_file + 1) % 1000 == 0 : # 総行数不明だが一定行ごと
                                        current_app.logger.info(f"  File '{original_filename_for_display}': Processing row {row_idx_in_file + 1}...")
                                    # --- ▲▲▲ 定期的な進捗ログ出力 ▲▲▲ ---
                                    
                                    card_name = get_val_from_row(row_data_dict, 'name')
                                    card_id_csv = get_val_from_row(row_data_dict, 'card_id')
                                    raw_rarity = get_val_from_row(row_data_dict, 'rare')
                                    stock_csv_str = get_val_from_row(row_data_dict, 'stock')
                                    category_from_csv_row = get_val_from_row(row_data_dict, 'category')
                                    
                                    try:
                                        stock_csv = int(stock_csv_str) if stock_csv_str and stock_csv_str.strip() else 0
                                    except (ValueError, TypeError):
                                        current_app.logger.warning(
                                            f"File '{original_filename_for_display}' Row {current_csv_row_num_for_log}: "
                                            f"Invalid stock value '{stock_csv_str}' (type: {type(stock_csv_str).__name__}). Defaulting to 0."
                                        )
                                        stock_csv = 0

                                    if not card_name or not raw_rarity:
                                        msg = f"行 {current_csv_row_num_for_log}: 名前またはレアリティが空です。スキップします。"
                                        current_app.logger.warning(f"File '{original_filename_for_display}' {msg} Data: {row_data_dict}")
                                        if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                        error_file_messages[original_filename_for_display].append(msg)
                                        file_processing_summary['skipped_error_row'] +=1
                                        continue

                                    converted_rarity = RARITY_CONVERSION_MAP.get(raw_rarity.lower(), raw_rarity)
                                    final_card_id_for_db = card_id_csv if card_id_csv else None
                                    
                                    final_category = category_from_csv_row if category_from_csv_row else category_name_from_filename
                                    if not final_category: 
                                        final_category = "不明カテゴリ" 
                                        current_app.logger.warning(f"File '{original_filename_for_display}' Row {current_csv_row_num_for_log}: Category could not be determined. Defaulting to '{final_category}'.")

                                    existing_card_data = None
                                    try:
                                        if final_card_id_for_db is not None:
                                            cur.execute("SELECT id, name, rare, stock, category FROM items WHERE card_id = %s AND rare = %s", (str(final_card_id_for_db), converted_rarity))
                                            existing_card_data = cur.fetchone()

                                        if existing_card_data:
                                            db_name = existing_card_data['name']
                                            db_category = existing_card_data['category']
                                            csv_name_val = card_name
                                            name_changed = (db_name != csv_name_val)
                                            category_changed = (str(db_category or '').strip().lower() != str(final_category or '').strip().lower())
                                            needs_db_update = name_changed or category_changed

                                            if needs_db_update:
                                                cur.execute("UPDATE items SET name = %s, category = %s WHERE id = %s", (csv_name_val, final_category, existing_card_data['id']))
                                                if cur.rowcount > 0:
                                                    file_processing_summary['updated_info'] += 1
                                                    file_had_committable_change_this_file = True
                                            else:
                                                file_processing_summary['skipped_no_change'] +=1
                                        else:
                                            cur.execute("INSERT INTO items (name, card_id, rare, stock, category) VALUES (%s, %s, %s, %s, %s)",
                                                        (card_name, final_card_id_for_db, converted_rarity, stock_csv, final_category))
                                            file_processing_summary['added'] += 1
                                            file_had_committable_change_this_file = True

                                    except psycopg2.Error as e_db_row:
                                        current_app.logger.error(
                                            f"File '{original_filename_for_display}' Row {current_csv_row_num_for_log}: "
                                            f"DB Error ({type(e_db_row).__name__}): {str(e_db_row).strip()}. "
                                            f"Card: '{card_name}', ID: '{final_card_id_for_db}', Rare: '{converted_rarity}', Stock_CSV_Attempted: '{stock_csv_str}' (became {stock_csv})."
                                        )
                                        pgcode = getattr(e_db_row, 'pgcode', None)
                                        current_app.logger.error(f"  PostgreSQL error code (pgcode): {pgcode}")
                                        if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                        error_file_messages[original_filename_for_display].append(f"行 {current_csv_row_num_for_log}: DBエラー ({type(e_db_row).__name__})。このファイルの処理を中断。")
                                        file_had_db_error_preventing_commit = True
                                        break 

                            except (UnicodeDecodeError, csv.Error, ValueError) as e_file_read:
                                current_app.logger.error(f"Critical error processing file '{original_filename_for_display}' (before or during row processing): {e_file_read}\n{traceback.format_exc()}")
                                if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                error_file_messages[original_filename_for_display].append(f"ファイル読み込み/解析エラー: {e_file_read}")
                                file_had_db_error_preventing_commit = True

                            if file_had_db_error_preventing_commit:
                                cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                                current_app.logger.warning(f"Rolled back to savepoint {savepoint_name} for file '{original_filename_for_display}' due to errors.")
                                file_processing_summary['added'] = 0
                                file_processing_summary['updated_info'] = 0
                                # エラー発生時点で処理した行数までをエラーカウントに含めるか、あるいは未処理行をエラーとしてカウント
                                # ここでは、エラー発生行以降は処理されないので、そのファイル内の処理済み行数でエラーが起きたと見なす
                                # 正確には、breakまでに処理した行から成功分を引いたものがエラー行だが、ここでは簡略化
                                if file_processing_summary['rows_processed_in_file'] > 0: # 少なくとも1行は処理しようとした場合
                                     file_processing_summary['skipped_error_row'] = file_processing_summary['rows_processed_in_file'] - (file_processing_summary['added'] + file_processing_summary['updated_info'] + file_processing_summary['skipped_no_change'])
                                else: # ヘッダー読み込みなどでエラーになった場合など
                                    file_processing_summary['skipped_error_row'] = 1 # ファイル自体を1エラーとしてカウント

                            elif file_had_committable_change_this_file:
                                cur.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                                made_committable_changes_in_any_file = True
                                current_app.logger.info(f"Released savepoint {savepoint_name} for file '{original_filename_for_display}' with changes.")
                            else:
                                cur.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                                current_app.logger.info(f"Released savepoint {savepoint_name} for file '{original_filename_for_display}', no changes made.")

                    except psycopg2.Error as e_cursor_or_sp_level:
                        current_app.logger.error(f"Error at cursor or savepoint level for file '{original_filename_for_display}': {e_cursor_or_sp_level}\n{traceback.format_exc()}")
                        if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                        error_file_messages[original_filename_for_display].append(f"ファイル処理の準備/終了処理中にDBエラー: {e_cursor_or_sp_level}。このファイルはスキップされました。")
                        overall_summary_stats['skipped_error_row'] += file_processing_summary.get('rows_processed_in_file', 1)
                    finally:
                        pass

                    overall_summary_stats['added'] += file_processing_summary['added']
                    overall_summary_stats['updated_info'] += file_processing_summary['updated_info']
                    overall_summary_stats['skipped_no_change'] += file_processing_summary['skipped_no_change']
                    overall_summary_stats['skipped_error_row'] += file_processing_summary['skipped_error_row']
                    overall_summary_stats['rows_processed_total'] += file_processing_summary['rows_processed_in_file']

                elif file_obj and not allowed_file(file_obj.filename):
                    err_msg = f"拡張子不正 ({os.path.splitext(file_obj.filename)[1]})。CSVファイルのみ許可。"
                    key_for_error_msg = file_obj.filename # この時点では original_filename_for_display は未設定
                    if key_for_error_msg not in error_file_messages: error_file_messages[key_for_error_msg] = []
                    error_file_messages[key_for_error_msg].append(err_msg)
                    overall_summary_stats['skipped_error_row'] += 1


            if made_committable_changes_in_any_file:
                conn_outer.commit()
                current_app.logger.info("Main transaction committed.")
            else:
                conn_outer.rollback()
                current_app.logger.info("No committable changes in any file or all changes rolled back. Main transaction rolled back.")

            summary_parts = [f"CSVインポート処理完了。処理試行ファイル数: {total_files_processed_count}。"]
            summary_parts.append(f"総処理行数: {overall_summary_stats['rows_processed_total']}。")
            summary_parts.append(f"新規追加: {overall_summary_stats['added']}件。")
            summary_parts.append(f"既存情報更新: {overall_summary_stats['updated_info']}件。")
            summary_parts.append(f"変更なしスキップ: {overall_summary_stats['skipped_no_change']}件。")
            summary_parts.append(f"エラースキップ行/ファイル問題: {overall_summary_stats['skipped_error_row']}件。")

            flash_cat = 'success'
            if error_file_messages or overall_summary_stats['skipped_error_row'] > 0 :
                flash_cat = 'warning'
            if not made_committable_changes_in_any_file and \
               overall_summary_stats['added'] == 0 and \
               overall_summary_stats['updated_info'] == 0 and \
               overall_summary_stats['skipped_error_row'] == 0 :
                 flash_cat = 'info'
                 if overall_summary_stats['skipped_no_change'] > 0 :
                     summary_parts.append("全ての処理対象データは既に登録済みか、変更の必要がありませんでした。")
                 elif overall_summary_stats['rows_processed_total'] == 0 and total_files_processed_count > 0 and not error_file_messages:
                     summary_parts.append("処理対象データが含まれていないファイルでした。")
                 elif total_files_processed_count == 0 :
                     summary_parts.append("処理対象ファイルがありませんでした。")


            if error_file_messages:
                summary_parts.append("ファイルごとのエラー/警告詳細:")
                for fname, reasons in error_file_messages.items():
                    summary_parts.append(f"  ファイル '{fname}': {', '.join(reasons)}")

            final_flash_message = " ".join(summary_parts)
            flash(final_flash_message, flash_cat)
            current_app.logger.info(f"CSV Import Overall Summary: {final_flash_message}")

        except psycopg2.Error as e_db_main_conn:
            if conn_outer: conn_outer.rollback()
            error_message = f"CSVインポート処理中にデータベース接続または主要なトランザクションエラーが発生しました: {e_db_main_conn}"
            current_app.logger.error(f"Main DB Error during CSV import: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        except Exception as e_general_main:
            if conn_outer: conn_outer.rollback()
            error_message = f"CSVインポート処理中に予期せぬエラーが発生しました: {e_general_main}"
            current_app.logger.error(f"Main General Error during CSV import: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn_outer and not conn_outer.closed:
                conn_outer.close()
                current_app.logger.info("Closed main database connection after CSV import process.")

        return redirect(url_for('admin.admin_import_csv'))

    return render_template('admin/admin_import_csv.html')