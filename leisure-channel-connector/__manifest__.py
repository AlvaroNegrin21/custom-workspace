# -*- coding: utf-8 -*-
{
    'name': 'Leisure Channel Sync',
    'version': '1.0',
    'summary': 'Synchronize products from Leisure Channel CSV feed',
    'description': """
        Fetches product data from a Leisure Channel CSV feed via URL,
        parses it, and creates/updates products (including second-hand variants) in Odoo.
        Includes configuration options and a scheduled action.
    """,
    'category': 'Inventory/Inventory',
    'author': 'Binhex',
    'depends': [
        'base',
        'product',
        'stock',   # Make sure this dependency is needed/correct
        ],
    'data': [
        'security/ir.model.access.csv',
        'views/leisure_channel_sync_views.xml',
        'data/leisure_channel_sync_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'external_dependencies': {'python': ['requests']},
}
