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
from werkzeug.utils import secure_filename

from app.db import get_db_connection
from app.auth import login_required
from app.data_definitions import DEFINED_RARITIES, RARITY_CONVERSION_MAP

# Define ALLOWED_EXTENSIONS for CSV import
ALLOWED_EXTENSIONS = {'csv'}

bp = Blueprint('admin', __name__, url_prefix='/admin')

def allowed_file(filename):
    """Checks if the uploaded file has an allowed extension (CSV)."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route('/unify_rarities', methods=('GET', 'POST'))
@login_required
def admin_unify_rarities():
    """
    Handles the unification of rarity notations in the database
    based on the RARITY_CONVERSION_MAP.
    """
    if request.method == 'POST':
        conn = None
        updated_count_total = 0
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Iterate through the conversion map and update rarities
            for old_rare, new_rare in RARITY_CONVERSION_MAP.items():
                # Update if the current rarity (case-insensitive) matches an old_rare key
                # and is not already the new_rare value (to avoid redundant updates and count issues)
                cur.execute("""
                    UPDATE items 
                    SET rare = %s 
                    WHERE LOWER(rare) = LOWER(%s) AND rare != %s
                """, (new_rare, old_rare, new_rare))
                updated_count_total += cur.rowcount
            
            conn.commit()
            if updated_count_total > 0:
                flash(f'{updated_count_total}件のレアリティ表記をデータベース内で更新/確認しました。', 'success')
                current_app.logger.info(f"{updated_count_total} rarities unified by user '{session.get('username', 'unknown_user')}'")
            else:
                flash('レアリティ表記の更新対象はありませんでした。または、既に統一済みか、変換ルールに該当しませんでした。', 'info')
        except (psycopg2.Error, Exception) as e:
            if conn: conn.rollback()
            error_message = f"レアリティ統一中にデータベースエラー: {e}"
            current_app.logger.error(f"Error during rarity unification: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn:
                if 'cur' in locals() and cur and not cur.closed:
                    cur.close()
                conn.close()
        return redirect(url_for('admin.admin_unify_rarities'))

    # GET request: Display current rarities and conversion map
    conn_get = None
    current_db_rarities = []
    try:
        conn_get = get_db_connection()
        cur_get = conn_get.cursor()
        cur_get.execute("SELECT DISTINCT rare FROM items WHERE rare IS NOT NULL AND rare != '' ORDER BY rare")
        current_db_rarities_tuples = cur_get.fetchall()
        current_db_rarities = [row['rare'] for row in current_db_rarities_tuples]
    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Error fetching current DB rarities: {e}\n{traceback.format_exc()}")
        flash("現在のレアリティ情報の取得中にエラーが発生しました。", "danger")
    finally:
        if conn_get:
            if 'cur_get' in locals() and cur_get and not cur_get.closed:
                cur_get.close()
            conn_get.close()

    return render_template('admin/admin_unify_rarities.html', 
                           rarity_map=RARITY_CONVERSION_MAP, 
                           defined_rarities=DEFINED_RARITIES,
                           current_db_rarities=current_db_rarities)


def get_items_by_category_for_batch(category_keyword=None, page=1, per_page=20, sort_by="name", sort_order="asc"):
    """
    Retrieves items for batch registration based on category keyword with pagination.
    """
    if not category_keyword:
        return [], 0 

    conn = None
    items = []
    total_items = 0
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        base_query = "SELECT id, name, card_id, rare, stock, category FROM items WHERE LOWER(category) LIKE %s"
        count_query = "SELECT COUNT(*) FROM items WHERE LOWER(category) LIKE %s"
        
        search_term = f"%{category_keyword.lower()}%"
        
        cur.execute(count_query, (search_term,))
        total_items_result = cur.fetchone()
        total_items = total_items_result['count'] if total_items_result else 0

        valid_sort_keys_batch = ["name", "card_id", "rare", "stock", "id"] 
        if sort_by not in valid_sort_keys_batch:
            sort_by = "name" # Default sort key
        if sort_order.lower() not in ["asc", "desc"]:
            sort_order = "asc" # Default sort order

        offset = (page - 1) * per_page
        query_with_order_limit = f"{base_query} ORDER BY {sort_by} {sort_order.upper()} LIMIT %s OFFSET %s"
        
        cur.execute(query_with_order_limit, (search_term, per_page, offset))
        items = cur.fetchall()
    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Error in get_items_by_category_for_batch: {e}\n{traceback.format_exc()}")
        flash("カテゴリ別商品取得中にエラーが発生しました。", "danger")
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()
    return items, total_items


@bp.route('/batch_register', methods=('GET', 'POST'))
@login_required
def admin_batch_register():
    """
    Handles batch registration/update of item stocks based on category.
    """
    if request.method == 'POST':
        conn = None
        updated_count = 0
        error_messages = []
        category_keyword_hidden = request.form.get('category_keyword_hidden', '')
        current_page_hidden = request.form.get('current_page', '1')

        try:
            conn = get_db_connection()
            with conn.cursor() as cur: # Use 'with' for automatic cursor closing
                for key, value in request.form.items():
                    if key.startswith('stock_item_'):
                        try:
                            item_id_str = key.split('_')[-1]
                            if not item_id_str.isdigit():
                                current_app.logger.warning(f"Batch update: Invalid item_id format in key '{key}'")
                                error_messages.append(f"キー '{key}' の商品IDが無効です。")
                                continue
                            
                            item_id = int(item_id_str)
                            stock_count_str = value.strip()
                            
                            if not stock_count_str: # Treat empty string as 0
                                stock_count = 0
                            elif not stock_count_str.isdigit():
                                current_app.logger.warning(f"Batch update: Invalid stock value '{value}' for item_id {item_id}. Using 0.")
                                error_messages.append(f"ID {item_id} の在庫数に不正な値「{value}」が入力されました。0として扱います。")
                                stock_count = 0 # Default to 0 if not a digit
                            else:
                                stock_count = int(stock_count_str)
                            
                            if stock_count < 0:
                                stock_count = 0 # Ensure stock is not negative
                                error_messages.append(f"ID {item_id} の在庫数に負の値が入力されました。0として扱います。")


                            cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
                            current_item = cur.fetchone()

                            if current_item:
                                if current_item['stock'] != stock_count:
                                    cur.execute("UPDATE items SET stock = %s WHERE id = %s", (stock_count, item_id))
                                    updated_count += 1
                                    current_app.logger.info(f"Batch update: Item ID {item_id} stock updated to {stock_count}")
                            else:
                                current_app.logger.warning(f"Batch update: Item ID {item_id} not found in database.")
                                error_messages.append(f"ID {item_id} の商品がデータベースに見つかりませんでした。")
                        
                        except ValueError as ve: # Handles int conversion errors for item_id or stock_count
                            flash(f"処理中に値のエラーが発生しました (キー: {key}, 値: {value}): {ve}", "warning")
                            current_app.logger.warning(f"Batch update: ValueError for key '{key}', value '{value}': {ve}")
                        # Individual item update errors should not stop the whole batch, log and continue
                        except Exception as e_inner:
                            # conn.rollback() # Rollback might not be desired for individual errors in a batch
                            flash(f"ID {key.split('_')[-1]} の更新中にエラー: {e_inner}", "danger")
                            current_app.logger.error(f"Batch update inner loop for item_id {key.split('_')[-1]}: {e_inner}\n{traceback.format_exc()}")
                            error_messages.append(f"ID {key.split('_')[-1]} の更新中に予期せぬエラーが発生しました。")
                
                if updated_count > 0:
                    conn.commit()
                    flash(f"{updated_count}件のカードの在庫を一括更新しました。", "success")
                elif not error_messages: # No updates and no errors
                    flash("在庫が変更されたカードはありませんでした。", "info")
                
                for err_msg in error_messages:
                    flash(err_msg, 'warning') # Show accumulated warnings/errors

        except (psycopg2.Error, Exception) as e_db:
            if conn: conn.rollback() # Rollback on major DB error for the whole transaction
            error_message = f"一括在庫更新中にデータベースエラー: {e_db}"
            current_app.logger.error(f"Error during batch stock update (DB): {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn and not conn.closed:
                conn.close()
        
        return redirect(url_for('admin.admin_batch_register', 
                                category_keyword=category_keyword_hidden, 
                                page=current_page_hidden))

    # GET request
    category_keyword = request.args.get('category_keyword', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page_batch = 20 # Items per page for batch view
    
    items_for_batch = []
    total_items_batch = 0
    if category_keyword:
        items_for_batch, total_items_batch = get_items_by_category_for_batch(category_keyword, page, per_page_batch)
        if not items_for_batch and page == 1 and total_items_batch == 0: 
            flash(f"カテゴリ「{category_keyword}」に該当するカードは見つかりませんでした。", "info")

    total_pages_batch = (total_items_batch + per_page_batch - 1) // per_page_batch if per_page_batch > 0 else 1
    if page > total_pages_batch and total_pages_batch > 0: # page out of bounds
        page = total_pages_batch
        items_for_batch, _ = get_items_by_category_for_batch(category_keyword, page, per_page_batch)


    return render_template('admin/admin_batch_register.html',
                           items=items_for_batch,
                           category_keyword=category_keyword,
                           page=page,
                           per_page=per_page_batch,
                           total_pages=total_pages_batch,
                           total_items=total_items_batch)


@bp.route('/import_csv', methods=('GET', 'POST'))
@login_required
def admin_import_csv():
    """
    Handles CSV file import for batch adding/updating items.
    Category is derived from the CSV filename.
    Stock is only set for new items; existing items' stock is not modified by CSV import.
    """
    if request.method == 'POST':
        if 'csv_files' not in request.files:
            flash('ファイルが選択されていません。', 'warning')
            return redirect(request.url)
        
        files = request.files.getlist('csv_files') # For multiple file uploads
        
        if not files or all(f.filename == '' for f in files):
            flash('ファイルが選択されていません。', 'warning')
            return redirect(request.url)

        total_files_processed = 0
        overall_summary = {
            'added': 0, 'updated_info': 0, 'skipped_no_change': 0, 'skipped_error': 0, 'rows_processed':0
        }
        error_file_details = {} # To store errors per file: {'filename': ['error1', 'error2']}

        conn_outer = None
        try:
            conn_outer = get_db_connection() # Get one connection for all files in this request
            
            for file_obj in files:
                if file_obj and allowed_file(file_obj.filename):
                    filename = secure_filename(file_obj.filename)
                    # Use filename (without extension) as category
                    category_name_from_file = os.path.splitext(filename)[0]
                    total_files_processed += 1
                    
                    file_summary = {'added': 0, 'updated_info': 0, 'skipped_no_change': 0, 'skipped_error': 0, 'rows_processed':0}
                    current_csv_row_num = 0 # For error reporting

                    current_app.logger.info(f"Processing CSV file: {filename} for category: {category_name_from_file}")

                    try:
                        # Each file is processed in its own transaction block within the outer connection
                        with conn_outer.cursor() as cur: # Use 'with' for cursor management
                            # Decode file stream, ensure utf-8-sig to handle BOM
                            stream = io.StringIO(file_obj.stream.read().decode("utf-8-sig"), newline=None)
                            csv_reader = csv.DictReader(stream)

                            required_headers = ['name', 'rare'] # card_id and stock are optional but recommended
                            if not csv_reader.fieldnames or not all(h.lower() in [fn.lower() for fn in csv_reader.fieldnames] for h in required_headers):
                                err_msg = f"ヘッダー不正。必須列: {', '.join(required_headers)} が見つかりません (大文字小文字区別なし)。検出されたヘッダー: {csv_reader.fieldnames}"
                                current_app.logger.error(f"File '{filename}': {err_msg}")
                                if filename not in error_file_details: error_file_details[filename] = []
                                error_file_details[filename].append(err_msg)
                                file_summary['skipped_error'] +=1 # Count this file as an error
                                continue # Skip to next file
                            
                            # Normalize header names (e.g., convert to lowercase) for consistent access
                            def get_row_val(row, key, default=''):
                                for r_key in row:
                                    if r_key.strip().lower() == key.lower():
                                        return row[r_key].strip()
                                return default

                            for row_idx, row_dict in enumerate(csv_reader):
                                current_csv_row_num = row_idx + 2 # +1 for 0-index, +1 for header row
                                file_summary['rows_processed'] +=1

                                card_name = get_row_val(row_dict, 'name')
                                card_id_csv = get_row_val(row_dict, 'card_id')
                                raw_rarity = get_row_val(row_dict, 'rare')
                                stock_csv_str = get_row_val(row_dict, 'stock', '0') # Default to '0' if stock col missing
                                
                                try:
                                    stock_csv = int(stock_csv_str) if stock_csv_str.isdigit() else 0
                                except ValueError:
                                    stock_csv = 0
                                    current_app.logger.warning(f"File '{filename}' Row {current_csv_row_num}: Invalid stock value '{stock_csv_str}', using 0.")

                                if not card_name or not raw_rarity: 
                                    current_app.logger.warning(f"SKIPPING: File '{filename}' Row {current_csv_row_num}: Missing name or rarity. Row: {row_dict}")
                                    file_summary['skipped_error'] +=1
                                    if filename not in error_file_details: error_file_details[filename] = []
                                    error_file_details[filename].append(f"行 {current_csv_row_num}: 名前またはレアリティが空です。")
                                    continue

                                # Convert rarity
                                converted_rarity = raw_rarity
                                raw_rarity_lower = raw_rarity.lower()
                                for map_key, map_value in RARITY_CONVERSION_MAP.items():
                                    if map_key.lower() == raw_rarity_lower:
                                        converted_rarity = map_value
                                        break
                                
                                if converted_rarity not in DEFINED_RARITIES and converted_rarity != raw_rarity:
                                    # If conversion happened but still not in defined list, log it
                                    current_app.logger.info(f"File '{filename}' Row {current_csv_row_num}: Rarity '{raw_rarity}' converted to '{converted_rarity}' which is not in DEFINED_RARITIES. Using it as is or consider adding to DEFINED_RARITIES or map to 'その他'.")
                                    # For now, we'll use the converted_rarity. If it's critical it must be in DEFINED_RARITIES,
                                    # you might want to map it to 'その他' or '不明' here.
                                elif converted_rarity not in DEFINED_RARITIES and converted_rarity == raw_rarity:
                                     current_app.logger.info(f"File '{filename}' Row {current_csv_row_num}: Rarity '{raw_rarity}' is not in DEFINED_RARITIES and no conversion rule found. Using it as is.")


                                final_card_id = card_id_csv if card_id_csv else None # Use None if empty for DB check

                                existing_card = None
                                if final_card_id: # Only search if card_id is provided
                                    cur.execute("SELECT id, name, rare, stock, category FROM items WHERE card_id = %s", (final_card_id,))
                                    existing_card = cur.fetchone()
                                
                                if existing_card:
                                    # Item exists, update its info (name, rare, category) if different. Stock is NOT updated from CSV for existing items.
                                    if (existing_card['name'] != card_name or
                                        existing_card['rare'] != converted_rarity or
                                        existing_card['category'] != category_name_from_file):
                                        cur.execute("""
                                            UPDATE items SET name = %s, rare = %s, category = %s 
                                            WHERE id = %s
                                        """, (card_name, converted_rarity, category_name_from_file, existing_card['id']))
                                        file_summary['updated_info'] += 1
                                        current_app.logger.info(f"CSV Import: Updated info for existing card ID {final_card_id} (Name: {card_name}, Rare: {converted_rarity}, Category: {category_name_from_file})")
                                    else:
                                        file_summary['skipped_no_change'] +=1
                                else:
                                    # Item does not exist, insert new item with stock from CSV
                                    cur.execute("""
                                        INSERT INTO items (name, card_id, rare, stock, category)
                                        VALUES (%s, %s, %s, %s, %s)
                                    """, (card_name, final_card_id, converted_rarity, stock_csv, category_name_from_file))
                                    file_summary['added'] += 1
                                    current_app.logger.info(f"CSV Import: Added new card. Name: {card_name}, CardID: '{final_card_id or 'N/A'}', Stock: {stock_csv}")
                            
                        # Commit changes for the current file if no major errors occurred during its processing
                        conn_outer.commit() 
                        current_app.logger.info(f"File '{filename}' processed and committed. Summary: {file_summary}")

                    # Handle errors specific to this file's processing
                    except UnicodeDecodeError as e_decode:
                        conn_outer.rollback() # Rollback changes for this file
                        err_msg = f"文字コードエラー: {e_decode}。UTF-8 (BOM付き推奨) を確認してください。"
                        current_app.logger.error(f"Error processing file '{filename}': {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_file_details: error_file_details[filename] = []
                        error_file_details[filename].append(err_msg)
                        file_summary['skipped_error'] += file_summary['rows_processed'] # Assume all rows in this file failed
                        file_summary['rows_processed'] = 0 # Reset for this file
                    except csv.Error as e_csv: 
                        conn_outer.rollback()
                        err_msg = f"CSV解析エラー (行 {current_csv_row_num} 付近): {e_csv}"
                        current_app.logger.error(f"Error processing file '{filename}': {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_file_details: error_file_details[filename] = []
                        error_file_details[filename].append(err_msg)
                        file_summary['skipped_error'] += (file_summary['rows_processed'] - (file_summary['added'] + file_summary['updated_info'] + file_summary['skipped_no_change']))
                    except psycopg2.Error as e_db_file: # DB error during this file's transaction
                        conn_outer.rollback()
                        err_msg = f"DBエラー (ファイル '{filename}' 行 {current_csv_row_num} 付近): {e_db_file}"
                        current_app.logger.error(f"DB Error processing file '{filename}': {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_file_details: error_file_details[filename] = []
                        error_file_details[filename].append(err_msg)
                        file_summary['skipped_error'] += (file_summary['rows_processed'] - (file_summary['added'] + file_summary['updated_info'] + file_summary['skipped_no_change']))
                    except Exception as e_general_file:
                        conn_outer.rollback()
                        err_msg = f"予期せぬエラー (ファイル '{filename}' 行 {current_csv_row_num} 付近): {e_general_file}"
                        current_app.logger.error(f"General Error processing file '{filename}': {err_msg}\n{traceback.format_exc()}")
                        if filename not in error_file_details: error_file_details[filename] = []
                        error_file_details[filename].append(err_msg)
                        file_summary['skipped_error'] += (file_summary['rows_processed'] - (file_summary['added'] + file_summary['updated_info'] + file_summary['skipped_no_change']))
                    finally:
                        # Aggregate file summary to overall summary
                        overall_summary['added'] += file_summary['added']
                        overall_summary['updated_info'] += file_summary['updated_info']
                        overall_summary['skipped_no_change'] += file_summary['skipped_no_change']
                        overall_summary['skipped_error'] += file_summary['skipped_error']
                        overall_summary['rows_processed'] += file_summary['rows_processed']

                elif file_obj and not allowed_file(file_obj.filename): 
                    err_msg = f"拡張子不正 ({os.path.splitext(file_obj.filename)[1]})。CSVファイルのみ許可されています。"
                    current_app.logger.warning(f"File '{file_obj.filename}' skipped: {err_msg}")
                    if file_obj.filename not in error_file_details: error_file_details[file_obj.filename] = []
                    error_file_details[file_obj.filename].append(err_msg)
            
            # After processing all files
            summary_msg_parts = [f"CSVインポート処理完了。処理ファイル数: {total_files_processed}。"]
            summary_msg_parts.append(f"総行数: {overall_summary['rows_processed']}。")
            summary_msg_parts.append(f"追加: {overall_summary['added']}件。")
            summary_msg_parts.append(f"情報更新: {overall_summary['updated_info']}件。")
            summary_msg_parts.append(f"変更なしスキップ: {overall_summary['skipped_no_change']}件。")
            summary_msg_parts.append(f"エラースキップ: {overall_summary['skipped_error']}件。")

            if error_file_details:
                summary_msg_parts.append("エラー詳細:")
                for fname, reasons in error_file_details.items():
                    summary_msg_parts.append(f"  ファイル '{fname}': {'; '.join(reasons)}")
                flash_category = 'warning'
            else:
                flash_category = 'success'
            
            final_summary_message = " ".join(summary_msg_parts)
            flash(final_summary_message, flash_category)
            current_app.logger.info(f"CSV Import Overall Summary: {final_summary_message}")

        except psycopg2.Error as e_db_outer: # Error with the main connection itself
            # No rollback needed here as individual file transactions should handle it,
            # or the connection itself failed.
            error_message = f"CSVインポート処理中にデータベース接続エラーが発生しました: {e_db_outer}"
            current_app.logger.error(f"Outer DB Error during CSV import: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        except Exception as e_general_outer:
            error_message = f"CSVインポート処理中に予期せぬエラーが発生しました: {e_general_outer}"
            current_app.logger.error(f"Outer General Error during CSV import: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn_outer and not conn_outer.closed:
                conn_outer.close()
        
        return redirect(url_for('admin.admin_import_csv'))

    # GET request
    return render_template('admin/admin_import_csv.html')

