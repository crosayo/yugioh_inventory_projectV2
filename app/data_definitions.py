# app/data_definitions.py

DEFINED_RARITIES = [
    "N", "R", "SR", "UR", "SE", "PSE", "UL", "GR", "HR",
    "N-P", "SR-P", "UR-P", "SE-P", "P", # Parallel Rares
    "KC", "M", "CR", "EXSE", "20thSE", "QCSE", # Special Rares
    "NR", # Normal Rare
    "HP", # Holographic Parallel
    "GSE", # Gold Secret Rare
    "Ten Thousand Secret", # 10000 Secret Rare
    "Ultra RED Ver.", "Ultra BLUE Ver.", # Special Ultra versions
    "Secret BLUE Ver.", # Special Secret version
    "Ultimate(Secret)", # Specific Ultimate variant
    "Millennium-Ultra", # Millennium Ultra Rare
    "不明", # Unknown
    "その他"  # Other
]

RARITY_CONVERSION_MAP = {
    # (この部分は元のままで変更ありません)
    'nomal': 'N', 'normal': 'N', 'ノーマル': 'N',
    'rare': 'R', 'レア': 'R', '（「キ」＝玉偏に幾） rare': 'R',
    'super': 'SR', 'スーパー': 'SR', 'sr(スーパー)': 'SR', 'スーパーレア': 'SR',
    'ultra': 'UR', 'ウルトラ': 'UR', 'ur(ウルトラ)': 'UR', 'ウルトラレア': 'UR',
    'secret': 'SE', 'シークレット': 'SE', 'se(シークレット)': 'SE', 'シークレットレア': 'SE',
    'prismatic secret': 'PSE', 'プリズマティックシークレット': 'PSE', 'pse(プリズマティックシークレット)': 'PSE', 'プリズマティックシークレットレア': 'PSE',
    'ultimate': 'UL', 'アルティメット': 'UL', 'ul(アルティメット)': 'UL', 'relief': 'UL', 'レリーフ': 'UL', 'アルティメットレア': 'UL',
    'gold': 'GR', 'ゴールド': 'GR', 'ゴールドレア': 'GR',
    'holographic': 'HR', 'ホログラフィック': 'HR', 'ホログラフィックレア': 'HR',
    'normal parallel': 'N-P', 'ノーマルパラレル': 'N-P', 'n-parallel': 'N-P', 'nパラ': 'N-P',
    'kc rare': 'KC', 'kcレア': 'KC', 'kcr': 'KC',
    'millennium': 'M', 'ミレニアム': 'M', 'ミレニアムレア': 'M',
    'collectors': 'CR', 'コレクターズ': 'CR', 'コレクターズレア': 'CR',
    'extra secret': 'EXSE', 'エクストラシークレット': 'EXSE', 'ex-secret': 'EXSE', 'エクストラシークレットレア': 'EXSE',
    '20th secret': '20thSE', '20thシークレット': '20thSE', '20thse(20thシークレット)': '20thSE', '20thシークレットレア': '20thSE',
    'quarter century secret': 'QCSE', 'クォーターセンチュリーシークレット': 'QCSE', 'クォーターセンチュリーシークレットレア': 'QCSE',
    'n-rare': 'NR',
    'holographic-parallel': 'HP',
    'parallel': 'P',
    'g-secret': 'GSE',
    'ultra-parallel': 'UR-P', 'ur-parallel': 'UR-P',
    'super-parallel': 'SR-P',
    '（エド・フェニックス仕様）': 'その他',
    '（真帝王降臨）': 'その他',
    '（オレンジ）': 'その他',
    '（黄）': 'その他',
    '（緑）': 'その他',
    'レアリティ': '不明',
    '（「セン」＝玉偏に旋）': 'その他',
    '（「こう」＝網頭に正） rare': 'その他'
}

# --- ▼▼▼「期」の定義を追加 ▼▼▼ ---
ERA_DEFINITIONS = [
    # (期番号, '期シーズンの開始日YYYY-MM-DD', '期シーズンの終了日YYYY-MM-DD', '表示名')
    # 新しい期を上に追加していく
    (13, '2025-04-01', '2028-03-31', '第13期'), # 仮の期間
    (12, '2023-04-01', '2025-03-31', '第12期'),
    (11, '2020-04-01', '2023-03-31', '第11期'),
    (10, '2017-04-01', '2020-03-31', '第10期'),
    (9, '2014-04-01', '2017-03-31', '第9期'),
    (8, '2012-04-01', '2014-03-31', '第8期'),
    (7, '2010-04-01', '2012-03-31', '第7期'),
    (6, '2008-04-01', '2010-03-31', '第6期'),
    (5, '2006-04-01', '2008-03-31', '第5期'),
    (4, '2004-04-01', '2006-03-31', '第4期'),
    (3, '2002-04-01', '2004-03-31', '第3期'),
    (2, '2000-04-01', '2002-03-31', '第2期'),
    (1, '1999-02-04', '2000-03-31', '第1期'),
]

# サイドバーやソート順で使うための期の順序 (新しいものが先)
ERA_DISPLAY_ORDER = [era[0] for era in ERA_DEFINITIONS]

# 期番号から表示名を取得するための辞書
ERA_DISPLAY_NAMES = {era[0]: era[3] for era in ERA_DEFINITIONS}