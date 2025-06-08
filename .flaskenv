        FLASK_APP=wsgi.py
        FLASK_DEBUG=True
        # ローカル開発用のSECRET_KEY (Renderとは別のものでOK)
        SECRET_KEY='a_very_secret_key_for_local_dev_12345' 
        # RenderのDBに接続する場合 (またはローカルDBのURL)
        DATABASE_URL="postgresql://neondb_owner:npg_dvQj14sxUMEX@ep-white-leaf-a1xm5fc6-pooler.ap-southeast-1.aws.neon.tech:5432/neondb?sslmode=require"
        