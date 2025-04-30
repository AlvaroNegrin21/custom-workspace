{
    "name": "Canalocio Importer (Integrated Logic)",
    "version": "17.0.1.0", # Change it
    "summary": "Import products from Canalocio CSV feed with integrated logic",
    "description": """
        Fetches product data from a Canalocio CSV feed via URL,
        parses it, and creates/updates products (including second-hand variants) in Odoo
        using the connector_importer framework with logic from the leisure_channel_sync implementation.
        Includes configuration options on the import source and a scheduled action.
    """,
    "category": "Connetor",
    "author": "Binhex",
    "depends": [
        "base",
        "product",
        "stock",
        "queue_job",
        "account",
        "sale",
        "connector_importer",
        "connector",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/import_source_canal_view.xml",
        "data/import_backend_data.xml",
        "data/import_type_data.xml",
        "data/import_recordset_data.xml",
        "data/import_tag_data.xml",
        "data/ir_cron_data.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "external_dependencies": {"python": ["requests", "Pillow"]},
}
