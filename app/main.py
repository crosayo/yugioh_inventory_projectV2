# app/main.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app, abort, make_response
)
import psycopg2
import psycopg2.extras
import traceback
import csv
import io
import datetime

from app.db import get_db_connection
from app.auth import login_required
from app.data_definitions import DEFINED_RARITIES, RARITY_CONVERSION_MAP, ERA_DEFINITIONS, ERA_DISPLAY_NAMES, ERA_DISPLAY_ORDER

bp = Blueprint('main', __name__)

def card_id_in_results(items, keyword):
    # (この関数は変更ありません)
    if not items or not keyword:
        return False
    for item in items:
        if item and 'card_id' in item and isinstance(item['card_id'], str):
            if keyword.lower() in item['card_id'].lower():
                return True
    return False

# --- ▼▼▼ get_items_from_db 関数のクエリを修正 ▼▼▼ ---
def get_items_from_db(show_zero=True, keyword=None, sort_by="release_date", sort_order="desc"):
    conn = None
    items_result = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # itemsのcategoryを主とし、productsの情報を付加する形にクエリを修正
        query_base = """
            SELECT
                i.id,
                i.name,
                i.card_id,
                i.rare,
                i.stock,
                i.category,  -- itemsテーブルのカテゴリ名を常に取得
                p.release_date,
                p.era,
                p.display_name,
                p.show_in_sidebar
            FROM items i
            LEFT JOIN products p ON i.category = p.name
        """
        
        conditions = []
        params = []

        if not show_zero:
            conditions.append("i.stock > 0")
        
        if keyword:
            keyword_lower_like = f"%{keyword.lower()}%"
            keyword_conditions = [
                "LOWER(i.name) LIKE %s",
                "LOWER(i.card_id) LIKE %s",
                "LOWER(i.rare) LIKE %s",
                "LOWER(i.category) LIKE %s" # i.category を検索対象に
            ]
            conditions.append(f"({' OR '.join(keyword_conditions)})")
            params.extend([keyword_lower_like] * 4)

        if conditions:
            query_base += " WHERE " + " AND ".join(conditions)
        
        valid_sort_keys = ["name", "card_id", "rare", "stock", "id", "category", "release_date"]
        if sort_by not in valid_sort_keys:
            sort_by = "release_date"
        if sort_order.lower() not in ["asc", "desc"]:
            sort_order = "desc"

        if sort_by == "release_date":
            query_base += f" ORDER BY p.release_date {sort_order.upper()} NULLS LAST, i.name ASC"
        else:
            # categoryでソートする場合は、itemsテーブルのcategoryカラムを使う
            sort_column = f"i.{sort_by}"
            query_base += f" ORDER BY {sort_column} {sort_order.upper()}, i.name ASC"

        cur.execute(query_base, tuple(params))
        items_result = cur.fetchall()
        
        current_app.logger.debug(f"Executed query: {cur.query.decode() if cur.query else 'N/A'}")

    except (psycopg2.Error, Exception) as e:
        current_app.logger.error(f"Database error in get_items_from_db: {e}\n{traceback.format_exc()}")
        flash("データベースからのアイテム取得中にエラーが発生しました。", "danger")
    finally:
        if conn:
            if 'cur' in locals() and cur and not cur.closed:
                 cur.close()
            conn.close()
    return items_result
# --- ▲▲▲ get_items_from_db 関数のクエリを修正 ▲▲▲ ---

@bp.route('/')
def index():
    per_page = int(request.args.get('per_page', 20))
    page = int(request.args.get('page', 1))
    show_zero = request.args.get('show_zero') == 'on'
    keyword = request.args.get('keyword', '').strip()
    sort_by = request.args.get('sort_key', 'release_date')
    sort_order = request.args.get('sort_order', 'desc')

    all_items = get_items_from_db(show_zero, keyword, sort_by, sort_order)
    total_items_count = len(all_items)

    if per_page > 0:
        start = (page - 1) * per_page
        end = start + per_page
        paginated_items = all_items[start:end]
        total_pages = (total_items_count + per_page - 1) // per_page
    else:
        paginated_items = all_items
        total_pages = 1 if total_items_count > 0 else 0
    
    if page > total_pages and total_pages > 0:
        page = total_pages
        if per_page > 0:
            start = (page - 1) * per_page
            end = start + per_page
            paginated_items = all_items[start:end]

    show_add_hint = False
    if keyword and not all_items:
        show_add_hint = True
    
    # テンプレートに渡す変数名を 'items' に統一
    return render_template('main/index.html',
                           items=paginated_items,
                           page=page,
                           per_page=per_page,
                           total_pages=total_pages,
                           total_items=total_items_count,
                           show_zero=show_zero,
                           keyword=keyword,
                           sort_key=sort_by,
                           sort_order=sort_order,
                           show_add_hint=show_add_hint)


# (add_item, edit_item, などの残りの関数は変更ありません。元のコードのままです)
# ... (元のmain.pyのadd_item以降の関数をここに貼り付け) ...
@bp.route('/add', methods=('GET', 'POST'))
@login_required
def add_item():
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
            stock = 0
            flash('在庫数には数値を入力してください。0として登録します。', 'warning')
        
        category = request.form.get('category', '').strip()

        error_occurred = False
        if not name:
            flash('名前は必須です。', 'danger')
            error_occurred = True
        if not rare:
            flash('レアリティを選択または入力してください。', 'danger')
            error_occurred = True
        
        if error_occurred:
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
            final_card_id = card_id if card_id else None
            
            cur.execute("""
                INSERT INTO items (name, card_id, rare, stock, category)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, final_card_id, rare, stock, category if category else None))
            conn.commit()
            flash(f'商品「{name}」が追加されました。', 'success')
            current_app.logger.info(f"Item added: Name='{name}', CardID='{final_card_id}', Rare='{rare}'")
            return redirect(url_for('main.index'))
        except psycopg2.IntegrityError as e:
            conn.rollback()
            constraint_name_from_error = getattr(getattr(e, 'diag', None), 'constraint_name', '')

            if 'unique_card_id_rare' in str(e).lower() or \
               (constraint_name_from_error and 'unique_card_id_rare' in constraint_name_from_error.lower()):
                error_message = f"データベース登録エラー: カードID「{final_card_id or '(未設定)'}」とレアリティ「{rare}」の組み合わせは既に登録されています。"
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
        
        return render_template('main/add_item.html', 
                               prefill_name=name,
                               prefill_card_id=card_id,
                               prefill_category=category,
                               prefill_stock=stock_str,
                               rarities=DEFINED_RARITIES,
                               selected_rarity=rare_select,
                               custom_rarity_value=rare_custom)

    name_prefill = request.args.get('name', '')
    card_id_prefill = request.args.get('card_id', '')
    return render_template('main/add_item.html', 
                           prefill_name=name_prefill,
                           prefill_card_id=card_id_prefill,
                           rarities=DEFINED_RARITIES)


@bp.route('/edit/<int:item_id>', methods=('GET', 'POST'))
@login_required
def edit_item(item_id):
    conn = None
    item_for_render = None

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
            conn.close()

    if not item_for_render:
        abort(404, description=f"商品ID {item_id} が見つかりませんでした。")

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        new_rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        
        stock_str = request.form.get('stock', '0').strip()
        try:
            stock = int(stock_str) if stock_str.isdigit() else 0
        except ValueError:
            stock = item_for_render['stock']
            flash('在庫数に不正な値が入力されました。元の在庫数を維持します。', 'warning')

        category = request.form.get('category', '').strip()

        error_occurred_edit = False
        if not name:
            flash('名前は必須です。', 'danger')
            error_occurred_edit = True
        if not new_rare:
            flash('レアリティを選択または入力してください。', 'danger')
            error_occurred_edit = True
        
        if not error_occurred_edit and item_for_render['rare'] != new_rare:
            conn_check = None
            try:
                conn_check = get_db_connection()
                cur_check = conn_check.cursor()
                query_check_duplicate = "SELECT id FROM items WHERE card_id = %s AND rare = %s AND id != %s"
                params_check_duplicate = [item_for_render['card_id'], new_rare, item_id]
                if item_for_render['card_id'] is None:
                    query_check_duplicate = "SELECT id FROM items WHERE card_id IS NULL AND rare = %s AND id != %s"
                    params_check_duplicate = [new_rare, item_id]
                
                cur_check.execute(query_check_duplicate, tuple(params_check_duplicate))
                if cur_check.fetchone():
                    flash(f"更新エラー: カードID「{item_for_render['card_id'] or '(未設定)'}」と新しいレアリティ「{new_rare}」の組み合わせは既に他のカードで存在します。", "danger")
                    error_occurred_edit = True
            except (psycopg2.Error, Exception) as e_check:
                flash(f"重複チェック中にエラーが発生しました: {e_check}", "danger")
                error_occurred_edit = True
            finally:
                if conn_check:
                    if 'cur_check' in locals() and cur_check and not cur_check.closed: cur_check.close()
                    conn_check.close()

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
                """, (name, new_rare, stock, category if category else None, item_id))
                conn_update.commit()
                flash('商品情報が更新されました。', 'success')
                current_app.logger.info(f"Item updated: ID={item_id}, Name='{name}', Rare='{new_rare}'")
                return redirect(url_for('main.index'))
            except psycopg2.IntegrityError as e_int:
                 if conn_update: conn_update.rollback()
                 error_message = f"データベース更新エラー: カードID「{item_for_render['card_id'] or '(未設定)'}」とレアリティ「{new_rare}」の組み合わせが既に存在する可能性があります。"
                 current_app.logger.error(f"IntegrityError updating item {item_id}: {e_int}\n{traceback.format_exc()}")
                 flash(error_message, 'danger')
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
        
        temp_item_data_for_form = dict(item_for_render)
        temp_item_data_for_form.update({
            'name': name,
            'rare': new_rare,
            'stock': stock_str,
            'category': category
        })
        return render_template('main/edit_item.html', 
                               item=temp_item_data_for_form, 
                               rarities=DEFINED_RARITIES)

    return render_template('main/edit_item.html', item=item_for_render, rarities=DEFINED_RARITIES)


@bp.route('/delete/<int:item_id>/confirm', methods=('GET',))
@login_required
def confirm_delete_item(item_id):
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
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM items WHERE id = %s", (item_id,))
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
    try:
        delta = int(request.form.get('delta'))
    except (ValueError, TypeError):
        flash('不正な在庫更新リクエストです。', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    if delta not in [1, -1]:
        flash('不正な在庫変更値です。', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
        result = cur.fetchone()
        
        if not result:
            flash("商品が見つかりません。", 'warning')
        else:
            new_stock = result['stock'] + delta
            if new_stock < 0:
                new_stock = 0
                if delta == -1 and result['stock'] == 0:
                     pass
                else:
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
    conn = None
    items = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # カテゴリ情報も取得するためにJOIN
        cur.execute("""
            SELECT 
                i.id, i.name, i.card_id, i.rare, i.stock, i.category
            FROM items i
            ORDER BY i.id
        """)
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
    si.write('\ufeff') 
    cw = csv.writer(si)
    
    headers = ['ID', '名前', 'カードID', 'レアリティ', '在庫数', 'カテゴリ']
    column_keys = ['id', 'name', 'card_id', 'rare', 'stock', 'category']
    cw.writerow(headers)

    for item_dict in items:
        row_data = [item_dict[key] if item_dict[key] is not None else '' for key in column_keys]
        cw.writerow(row_data)

    output = make_response(si.getvalue())
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"yugioh_inventory_backup_{timestamp}.csv"
    output.headers["Content-Disposition"] = f"attachment; filename=\"{filename}\""
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    current_app.logger.info(f"CSV download generated: {filename}")
    return output