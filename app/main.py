# app/main.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app, abort, make_response, jsonify
)
import psycopg2
import psycopg2.extras
import traceback
import csv
import io
import datetime

# --- ここから修正 ---
# db, auth, utilsモジュールと、新しくconfigモジュールをインポート
from . import db, config
from .auth import login_required
from .utils import normalize_for_search
# data_definitionsは不要になったので削除
# --- ここまで修正 ---


bp = Blueprint('main', __name__)

def get_all_product_names():
    conn = None
    names = []
    try:
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM products WHERE name IS NOT NULL AND name != '' ORDER BY name ASC")
        names = [row['name'] for row in cur.fetchall()]
    except (Exception, psycopg2.Error) as error:
        current_app.logger.error(f"Error fetching all product names: {error}")
    finally:
        if conn:
            if 'cur' in locals() and not cur.closed:
                cur.close()
            conn.close()
    return names

def get_items_from_db(show_zero=True, keyword=None, search_field='all', sort_by="release_date", sort_order="desc", category=None):
    conn = None
    items_result = []
    try:
        conn = db.get_db_connection()
        cur = conn.cursor()
        
        query_base = """
            SELECT
                i.id, i.name, i.card_id, i.rare, i.stock, i.category,
                p.release_date, p.era, p.display_name, p.show_in_sidebar
            FROM items i
            LEFT JOIN products p ON LOWER(TRIM(i.category)) = LOWER(TRIM(p.name))
        """
        
        conditions = []
        params = []

        if not show_zero:
            conditions.append("i.stock > 0")
        
        if category:
            conditions.append("i.category = %s")
            params.append(category)

        if keyword:
            normalized_keyword = normalize_for_search(keyword)
            keyword_like = f"%{normalized_keyword}%"
            
            if search_field == 'name':
                conditions.append("i.name_normalized LIKE %s")
                params.append(keyword_like)
            elif search_field == 'card_id':
                conditions.append("i.card_id_normalized LIKE %s")
                params.append(keyword_like)
            elif search_field == 'category':
                conditions.append("LOWER(i.category) LIKE %s")
                params.append(f"%{keyword.lower()}%")
            elif search_field == 'rare':
                conditions.append("LOWER(i.rare) LIKE %s")
                params.append(f"%{keyword.lower()}%")
            else: # 'all'
                keyword_conditions = [
                    "i.name_normalized LIKE %s",
                    "i.card_id_normalized LIKE %s",
                    "LOWER(i.rare) LIKE %s",
                    "LOWER(i.category) LIKE %s"
                ]
                conditions.append(f"({' OR '.join(keyword_conditions)})")
                params.extend([keyword_like, keyword_like, f"%{keyword.lower()}%", f"%{keyword.lower()}%"])

        if conditions:
            query_base += " WHERE " + " AND ".join(conditions)
        
        valid_sort_keys = ["name", "card_id", "rare", "stock", "id", "category", "release_date"]
        if sort_by not in valid_sort_keys:
            sort_by = "release_date"
        if sort_order.lower() not in ["asc", "desc"]:
            sort_order = "desc"

        if sort_by == "release_date":
            query_base += f" ORDER BY CAST(p.release_date AS DATE) {sort_order.upper()} NULLS LAST, i.name ASC"
        else:
            sort_column = f"i.{sort_by}"
            query_base += f" ORDER BY {sort_column} {sort_order.upper()}, i.name ASC"

        cur.execute(query_base, tuple(params))
        items_result = cur.fetchall()
        
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
    # --- ここから修正 ---
    # デフォルト値をconfigから読み込むように変更
    per_page = int(request.args.get('per_page', config.DEFAULT_PER_PAGE))
    page = int(request.args.get('page', 1))
    show_zero = request.args.get('show_zero') == 'on'
    keyword = request.args.get('keyword', '').strip()
    search_field = request.args.get('search_field', 'all')
    sort_by = request.args.get('sort_key', config.DEFAULT_SORT_KEY)
    sort_order = request.args.get('sort_order', config.DEFAULT_SORT_ORDER)
    category_filter = request.args.get('category', None)
    # --- ここまで修正 ---

    all_items = get_items_from_db(show_zero, keyword, search_field, sort_by, sort_order, category_filter)
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

    return render_template('main/index.html',
                           items=paginated_items,
                           page=page,
                           per_page=per_page,
                           total_pages=total_pages,
                           total_items=total_items_count,
                           show_zero=show_zero,
                           keyword=keyword,
                           search_field=search_field,
                           sort_key=sort_by,
                           sort_order=sort_order,
                           category_filter=category_filter)

@bp.route('/add_variant/<int:id>')
@login_required
def add_item_variant(id):
    """ 既存のアイテムに基づいて新しいアイテムを追加する（別レアリティ追加用） """
    conn = None
    item_data = {}

    try:
        conn = db.get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT name, card_id, category FROM items WHERE id = %s', (id,))
        item = cursor.fetchone()
        
        if item is None:
            flash('元のアイテムが見つかりませんでした。', 'error')
            return redirect(url_for('main.index'))

        item_data = {
            'name': item['name'],
            'card_id': item['card_id'],
            'category': item['category'],
            'rare': '',
            'stock': 1
        }

    except (Exception, psycopg2.Error) as error:
        current_app.logger.error(f"Error in add_item_variant: {error}")
        flash('アイテムの読み込み中にエラーが発生しました。', 'danger')
        return redirect(url_for('main.index'))
    finally:
        if conn:
            if 'cursor' in locals() and not cursor.closed:
                cursor.close()
            conn.close()

    # --- ここから修正 ---
    # raritiesをconfigから読み込むように変更
    return render_template('main/add_item.html',
                           prefill_name=item_data.get('name'),
                           prefill_card_id=item_data.get('card_id'),
                           prefill_category=item_data.get('category'),
                           prefill_stock=item_data.get('stock', 1),
                           rarities=config.DEFINED_RARITIES,
                           product_names=get_all_product_names()
                           )
    # --- ここまで修正 ---
    
@bp.route('/add', methods=('GET', 'POST'))
@login_required
def add_item():
    product_names = get_all_product_names()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        card_id = request.form.get('card_id', '').strip() or None
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        stock = request.form.get('stock', 0, type=int)
        category = request.form.get('category', '').strip() or None

        if not name or not rare:
            flash('名前とレアリティは必須です。', 'danger')
            # --- ここから修正 ---
            # raritiesをconfigから読み込むように変更
            return render_template('main/add_item.html',
                                   prefill_name=name, prefill_card_id=card_id, prefill_category=category,
                                   prefill_stock=stock, rarities=config.DEFINED_RARITIES,
                                   selected_rarity=rare_select, custom_rarity_value=rare_custom,
                                   product_names=product_names)
            # --- ここまで修正 ---

        name_normalized = normalize_for_search(name)
        card_id_normalized = normalize_for_search(card_id)

        conn = None
        try:
            conn = db.get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO items (name, card_id, rare, stock, category, name_normalized, card_id_normalized)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (name, card_id, rare, stock, category, name_normalized, card_id_normalized))
            conn.commit()
            flash(f'商品「{name}」が追加されました。', 'success')
            return redirect(url_for('main.index'))
        except psycopg2.IntegrityError:
            conn.rollback()
            flash(f"データベース登録エラー: カードIDとレアリティの組み合わせが既に存在する可能性があります。", 'danger')
        except (Exception, psycopg2.Error) as e:
            if conn: conn.rollback()
            flash(f"データベース登録エラー: {e}", 'danger')
        finally:
            if conn:
                cur.close()
                conn.close()
        
        # --- ここから修正 ---
        # raritiesをconfigから読み込むように変更
        return render_template('main/add_item.html',
                               prefill_name=name, prefill_card_id=card_id, prefill_category=category,
                               prefill_stock=stock, rarities=config.DEFINED_RARITIES,
                               selected_rarity=rare_select, custom_rarity_value=rare_custom,
                               product_names=product_names)
        # --- ここまで修正 ---

    # --- ここから修正 ---
    # raritiesをconfigから読み込むように変更
    return render_template('main/add_item.html',
                           rarities=config.DEFINED_RARITIES,
                           product_names=product_names)
    # --- ここまで修正 ---

@bp.route('/edit/<int:item_id>', methods=('GET', 'POST'))
@login_required
def edit_item(item_id):
    product_names = get_all_product_names()
    
    def get_item(id):
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM items WHERE id = %s", (id,))
        item = cur.fetchone()
        cur.close()
        conn.close()
        return item

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        rare_select = request.form.get('rare_select')
        rare_custom = request.form.get('rare_custom', '').strip()
        new_rare = rare_custom if rare_select == 'その他' and rare_custom else rare_select
        stock = request.form.get('stock', 0, type=int)
        category = request.form.get('category', '').strip() or None

        if not name or not new_rare:
            flash('名前とレアリティは必須です。', 'danger')
            return redirect(url_for('main.edit_item', item_id=item_id))

        name_normalized = normalize_for_search(name)

        conn = None
        try:
            conn = db.get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE items
                   SET name = %s, rare = %s, stock = %s, category = %s, name_normalized = %s
                 WHERE id = %s
            """, (name, new_rare, stock, category, name_normalized, item_id))
            conn.commit()
            flash('商品情報が更新されました。', 'success')
            return redirect(url_for('main.index'))
        except (Exception, psycopg2.Error) as e:
            if conn: conn.rollback()
            flash(f"データベース更新エラー: {e}", 'danger')
        finally:
            if conn:
                cur.close()
                conn.close()

        return redirect(url_for('main.edit_item', item_id=item_id))

    item = get_item(item_id)
    if not item:
        abort(404)
        
    # --- ここから修正 ---
    # raritiesをconfigから読み込むように変更
    return render_template('main/edit_item.html',
                           item=item,
                           rarities=config.DEFINED_RARITIES,
                           product_names=product_names)
    # --- ここまで修正 ---

# (以降の delete_item や API などの関数は変更なし)
# ... (省略) ...

@bp.route('/delete/<int:item_id>/confirm', methods=('GET',))
@login_required
def confirm_delete_item(item_id):
    conn = None
    item = None
    try:
        conn = db.get_db_connection()
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
        conn = db.get_db_connection()
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

    return redirect(request.referrer or url_for('main.index'))


@bp.route('/download_csv')
@login_required
def download_csv():
    conn = None
    items = []
    try:
        conn = db.get_db_connection()
        cur = conn.cursor()
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

@bp.route('/api/update_stock/<int:item_id>', methods=['POST'])
@login_required
def api_update_stock(item_id):
    """【API】在庫数を非同期で更新し、結果をJSONで返す"""
    try:
        delta = int(request.form.get('delta'))
        if delta not in [1, -1]:
            return jsonify({'success': False, 'message': '不正な在庫変更値です。'}), 400
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': '不正な在庫更新リクエストです。'}), 400

    conn = None
    try:
        conn = db.get_db_connection()
        with conn: 
            with conn.cursor() as cur:
                cur.execute("SELECT stock FROM items WHERE id = %s FOR UPDATE", (item_id,))
                result = cur.fetchone()
                
                if not result:
                    return jsonify({'success': False, 'message': '商品が見つかりません。'}), 404

                current_stock = result['stock']
                
                if current_stock == 0 and delta == -1:
                    return jsonify({'success': True, 'new_stock': 0})
                
                new_stock = current_stock + delta
                
                cur.execute("UPDATE items SET stock = %s WHERE id = %s", (new_stock, item_id))
                current_app.logger.info(f"API: Stock updated for item ID {item_id} to {new_stock}")
        
        return jsonify({'success': True, 'new_stock': new_stock})

    except (psycopg2.Error, Exception) as e:
        if conn: conn.rollback()
        error_message = f"在庫更新APIエラー (商品ID: {item_id}): {e}"
        current_app.logger.error(f"Error updating stock via API: {error_message}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'message': 'データベースエラーが発生しました。'}), 500
    finally:
        if conn:
            conn.close()

@bp.route('/delete_multiple_items', methods=['POST'])
@login_required
def delete_multiple_items():
    """ 複数のアイテムを一度に削除する """
    data = request.get_json()
    item_ids = data.get('item_ids')

    if not item_ids:
        return jsonify({'success': False, 'message': '削除するアイテムが選択されていません。'})

    try:
        # 文字列のIDを整数のリストに変換
        item_ids_int = [int(i) for i in item_ids]
        
        # データベースから削除
        deleted_count = db.delete_items_by_ids(item_ids_int)
        
        if deleted_count > 0:
            flash(f'{deleted_count}件のアイテムを削除しました。', 'success')
            return jsonify({'success': True})
        else:
            flash('削除対象のアイテムが見つかりませんでした。', 'warning')
            return jsonify({'success': False, 'message': '削除対象が見つかりません。'})

    except Exception as e:
        current_app.logger.error(f"一括削除処理でエラーが発生: {e}")
        flash('削除処理中にエラーが発生しました。', 'danger')
        return jsonify({'success': False, 'message': 'サーバーエラーが発生しました。'}), 500