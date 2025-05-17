        FLASK_APP=wsgi.py
        FLASK_DEBUG=True
        # ローカル開発用のSECRET_KEY (Renderとは別のものでOK)
        SECRET_KEY='a_very_secret_key_for_local_dev_12345' 
        # RenderのDBに接続する場合 (またはローカルDBのURL)
        DATABASE_URL='postgresql://yu_gi_oh_inventory_db_user:SulMEphNxN6FviTKMTRUm569rS7KVuHG@dpg-d0dkoqidbo4c738lkh6g-a.singapore-postgres.render.com/yu_gi_oh_inventory_db'
        