# app/auth.py
import functools
import json
import os

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app
)
from werkzeug.security import check_password_hash # generate_password_hash は users.json 作成時に使用

# 'auth' という名前のBlueprintを作成
# url_prefix='/auth' とすると、このBlueprint内のルートはすべて /auth が先頭につく
# (例: /auth/login, /auth/logout)
# 今回はトップレベルの /login, /logout とするため url_prefix は設定しないか、
# app/__init__.py での登録時に調整します。
# 元の構成に合わせて url_prefixなしで進めます。
bp = Blueprint('auth', __name__, url_prefix='/auth')


def login_required(view):
    """
    ビューデコレータ。ログインが必要なビューをラップし、
    未ログインの場合はログインページにリダイレクトする。
    """
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash('このページにアクセスするにはログインが必要です。', 'warning')
            return redirect(url_for('auth.login', next=request.url)) # nextパラメータでリダイレクト先を渡す
        return view(**kwargs)
    return wrapped_view

@bp.before_app_request
def load_logged_in_user():
    """
    各リクエストの前に実行される関数。
    セッションに user_id があれば、対応するユーザー情報をデータベース（今回はusers.json）から取得し、
    g.user に格納する。g.user はリクエストの間だけ有効なオブジェクト。
    """
    user_id = session.get('user_id') # sessionにはユーザー名そのものを入れる
    username = session.get('username')

    if username is None:
        g.user = None
    else:
        # ユーザー情報を users.json から読み込む
        # USER_FILE のパスは current_app.config から取得
        user_file_path = current_app.config['USER_FILE']
        if not os.path.exists(user_file_path):
            current_app.logger.error(f"User file '{user_file_path}' not found.")
            g.user = None # ファイルがなければユーザー情報なし
            # flash(f"エラー: ユーザーファイル ({os.path.basename(user_file_path)}) が見つかりません。", "danger")
            return

        try:
            with open(user_file_path, 'r', encoding='utf-8') as f:
                users = json.load(f)
            
            if username in users:
                # 簡単なユーザーオブジェクトとしてユーザー名をg.userに設定
                # 本来はDBからもっと詳細なユーザー情報を取得する
                g.user = {'username': username} 
                session['logged_in'] = True # セッションのlogged_inもここで再確認
            else:
                g.user = None
                session.clear() # ユーザーが存在しない場合はセッションクリア

        except json.JSONDecodeError:
            current_app.logger.error(f"Error decoding JSON from user file '{user_file_path}'.")
            g.user = None
        except Exception as e:
            current_app.logger.error(f"Error loading user from file '{user_file_path}': {e}")
            g.user = None


def check_login_credentials(username, password):
    """
    ユーザー名とパスワードが正しいかを確認する。
    users.json からハッシュ化されたパスワードを読み込んで比較する。
    """
    user_file_path = current_app.config['USER_FILE']
    if not os.path.exists(user_file_path):
        current_app.logger.error(f"User file '{user_file_path}' not found during login check.")
        flash(f"エラー: ユーザー認証システムに問題があります。(ファイル欠損)", "danger")
        return False
    
    try:
        with open(user_file_path, 'r', encoding='utf-8') as f:
            users = json.load(f)
        
        hashed_password = users.get(username)
        if hashed_password and check_password_hash(hashed_password, password):
            return True
        return False
    except json.JSONDecodeError:
        current_app.logger.error(f"Error decoding JSON from user file '{user_file_path}' during login check.")
        flash(f"エラー: ユーザー認証システムに問題があります。(ファイル形式)", "danger")
        return False
    except Exception as e:
        current_app.logger.error(f"Error checking credentials from file '{user_file_path}': {e}")
        flash(f"エラー: ユーザー認証中に予期せぬ問題が発生しました。", "danger")
        return False


@bp.route('/login', methods=('GET', 'POST'))
def login():
    """
    ログイン処理。POSTリクエストでユーザー名とパスワードを受け取り、
    認証が成功すればセッションにユーザー情報を保存してメインページへリダイレクト。
    GETリクエストの場合はログインページを表示。
    """
    if g.user: # 既にログイン済みならメインページへ
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        error = None

        if not username:
            error = 'ユーザー名は必須です。'
        elif not password:
            error = 'パスワードは必須です。'
        
        if error is None:
            if check_login_credentials(username, password):
                session.clear() # 既存のセッション情報をクリア
                session['user_id'] = username # 簡単のためユーザー名をIDとして使用
                session['username'] = username
                session['logged_in'] = True 
                current_app.logger.info(f"User '{username}' logged in successfully.")
                flash('ログインしました。', 'success')
                
                next_url = request.args.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect(url_for('main.index')) # main.index は後で作成
            else:
                error = 'ユーザー名またはパスワードが正しくありません。'
                current_app.logger.warning(f"Failed login attempt for user '{username}'.")
        
        if error:
            flash(error, 'danger')

    return render_template('auth/login.html') # templates/auth/login.html を使用

@bp.route('/logout')
def logout():
    """
    ログアウト処理。セッションをクリアしてログインページへリダイレクト。
    """
    username = session.get('username', 'Unknown user')
    session.clear()
    flash('ログアウトしました。', 'info')
    current_app.logger.info(f"User '{username}' logged out.")
    return redirect(url_for('auth.login'))

