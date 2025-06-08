# app/utils.py
import unicodedata

def normalize_for_search(text: str) -> str:
    """
    文字列を検索用に正規化（標準化）する。
    - 全角英数字記号を半角に変換 (NFKC正規化)
    - 全て小文字に変換
    - 前後の空白を削除
    """
    if not text:
        return ""
    
    # NFKC正規化: 全角英数字や記号などを半角に変換する
    # 'Ｎｏ．７０' -> 'No.70' のような変換が行われる
    normalized_text = unicodedata.normalize('NFKC', text)
    
    # 全て小文字に変換
    lower_text = normalized_text.lower()
    
    # 前後の空白を削除
    stripped_text = lower_text.strip()
    
    return stripped_text