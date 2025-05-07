# canalocio_importer/components/importer_override.py

import logging
import traceback

from odoo.addons.component.core import Component
from odoo import exceptions, _

# Import the original logger (adjust path if needed)
try:
    from odoo.addons.connector_importer.log import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning("Could not import original logger. Using standard __name__ logger.")


class CanalocioRecordImporterOverride(Component):
    _inherit = "importer.record"

    # Override the 'run' method
    def run(self, record, is_last_importer=True, **kw):
        """
        Override run method from 'importer.record' to fix the
        .values(**options) bug, handle mapper returning None,
        and prevent 'override_existing' from being passed to ORM.
        """

        self.record = record
        if not self.record:
            msg = "NO RECORD FOUND, maybe deleted? Check your jobs!"
            logger.error(msg)
            return

        self._init_importer(self.record.recordset_id)

        for line in self._record_lines():
            line = self.prepare_line(line)
            options = self._load_mapper_options() # options includes 'override_existing'

            odoo_record = None
            values = {} # Initialize values before the try block


            # --- First Try/Except Block: Mapping and initial processing ---
            try:
                with self.env.cr.savepoint():
                    mapped_values = self.mapper.map_record(line)

                    # --- Refined Logic for values preparation ---
                    # 1. Assign mapped values (dict or None) to values
                    values = mapped_values

                    # 2. If the mapper returned a dictionary, process options
                    if isinstance(values, dict):
                         # Create a dictionary for ORM values, excluding 'override_existing'
                         # The 'options' dictionary might contain other keys besides 'override_existing'
                         # so we iterate through it and exclude only the problematic key.
                         orm_values_update = {k: v for k, v in options.items() if k != 'override_existing'}
                         if orm_values_update: # Only update if there are valid options to merge
                             values.update(orm_values_update)
                    # --- End of Refined Logic ---

                logger.debug("Mapped and prepared values for record %s (%s): %s", line.get('_line_nr', 'N/A'), line.get(self.unique_key, 'N/A'), values)

            except Exception as err:
                values = {}
                self.tracker.log_error({}, line, odoo_record, message=err)
                if self.must_break_on_error:
                     logger.error("Import failed during mapping/savepoint for record %s (%s): %s", line.get('_line_nr', 'N/A'), line.get(self.unique_key, 'N/A'), err, exc_info=True)
                     raise
                logger.warning("Import skipped during mapping/savepoint for record %s (%s) due to error: %s", line.get('_line_nr', 'N/A'), line.get(self.unique_key, 'N/A'), err)
                continue


            # --- Check if mapper returned None, skip record processing ---
            if values is None:
                logger.debug("Mapper returned None for line %s (%s). Skipping record processing.", line.get('_line_nr', 'N/A'), line.get(self.unique_key, 'N/A'))
                # The mapper is responsible for logging *why* it returned None
                continue # Skip to the next line in the loop


            # --- Handle Forced Skipping (This block now only runs if values is a dict) ---
            skip_info = self.skip_it(values, line)
            if skip_info:
                self.tracker.log_skipped(values, line, skip_info)
                continue # Move to the next record


            # --- Second Try/Except Block: Odoo ORM operations (exists, write, create) ---
            # This block also now only runs if values is a dictionary (checked by 'if values is None' above)
            try:
                with self.env.cr.savepoint():
                    # --- Add log here to see the exact values passed to the handler ---
                    # This is where the error happens, so seeing the values right before is key
                    logger.debug("Attempting ORM operation for record %s (%s) with values: %s", line.get('_line_nr', 'N/A'), line.get(self.unique_key, 'N/A'), values)
                    # --- End log ---

                    if self.record_handler.odoo_exists(values, line):
                        odoo_record = self.record_handler.odoo_write(values, line)
                        self.tracker.log_updated(values, line, odoo_record)
                    else:
                        if self.work.options.importer.write_only:
                            self.tracker.log_skipped(
                                values,
                                line,
                                {"message": "Write-only importer, record not found."},
                            )
                            continue

                        # We know values is a dict here due to the check above 'if values is None'
                        odoo_record = self.record_handler.odoo_create(values, line)
                        self.tracker.log_created(values, line, odoo_record)

            except Exception as err:
                # Error handling for the ORM operations
                self.tracker.log_error(values, line, odoo_record, message=err)
                if self.must_break_on_error:
                     logger.error("Import failed during ORM operation for record %s (%s): %s", line.get('_line_nr', 'N/A'), line.get(self.unique_key, 'N/A'), err, exc_info=True)
                     if odoo_record and odoo_record.exists():
                         logger.error("Related Odoo record ID: %s", odoo_record.id)
                     raise

                logger.warning("Import skipped during ORM operation for record %s (%s) due to error: %s", line.get('_line_nr', 'N/A'), line.get(self.unique_key, 'N/A'), err)
                continue


        self._do_report()
        counters = self.tracker.get_counters()
        msg = " ".join(
            [
                "CHUNK FINISHED",
                "[created: {created}]",
                "[updated: {updated}]",
                "[skipped: {skipped}]",
                "[errored: {errored}]",
            ]
        ).format(**counters)
        self.tracker._log(msg)

        self.finalize_session(record, is_last_importer=is_last_importer)

        return counters

    # --- NEW: Override the required_keys method ---
    def required_keys(self, create=False):
        """
        Override required_keys to return only the source keys needed by the mapper.
        This prevents the base importer from incorrectly requiring
        'barcode' as a source key when 'ean13' is the actual source column.
        """
        # Get the required keys as defined by your specific mapper.
        # Your mapper's required_keys method should return something like:
        # {'ean13': 'barcode', 'titulo': 'name', 'pvp': 'list_price', ...}
        # We just need the source keys from this: 'ean13', 'titulo', 'pvp', etc.
        mapper_required = self.mapper.required_keys()

        # The _check_missing method checks the KEYS of the dictionary returned by required_keys
        # against the 'orig_values' (the cleaned 'line' dictionary).
        # So, we need to return a dictionary whose keys are the required SOURCE column names.
        # The values of this dictionary can be anything, but it's conventional
        # to return the source_key -> dest_key mapping.
        return mapper_required

    # Keep other methods like finalize_session etc. here if they are part of this class definition
    # ...
