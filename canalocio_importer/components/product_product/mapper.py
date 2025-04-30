import logging
from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping
from odoo.fields import Command

_logger = logging.getLogger(__name__)


class ProductProductCanalMapper(Component):
    _name = "product.product.canal.mapper"
    _inherit = "importer.mapper.dynamic"
    _apply_on = "product.product"
    _mapper_usage = "importer.mapper"


    @mapping
    def map_record(self, record):
        """
        Main mapping method to transform source record (CSV row dict)
        into Odoo product.template values.
        """
        source_config = self.recordset.backend_id.import_source_id
        if not source_config or not source_config._name == 'import.source.csv':
            _logger.error("Mapper %s: Could not find linked import.source.csv configuration.", self._name)
            raise ValueError("Import source configuration not found or is of the wrong type.")

        parse_float = source_config._parse_float
        fetch_image_b64 = source_config._fetch_image_b64

        barcode = record.get("ean13", "").strip()
        if not barcode or not barcode.isdigit() or not (8 <= len(barcode) <= 13):
            _logger.warning(
                "Config ID %s: Row skipped - Invalid or missing EAN13 (non-digit or invalid length). Data: %s",
                source_config.id, record
            )
            return None

        title = record.get("titulo", f"Producto {barcode}").strip() or f"Producto {barcode}"


        pvp = parse_float(record.get("pvp", ""))
        pvd = parse_float(record.get("pvd", ""))
        weight = parse_float(record.get("peso", ""))
        is_available = record.get("estado", "").strip().lower() == source_config.available_state.lower()


        image_url = record.get("caratula", "").strip()
        image_b64 = False
        if image_url:
            image_b64 = fetch_image_b64(image_url)


        html_content = ""
        html_content += f"<p><label>Fecha distribución:</label> {record.get('disponibilidad', '').strip()}</p>"
        html_content += f"<p><label>Distribuidor:</label> {record.get('distribuidor', '').strip()}</p>"
        html_content += f"<p><label>Info:</label> {record.get('sinopsis', '').strip()}</p>"
        html_content += f"<p><label>Directores:</label> {record.get('pelicula director', '').strip()}</p>"
        html_content += f"<p><label>Actores:</label> {record.get('pelicula actores', '').strip()}</p>"
        html_content += f"<p><label>Duración:</label> {record.get('pelicula duracion', '').strip()}</p>"
        html_content += f"<p><label>Audio:</label> {record.get('pelicula audio', '').strip()}</p>"
        html_content += f"<p><label>Subtítulos:</label> {record.get('pelicula subtitulos', '').strip()}</p>"
        html_content += f"<p><label>Clasificación:</label> {record.get('pelicula clasificación', '').strip()}</p>"

        genre_names = []
        for i in range(1, 6):
            genre_name = record.get(f"genero_{i}", "").strip()
            if genre_name:
                genre_names.append(genre_name)
        if genre_names:
            html_content += f"<p><label>Género:</label> {', '.join(genre_names)}</p>"

        description_sale = record.get('sinopsis', '').strip()
        description = html_content

        tag_names = []
        for i in range(1, 7):
            tag_column = f"tag_{i}"
            tag_name = record.get(tag_column, "").strip()
            if tag_name:
                tag_names.append(tag_name)

        if not hasattr(self, '_tag_cache'):
            self._tag_cache = {}

        tag_ids = []
        ProductTag = self.env['product.tag']

        for tag_name in tag_names:
            if not tag_name:
                continue

            if tag_name in self._tag_cache:
                tag_id = self._tag_cache[tag_name]
                if tag_id:
                    tag_ids.append(tag_id)
            else:
                tag = ProductTag.search([("name", "=ilike", tag_name)], limit=1)
                if tag:
                    self._tag_cache[tag_name] = tag.id
                    tag_ids.append(tag.id)
                else:
                    try:
                        new_tag = ProductTag.create({"name": tag_name})
                        self._tag_cache[tag_name] = new_tag.id
                        tag_ids.append(new_tag.id)
                        _logger.info(
                            f"Config ID {source_config.id}: Created new tag '{tag_name}' (ID: {new_tag.id})"
                        )
                    except Exception as e:
                        _logger.error(
                            f"Config ID {source_config.id}: Failed to create tag '{tag_name}' for barcode {barcode}: {e}", exc_info=True
                        )
                        self._tag_cache[tag_name] = None


        unique_tag_ids = list(set(tag_ids))
        tag_m2m_command = [(6, 0, unique_tag_ids)]

        odoo_values = {
            "name": title,
            "barcode": barcode,
            "list_price": pvp,
            "standard_price": pvd,
            "weight": weight,
            "sale_ok": is_available,
            "detailed_type": "product",
            "categ_id": self.env.ref("product.product_category_all").id,
            "description_sale": description_sale,
            "description": description,
            "product_tag_ids": tag_m2m_command,
        }

        if image_b64:
            odoo_values["image_1920"] = image_b64

        return odoo_values


