from odoo import models, fields, api
from odoo.exceptions import UserError
from PIL import Image

import csv
import logging
import requests
import io
import base64
import copy

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
    _inherit = ['mail.thread', 'mail.activity.mixin'] # Add chatter

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
    # Add message_follower_ids, activity_ids, message_ids if inheriting mail.thread/activity.mixin
    # message_follower_ids = fields.One2many('mail.followers', 'res_id', string='Followers')
    # activity_ids = fields.One2many('mail.activity', 'res_id', string='Activities')
    # message_ids = fields.One2many('mail.message', 'res_id', string='Messages')

    def _fetch_parse_csv(self, url):
        self.ensure_one()
        _logger.info("Fetching CSV from %s for config %s", url, self.name)
        try:
            response = requests.get(url, stream=True, timeout=REQUESTS_TIMEOUT)
            response.raise_for_status()
            csv_data = io.StringIO(response.content.decode("ISO-8859-1"))
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
                    "Config %s: Missing headers: %s", self.name, missing_headers
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
            if "csv_data" in locals() and csv_data:
                csv_data.close()
            if "response" in locals() and response:
                response.close()

    def _fetch_image_64(self, url):
        self.ensure_one()
        try:
            response = requests.get(url, stream=True, timeout=IMAGE_TIMEOUT)
            response.raise_for_status()
            image_data = response.content
            base64_image = base64.b64encode(image_data).decode("utf-8")
            return base64_image
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
            if "response" in locals() and response:
                response.close()

    def _parse_float(self, value):
        if not value or not isinstance(value, str):
            return 0.0
        cleaned_value = value.strip().replace(",", "")
        try:
            return float(cleaned_value)
        except ValueError:
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
                f"Config {self.name}: Row skipped - Invalid or missing EAN13. Data: {row}"
            )
            return None, None

        # image_url = row.get("caratula", "").strip()
        # base64_image = self._fetch_image_64(image_url) if image_url else False
        # validated_image_b64 = None

        # if base64_image:
        #     try:
        #         if len(base64_image) % 4 == 0 and all(
        #             c
        #             in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        #             for c in base64_image
        #         ):
        #             img_data = base64.b64decode(base64_image, validate=True)
        #             img_file_like = io.BytesIO(img_data)
        #             with Image.open(img_file_like) as img:
        #                 img.verify()
        #             validated_image_b64 = base64_image
        #         else:
        #             _logger.warning(
        #                 f"Config {self.name}: Invalid base64 characters or padding for URL {image_url}. Skipping image."
        #             )
        #     except (
        #         base64.binascii.Error,
        #         OSError,
        #         Image.UnidentifiedImageError,
        #         EOFError,
        #         Exception,
        #     ) as img_err:  # Added EOFError
        #         _logger.warning(
        #             f"Config {self.name}: Failed to decode/validate image from URL {image_url}. Barcode: {barcode}. Skipping image. Error: {img_err}"
        #         )
        #     finally:
        #         if "img_file_like" in locals() and img_file_like:
        #             img_file_like.close()

        main_vals = {
            "name": row.get("titulo", f"Producto {barcode}").strip(),
            "barcode": barcode,
            "list_price": self._parse_float(row.get("pvp", "")),
            "standard_price": self._parse_float(row.get("pvd", "")),
            "weight": self._parse_float(row.get("peso", "")),
            "sale_ok": row.get("estado", "").strip().lower()
            == self.available_state.lower(),
            "detailed_type": DEFAULT_PRODUCT_TYPE,
            #**({"image_1920": validated_image_b64} if validated_image_b64 else {}),
            "company_id": self.company_id.id,
            "categ_id": self.env.ref("product.product_category_all").id,
        }

        second_hand_vals = copy.deepcopy(main_vals)
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
        config = self.env["leisure.channel.sync"].browse(config_id)
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
        ProductTemplate = self.env["product.template"].with_context(active_test=False)
        products_to_create = []
        products_to_update = {}
        updated_count = 0
        created_count = 0
        skipped_count = 0
        error_detail = None

        try:
            data = config._fetch_parse_csv(config.location)

            if not data:
                _logger.warning(
                    "Config %s: No data found in CSV or file is empty.", config.name
                )
                return f"Sync Job for '{config.name}': No data found in CSV."

            all_barcodes_in_csv = set()
            products_data = {}

            for i, row in enumerate(data):
                try:
                    row_dict = dict(row)
                    main_vals, second_hand_vals = config._process_row_data(row_dict)

                    if not main_vals:
                        skipped_count += 1
                        continue

                    if main_vals["barcode"] in all_barcodes_in_csv:
                        _logger.warning(
                            f"Config {config.name}: Duplicate barcode {main_vals['barcode']} found in CSV row {i+1}. Skipping subsequent occurrences."
                        )
                        skipped_count += 1
                        continue
                    if second_hand_vals["barcode"] in all_barcodes_in_csv:
                        _logger.warning(
                            f"Config {config.name}: Duplicate second-hand barcode {second_hand_vals['barcode']} generated from row {i+1}. Skipping."
                        )
                        skipped_count += 1
                        continue

                    all_barcodes_in_csv.add(main_vals["barcode"])
                    all_barcodes_in_csv.add(second_hand_vals["barcode"])
                    products_data[main_vals["barcode"]] = {
                        "main": main_vals,
                        "second": second_hand_vals,
                    }

                except Exception as e:
                    _logger.error(
                        f"Config {config.name}: Error processing CSV row {i+1}: {row}. Error: {e}",
                        exc_info=True,
                    )
                    skipped_count += 1

            if not products_data:
                _logger.warning(
                    "Config %s: No valid products processed from the CSV.", config.name
                )
                return f"Sync Job for '{config.name}': No valid products processed from CSV."

            _logger.info(
                f"Config {config.name}: Searching for {len(all_barcodes_in_csv)} barcodes in Odoo..."
            )
            existing_products = ProductTemplate.search_read(
                [
                    ("barcode", "in", list(all_barcodes_in_csv)),
                    ("company_id", "=", config.company_id.id),
                ],
                ["barcode"],
            )
            existing_barcodes = {p["barcode"]: p["id"] for p in existing_products}
            _logger.info(
                f"Config {config.name}: Found {len(existing_barcodes)} existing products matching barcodes for company {config.company_id.name}."
            )

            for barcode, data_vals in products_data.items():
                main_vals = data_vals["main"]
                second_vals = data_vals["second"]

                main_product_id = existing_barcodes.get(main_vals["barcode"])
                if main_product_id:
                    products_to_update[main_product_id] = main_vals
                else:
                    products_to_create.append(main_vals)

                second_product_id = existing_barcodes.get(second_vals["barcode"])
                if second_product_id:
                    products_to_update[second_product_id] = second_vals
                else:
                    products_to_create.append(second_vals)

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
            raise

        except Exception as e:
            _logger.exception(
                f"Config {config.name}: Unhandled exception during sync job."
            )
            error_detail = f"Unexpected error: {e}"
            raise

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
                if config.exists():
                    config.message_post(body=summary_msg)
            except Exception as post_err:
                _logger.error(f"Failed to post summary message to config {config_id}: {post_err}")

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
            job_uuid,
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": ("Job Queued"),
                "message": f'Product synchronization job for "{self.name}" has been queued.',
                "sticky": False,
                "type": "info",
            },
        }

    #@api.model
    def trigger_sync_for_all_configs(self):
        """
        Method called by Cron or manually: Queues sync jobs for ALL active configurations.
        """
        all_configs = self.search(
            [("location", "!=", False)]
        )
        _logger.info(
            "Cron/Manual Trigger: Preparing to queue sync jobs for %d Leisure Channel configurations.",
            len(all_configs),
        )

        queued_count = 0
        for config in all_configs:
            try:
                job_uuid = config.with_delay(
                    description=f"Sync Leisure Channel (All/Cron): {config.name or config.id}",
                    identity_key=f"leisure-sync-{config.id}",
                )._perform_sync_for_config(
                    config.id
                )

                _logger.info(
                    "Queued sync job via Cron/All for config '%s' (ID: %s) with Job UUID: %s",
                    config.name,
                    config.id,
                    job_uuid,
                )
                queued_count += 1
            except Exception as e:
                _logger.error(
                    f"Failed to queue job for config '{config.name}' (ID: {config.id}): {e}",
                    exc_info=True,
                )

        _logger.info(
            "Cron/Manual Trigger: Finished queuing sync jobs. Total queued: %d",
            queued_count,
        )

    @api.model
    def _simple_job(self, message):
        _logger.warning(f"SIMPLE QUEUE JOB EXECUTED: {message}")
        return f"Job done: {message}"

    def run_simple_job(self):
        self.with_delay(description="Simple Test Job")._simple_job("Hello from queue!")
        _logger.info("Simple test job queued.")
