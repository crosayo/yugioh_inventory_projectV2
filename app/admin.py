# app/admin.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, current_app, session, jsonify, make_response
)
import psycopg2
import psycopg2.extras
import traceback
import csv
import io
import os
import re
from werkzeug.utils import secure_filename
import datetime
from app.db import get_db_connection
from app.auth import login_required
from app.data_definitions import DEFINED_RARITIES, RARITY_CONVERSION_MAP, calculate_era
from app.utils import normalize_for_search
from urllib.parse import unquote, quote

# SeleniumとBeautifulSoupのインポート
# SeleniumとBeautifulSoupのインポート
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time


ALLOWED_EXTENSIONS = {'csv'}
bp = Blueprint('admin', __name__, url_prefix='/admin')

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

# ...(中略)...CSVインポートや製品マスタ管理など、他の既存関数は変更ありません...
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
                    num_total_rows_in_file = 0

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
                                file_content_for_count = file_obj.read()
                                file_obj.seek(0)
                                
                                temp_file_like_object_for_count = io.StringIO(file_content_for_count.decode('utf-8-sig'))
                                temp_reader_for_count = csv.reader(temp_file_like_object_for_count)
                                try:
                                    header_for_count = next(temp_reader_for_count) 
                                    num_total_rows_in_file = sum(1 for row in temp_reader_for_count)
                                    current_app.logger.info(f"File '{original_filename_for_display}' has approx. {num_total_rows_in_file} data rows.")
                                except StopIteration: 
                                    num_total_rows_in_file = 0
                                    current_app.logger.info(f"File '{original_filename_for_display}' appears to be empty or header-only.")
                                file_stream = io.StringIO(file_content_for_count.decode('utf-8-sig'))
                                
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
                                
                                report_interval = 1000 
                                if num_total_rows_in_file > 0 and num_total_rows_in_file < report_interval * 5: 
                                    report_interval = max(100, num_total_rows_in_file // 10) 
                                if report_interval == 0 and num_total_rows_in_file > 0 :
                                     report_interval = 1

                                for row_idx_in_file, row_data_dict in enumerate(csv_reader):
                                    current_csv_row_num_for_log = row_idx_in_file + 1
                                    file_processing_summary['rows_processed_in_file'] += 1
                                    
                                    if num_total_rows_in_file > 0 and report_interval > 0 and \
                                       (current_csv_row_num_for_log % report_interval == 0 or current_csv_row_num_for_log == num_total_rows_in_file):
                                        progress_percent = (current_csv_row_num_for_log / num_total_rows_in_file * 100)
                                        current_app.logger.info(
                                            f"  File '{original_filename_for_display}': Processing row {current_csv_row_num_for_log}/{num_total_rows_in_file} "
                                            f"({progress_percent:.2f}%)"
                                        )
                                    elif num_total_rows_in_file == 0 and (row_idx_in_file + 1) % 1000 == 0 :
                                        current_app.logger.info(f"  File '{original_filename_for_display}': Processing row {row_idx_in_file + 1}...")
                                    
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
                                if file_processing_summary['rows_processed_in_file'] > 0:
                                     file_processing_summary['skipped_error_row'] = file_processing_summary['rows_processed_in_file'] - (file_processing_summary['added'] + file_processing_summary['updated_info'] + file_processing_summary['skipped_no_change'])
                                else:
                                    file_processing_summary['skipped_error_row'] = 1

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
                    key_for_error_msg = file_obj.filename
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

@bp.route('/check_categories')
@login_required
def admin_check_categories():
    conn = None
    unmatched_categories = []
    matched_but_null_date = []
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT DISTINCT category FROM items WHERE category IS NOT NULL AND category != '' ORDER BY category")
        items_categories_raw = [row['category'] for row in cur.fetchall()]
        
        cur.execute("SELECT name, release_date FROM products WHERE name IS NOT NULL AND name != ''")
        products_raw = cur.fetchall()

        products_map_normalized = {
            row['name'].strip().lower(): row for row in products_raw
        }

        for category in items_categories_raw:
            normalized_cat = category.strip().lower()
            matching_product = products_map_normalized.get(normalized_cat)

            if not matching_product:
                unmatched_categories.append(category)
            elif matching_product['release_date'] is None:
                matched_but_null_date.append(category)

        total_issues = len(unmatched_categories) + len(matched_but_null_date)
        if total_issues > 0:
            flash(f"合計 {total_issues} 件のカテゴリでデータの問題が発見されました。詳細は以下を確認してください。", "warning")
        else:
            flash("素晴らしい！全てのアイテムカテゴリが製品マスタと正常に紐付いています。", "success")

    except (Exception, psycopg2.Error) as error:
        current_app.logger.error(f"Error in admin_check_categories: {error}")
        traceback.print_exc()
        flash(f"カテゴリのチェック中にエラーが発生しました: {error}", "danger")
    finally:
        if conn:
            if 'cur' in locals() and not cur.closed:
                cur.close()
            conn.close()

    return render_template(
        'admin/admin_check_categories.html', 
        unmatched_categories=unmatched_categories,
        matched_but_null_date=matched_but_null_date
    )

@bp.route('/products')
@login_required
def manage_products():
    """製品マスタの一覧表示ページ"""
    conn = None
    search_keyword = request.args.get('keyword', '').strip()
    sort_key = request.args.get('sort_key', 'release_date')
    sort_order = request.args.get('sort_order', 'desc')

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        query = "SELECT name, display_name, release_date, era, show_in_sidebar FROM products"
        params = []
        
        if search_keyword:
            query += " WHERE LOWER(name) LIKE %s OR LOWER(display_name) LIKE %s"
            params.append(f"%{search_keyword.lower()}%")
            params.append(f"%{search_keyword.lower()}%")
            
        valid_sort_keys = ['name', 'display_name', 'release_date', 'era', 'show_in_sidebar']
        if sort_key not in valid_sort_keys:
            sort_key = 'release_date'
        if sort_order not in ['asc', 'desc']:
            sort_order = 'desc'
            
        query += f" ORDER BY {sort_key} {sort_order.upper()}"
        
        cur.execute(query, tuple(params))
        products = cur.fetchall()

    except (Exception, psycopg2.Error) as error:
        flash(f'製品リストの取得中にエラーが発生しました: {error}', 'danger')
        products = []
    finally:
        if conn:
            cur.close()
            conn.close()

    return render_template('admin/manage_products.html', 
                           products=products, 
                           keyword=search_keyword,
                           sort_key=sort_key,
                           sort_order=sort_order)

@bp.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product():
    """新しい製品を登録するページ"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        display_name = request.form.get('display_name', '').strip()
        release_date_str = request.form.get('release_date', '').strip()
        show_in_sidebar = request.form.get('show_in_sidebar') == 'on'
        
        # エラー時にフォームを再表示するためのデータを準備
        product_for_form = {
            'name': name, 
            'display_name': display_name, 
            'release_date': release_date_str, 
            'show_in_sidebar': show_in_sidebar
        }

        if not name or not release_date_str:
            flash('製品名と発売日は必須です。', 'danger')
            return render_template('admin/product_form.html', 
                                   action_url=url_for('admin.add_product'), 
                                   product=product_for_form,
                                   page_title='製品の新規登録')
        
        era = calculate_era(release_date_str)
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO products (name, display_name, release_date, era, show_in_sidebar) VALUES (%s, %s, %s, %s, %s)",
                (name, display_name or name, release_date_str, era, show_in_sidebar)
            )
            conn.commit()
            flash(f'製品「{name}」を登録しました。', 'success')
            return redirect(url_for('admin.manage_products'))

        except psycopg2.IntegrityError:
            if conn: conn.rollback()
            flash(f'エラー: 製品名「{name}」は既に存在します。', 'danger')
            # エラー発生時にフォームを再表示
            return render_template('admin/product_form.html',
                                   action_url=url_for('admin.add_product'),
                                   product=product_for_form,
                                   page_title='製品の新規登録')
        except (Exception, psycopg2.Error) as error:
            if conn: conn.rollback()
            flash(f'データベース登録中にエラーが発生しました: {error}', 'danger')
            # エラー発生時にフォームを再表示
            return render_template('admin/product_form.html',
                                   action_url=url_for('admin.add_product'),
                                   product=product_for_form,
                                   page_title='製品の新規登録')
        finally:
            if conn:
                if 'cur' in locals() and cur and not cur.closed:
                    cur.close()
                conn.close()

    # GETリクエストの場合の処理
    return render_template('admin/product_form.html', 
                           action_url=url_for('admin.add_product'),
                           product={},
                           page_title='製品の新規登録')


@bp.route('/products/edit/<path:product_name>', methods=['GET', 'POST'])
@login_required
def edit_product(product_name):
    """既存の製品を編集するページ"""
    original_name = unquote(product_name)
    
    if request.method == 'POST':
        new_name = request.form.get('name', '').strip()
        new_display_name = request.form.get('display_name', '').strip()
        new_release_date_str = request.form.get('release_date', '').strip()
        new_show_in_sidebar = request.form.get('show_in_sidebar') == 'on'

        product_for_form = {
            'name': new_name, 
            'display_name': new_display_name, 
            'release_date': new_release_date_str, 
            'show_in_sidebar': new_show_in_sidebar
        }

        if not new_name or not new_release_date_str:
            flash('製品名と発売日は必須です。', 'danger')
            return render_template('admin/product_form.html', 
                                   action_url=url_for('admin.edit_product', product_name=quote(original_name)),
                                   product=product_for_form,
                                   page_title=f'製品の編集: {original_name}')
        
        new_era = calculate_era(new_release_date_str)
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE products SET name=%s, display_name=%s, release_date=%s, era=%s, show_in_sidebar=%s WHERE name=%s",
                (new_name, new_display_name or new_name, new_release_date_str, new_era, new_show_in_sidebar, original_name)
            )
            conn.commit()
            flash(f'製品「{original_name}」の情報を更新しました。', 'success')
            return redirect(url_for('admin.manage_products'))
        except psycopg2.IntegrityError:
            if conn: conn.rollback()
            flash(f'エラー: 更新後の製品名「{new_name}」は既に別の製品で使われています。', 'danger')
            return render_template('admin/product_form.html',
                                   action_url=url_for('admin.edit_product', product_name=quote(original_name)),
                                   product=product_for_form,
                                   page_title=f'製品の編集: {original_name}')
        except (Exception, psycopg2.Error) as error:
            if conn: conn.rollback()
            flash(f'データベース更新中にエラーが発生しました: {error}', 'danger')
            return render_template('admin/product_form.html',
                                   action_url=url_for('admin.edit_product', product_name=quote(original_name)),
                                   product=product_for_form,
                                   page_title=f'製品の編集: {original_name}')
        finally:
            if conn:
                if 'cur' in locals() and cur and not cur.closed:
                    cur.close()
                conn.close()

    # GETリクエストの処理
    conn = None
    product = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, display_name, release_date, era, show_in_sidebar FROM products WHERE name = %s", (original_name,))
        product = cur.fetchone()
    except (Exception, psycopg2.Error) as error:
        flash(f'製品情報の取得中にエラーが発生しました: {error}', 'danger')
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()

    if not product:
        flash(f'製品「{original_name}」が見つかりません。', 'warning')
        return redirect(url_for('admin.manage_products'))

    return render_template('admin/product_form.html',
                           action_url=url_for('admin.edit_product', product_name=quote(original_name)),
                           product=product,
                           page_title=f'製品の編集: {original_name}')

@bp.route('/products/export')
@login_required
def export_products():
    """製品マスタをCSVファイルとしてエクスポートする"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, display_name, release_date, era, show_in_sidebar FROM products ORDER BY release_date DESC")
        products = cur.fetchall()
    except (Exception, psycopg2.Error) as error:
        flash(f'製品データのエクスポート中にエラーが発生しました: {error}', 'danger')
        return redirect(url_for('admin.manage_products'))
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()

    si = io.StringIO()
    si.write('\ufeff') 
    cw = csv.writer(si)
    
    headers = ['name', 'display_name', 'release_date', 'era', 'show_in_sidebar']
    cw.writerow(headers)

    for product in products:
        row = list(product)
        if isinstance(row[2], datetime.date):
            row[2] = row[2].strftime('%Y-%m-%d')
        cw.writerow(row)
    
    output = make_response(si.getvalue())
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"products_export_{timestamp}.csv"
    output.headers["Content-Disposition"] = f"attachment; filename=\"{filename}\""
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    
    return output

@bp.route('/api/products/toggle_sidebar/<path:product_name>', methods=['POST'])
@login_required
def api_toggle_sidebar(product_name):
    """【API】製品のサイドバー表示/非表示を切り替える"""
    product_to_toggle = unquote(product_name)
    conn = None
    try:
        conn = get_db_connection()
        new_state = None
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE products SET show_in_sidebar = NOT show_in_sidebar WHERE name = %s RETURNING show_in_sidebar",
                    (product_to_toggle,)
                )
                result = cur.fetchone()
                if result:
                    new_state = result['show_in_sidebar']
                else:
                    return jsonify({'success': False, 'message': '対象の製品が見つかりませんでした。'}), 404
        
        return jsonify({'success': True, 'newState': new_state})

    except Exception as e:
        if conn: conn.rollback()
        current_app.logger.error(f"Error toggling sidebar visibility via API for {product_to_toggle}: {e}")
        return jsonify({'success': False, 'message': 'データベースエラーが発生しました。'}), 500
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()

def process_products_csv(file_stream):
    """
    製品マスタ(products)更新用のCSVファイルを処理する。
    """
    stats = {'updated': 0, 'not_found': 0, 'error': 0, 'total': 0}
    errors = []
    
    try:
        content = file_stream.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        
        header_map = {
            'name': ['name', '製品名'],
            'release_date': ['release_date', '発売日'],
            'display_name': ['display_name', '表示名'],
            'show_in_sidebar': ['show_in_sidebar', 'サイドバー表示']
        }
        
        normalized_headers = {h.lower(): h for h in reader.fieldnames}
        
        mapped_cols = {}
        for key, possible_names in header_map.items():
            for name in possible_names:
                if name.lower() in normalized_headers:
                    mapped_cols[key] = normalized_headers[name.lower()]
                    break
        
        if 'name' not in mapped_cols or 'release_date' not in mapped_cols:
            errors.append("CSVヘッダーに 'name' (製品名) と 'release_date' (発売日) が必要です。")
            stats['error'] = 1
            return stats, errors

        conn = get_db_connection()
        with conn.cursor() as cur:
            for i, row in enumerate(reader):
                stats['total'] += 1
                row_num = i + 2
                
                product_name = row.get(mapped_cols['name'], '').strip()
                release_date_str = row.get(mapped_cols['release_date'], '').strip()

                if not product_name or not release_date_str:
                    errors.append(f"行 {row_num}: 製品名または発売日が空です。スキップしました。")
                    stats['error'] += 1
                    continue
                
                try:
                    datetime.datetime.strptime(release_date_str, '%Y-%m-%d')
                except ValueError:
                    try:
                        release_date_obj = datetime.datetime.strptime(release_date_str, '%Y/%m/%d')
                        release_date_str = release_date_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        errors.append(f"行 {row_num} ({product_name}): 発売日の形式が不正です ('YYYY-MM-DD' または 'YYYY/MM/DD' を使用してください): {release_date_str}")
                        stats['error'] += 1
                        continue

                new_era = calculate_era(release_date_str)
                
                updates = {
                    'release_date': release_date_str,
                    'era': new_era
                }
                
                if 'display_name' in mapped_cols and row.get(mapped_cols['display_name']):
                    updates['display_name'] = row.get(mapped_cols['display_name'], '').strip()
                
                if 'show_in_sidebar' in mapped_cols:
                    show_val = row.get(mapped_cols['show_in_sidebar'], '').strip().lower()
                    if show_val in ['true', '1', 'yes', 't']:
                        updates['show_in_sidebar'] = True
                    elif show_val in ['false', '0', 'no', 'f', '']:
                        updates['show_in_sidebar'] = False

                set_clauses = [f"{key} = %s" for key in updates.keys()]
                sql = f"UPDATE products SET {', '.join(set_clauses)} WHERE name = %s"
                
                params = list(updates.values()) + [product_name]
                
                cur.execute(sql, tuple(params))
                
                if cur.rowcount > 0:
                    stats['updated'] += 1
                else:
                    stats['not_found'] += 1
                    errors.append(f"行 {row_num}: 製品 '{product_name}' がデータベースに見つかりませんでした。")
            
            conn.commit()

    except (Exception, psycopg2.Error) as e:
        if 'conn' in locals() and conn:
            conn.rollback()
        current_app.logger.error(f"製品CSVの処理中にエラーが発生しました: {e}\n{traceback.format_exc()}")
        errors.append(f"致命的なエラーが発生しました: {e}")
        stats['error'] += 1
    finally:
        if 'conn' in locals() and conn:
            conn.close()

    return stats, errors


@bp.route('/products/import', methods=['GET', 'POST'])
@login_required
def import_products_csv():
    """製品マスタをCSVから一括更新するページ"""
    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('ファイルが選択されていません。', 'warning')
            return redirect(request.url)
        
        file = request.files['csv_file']

        if file.filename == '':
            flash('ファイルが選択されていません。', 'warning')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            stats, errors = process_products_csv(file.stream)
            
            if stats['updated'] > 0:
                flash(f"{stats['updated']}件の製品情報が正常に更新されました。", 'success')
            
            if stats['not_found'] > 0:
                flash(f"{stats['not_found']}件の製品がDBに見つからず、スキップされました。", 'warning')
            
            if stats['error'] > 0:
                flash(f"{stats['error']}件の処理でエラーが発生しました。詳細はログを確認してください。", 'danger')

            if not any([stats['updated'], stats['not_found'], stats['error']]):
                 flash('CSVファイルが空か、処理対象のデータがありませんでした。', 'info')

            for error_msg in errors:
                flash(error_msg, 'danger')

            return redirect(url_for('admin.manage_products'))

    return render_template('admin/import_products.html')

@bp.route('/products/delete/<path:product_name>/confirm')
@login_required
def confirm_delete_product(product_name):
    """製品を削除する前の確認ページ"""
    original_name = unquote(product_name)
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT * FROM products WHERE name = %s", (original_name,))
        product = cur.fetchone()

        if not product:
            flash(f'製品「{original_name}」が見つかりません。', 'warning')
            return redirect(url_for('admin.manage_products'))

        cur.execute("SELECT COUNT(*) as item_count FROM items WHERE category = %s", (original_name,))
        item_count = cur.fetchone()['item_count']

    except (Exception, psycopg2.Error) as error:
        flash(f'製品情報の取得中にエラーが発生しました: {error}', 'danger')
        return redirect(url_for('admin.manage_products'))
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()
            
    return render_template('admin/confirm_delete_product.html', product=product, item_count=item_count)

@bp.route('/products/delete/<path:product_name>', methods=['POST'])
@login_required
def delete_product(product_name):
    """製品を実際に削除する"""
    original_name = unquote(product_name)
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE name = %s", (original_name,))
        conn.commit()
        
        flash(f'製品「{original_name}」を削除しました。', 'success')
        current_app.logger.info(f"Product '{original_name}' deleted by user '{session.get('username', 'unknown')}'.")

    except (Exception, psycopg2.Error) as error:
        if conn: conn.rollback()
        flash(f'製品の削除中にエラーが発生しました: {error}', 'danger')
        current_app.logger.error(f"Error deleting product '{original_name}': {error}\n{traceback.format_exc()}")
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()

    return redirect(url_for('admin.manage_products'))


# ===== Wikiインポート機能 ここから =====

# admin.py内の既存のscrape_wiki_page関数を、以下の新しい関数で置き換える

# admin.py内の既存のscrape_wiki_page関数を、以下の新しい関数で置き換える

# admin.py内の既存のscrape_wiki_page関数を、以下の新しい関数で置き換える

def scrape_wiki_page(url):
    """
    指定された遊戯王WikiのURLからカードリストを抽出する。
    ページ内の全セクションを探索し、リスト形式とテーブル形式の両方に個別に対応する。
    成功した場合は (カテゴリ名, カードリスト)、失敗した場合は (None, エラーメッセージ) を返す。
    """
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--blink-settings=imagesEnabled=false')
    driver = None
    
    debug_screenshot_path = os.path.join(current_app.root_path, '..', 'debug_screenshot.png')
    debug_html_path = os.path.join(current_app.root_path, '..', 'debug_page.html')

    try:
        current_app.logger.info("Selenium WebDriverを初期化しています...")
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        driver.set_page_load_timeout(90)
        
        current_app.logger.info(f"指定されたURLにアクセスします: {url}")
        driver.get(url)
        
        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "body")))
        current_app.logger.info("ページの基本要素(#body)の読み込みを確認しました。")

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        main_category_tag = soup.select_one('#body > h2')
        main_category = main_category_tag.text.strip().replace(' †', '') if main_category_tag else driver.title.split('-')[0].strip()
        current_app.logger.info(f"メインカテゴリ名を '{main_category}' として特定しました。")

        # ページ内のすべてのカードリスト見出し (h3 or h4) を探す
        all_card_list_headers = soup.select("#body h3, #body h4")
        
        final_card_list = []
        found_any_list = False

        for header in all_card_list_headers:
            header_text = header.get_text(strip=True).replace(' †', '')
            
            # カードリストの可能性のある見出しをキーワードで探す
            if any(keyword in header_text for keyword in ['収録カードリスト', 'パック']):
                current_app.logger.info(f"カードリストの見出しを発見: '{header_text}'")
                
                # 付属パックの場合のカテゴリ名を決定
                current_category = f"{main_category}_{header_text}" if 'パック' in header_text else main_category
                
                # 見出しの直後にある意味のある要素(ulまたはtable)を探す (間の空の要素はスキップ)
                next_element = header.find_next_sibling()
                while next_element and (next_element.name not in ['ul', 'table'] or not next_element.get_text(strip=True)):
                    next_element = next_element.find_next_sibling()

                # --- パターン1: リスト形式 ---
                if next_element and next_element.name == 'ul':
                    current_app.logger.info(f"  -> リスト(ul)形式と判断。カテゴリ: '{current_category}'")
                    found_any_list = True
                    list_items = next_element.find_all('li')
                    for item in list_items:
                        full_text = item.get_text(strip=True)
                        match = re.match(r'([A-Z0-9\-]+)\s*《(.+?)》\s*(.*)', full_text)
                        if match:
                            card_id, name, raw_rare_text = match.groups()
                            rarities = [r.strip() for r in raw_rare_text.split(',')] if raw_rare_text else ['Normal']
                            for rare in rarities:
                                final_card_list.append({'name': name.strip(), 'card_id': card_id.strip(), 'rare': rare if rare else 'Normal', 'stock': 0, 'category': current_category})
                
                # --- パターン2: テーブル形式 ---
                elif next_element and next_element.name == 'table' and 'style_table' in next_element.get('class', []):
                    current_app.logger.info(f"  -> テーブル(table)形式と判断。カテゴリ: '{current_category}'")
                    found_any_list = True
                    rows = next_element.find_all("tr")
                    for row in rows[1:]: # ヘッダー行をスキップ
                        cols = row.find_all(["td", "th"])
                        if len(cols) >= 3:
                            name = cols[0].get_text(strip=True)
                            card_id = cols[1].get_text(strip=True)
                            raw_rare_text = cols[2].get_text(strip=True)
                            
                            # レアリティから封入枚数（末尾の数字）を除去
                            clean_rare_text = re.sub(r'\d+$', '', raw_rare_text).strip()
                            
                            if name and card_id:
                                rarities = [r.strip() for r in clean_rare_text.split(',')] if clean_rare_text else ['Normal']
                                for r in rarities:
                                    final_card_list.append({'name': name, 'card_id': card_id, 'rare': r if r else 'Normal', 'stock': 0, 'category': current_category})
        
        if not found_any_list:
            return None, "カードリストを含む可能性のあるセクションが見つかりませんでした。"
        if not final_card_list:
            return None, "カードリストの解析に失敗しました。ページの構造が未対応の可能性があります。"

        current_app.logger.info(f"最終的に {len(final_card_list)} 件のカードデータを抽出しました。")
        # 最初のカテゴリ名を代表として返す（表示用）
        return main_category, final_card_list

    except Exception as e:
        error_type = type(e).__name__
        current_app.logger.error(f"スクレイピング中に予期せぬエラー({error_type})が発生しました: {e}\n{traceback.format_exc()}")
        if driver:
            try:
                driver.save_screenshot(debug_screenshot_path)
                with open(debug_html_path, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                current_app.logger.info(f"デバッグ用のスクリーンショットとHTMLを保存しました。")
            except Exception as e_debug:
                 current_app.logger.error(f"デバッグファイルの保存中にエラーが発生しました: {e_debug}")
        return None, f"エラーが発生しました: {error_type}。({os.path.basename(debug_screenshot_path)} を確認してください)"
    finally:
        if driver:
            driver.quit()
            current_app.logger.info("Selenium WebDriverを終了しました。")


@bp.route('/wiki_import', methods=['GET', 'POST'])
@login_required
def wiki_import():
    if request.method == 'POST':
        wiki_url = request.form.get('wiki_url', '').strip()
        if not wiki_url:
            flash('URLが入力されていません。', 'warning')
            return redirect(url_for('admin.wiki_import'))
        
        current_app.logger.info(f"Wiki import started by user '{session.get('username', 'unknown')}' for URL: {wiki_url}")
        
        category, cards = scrape_wiki_page(wiki_url)
        
        if cards:
            session['wiki_import_cards'] = cards
            session['wiki_import_category'] = category 
            flash(f'URLから {len(cards)} 件のカードが見つかりました。内容を確認してください。', 'success')
            return redirect(url_for('admin.wiki_import_confirm'))
        else:
            flash(category, 'danger')
            return redirect(url_for('admin.wiki_import'))

    return render_template('admin/wiki_import.html')


@bp.route('/wiki_import/confirm', methods=['GET', 'POST'])
@login_required
def wiki_import_confirm():
    cards_to_import = session.get('wiki_import_cards')
    display_category = session.get('wiki_import_category', 'インポート')

    if not cards_to_import:
        flash('登録対象のカード情報が見つかりません。もう一度URLからやり直してください。', 'warning')
        return redirect(url_for('admin.wiki_import'))

    if request.method == 'POST':
        conn = None
        added_count = 0
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                for card in cards_to_import:
                    name_normalized = normalize_for_search(card['name'])
                    card_id_normalized = normalize_for_search(card['card_id'])

                    try:
                        cur.execute(
                            """
                            INSERT INTO items (name, card_id, rare, stock, category, name_normalized, card_id_normalized)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (card['name'], card['card_id'], card['rare'], card['stock'], card['category'], name_normalized, card_id_normalized)
                        )
                        added_count += 1
                    except psycopg2.IntegrityError:
                        conn.rollback() 
                        current_app.logger.warning(f"Skipping duplicate card: {card['card_id']} ({card['rare']}) - {card['name']}")
                        continue

            conn.commit()
            
            session.pop('wiki_import_cards', None)
            session.pop('wiki_import_category', None)
            
            flash(f'{added_count} 件のカードをデータベースに登録しました。', 'success')
            current_app.logger.info(f"{added_count} cards from URL import have been added to DB.")
            return redirect(url_for('main.index'))
            
        except (Exception, psycopg2.Error) as e:
            if conn: conn.rollback()
            current_app.logger.error(f"DB Error during wiki commit: {e}\n{traceback.format_exc()}")
            flash(f"データベースへの登録中にエラーが発生しました: {e}", "danger")
            return redirect(url_for('admin.wiki_import'))
        finally:
            if conn:
                conn.close()

    return render_template('admin/wiki_import_confirm.html', 
                           cards=cards_to_import, 
                           category=display_category)


@bp.route('/wiki_import/cancel', methods=['POST'])
@login_required
def wiki_import_cancel():
    session.pop('wiki_import_cards', None)
    session.pop('wiki_import_category', None)
    flash('インポート処理をキャンセルしました。', 'info')
    return redirect(url_for('admin.wiki_import'))