# app/main.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app, abort, make_response
)
import psycopg2 # Keep for specific error types if needed, but db connection is from db.py
import psycopg2.extras
import traceback # For detailed error logging
import csv
import io
import datetime

from app.db import get_db_connection # Import the centralized db connection function
from app.auth import login_required # Import the login_required decorator
# Import data definitions (rarities, conversion map)
from app.data_definitions import DEFINED_RARITIES, RARITY_CONVERSION_MAP

bp = Blueprint('main', __name__) # No url_prefix, as it's the main part of the app

def card_id_in_results(items, keyword):
    """
    Checks if the given keyword (presumably a card_id) exists in the card_id field of any item in the results.
    """
    if not items or not keyword:
        return False
    for item in items:
        if item and 'card_id' in item and isinstance(item['card_id'], str):
            if keyword.lower() in item['card_id'].lower():
                return True
    return False

def get_items_from_db(show_zero=True, keyword=None, sort_by="name", sort_order="asc"):
    """
    Retrieves items from the database based on filter, search, and sort criteria.
    Uses pykakasi for Japanese keyword conversion.
    """
    valid_sort_keys = ["name", "card_id", "rare", "stock", "id", "category"]
    if sort_by not in valid_sort_keys:
        sort_by = "name"
    if sort_order.lower() not in ["asc", "desc"]:
        sort_order = "asc"

    conn = None
    items_result = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query_base = "SELECT * FROM items"
        conditions = []
        params = []

        if not show_zero:
            conditions.append("stock > 0")
        
        if keyword:
            keyword_lower = keyword.lower()
            keyword_lower_like = f"%{keyword_lower}%"
            
            # Get pykakasi converters from the application context
            kks_hira_converter = current_app.kks_hira_converter
            kks_kata_converter = current_app.kks_kata_converter

            hira_result = kks_hira_converter.convert(keyword)
            keyword_hira = "".join([item['hira'] for item in hira_result])
            keyword_hira_like = f"%{keyword_hira.lower()}%" if keyword_hira else None

            kata_result = kks_kata_converter.convert(keyword)
            keyword_kata = "".join([item['kana'] for item in kata_result])
            keyword_kata_like = f"%{keyword_kata.lower()}%" if keyword_kata else None
            
            name_conditions_list = []
            name_params_list = []
            
            name_conditions_list.append("LOWER(name) LIKE %s")
            name_params_list.append(keyword_lower_like)
            
            if keyword_hira_like and keyword_hira.lower() != keyword_lower:
                name_conditions_list.append("LOWER(name) LIKE %s") 
                name_params_list.append(keyword_hira_like)
            
            if keyword_kata_like and keyword_kata.lower() != keyword_lower and \
               (not keyword_hira or keyword_kata.lower() != keyword_hira.lower()):
                name_conditions_list.append("LOWER(name) LIKE %s")
                name_params_list.append(keyword_kata_like)

            name_search_clause_str = "(" + " OR ".join(name_conditions_list) + ")"
            
            other_column_conditions = [
                "LOWER(card_id) LIKE %s",
                "LOWER(rare) LIKE %s",
                "LOWER(category) LIKE %s"
            ]
            # Check if keyword can be an ID (integer)
            # This part might need adjustment if card_id is not always numeric or if searching by primary key 'id'
            # For now, assuming keyword might also be a string representation of 'id'
            try:
                keyword_as_int = int(keyword)
                other_column_conditions.append("id = %s") # Search by primary key if keyword is integer
                other_column_params = [keyword_lower_like] * (len(other_column_conditions) -1) + [keyword_as_int]

            except ValueError:
                 other_column_params = [keyword_lower_like] * len(other_column_conditions)


            all_search_conditions = [name_search_clause_str] + other_column_conditions
            conditions.append("(" + " OR ".join(all_search_conditions) + ")")
            params.extend(name_params_list)
            params.extend(other_column_params)
        
        if conditions:
            query_base += " WHERE " + " AND ".join(conditions)
        
        query_base += f" ORDER BY {sort_by} {sort_order.upper()}"
        
        cur.execute(query_base, tuple(params))
        items_result = cur.fetchall()
        current_app.logger.debug(f"Executed query: {cur.query.decode() if cur.query else 'N/A'} with params: {params}")

    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Database error in get_items_from_db: {e}\n{traceback.format_exc()}")
        flash("データベースからのアイテム取得中にエラーが発生しました。", "danger")
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                 cur.close()
            conn.close()
    return items_result

@bp.route('/')
def index():
    """
    Main page displaying the list of items with pagination, search, and sort.
    """
    per_page = int(request.args.get('per_page', 20)) # Default to 20 items per page
    page = int(request.args.get('page', 1))
    show_zero = request.args.get('show_zero') == 'on'
    keyword = request.args.get('keyword', '').strip()
    sort_by = request.args.get('sort_key', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    items = get_items_from_db(show_zero, keyword, sort_by, sort_order)
    total_items_count = len(items)
    
    if per_page <= 0: # Show all items if per_page is 0 or negative
        paginated_items = items
        total_pages = 1 if total_items_count > 0 else 0
    else:
        paginated_items = items[(page - 1) * per_page : page * per_page]
        total_pages = (total_items_count + per_page - 1) // per_page if per_page > 0 else 1
    
    if page > total_pages and total_pages > 0 : # If requested page is out of bounds
        page = total_pages # Go to last page
        if per_page > 0:
            paginated_items = items[(page - 1) * per_page : page * per_page]


    show_add_hint = False
    if keyword and paginated_items:
        has_exact_card_id = card_id_in_results(paginated_items, keyword)
        show_add_hint = not has_exact_card_id
    elif keyword and not paginated_items: # Keyword searched but no results
        show_add_hint = True


    return render_template('main/index.html',
                           items=paginated_items,
                           per_page=per_page,
                           page=page,
                           total_pages=total_pages,
                           total_items=total_items_count,
                           show_zero=show_zero,
                           keyword=keyword,
                           sort_key=sort_by,
                           sort_order=sort_order,
                           show_add_hint=show_add_hint)


@bp.route('/add', methods=('GET', 'POST'))
@login_required
def add_item():
    """
    Handles adding a new item.
    GET: Displays the form to add an item.
    POST: Processes the form submission and adds the item to the database.
    """
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        card_id = request.form.get('card_id', '').strip()
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        
        stock_str = request.form.get('stock', '0').strip()
        try:
            stock = int(stock_str) if stock_str.isdigit() else 0
        except ValueError:
            stock = 0 # Default to 0 if conversion fails
            flash('在庫数には数値を入力してください。0として登録します。', 'warning')
        
        category = request.form.get('category', '').strip()

        error_occurred = False
        if not name:
            flash('名前は必須です。', 'danger')
            error_occurred = True
        if not rare: # rare_select might be empty if no selection is made
            flash('レアリティを選択または入力してください。', 'danger')
            error_occurred = True
        
        if error_occurred:
            # Re-render form with user's previous input and error messages
            return render_template('main/add_item.html', 
                                   prefill_name=name,
                                   prefill_card_id=card_id,
                                   prefill_category=category,
                                   prefill_stock=stock_str,
                                   rarities=DEFINED_RARITIES,
                                   selected_rarity=rare_select,
                                   custom_rarity_value=rare_custom)

        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            final_card_id = card_id if card_id else '' # Ensure empty string if not provided, not None
            
            cur.execute("""
                INSERT INTO items (name, card_id, rare, stock, category)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, final_card_id, rare, stock, category if category else None)) # Use None for empty category
            conn.commit()
            flash(f'商品「{name}」が追加されました。', 'success')
            current_app.logger.info(f"Item added: Name='{name}', CardID='{final_card_id}', Rare='{rare}'")
            return redirect(url_for('main.index'))
        except psycopg2.IntegrityError as e:
            conn.rollback()
            # More specific error for unique constraint violation if card_id is unique
            if 'items_card_id_key' in str(e) or 'unique constraint' in str(e).lower() and 'card_id' in str(e).lower():
                 error_message = f"データベース登録エラー: カードID「{final_card_id}」は既に存在する可能性があります。"
            else:
                error_message = f"データベース登録エラー: {e}"
            current_app.logger.error(f"IntegrityError adding item: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        except (psycopg2.Error, Exception) as e:
            if conn: conn.rollback()
            error_message = f"データベース登録エラー (カード名: {name}): {e}"
            current_app.logger.error(f"Error adding item: {error_message}\n{traceback.format_exc()}")
            flash(error_message, 'danger')
        finally:
            if conn:
                if 'cur' in locals() and cur and not cur.closed:
                    cur.close()
                conn.close()
        
        # If an error occurred and wasn't redirected, re-render form with data
        return render_template('main/add_item.html', 
                               prefill_name=name,
                               prefill_card_id=card_id,
                               prefill_category=category,
                               prefill_stock=stock_str,
                               rarities=DEFINED_RARITIES,
                               selected_rarity=rare_select,
                               custom_rarity_value=rare_custom)

    # GET request
    name_prefill = request.args.get('name', '') # For prefilling from index page hint
    card_id_prefill = request.args.get('card_id', '') # For prefilling from index page hint
    return render_template('main/add_item.html', 
                           prefill_name=name_prefill,
                           prefill_card_id=card_id_prefill,
                           rarities=DEFINED_RARITIES)


@bp.route('/edit/<int:item_id>', methods=('GET', 'POST'))
@login_required
def edit_item(item_id):
    """
    Handles editing an existing item.
    GET: Displays the form pre-filled with the item's data.
    POST: Processes the form submission and updates the item in the database.
    """
    conn = None
    item_for_render = None

    # Fetch item for GET request or if POST fails and needs re-rendering
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
        item_for_render = cur.fetchone()
    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Error fetching item {item_id} for edit: {e}\n{traceback.format_exc()}")
        flash("商品情報の取得中にエラーが発生しました。", "danger")
        return redirect(url_for('main.index'))
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close() # Close connection after initial fetch

    if not item_for_render:
        abort(404, description=f"商品ID {item_id} が見つかりませんでした。")

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        # card_id is not editable in this form, so we use the one from item_for_render
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        
        stock_str = request.form.get('stock', '0').strip()
        try:
            stock = int(stock_str) if stock_str.isdigit() else 0
        except ValueError:
            stock = item_for_render['stock'] # Keep original stock if input is invalid
            flash('在庫数に不正な値が入力されました。元の在庫数を維持します。', 'warning')

        category = request.form.get('category', '').strip()

        error_occurred_edit = False
        if not name:
            flash('名前は必須です。', 'danger')
            error_occurred_edit = True
        if not rare:
            flash('レアリティを選択または入力してください。', 'danger')
            error_occurred_edit = True
        
        if not error_occurred_edit:
            conn_update = None
            try:
                conn_update = get_db_connection()
                cur_update = conn_update.cursor()
                cur_update.execute("""
                    UPDATE items
                       SET name = %s,
                           rare = %s,
                           stock = %s,
                           category = %s
                     WHERE id = %s
                """, (name, rare, stock, category if category else None, item_id))
                conn_update.commit()
                flash('商品情報が更新されました。', 'success')
                current_app.logger.info(f"Item updated: ID={item_id}, Name='{name}'")
                return redirect(url_for('main.index'))
            except (psycopg2.Error, Exception) as e:
                if conn_update: conn_update.rollback()
                error_message = f"データベース更新エラー (商品ID: {item_id}): {e}"
                current_app.logger.error(f"Error updating item: {error_message}\n{traceback.format_exc()}")
                flash(error_message, 'danger')
            finally:
                if conn_update:
                    if 'cur_update' in locals() and cur_update and not cur_update.closed:
                         cur_update.close()
                    conn_update.close()
        
        # If POST had errors or DB update failed, re-render with submitted (potentially flawed) data
        # but ensure item_for_render is up-to-date for card_id display
        # We already have item_for_render from the top of the function
        # Update it with form values for re-rendering if necessary
        temp_item_data_for_form = dict(item_for_render) # Make a mutable copy
        temp_item_data_for_form.update({
            'name': name,
            'rare': rare, # This will be used to re-select in dropdown or fill custom
            'stock': stock_str, # Show what user typed
            'category': category
        })
        return render_template('main/edit_item.html', 
                               item=temp_item_data_for_form, 
                               rarities=DEFINED_RARITIES)

    # GET request: item_for_render was fetched at the beginning
    return render_template('main/edit_item.html', item=item_for_render, rarities=DEFINED_RARITIES)


@bp.route('/delete/<int:item_id>/confirm', methods=('GET',))
@login_required
def confirm_delete_item(item_id):
    """Displays a confirmation page before deleting an item."""
    conn = None
    item = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
        item = cur.fetchone()
    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Error fetching item {item_id} for delete confirmation: {e}\n{traceback.format_exc()}")
        flash("商品情報の取得中にエラーが発生しました。", "danger")
        return redirect(url_for('main.index'))
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()
            
    if not item:
        abort(404, description=f"商品ID {item_id} が見つかりませんでした。")
    return render_template('main/confirm_delete.html', item=item)


@bp.route('/delete/<int:item_id>', methods=('POST',))
@login_required
def delete_item(item_id):
    """Deletes an item from the database."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM items WHERE id = %s", (item_id,)) # Get name for flash message
        item_name_tuple = cur.fetchone()
        item_name = item_name_tuple['name'] if item_name_tuple else f"ID {item_id}"

        cur.execute("DELETE FROM items WHERE id = %s", (item_id,))
        conn.commit()
        flash(f'商品「{item_name}」が削除されました。', 'info')
        current_app.logger.info(f"Item deleted: ID={item_id}, Name='{item_name}'")
    except (psycopg2.Error, Exception) as e:
        if conn: conn.rollback()
        error_message = f"データベース削除エラー (商品ID: {item_id}): {e}"
        current_app.logger.error(f"Error deleting item: {error_message}\n{traceback.format_exc()}")
        flash(error_message, 'danger')
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()
    return redirect(url_for('main.index'))


@bp.route('/update_stock/<int:item_id>', methods=('POST',))
@login_required
def update_stock(item_id):
    """Updates the stock of an item by a given delta (+1 or -1)."""
    try:
        delta = int(request.form.get('delta'))
    except (ValueError, TypeError):
        flash('不正な在庫更新リクエストです。', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    if delta not in [1, -1]: # Only allow +1 or -1
        flash('不正な在庫変更値です。', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Use FOR UPDATE to lock the row if concurrent updates are a concern, though less critical here.
        cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
        result = cur.fetchone()
        
        if not result:
            flash("商品が見つかりません。", 'warning')
        else:
            new_stock = result['stock'] + delta
            if new_stock < 0:
                # flash('在庫数が0未満になるため、操作はキャンセルされました。', 'warning')
                # Instead of flashing, just set stock to 0 if delta is -1 and stock is 0
                new_stock = 0
                if delta == -1 and result['stock'] == 0:
                     pass # Do nothing if trying to decrement a zero stock
                else: # Allow decrementing to 0
                    cur.execute("UPDATE items SET stock = %s WHERE id = %s", (new_stock, item_id))
                    conn.commit()
                    current_app.logger.info(f"Stock updated for item ID {item_id} to {new_stock}")
            else:
                cur.execute("UPDATE items SET stock = %s WHERE id = %s", (new_stock, item_id))
                conn.commit()
                current_app.logger.info(f"Stock updated for item ID {item_id} to {new_stock}")

    except (psycopg2.Error, Exception) as e:
        if conn: conn.rollback()
        error_message = f"在庫更新エラー (商品ID: {item_id}): {e}"
        current_app.logger.error(f"Error updating stock: {error_message}\n{traceback.format_exc()}")
        flash(error_message, 'danger')
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()
            
    return redirect(request.referrer or url_for('main.index'))


@bp.route('/download_csv')
@login_required
def download_csv():
    """Generates and serves a CSV file of all items in the inventory."""
    conn = None
    items = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name, card_id, rare, stock, category FROM items ORDER BY id")
        items = cur.fetchall()
    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Error fetching items for CSV download: {e}\n{traceback.format_exc()}")
        flash("CSVエクスポート用のデータ取得中にエラーが発生しました。", "danger")
        return redirect(url_for('main.index'))
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                cur.close()
            conn.close()

    si = io.StringIO()
    # Add BOM for Excel to correctly interpret UTF-8
    si.write('\ufeff') 
    cw = csv.writer(si)
    
    headers = ['ID', '名前', 'カードID', 'レアリティ', '在庫数', 'カテゴリ']
    # These keys must match the SELECT query order/names if using DictCursor, or column indices
    column_keys = ['id', 'name', 'card_id', 'rare', 'stock', 'category']
    cw.writerow(headers)

    for item_dict in items: # items are DictRow objects
        row_data = [item_dict[key] if item_dict[key] is not None else '' for key in column_keys]
        cw.writerow(row_data)

    output = make_response(si.getvalue())
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"yugioh_inventory_backup_{timestamp}.csv"
    output.headers["Content-Disposition"] = f"attachment; filename=\"{filename}\"" # Ensure filename is quoted
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    current_app.logger.info(f"CSV download generated: {filename}")
    return output

