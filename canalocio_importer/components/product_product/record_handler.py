# Copyright 2025 Binhex
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo.fields import Command

from odoo.addons.component.core import Component


class ProductProductCanalRecordHandler(Component):
    """Interact w/ odoo canal ocio importable product records."""

    _name = "product.product.canal.handler"
    _inherit = "importer.odoorecord.handler"
    _apply_on = "product.product"

    def _prepare_second_hand_product(odoo_record):
        product_template = odoo_record.product_tmpl_id
        default = {
            "name": product_template.name,
            "default_code": f"OKA{product_template.default_code}",
            "barcode": f"OKA{product_template.barcode}",
        }
        return product_template, default

    def odoo_post_create(self, odoo_record, values, orig_values):
        """Post-create hook for odoo product.product records."""

        # Create a new second-hand product template
        product_template, default_values = self._prepare_second_hand_product(
            odoo_record
        )
        record_copy = product_template.with_context(create_product_product=True).copy(
            default=default_values
        )
        snd_hand_tag = self.env.ref("connector_importer_canal.product_tag_second_hand")
        record_copy.write(
            {
                "product_tag_ids": [Command.set(snd_hand_tag.ids)],
                "taxes_id": [Command.clear()],
            }
        )

    def odoo_post_write(self, odoo_record, values, orig_values):
        """Post-write hook for odoo product.product records."""

        product_template, default_values = self._prepare_second_hand_product(
            odoo_record
        )
        product_template = odoo_record.product_tmpl_id
        second_hand_product_template = self.env["product.template"].search(
            [("default_code", "=", default_values.get("default_code"))], limit=1
        )
        updated_values = product_template.copy_data(default=default_values)[0]
        second_hand_product_template.write(updated_values)
