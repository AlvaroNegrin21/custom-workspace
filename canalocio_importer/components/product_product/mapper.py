# Copyright 2025 Binhex
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping


class ProductProductCanalMapper(Component):
    _name = "product.product.canal.mapper"
    _inherit = "importer.mapper.dynamic"
    _apply_on = "product.product"
    _mapper_usage = "importer.mapper"

    direct = [
        ("titulo", "name"),
        ("ean13", "barcode"),
        ("id", "default_code"),
        ("sinopsis", "description_sale"),
        ("tipo", "categ_id"),
    ]
    required = {
        "titulo": "name",
        "ean13": "barcode",
        "tipo": "categ_id",
    }

    defaults = [("sale_ok", True)]

    @mapping
    def custom_csv_columns(self, record):
        """
        Custom method to handle additional CSV columns
        """
        csv_column2label_mapping = {
            "disponibilidad": "Fecha distribución",
            "distribuidor": "Distribuidor",
            "sinopsis": "Info",
            "pelicula director": "Directores",
            "pelicula actores": "Actores",
            "pelicula duracion": "Duración",
            "pelicula audio": "Audio",
            "pelicula subtitulos": "Subtítulos",
            "pelicula clasificación": "Clasificación",
            "genero_": "Género",
            "tag_": "Tag",
        }

        html_content = ""
        for key, label in csv_column2label_mapping.items():
            value = ""
            if key.startswith("genero_"):
                value = ",".join(
                    record.get(f"genero_{i}", "")
                    for i in range(1, 6)
                    if record.get(f"genero_{i}")
                )
            elif key.startswith("tag_"):
                value = ",".join(
                    record.get(f"tag_{i}", "")
                    for i in range(1, 7)
                    if record.get(f"tag_{i}")
                )
            else:
                value = record.get(key, "")
            html_content += f"<p><label>{label}:</label> {value}</p>"
        return {"description": html_content}
