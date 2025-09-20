# app/data_definitions.py
from datetime import datetime
from . import config # 新しくconfigをインポート

def calculate_era(release_date):
    """
    dateオブジェクトまたは'YYYY-MM-DD'形式の文字列から期を計算する
    """
    if not release_date:
        return None
    
    # release_dateが文字列の場合、dateオブジェクトに変換
    if isinstance(release_date, str):
        try:
            # ISO 8601形式 (YYYY-MM-DD) を想定
            release_date = datetime.strptime(release_date, '%Y-%m-%d').date()
        except ValueError:
            return None

    # config.pyのERA_DEFINITIONS を使って期を判定
    for era_tuple in config.ERA_DEFINITIONS:
        era_num = era_tuple[0]
        start_date = datetime.strptime(era_tuple[1], '%Y-%m-%d').date()
        end_date = datetime.strptime(era_tuple[2], '%Y-%m-%d').date()
        
        if start_date <= release_date <= end_date:
            return era_num
            
    return None # どの期にも当てはまらない場合