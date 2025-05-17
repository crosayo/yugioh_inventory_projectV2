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
    # Normal variations
    'nomal': 'N', 'Nomal': 'N', 'Normal': 'N', 'ノーマル': 'N',
    # Rare variations
    'Rare': 'R', 'レア': 'R', '（「キ」＝玉偏に幾） Rare': 'R', # A specific Japanese variant for Rare
    # Super Rare variations
    'Super': 'SR', 'スーパー': 'SR', 'SR(スーパー)': 'SR', 'スーパーレア': 'SR',
    # Ultra Rare variations
    'Ultra': 'UR', 'ウルトラ': 'UR', 'UR(ウルトラ)': 'UR', 'ウルトラレア': 'UR',
    # Secret Rare variations
    'Secret': 'SE', 'シークレット': 'SE', 'SE(シークレット)': 'SE', 'シークレットレア': 'SE',
    # Prismatic Secret Rare variations
    'Prismatic Secret': 'PSE', 'プリズマティックシークレット': 'PSE', 
    'PSE(プリズマティックシークレット)': 'PSE', 'プリズマティックシークレットレア': 'PSE',
    # Ultimate Rare variations (Relief)
    'Ultimate': 'UL', 'アルティメット': 'UL', 'UL(アルティメット)': 'UL', 
    'Relief': 'UL', 'レリーフ': 'UL', 'アルティメットレア': 'UL',
    # Gold Rare variations
    'Gold': 'GR', 'ゴールド': 'GR', 'ゴールドレア': 'GR',
    # Holographic Rare variations
    'Holographic': 'HR', 'ホログラフィック': 'HR', 'ホログラフィックレア': 'HR',
    # Normal Parallel variations
    'Normal Parallel': 'N-P', 'ノーマルパラレル': 'N-P', 'N-Parallel': 'N-P', 'Nパラ': 'N-P',
    # KC Rare variations
    'KC Rare': 'KC', 'KCレア': 'KC', 'KCR': 'KC',
    # Millennium Rare variations
    'Millennium': 'M', 'ミレニアム': 'M', 'ミレニアムレア': 'M',
    # Collectors Rare variations
    'Collectors': 'CR', 'コレクターズ': 'CR', 'コレクターズレア': 'CR',
    # Extra Secret Rare variations
    'Extra Secret': 'EXSE', 'エクストラシークレット': 'EXSE', 'Ex-Secret': 'EXSE', 'エクストラシークレットレア': 'EXSE',
    # 20th Secret Rare variations
    '20th Secret': '20thSE', '20thシークレット': '20thSE', 
    '20thSE(20thシークレット)': '20thSE', '20thシークレットレア': '20thSE',
    # Quarter Century Secret Rare variations
    'Quarter Century Secret': 'QCSE', 'クォーターセンチュリーシークレット': 'QCSE', 
    'クォーターセンチュリーシークレットレア': 'QCSE',
    # N-Rare
    'N-Rare': 'NR',
    # Holographic-Parallel
    'Holographic-Parallel': 'HP',
    # Generic Parallel
    'Parallel': 'P',
    # Gold Secret
    'G-Secret': 'GSE',
    # Ultra Parallel
    'Ultra-Parallel': 'UR-P', 'UR-Parallel': 'UR-P',
    # Super Parallel
    'Super-Parallel': 'SR-P',
    # Specific card/set related rarities that map to 'その他' (Other) or '不明' (Unknown)
    '（エド・フェニックス仕様）': 'その他',
    '（真帝王降臨）': 'その他',
    '（オレンジ）': 'その他',
    '（黄）': 'その他',
    '（緑）': 'その他',
    'レアリティ': '不明', # "Rarity" itself, likely a header or placeholder
    '（「セン」＝玉偏に旋）': 'その他', # Another specific Japanese variant
    '（「こう」＝網頭に正） Rare': 'その他' # Another specific Japanese variant
}

# pykakasi converters (will be initialized in app factory)
# These are here just as a note that they were global in the original app.py
# kks_hira_converter = None
# kks_kata_converter = None
