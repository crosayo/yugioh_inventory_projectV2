# app/admin.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, current_app, session
)
import psycopg2 # For specific error types if needed
import psycopg2.extras
import traceback # For detailed error logging
import csv
import io
import os
from werkzeug.utils import secure_filename # For secure filenames

from app.db import get_db_connection # Centralized db connection
from app.auth import login_required # Login decorator
from app.data_definitions import DEFINED_RARITIES, RARITY_CONVERSION_MAP # Data definitions

ALLOWED_EXTENSIONS = {'csv'}
bp = Blueprint('admin', __name__, url_prefix='/admin')

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
    # (This function remains the same as the previous version)
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
    # (This function remains the same as the previous version)
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
        try:
            conn_outer = get_db_connection()
            for file_obj in files:
                if file_obj and allowed_file(file_obj.filename):
                    original_filename_for_display = file_obj.filename 
                    # カテゴリ名は元のファイル名から拡張子を除いて生成
                    category_name_from_filename = os.path.splitext(original_filename_for_display)[0]
                    # ログや内部識別子用には secure_filename を通す
                    filename_secure_internal = secure_filename(original_filename_for_display)

                    total_files_processed_count += 1
                    file_processing_summary = {'added': 0, 'updated_info': 0, 'skipped_no_change': 0, 'skipped_error_row': 0, 'rows_processed_in_file':0}
                    current_csv_row_num_for_log = 0 
                    
                    current_app.logger.info(f"Processing CSV file: '{original_filename_for_display}'")
                    current_app.logger.info(f"==> Derived category name: '{category_name_from_filename}'")
                    current_app.logger.info(f"==> Secured internal filename (for savepoint etc.): '{filename_secure_internal}'")

                    try:
                        with conn_outer.cursor() as cur:
                            savepoint_name = f"sp_{filename_secure_internal.replace('.', '_').replace('-', '_').replace(' ', '_')}"
                            cur.execute(f"SAVEPOINT {savepoint_name}")
                            current_app.logger.debug(f"Created savepoint {savepoint_name} for file {original_filename_for_display}")

                            try:
                                file_stream = io.TextIOWrapper(file_obj.stream, encoding='utf-8-sig', newline=None)
                                csv_reader = csv.DictReader(file_stream)
                                fieldnames_original = csv_reader.fieldnames or []
                                fieldnames_normalized = { (fn.strip().lower() if fn else ''): fn for fn in fieldnames_original }

                                required_headers_lower = ['name', 'rare']
                                if not all(h_req in fieldnames_normalized for h_req in required_headers_lower):
                                    err_msg = f"ヘッダー不正。必須列: {', '.join(required_headers_lower)} が見つかりません。検出ヘッダー: {fieldnames_original}"
                                    current_app.logger.error(f"File '{original_filename_for_display}': {err_msg}")
                                    if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                    error_file_messages[original_filename_for_display].append(err_msg)
                                    cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                                    current_app.logger.warning(f"Rolled back to savepoint {savepoint_name} for file {original_filename_for_display} due to header error.")
                                    continue 
                                
                                def get_normalized_row_val(row, key_lower, default=''):
                                    original_key = fieldnames_normalized.get(key_lower)
                                    return row.get(original_key, default).strip() if original_key else default

                                for row_idx, row_data_dict in enumerate(csv_reader):
                                    current_csv_row_num_for_log = row_idx + 2 
                                    file_processing_summary['rows_processed_in_file'] += 1
                                    card_name = get_normalized_row_val(row_data_dict, 'name')
                                    card_id_csv = get_normalized_row_val(row_data_dict, 'card_id')
                                    raw_rarity = get_normalized_row_val(row_data_dict, 'rare')
                                    stock_csv_str = get_normalized_row_val(row_data_dict, 'stock', '0')
                                    
                                    try:
                                        stock_csv = int(stock_csv_str) if stock_csv_str.isdigit() else 0
                                    except ValueError:
                                        stock_csv = 0
                                        current_app.logger.warning(f"File '{original_filename_for_display}' Row {current_csv_row_num_for_log}: Invalid stock value '{stock_csv_str}', using 0.")

                                    if not card_name or not raw_rarity: 
                                        current_app.logger.warning(f"SKIPPING Row {current_csv_row_num_for_log} in '{original_filename_for_display}': Missing name or rarity. Data: {row_data_dict}")
                                        file_processing_summary['skipped_error_row'] +=1
                                        if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                        error_file_messages[original_filename_for_display].append(f"行 {current_csv_row_num_for_log}: 名前またはレアリティが空です。")
                                        continue

                                    converted_rarity = RARITY_CONVERSION_MAP.get(raw_rarity.lower(), raw_rarity)
                                    if converted_rarity not in DEFINED_RARITIES:
                                        current_app.logger.info(f"File '{original_filename_for_display}' Row {current_csv_row_num_for_log}: Rarity '{raw_rarity}' (became '{converted_rarity}') is not in DEFINED_RARITIES. Using as is or map to 'その他'.")
                                    
                                    final_card_id_for_db = card_id_csv if card_id_csv else None
                                    existing_card_data = None

                                    if final_card_id_for_db is not None:
                                        current_app.logger.debug(f"CSV Import: Checking existing card. card_id_csv='{card_id_csv}', final_card_id_for_db='{final_card_id_for_db}', type={type(final_card_id_for_db)}")
                                        try:
                                            cur.execute("SELECT id, name, rare, stock, category FROM items WHERE card_id = %s", (str(final_card_id_for_db),))
                                            existing_card_data = cur.fetchone()
                                        except Exception as e_select:
                                            current_app.logger.error(f"CSV Import: DB Error selecting item by card_id='{final_card_id_for_db}'. Error: {e_select}")
                                            file_processing_summary['skipped_error_row'] +=1
                                            if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                            error_file_messages[original_filename_for_display].append(f"行 {current_csv_row_num_for_log}: card_id '{final_card_id_for_db}' でのDB検索エラー: {e_select}")
                                            continue 
                                    else:
                                        current_app.logger.debug(f"CSV Import: card_id is empty for row {current_csv_row_num_for_log} in '{original_filename_for_display}'. Treating as new item if name/rare are present.")
                                    
                                    if existing_card_data:
                                        needs_update = False
                                        update_payload = {
                                            'name': existing_card_data['name'],
                                            'rare': existing_card_data['rare'],
                                            'category': existing_card_data['category']
                                        }

                                        if existing_card_data['name'] != card_name:
                                            update_payload['name'] = card_name
                                            needs_update = True
                                        if existing_card_data['rare'] != converted_rarity:
                                            update_payload['rare'] = converted_rarity
                                            needs_update = True
                                        if existing_card_data['category'] != category_name_from_filename: # This is the key change
                                            update_payload['category'] = category_name_from_filename
                                            needs_update = True
                                            current_app.logger.info(f"CSV Import: Category for card ID {final_card_id_for_db} WILL BE updated from '{existing_card_data['category']}' to '{category_name_from_filename}'.")


                                        if needs_update:
                                            current_app.logger.debug(f"CSV Import: Updating existing card ID {final_card_id_for_db}. Current DB: {existing_card_data}. New data from CSV (Name: {card_name}, Rare: {converted_rarity}, Category from Filename: {category_name_from_filename})")
                                            cur.execute("""
                                                UPDATE items SET name = %s, rare = %s, category = %s 
                                                WHERE id = %s
                                            """, (update_payload['name'], update_payload['rare'], update_payload['category'], existing_card_data['id']))
                                            file_processing_summary['updated_info'] += 1
                                        else:
                                            file_processing_summary['skipped_no_change'] +=1
                                            current_app.logger.debug(f"CSV Import: No changes needed for existing card ID {final_card_id_for_db}. DB Category: '{existing_card_data['category']}', Filename Category: '{category_name_from_filename}'")
                                    else: # New item
                                        current_app.logger.debug(f"CSV Import: Inserting new card. Name: {card_name}, CardID: '{final_card_id_for_db or 'N/A'}', Stock: {stock_csv}, Category: {category_name_from_filename}")
                                        cur.execute("""
                                            INSERT INTO items (name, card_id, rare, stock, category)
                                            VALUES (%s, %s, %s, %s, %s)
                                        """, (card_name, final_card_id_for_db, converted_rarity, stock_csv, category_name_from_filename))
                                        file_processing_summary['added'] += 1
                                
                                cur.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                                current_app.logger.info(f"Successfully processed and released savepoint for file '{original_filename_for_display}'. Summary: {file_processing_summary}")

                            except psycopg2.Error as e_db_in_sp:
                                cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                                current_app.logger.error(f"DB Error during row processing in file '{original_filename_for_display}', rolled back to savepoint {savepoint_name}. Error: {e_db_in_sp}\n{traceback.format_exc()}")
                                if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                error_file_messages[original_filename_for_display].append(f"ファイル処理中のDBエラー(行 {current_csv_row_num_for_log} 付近): {e_db_in_sp}。このファイルの変更は取消。")
                                file_processing_summary['skipped_error_row'] = file_processing_summary['rows_processed_in_file'] 
                                file_processing_summary['added'] = 0; file_processing_summary['updated_info'] = 0; file_processing_summary['skipped_no_change'] = 0;
                            except Exception as e_file_processing:
                                cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                                current_app.logger.error(f"Error processing rows in file '{original_filename_for_display}', rolled back to savepoint {savepoint_name}. Error: {e_file_processing}\n{traceback.format_exc()}")
                                if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                                error_file_messages[original_filename_for_display].append(f"ファイル処理中にエラーが発生: {e_file_processing} (行 {current_csv_row_num_for_log} 付近)。このファイルの変更は取消。")
                                file_processing_summary['skipped_error_row'] = file_processing_summary['rows_processed_in_file']
                                file_processing_summary['added'] = 0; file_processing_summary['updated_info'] = 0; file_processing_summary['skipped_no_change'] = 0;
                    
                    except UnicodeDecodeError as e_decode_outer:
                        err_msg = f"文字コードエラー: {e_decode_outer}。UTF-8 (BOM付き推奨) を確認してください。"
                        current_app.logger.error(f"Critical error decoding file '{original_filename_for_display}': {err_msg}\n{traceback.format_exc()}")
                        if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                        error_file_messages[original_filename_for_display].append(err_msg)
                        file_processing_summary['skipped_error_row'] = file_processing_summary.get('rows_processed_in_file', 1) 
                    except (csv.Error, Exception) as e_critical_file:
                        err_msg = f"ファイル '{original_filename_for_display}' の処理中に致命的なエラー: {e_critical_file}"
                        current_app.logger.error(f"{err_msg}\n{traceback.format_exc()}")
                        if original_filename_for_display not in error_file_messages: error_file_messages[original_filename_for_display] = []
                        error_file_messages[original_filename_for_display].append(err_msg)
                        file_processing_summary['skipped_error_row'] = file_processing_summary.get('rows_processed_in_file', 1)
                    finally:
                        overall_summary_stats['added'] += file_processing_summary['added']
                        overall_summary_stats['updated_info'] += file_processing_summary['updated_info']
                        overall_summary_stats['skipped_no_change'] += file_processing_summary['skipped_no_change']
                        overall_summary_stats['skipped_error_row'] += file_processing_summary['skipped_error_row']
                        overall_summary_stats['rows_processed_total'] += file_processing_summary['rows_processed_in_file']
                
                elif file_obj and not allowed_file(file_obj.filename): 
                    err_msg = f"拡張子不正 ({os.path.splitext(file_obj.filename)[1]})。CSVファイルのみ許可されています。"
                    current_app.logger.warning(f"File '{file_obj.filename}' skipped: {err_msg}")
                    if file_obj.filename not in error_file_messages: error_file_messages[file_obj.filename] = []
                    error_file_messages[file_obj.filename].append(err_msg)
            
            summary_parts = [f"CSVインポート処理完了。処理試行ファイル数: {total_files_processed_count}。"]
            summary_parts.append(f"総処理行数: {overall_summary_stats['rows_processed_total']}。")
            summary_parts.append(f"新規追加: {overall_summary_stats['added']}件。")
            summary_parts.append(f"既存情報更新: {overall_summary_stats['updated_info']}件。")
            summary_parts.append(f"変更なしスキップ: {overall_summary_stats['skipped_no_change']}件。")
            summary_parts.append(f"エラースキップ行: {overall_summary_stats['skipped_error_row']}件。")

            flash_cat = 'success'
            if error_file_messages or overall_summary_stats['skipped_error_row'] > 0:
                flash_cat = 'warning'
                summary_parts.append("エラー/警告詳細:")
                for fname, reasons in error_file_messages.items():
                    summary_parts.append(f"  ファイル '{fname}': {', '.join(reasons)}")
            
            final_flash_message = " ".join(summary_parts)
            flash(final_flash_message, flash_cat)
            current_app.logger.info(f"CSV Import Overall Summary: {final_flash_message}")

        except psycopg2.Error as e_db_main_conn:
            error_message = f"CSVインポート処理中にデータベース接続または主要なトランザクションエラーが発生しました: {e_db_main_conn}"
            current_app.logger.error(f"Main DB Error during CSV import: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        except Exception as e_general_main:
            error_message = f"CSVインポート処理中に予期せぬエラーが発生しました: {e_general_main}"
            current_app.logger.error(f"Main General Error during CSV import: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn_outer and not conn_outer.closed:
                conn_outer.close()
                current_app.logger.info("Closed main database connection after CSV import process.")
        
        return redirect(url_for('admin.admin_import_csv'))

    # GET request
    return render_template('admin/admin_import_csv.html')
