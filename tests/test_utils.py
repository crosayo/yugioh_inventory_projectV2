# tests/test_utils.py
from app.utils import normalize_for_search

def test_normalize_for_search():
    """
    normalize_for_search関数が、様々な文字列を正しく正規化できるかテストする。
    """
    # 1. 全角英数字が半角になり、大文字が小文字になるか
    assert normalize_for_search("ＡＢＣ１２３") == "abc123"
    
    # 2. カタカナはカタカナのままで、大文字が小文字になるか (仕様に合わせて修正)
    assert normalize_for_search("ブラック・マジシャン") == "ブラック・マジシャン"
    
    # 3. 大文字が小文字になるか
    assert normalize_for_search("Blue-Eyes White Dragon") == "blue-eyes white dragon"
    
    # 4. 前後の空白が除去されるか
    assert normalize_for_search("  灰流うらら  ") == "灰流うらら"
    
    # 5. 複合的なケース（全角空白、全角英字、カタカナ）
    assert normalize_for_search("　Ｅ・ＨＥＲＯ ネオス　") == "e・hero ネオス"
    
    # 6. 空文字やNoneの場合
    assert normalize_for_search("") == ""
    assert normalize_for_search(None) == ""