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
    'nomal': 'N', 'normal': 'N', 'ノーマル': 'N', # 'Nomal' was likely a typo, corrected to 'normal'
    # Rare variations
    'rare': 'R', 'レア': 'R', '（「キ」＝玉偏に幾） rare': 'R',
    # Super Rare variations
    'super': 'SR', 'スーパー': 'SR', 'sr(スーパー)': 'SR', 'スーパーレア': 'SR',
    # Ultra Rare variations
    'ultra': 'UR', 'ウルトラ': 'UR', 'ur(ウルトラ)': 'UR', 'ウルトラレア': 'UR',
    # Secret Rare variations
    'secret': 'SE', 'シークレット': 'SE', 'se(シークレット)': 'SE', 'シークレットレア': 'SE',
    # Prismatic Secret Rare variations
    'prismatic secret': 'PSE', 'プリズマティックシークレット': 'PSE', 
    'pse(プリズマティックシークレット)': 'PSE', 'プリズマティックシークレットレア': 'PSE',
    # Ultimate Rare variations (Relief)
    'ultimate': 'UL', 'アルティメット': 'UL', 'ul(アルティメット)': 'UL', 
    'relief': 'UL', 'レリーフ': 'UL', 'アルティメットレア': 'UL',
    # Gold Rare variations
    'gold': 'GR', 'ゴールド': 'GR', 'ゴールドレア': 'GR',
    # Holographic Rare variations
    'holographic': 'HR', 'ホログラフィック': 'HR', 'ホログラフィックレア': 'HR',
    # Normal Parallel variations
    'normal parallel': 'N-P', 'ノーマルパラレル': 'N-P', 'n-parallel': 'N-P', 'nパラ': 'N-P',
    # KC Rare variations
    'kc rare': 'KC', 'kcレア': 'KC', 'kcr': 'KC',
    # Millennium Rare variations
    'millennium': 'M', 'ミレニアム': 'M', 'ミレニアムレア': 'M',
    # Collectors Rare variations
    'collectors': 'CR', 'コレクターズ': 'CR', 'コレクターズレア': 'CR',
    # Extra Secret Rare variations
    'extra secret': 'EXSE', 'エクストラシークレット': 'EXSE', 'ex-secret': 'EXSE', 'エクストラシークレットレア': 'EXSE',
    # 20th Secret Rare variations
    '20th secret': '20thSE', '20thシークレット': '20thSE', 
    '20thse(20thシークレット)': '20thSE', '20thシークレットレア': '20thSE',
    # Quarter Century Secret Rare variations
    'quarter century secret': 'QCSE', 'クォーターセンチュリーシークレット': 'QCSE', 
    'クォーターセンチュリーシークレットレア': 'QCSE',
    # N-Rare
    'n-rare': 'NR',
    # Holographic-Parallel
    'holographic-parallel': 'HP',
    # Generic Parallel
    'parallel': 'P',
    # Gold Secret
    'g-secret': 'GSE',
    # Ultra Parallel
    'ultra-parallel': 'UR-P', 'ur-parallel': 'UR-P',
    # Super Parallel
    'super-parallel': 'SR-P',
    # Specific card/set related rarities that map to 'その他' (Other) or '不明' (Unknown)
    # These keys should also be lowercase if they are expected to be matched case-insensitively
    '（エド・フェニックス仕様）': 'その他', # Japanese specific, case might not matter as much if always exact
    '（真帝王降臨）': 'その他',
    '（オレンジ）': 'その他',
    '（黄）': 'その他',
    '（緑）': 'その他',
    'レアリティ': '不明', 
    '（「セン」＝玉偏に旋）': 'その他',
    '（「こう」＝網頭に正） rare': 'その他' # Keep 'rare' part if it's part of the string to match
}
