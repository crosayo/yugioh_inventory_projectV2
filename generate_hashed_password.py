from werkzeug.security import generate_password_hash
import json
import getpass # getpassモジュールをインポートしてパスワードを非表示入力

def create_hashed_users_file():
    """
    ユーザー名とパスワードを対話形式で入力させ、
    ハッシュ化されたパスワードを含むユーザー情報ファイルを生成する。
    """
    users_data = {}
    print("新しいユーザー情報を登録します。")
    while True:
        username = input("ユーザー名を入力してください (何も入力せずEnterで終了): ").strip()
        if not username:
            break
        
        # パスワード入力時にコンソールに表示されないようにする
        password = getpass.getpass(f"'{username}' のパスワードを入力してください: ")
        password_confirm = getpass.getpass(f"'{username}' のパスワードを再入力してください（確認）: ")

        if password != password_confirm:
            print("パスワードが一致しません。最初からやり直してください。")
            continue

        if not password:
            print("パスワードは空にできません。")
            continue
            
        hashed_password = generate_password_hash(password)
        users_data[username] = hashed_password
        print(f"ユーザー '{username}' を登録しました。")
    
    if users_data:
        output_filename = 'users_hashed.json'
        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(users_data, f, indent=4, ensure_ascii=False)
            print(f"\nハッシュ化されたユーザー情報が '{output_filename}' に保存されました。")
            print(f"このファイル名を 'users.json' に変更して使用してください。")
            print("\n生成された内容:")
            # セキュリティのため、ハッシュ値を直接コンソールに出力するのは控えるか、注意を促す
            # print(json.dumps(users_data, indent=4, ensure_ascii=False)) 
            print("ファイルの内容を確認してください。")

        except IOError as e:
            print(f"エラー: ファイル '{output_filename}' の書き込みに失敗しました。{e}")
    else:
        print("ユーザーは追加されませんでした。")

if __name__ == '__main__':
    create_hashed_users_file()
