from odoo.exceptions import UserError
import logging
from odoo.fields import Command
from odoo.addons.component.core import Component


_logger = logging.getLogger(__name__)


class ProductProductCanalRecordHandler(Component):
    """Interact w/ odoo canal ocio importable product records."""

    _name = "product.product.canal.handler"
    _inherit = "importer.odoorecord.handler"
    _apply_on = "product.product"
    _apply_on = "product.template"


    def _get_source_config(self):
        """ Helper to get the related source configuration """
        backend = self.collection.backend
        if backend and backend.import_recordset_ids:
            recordset = backend.import_recordset_ids.filtered(lambda r: r.import_type_id.mapper_name == self._name.replace('.handler', '.mapper'))[:1]
            if recordset and recordset.backend_id.import_source_id:
                    return recordset.backend_id.import_source_id

        _logger.error("Handler %s: Could not find linked import.source.csv configuration via backend/recordset.", self._name)
        raise UserError("Import source configuration not accessible from the handler. Check connector setup.")


    def _prepare_second_hand_product_vals(self, main_odoo_template):
        """
        Prepare values for the second-hand product template based on the main one.
        Logic adapted from the new code's _prepare_second_hand_product.
        """
        source_config = self._get_source_config()

        if not main_odoo_template.barcode:
            _logger.warning(
                "Cannot prepare second-hand product for template ID %s - main product has no barcode.",
                main_odoo_template.id
            )
            return None

        original_barcode = main_odoo_template.barcode
        second_hand_barcode = original_barcode + source_config.second_hand_suffix

        if len(second_hand_barcode) > 13:
            _logger.warning(
                f"Generated second-hand barcode '{second_hand_barcode}' exceeds 13 characters for main barcode '{original_barcode}' (Template ID: {main_odoo_template.id}). Skipping second-hand product."
            )
            return None


        second_hand_vals = {
            "name": f"{main_odoo_template.name} ({source_config.second_hand_default_code})",
            "barcode": second_hand_barcode,
            "default_code": source_config.second_hand_default_code,
            "list_price": main_odoo_template.list_price,
            "standard_price": main_odoo_template.standard_price,
            "weight": main_odoo_template.weight,
            "sale_ok": main_odoo_template.sale_ok,
            "detailed_type": main_odoo_template.detailed_type,
            "categ_id": main_odoo_template.categ_id.id,
            "description_sale": main_odoo_template.description_sale,
            "description": main_odoo_template.description,
            "image_1920": main_odoo_template.image_1920,
            "company_id": main_odoo_template.company_id.id,
        }

        second_hand_vals["taxes_id"] = [Command.clear()]

        all_tag_ids = main_odoo_template.product_tag_ids.ids
        try:
            snd_hand_tag = self.env.ref("connector_importer_canal.product_tag_second_hand", raise_if_not_found=False)
            if snd_hand_tag:
                if snd_hand_tag.id not in all_tag_ids:
                    all_tag_ids.append(snd_hand_tag.id)
            else:
                _logger.warning("Specific 'Second-hand' tag (connector_importer_canal.product_tag_second_hand) not found. Skipping.")
        except Exception as e:
            _logger.error("Error getting 'Second-hand' tag: %s", e)

        second_hand_vals["product_tag_ids"] = [Command.set(all_tag_ids)]


        return second_hand_vals


    def odoo_post_create(self, odoo_record, values, orig_values):
        """
        Post-create hook for main product.template records.
        Creates the corresponding second-hand product template.
        """
        _logger.info("Post-create handler for main product template ID: %s", odoo_record.id)

        second_hand_vals = self._prepare_second_hand_product_vals(odoo_record)

        if not second_hand_vals:
            _logger.info(
                "Skipping second-hand product creation for template ID %s (main barcode: %s) due to validation failure.",
                odoo_record.id, odoo_record.barcode
                )
            return

        existing_snd_hand_product = self.env['product.template'].search([
            ('barcode', '=', second_hand_vals['barcode']),
            ('company_id', '=', odoo_record.company_id.id),
        ], limit=1)

        if existing_snd_hand_product:
            _logger.warning(
                f"Second-hand product with barcode '{second_hand_vals['barcode']}' already exists (ID: {existing_snd_hand_product.id}). Skipping creation for main product ID {odoo_record.id}."
            )
            return


        _logger.info(
            "Creating second-hand product for main template ID: %s (main barcode: %s) with barcode: %s",
            odoo_record.id, odoo_record.barcode, second_hand_vals['barcode']
        )

        try:
            snd_hand_product = self.env["product.template"].with_context(create_product_product=True).create(second_hand_vals)
            _logger.info(
                "Created second-hand product template ID: %s for main template ID: %s",
                snd_hand_product.id, odoo_record.id
            )

        except Exception as e:
            _logger.error(
                f"Failed to create second-hand product for main template ID {odoo_record.id} "
                f"with proposed barcode {second_hand_vals.get('barcode', 'N/A')}: {e}",
                exc_info=True
            )


    def odoo_post_write(self, odoo_record, values, orig_values):
        """
        Post-write hook for main product.template records.
        Updates the corresponding second-hand product template.
        """
        _logger.info("Post-write handler for main product template ID: %s", odoo_record.id)

        source_config = self._get_source_config()


        if not odoo_record.barcode:
            _logger.warning(
                "Cannot update second-hand product for template ID %s - main product has no barcode.",
                odoo_record.id
            )
            return

        original_barcode = odoo_record.barcode
        expected_second_hand_barcode = original_barcode + source_config.second_hand_suffix

        second_hand_product_template = self.env["product.template"].search(
            [
                ("barcode", "=", expected_second_hand_barcode),
                ("company_id", "=", odoo_record.company_id.id),
            ],
            limit=1,
        )

        if not second_hand_product_template:
            _logger.warning(
                f"Could not find existing second-hand product with barcode '{expected_second_hand_barcode}' "
                f"for main product ID {odoo_record.id}. Skipping update."
            )
            return

        _logger.info(
            "Updating second-hand product template ID %s (barcode: %s) for main product ID %s",
            second_hand_product_template.id, expected_second_hand_barcode, odoo_record.id
        )

        updated_main_vals = odoo_record.read([
            'name', 'list_price', 'standard_price', 'weight', 'sale_ok',
            'detailed_type', 'categ_id', 'description_sale', 'description',
            'image_1920', 'product_tag_ids'
        ])[0]

        updated_main_vals['name'] = f"{updated_main_vals['name']} ({source_config.second_hand_default_code})"
        updated_main_vals['barcode'] = expected_second_hand_barcode
        updated_main_vals['default_code'] = source_config.second_hand_default_code
        updated_main_vals['taxes_id'] = [Command.clear()]

        all_tag_ids = updated_main_vals['product_tag_ids'][0][2]
        try:
            snd_hand_tag = self.env.ref("connector_importer_canal.product_tag_second_hand", raise_if_not_found=False)
            if snd_hand_tag and snd_hand_tag.id not in all_tag_ids:
                all_tag_ids.append(snd_hand_tag.id)
        except Exception as e:
            _logger.error("Error getting 'Second-hand' tag during update: %s", e)


        updated_main_vals['product_tag_ids'] = [Command.set(all_tag_ids)]


        try:
            second_hand_product_template.write(updated_main_vals)
            _logger.info(
                "Successfully updated second-hand product template ID: %s",
                second_hand_product_template.id
            )

        except Exception as e:
            _logger.error(
                f"Failed to update second-hand product template ID {second_hand_product_template.id} "
                f"(barcode: {expected_second_hand_barcode}): {e}",
                exc_info=True
            )


