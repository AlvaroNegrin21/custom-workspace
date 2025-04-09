from odoo import models, fields, api
from odoo.exceptions import UserError
from PIL import Image

import csv
import logging
import requests
import io
import base64
import copy
import binascii

CSV_DELIMITER = ";"
REQUESTS_TIMEOUT = 120
IMAGE_TIMEOUT = 50
BATCH_SIZE = 1000
DEFAULT_PRODUCT_TYPE = "product"
STATE_AVAILABLE = "disponible"
SECOND_HAND_SUFFIX = "OKA"
SECOND_HAND_DEFAULT_CODE = "Segunda Mano"

_logger = logging.getLogger(__name__)


class LeisureChannelSync(models.Model):
    _name = "leisure.channel.sync"
    _description = "Leisure Channel Sync Configuration"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string="Configuration Name", required=True, default="Default Configuration"
    )
    location = fields.Char(
        string="CSV URL Location",
        required=True,
        help="The URL location of the leisure channel CSV file",
    )
    second_hand_suffix = fields.Char(
        string="Second Hand Suffix",
        default=SECOND_HAND_SUFFIX,
        help="The suffix to identify second hand products",
    )
    second_hand_default_code = fields.Char(
        string="Second Hand Default Code",
        default=SECOND_HAND_DEFAULT_CODE,
        help="The default code for second hand products",
    )
    available_state = fields.Char(
        string="Available State",
        default=STATE_AVAILABLE,
        help="The state value in the CSV to identify available products",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    def _fetch_parse_csv(self, url):
        self.ensure_one()
        _logger.info("Fetching CSV from %s for config %s", url, self.name)
        response = None
        csv_data = None
        try:
            response = requests.get(url, stream=True, timeout=REQUESTS_TIMEOUT)
            response.raise_for_status()
            try:
                content = response.content.decode("utf-8")
            except UnicodeDecodeError:
                _logger.warning("Config %s: CSV is not UTF-8, trying ISO-8859-1.", self.name)
                content = response.content.decode("ISO-8859-1")

            csv_data = io.StringIO(content)
            reader = csv.DictReader(csv_data, delimiter=CSV_DELIMITER)

            expected_headers = {
                "ean13",
                "pvp",
                "pvd",
                "peso",
                "estado",
                "caratula",
                "titulo",
            }
            actual_headers = set(reader.fieldnames or [])
            if not expected_headers.issubset(actual_headers):
                missing_headers = expected_headers - actual_headers
                _logger.error(
                    "Config %s: Missing mandatory headers: %s", self.name, missing_headers
                )
                raise UserError(
                    f"CSV headers do not match expected format. Missing: {missing_headers}"
                )

            data = list(reader)
            _logger.info(
                "Config %s: CSV parsed successfully, %d records found",
                self.name,
                len(data),
            )
            return data
        except requests.Timeout:
            _logger.error(
                "Config %s: Timeout while fetching CSV from %s", self.name, url
            )
            raise UserError("Timeout while fetching CSV. Please try again later.")
        except requests.RequestException as e:
            _logger.error(
                "Config %s: Error fetching CSV from %s: %s", self.name, url, e
            )
            raise UserError(f"Error fetching CSV: {e}")
        except csv.Error as e:
            _logger.error("Config %s: Error parsing CSV: %s", self.name, e)
            raise UserError(f"Error parsing CSV: {e}")
        except Exception as e:
            _logger.exception(
                "Config %s: Unexpected error during CSV fetch/parse: %s", self.name, e
            )
            raise UserError(f"Unexpected error during CSV processing: {e}")
        finally:
            if csv_data:
                csv_data.close()
            if response:
                response.close()

    def _fetch_image_64(self, url):
        self.ensure_one()
        response = None
        try:
            response = requests.get(url, stream=True, timeout=IMAGE_TIMEOUT)
            response.raise_for_status()
            image_data = response.content
            try:
                with Image.open(io.BytesIO(image_data)) as img:
                    img.verify()
                base64_image = base64.b64encode(image_data).decode("utf-8")
                return base64_image
            except (OSError, Image.UnidentifiedImageError, Exception) as img_err:
                _logger.warning(
                    f"Config {self.name}: Content from URL {url} is not a valid image. Error: {img_err}"
                )
                return False

        except requests.Timeout:
            _logger.warning(
                "Config %s: Timeout fetching image from %s", self.name, url
            )
            return False
        except requests.RequestException as e:
            _logger.warning(
                "Config %s: Error fetching image from %s: %s", self.name, url, e
            )
            return False
        except Exception as e:
            _logger.error(
                "Config %s: Unexpected error fetching image %s: %s", self.name, url, e
            )
            return False
        finally:
            if response:
                response.close()

    def _parse_float(self, value):
        if not value or not isinstance(value, str):
            return 0.0
        cleaned_value = value.strip().replace(".", "").replace(",", ".")
        try:
            return float(cleaned_value)
        except ValueError:
            _logger.warning(f'Could not parse float from value: "{value}". Returning 0.0.')
            return 0.0
        except Exception as e:
            _logger.error(
                'Unexpected error parsing float value "%s": %s. Returning 0.0.',
                value,
                e,
            )
            return 0.0

    def _process_row_data(self, row):
        self.ensure_one()
        barcode = row.get("ean13", "").strip()
        if (
            not barcode or not barcode.isdigit() or len(barcode) > 13
        ):
            _logger.warning(
                f"Config {self.name}: Row skipped - Invalid or missing EAN13 (non-digit or >13 chars). Data: {row}"
            )
            return None, None

        image_url = row.get("caratula", "").strip()
        validated_image_b64 = None
        if image_url:
            base64_image = self._fetch_image_64(image_url)
            if base64_image:
                validated_image_b64 = base64_image

        main_vals = {
            "name": row.get("titulo", f"Producto {barcode}").strip(),
            "barcode": barcode,
            "list_price": self._parse_float(row.get("pvp", "")),
            "standard_price": self._parse_float(row.get("pvd", "")),
            "weight": self._parse_float(row.get("peso", "")),
            "sale_ok": row.get("estado", "").strip().lower()
            == self.available_state.lower(),
            "detailed_type": DEFAULT_PRODUCT_TYPE,
            "company_id": self.company_id.id,
            "categ_id": self.env.ref("product.product_category_all").id,
        }

        if validated_image_b64:
            main_vals["image_1920"] = validated_image_b64

        # --- Extract Tag Names ---
        tag_names = []
        for i in range(1, 7):
            tag_column = f"tag_{i}"
            tag_name = row.get(tag_column, "").strip()
            if tag_name:
                tag_names.append(tag_name)

        main_vals["_temp_product_tag_names"] = tag_names


        second_hand_vals = copy.deepcopy(main_vals)

        second_hand_vals.pop("_temp_product_tag_names", None)

        second_hand_barcode = barcode + self.second_hand_suffix
        second_hand_vals["barcode"] = second_hand_barcode
        second_hand_vals["taxes_id"] = [(6, 0, [])]
        second_hand_vals["default_code"] = self.second_hand_default_code
        second_hand_vals["name"] += f" ({self.second_hand_default_code})"

        return main_vals, second_hand_vals


    @api.model
    def _perform_sync_for_config(self, config_id):
        """
        Background job logic: Fetches, parses, and processes data for a specific config ID.
        This method is intended to be called via `with_delay()`.
        """
        job_env = self.env(context=dict(self.env.context, active_test=False))

        config = job_env["leisure.channel.sync"].browse(config_id)
        if not config.exists():
            _logger.error(
                "Leisure Channel Sync job started for non-existent config ID: %s",
                config_id,
            )
            return f"Job failed: Configuration ID {config_id} not found."

        _logger.info(
            "Starting background sync job for config: %s (ID: %s)",
            config.name,
            config_id,
        )
        ProductTemplate = job_env["product.template"]
        ProductTag = job_env["product.tag"]

        products_to_create = []
        products_to_update = {}
        updated_count = 0
        created_count = 0
        skipped_count = 0
        error_detail = None
        processed_barcodes = set()

        try:
            data = config._fetch_parse_csv(config.location)

            if not data:
                _logger.warning(
                    "Config %s: No data found in CSV or file is empty.", config.name
                )
                return f"Sync Job for '{config.name}': No data found in CSV."

            all_barcodes_in_csv_pre_process = set()
            products_data_pre_process = {}

            # --- Stage 1: Process rows and collect data ---
            for i, row in enumerate(data):
                try:
                    if not isinstance(row, dict):
                        _logger.warning(f"Config {config.name}: Skipping row {i+1} as it's not a dictionary: {row}")
                        skipped_count += 1
                        continue

                    row_dict = dict(row)
                    main_vals_raw, second_hand_vals_raw = config._process_row_data(row_dict)

                    if not main_vals_raw:
                        skipped_count += 1
                        continue

                    main_barcode = main_vals_raw.get("barcode")
                    second_barcode = second_hand_vals_raw.get("barcode")

                    if main_barcode in all_barcodes_in_csv_pre_process:
                        _logger.warning(
                            f"Config {config.name}: Duplicate barcode '{main_barcode}' found in CSV row {i+1}. Skipping this row's main product."
                        )
                        skipped_count += 2
                        continue
                    all_barcodes_in_csv_pre_process.add(main_barcode)

                    if second_barcode in all_barcodes_in_csv_pre_process:
                        _logger.warning(
                            f"Config {config.name}: Duplicate second-hand barcode '{second_barcode}' generated from CSV row {i+1}. Skipping this row's second-hand product."
                        )
                        all_barcodes_in_csv_pre_process.remove(main_barcode)
                        skipped_count += 2
                        continue
                    all_barcodes_in_csv_pre_process.add(second_barcode)

                    products_data_pre_process[main_barcode] = {
                        "main": main_vals_raw,
                        "second": second_hand_vals_raw,
                    }

                except Exception as e:
                    _logger.error(
                        f"Config {config.name}: Error processing CSV row {i+1}: {row}. Error: {e}",
                        exc_info=True,
                    )
                    skipped_count += 1

            if not products_data_pre_process:
                _logger.warning(
                    "Config %s: No valid products processed from the CSV after initial checks.", config.name
                )
                return f"Sync Job for '{config.name}': No valid products processed from CSV."

            # --- Stage 2: Find existing products ---
            _logger.info(
                f"Config {config.name}: Searching for {len(all_barcodes_in_csv_pre_process)} unique barcodes in Odoo..."
            )
            existing_products = ProductTemplate.search_read(
                [
                    ("barcode", "in", list(all_barcodes_in_csv_pre_process)),
                    ("company_id", "=", config.company_id.id),
                ],
                ["barcode"],
            )
            existing_barcodes_map = {p["barcode"]: p["id"] for p in existing_products}
            _logger.info(
                f"Config {config.name}: Found {len(existing_barcodes_map)} existing products matching barcodes for company {config.company_id.name}."
            )

            # --- Stage 3: Resolve Tags and Prepare Final Data ---
            tag_cache = {}

            for barcode, data_vals in products_data_pre_process.items():
                main_vals = data_vals["main"]
                second_vals = data_vals["second"]

                tag_names = main_vals.pop("_temp_product_tag_names", [])
                tag_ids = []

                if tag_names:
                    for tag_name in tag_names:
                        if not tag_name: continue

                        if tag_name in tag_cache:
                            tag_id = tag_cache[tag_name]
                            if tag_id:
                                tag_ids.append(tag_id)
                        else:
                            tag = ProductTag.search([('name', '=ilike', tag_name)], limit=1)
                            if tag:
                                tag_cache[tag_name] = tag.id
                                tag_ids.append(tag.id)
                            else:
                                try:
                                    new_tag = ProductTag.create({'name': tag_name})
                                    tag_cache[tag_name] = new_tag.id
                                    tag_ids.append(new_tag.id)
                                    _logger.info(f"Config {config.name}: Created new tag '{tag_name}' (ID: {new_tag.id})")
                                except Exception as e:
                                    _logger.error(f"Config {config.name}: Failed to create tag '{tag_name}' for barcode {barcode}: {e}")
                                    tag_cache[tag_name] = None

                unique_tag_ids = list(set(tag_ids))
                if unique_tag_ids:
                    m2m_command = [(6, 0, unique_tag_ids)]
                    main_vals["product_tag_ids"] = m2m_command
                    second_vals["product_tag_ids"] = m2m_command
                else:
                    main_vals["product_tag_ids"] = [(6, 0, [])]
                    second_vals["product_tag_ids"] = [(6, 0, [])]


                main_product_id = existing_barcodes_map.get(main_vals["barcode"])
                if main_product_id:
                    if main_product_id not in products_to_update:
                        products_to_update[main_product_id] = main_vals
                        processed_barcodes.add(main_vals["barcode"])
                    else:
                        _logger.warning(f"Config {config.name}: Barcode {main_vals['barcode']} mapped to multiple updates, using first encountered.")
                        skipped_count +=1
                elif main_vals['barcode'] not in processed_barcodes:
                    products_to_create.append(main_vals)
                    processed_barcodes.add(main_vals['barcode'])
                else:
                    _logger.warning(f"Config {config.name}: Barcode {main_vals['barcode']} already queued for creation, skipping duplicate.")
                    skipped_count +=1


                second_product_id = existing_barcodes_map.get(second_vals["barcode"])
                if second_product_id:
                    if second_product_id not in products_to_update:
                        products_to_update[second_product_id] = second_vals
                        processed_barcodes.add(second_vals['barcode'])
                    else:
                        _logger.warning(f"Config {config.name}: Barcode {second_vals['barcode']} mapped to multiple updates, using first encountered.")
                        skipped_count +=1
                elif second_vals['barcode'] not in processed_barcodes:
                    products_to_create.append(second_vals)
                    processed_barcodes.add(second_vals['barcode'])
                else:
                    _logger.warning(f"Config {config.name}: Barcode {second_vals['barcode']} already queued for creation, skipping duplicate.")
                    skipped_count +=1


            # --- Stage 4: Perform DB Operations (Update/Create) ---
            _logger.info(
                f"Config {config.name}: Updating {len(products_to_update)} products..."
            )
            for product_id, vals in products_to_update.items():
                try:
                    ProductTemplate.browse(product_id).write(vals)
                    updated_count += 1
                except Exception as e:
                    _logger.error(
                        f"Config {config.name}: Failed to update product ID {product_id} (barcode: {vals.get('barcode', 'N/A')}): {e}",
                        exc_info=True,
                    )
                    skipped_count += 1
            _logger.info(f"Config {config.name}: {updated_count} products updated.")

            _logger.info(
                f"Config {config.name}: Creating {len(products_to_create)} new products..."
            )
            total_to_create = len(products_to_create)
            for i in range(0, total_to_create, BATCH_SIZE):
                batch = products_to_create[i : i + BATCH_SIZE]
                batch_number = i // BATCH_SIZE + 1
                total_batches = (total_to_create + BATCH_SIZE - 1) // BATCH_SIZE
                _logger.info(
                    f"Config {config.name}: Creating batch {batch_number}/{total_batches} (Size: {len(batch)})"
                )
                try:
                    created_products = ProductTemplate.create(batch)
                    created_count += len(created_products)
                except Exception as e:
                    first_barcode = batch[0].get("barcode", "N/A") if batch else "N/A"
                    _logger.error(
                        f"Config {config.name}: Error creating product batch {batch_number} (starts with barcode {first_barcode}): {e}",
                        exc_info=True,
                    )
                    skipped_count += len(batch)
            _logger.info(f"Config {config.name}: {created_count} products created.")

        except UserError as ue:
            _logger.error(f"Config {config.name}: UserError during sync job: {ue}")
            error_detail = str(ue)

        except Exception as e:
            _logger.exception(
                f"Config {config.name}: Unhandled exception during sync job."
            )
            error_detail = f"Unexpected error: {e}"

        finally:
            summary_msg = (
                f"Sync job for config '{config.name}' finished. "
                f"Created: {created_count}, Updated: {updated_count}, Skipped/Errors: {skipped_count}."
            )
            if error_detail:
                summary_msg += f" Error encountered: {error_detail}"
                _logger.error(summary_msg)
            else:
                _logger.info(summary_msg)


            try:
                main_env_config = self.env["leisure.channel.sync"].browse(config_id)
                if main_env_config.exists():
                    main_env_config.message_post(body=summary_msg)
            except Exception as post_err:
                _logger.error(f"Failed to post summary message to config {config_id} chatter: {post_err}")

        return summary_msg


    def action_trigger_sync_job(self):
        """
        Button action: Queues the background job for THIS specific configuration.
        """
        self.ensure_one()
        job_uuid = self.with_delay(
            description=f"Sync Leisure Channel: {self.name or self.id}",
            identity_key=f"leisure-sync-{self.id}",
        )._perform_sync_for_config(
            self.id
        )

        _logger.info(
            "Queued sync job for config '%s' (ID: %s) with Job UUID: %s",
            self.name,
            self.id,
            job_uuid.uuid if job_uuid else "Not_Queued",
        )

        if not job_uuid:
            message = f'Product synchronization job for "{self.name}" is already running or queued.'
            msg_type = 'warning'
        else:
            message = f'Product synchronization job for "{self.name}" has been queued.'
            msg_type = 'info'


        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": ("Job Status"),
                "message": message,
                "sticky": False,
                "type": msg_type,
            },
        }

    @api.model
    def trigger_sync_for_all_configs(self):
        """
        Method called by Cron or manually: Queues sync jobs for ALL active configurations.
        """
        all_configs = self.search(
            [("location", "!=", False), ("location", "!=", "")]
        )
        _logger.info(
            "Cron/Manual Trigger: Preparing to queue sync jobs for %d Leisure Channel configurations.",
            len(all_configs),
        )

        queued_count = 0
        already_running_count = 0
        failed_to_queue_count = 0

        for config in all_configs:
            try:
                job_uuid = config.with_delay(
                    description=f"Sync Leisure Channel (All/Cron): {config.name or config.id}",
                    identity_key=f"leisure-sync-{config.id}",
                )._perform_sync_for_config(
                    config.id
                )

                if job_uuid:
                    _logger.info(
                        "Queued sync job via Cron/All for config '%s' (ID: %s) with Job UUID: %s",
                        config.name,
                        config.id,
                        job_uuid.uuid,
                    )
                    queued_count += 1
                else:
                    _logger.warning(
                        "Skipped queuing job for config '%s' (ID: %s) via Cron/All - already running/queued (identity_key match).",
                        config.name,
                        config.id,
                    )
                    already_running_count +=1

            except Exception as e:
                _logger.error(
                    f"Failed to queue job for config '{config.name}' (ID: {config.id}): {e}",
                    exc_info=True,
                )
                failed_to_queue_count += 1

        _logger.info(
            "Cron/Manual Trigger: Finished queuing sync jobs. Total Queued Now: %d, Already Running/Queued: %d, Failed to Queue: %d",
            queued_count,
            already_running_count,
            failed_to_queue_count
        )

    # Simple test job
    @api.model
    def _simple_job(self, message):
        _logger.warning(f"SIMPLE QUEUE JOB EXECUTED: {message}")
        return f"Job done: {message}"

    def run_simple_job(self):
        self.ensure_one()
        self.with_delay(description="Simple Test Job")._simple_job(f"Hello from queue via config {self.name}!")
        _logger.info("Simple test job queued.")
        return True
