# -*- coding: utf-8 -*-
{
    'name': 'Canalacio Importer',
    'version': '17.0.1.0',
    'summary': 'Import products from Canalocio',
    'description': """
        Fetches product data from a Leisure Channel CSV feed via URL,
        parses it, and creates/updates products (including second-hand variants) in Odoo.
        Includes configuration options and a scheduled action.
    """,
    'category': 'Connetor',
    'author': 'Binhex',
    'depends': [
        'base',
        'product',
        'stock',
        'queue_job',
        'account',
        'sale',
        'connector_importer',
        'connector'
        ],
    'data': [
        'data/import_tag_data.xml',
        'data/import_type_data.xml',
        'data/import_backend_data.xml',
        'data/import_source_data.xml',
        'data/import_recordset_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'external_dependencies': {'python': ['requests']},
}
