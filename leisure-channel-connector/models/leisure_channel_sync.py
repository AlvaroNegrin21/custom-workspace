from odoo import models, fields
from odoo.exceptions import UserError
from PIL import Image

import csv
import logging
import requests
import io
import base64
import copy


# --- Constantes ---
CSV_DELIMITER = ';'
REQUESTS_TIMEOUT = 120
IMAGE_TIMEOUT = 50
BATCH_SIZE = 1000
DEFAULT_PRODUCT_TYPE = 'product'
STATE_AVAILABLE = 'disponible'
SECOND_HAND_SUFFIX = 'OKA'
SECOND_HAND_DEFAULT_CODE = ('Segunda Mano')

_logger = logging.getLogger(__name__)

class LeisureChannelSync(models.Model):
    _name = 'leisure.channel.sync'
    _description = 'Leisure Channel Sync'

    location = fields.Char(
        string='Location',
        required=True,
        help='The location of the leisure channel'
    )

    second_hand_suffix = fields.Char(
        string='Second Hand Suffix',
        default=SECOND_HAND_SUFFIX,
        help='The suffix to identify second hand products'
    )

    second_hand_default_code = fields.Char(
        string='Second Hand Default Code',
        default=SECOND_HAND_DEFAULT_CODE,
        help='The default code for second hand products'
    )

    available_state = fields.Char(
        string='Available State',
        default=STATE_AVAILABLE,
        help='The state to identify available products'
    )

    def _fetch_parse_csv(self, url):
        """
        Fetch and parse the CSV file from the given URL.
        """

        self.ensure_one()
        _logger.info('Fetching CSV from %s', url)
        try:

            response = requests.get(
                url, stream=True, timeout=REQUESTS_TIMEOUT
            )
            response.raise_for_status()  # Raise an error for bad responses

            csv_data = io.StringIO(response.content.decode('ISO-8859-1'))
            reader = csv.DictReader(csv_data, delimiter=CSV_DELIMITER)

            expected_headers = {'ean13', 'pvp', 'pvd', 'peso', 'estado', 'caratula', 'titulo'}
            if not expected_headers.issubset(reader.fieldnames):
                missing_headers = expected_headers - set(reader.fieldnames)
                _logger.error('Missing headers: %s', missing_headers)
                raise UserError(f'CSV headers do not match expected format: {expected_headers}')

            data = list(reader)
            _logger.info('CSV parsed successfully, %d records found', len(data))
            return data
        except requests.Timeout:
            _logger.error('Timeout while fetching CSV from %s', url)
            raise UserError('Timeout while fetching CSV. Please try again later.')
        except requests.RequestException as e:
            _logger.error('Error fetching CSV from %s: %s', url, e)
            raise UserError(f'Error fetching CSV: {e}')
        except csv.Error as e:
            _logger.error('Error parsing CSV: %s', e)
            raise UserError(f'Error parsing CSV: {e}')
        except Exception as e:
            _logger.error('Unexpected error: %s', e)
            raise UserError(f'Unexpected error: {e}')
        finally:
            if 'csv_data' in locals():
                csv_data.close()
            if 'response' in locals():
                response.close()
            _logger.info('CSV file closed successfully')

    def _fetch_image_64(self, url):
        """
        Fetch an image from the given URL and return its base64 encoded string.
        """
        self.ensure_one()
        #_logger.info('Fetching image from %s', url)

        try:
            response = requests.get(url, stream=True, timeout=IMAGE_TIMEOUT)
            response.raise_for_status()  # Raise an error for bad responses

            image_data = response.content
            base64_image = base64.b64encode(image_data).decode('utf-8')
            #_logger.info('Image fetched successfully from %s', url)
            return base64_image
        except requests.Timeout:
            _logger.error('Timeout while fetching image from %s', url)
            raise UserError('Timeout while fetching image. Please try again later.')
        except requests.RequestException as e:
            _logger.error('Error fetching image from %s: %s', url, e)
            raise UserError(f'Error fetching image: {e}')
        except Exception as e:
            _logger.error('Unexpected error: %s', e)
            raise UserError(f'Unexpected error: {e}')
        finally:
            if 'response' in locals():
                response.close()
            #_logger.info('Image file closed successfully')

    def _parse_float(self, value):
        """
        Parse a float value from a string, handling thousands separators (,)
        and decimal separators (.). Returns 0.0 if parsing fails.
        """
        if not value or not isinstance(value, str):
            return 0.0

        cleaned_value = value.strip()

        cleaned_value = cleaned_value.replace(',', '')

        try:
            return float(cleaned_value)
        except ValueError:
            _logger.warning(
                'Could not parse float value "%s" (cleaned: "%s"). Returning 0.0.',
                value, cleaned_value
            )
            return 0.0
        except Exception as e:
            _logger.error(
                'Unexpected error parsing float value "%s": %s. Returning 0.0.',
                value, e
            )
            return 0.0

    def _process_row_data(self, row):
        """
        Process a single row of data from the CSV file.
        """
        self.ensure_one()
        #_logger.info('Processing row data: %s', row)

        barcode = row.get('ean13', '').strip()
        if not barcode or not barcode.isdigit():
            _logger.warning(f"Fila ignorada: EAN13 inválido o ausente. Datos: {row}")
            return None, None

        pvp = row.get('pvp', '').strip()

        pvd = row.get('pvd', '').strip()

        weight = row.get('peso', '').strip()

        sale_ok = row.get('estado', '').strip().lower() == self.available_state.lower()

        image_url = row.get('caratula', '').strip()

        base64_image = self._fetch_image_64(image_url) if image_url else False

        validated_image_b64 = None # Start with None

        if base64_image:
            try:
                img_data = base64.b64decode(base64_image)
                img_file_like = io.BytesIO(img_data)
                img = Image.open(img_file_like)
                img.verify()
                validated_image_b64 = base64_image
            except (base64.binascii.Error, OSError, Image.UnidentifiedImageError, Exception) as img_err:
                _logger.warning(f"Failed to decode/validate image from URL {image_url}. Skipping image for this product. Error: {img_err}")

        main_vals = {
            'name': row.get('titulo', 'Sin Nombre').strip(),
            'barcode': barcode,
            'list_price': self._parse_float(pvp),
            'standard_price': self._parse_float(pvd),
            'weight': self._parse_float(weight),
            'sale_ok': sale_ok,
            'detailed_type': DEFAULT_PRODUCT_TYPE,
            **({'image_1920': validated_image_b64} if validated_image_b64 else {}),
            'company_id': self.env.company.id,
            'categ_id': self.env.ref('product.product_category_all').id,
        }

        second_hand_vals = copy.deepcopy(main_vals)
        second_hand_vals['barcode'] += self.second_hand_suffix
        second_hand_vals['taxes_id'] = [(6, 0, [])]
        second_hand_vals['default_code'] = self.second_hand_default_code

        return main_vals, second_hand_vals

    def action_fetch_data(self):

        """
        Fetch data from the leisure channel and process it.
        """
        self.ensure_one()
        ProductTemplate = self.env['product.template']
        products_to_create = []
        updated_count = 0
        created_count = 0
        skipped_count = 0

        try:
            # 1. Obtener y parsear datos
            data = self._fetch_parse_csv(self.location)

            if not data:
                _logger.warning("No se encontraron datos en el CSV o el archivo está vacío.")
                raise UserError("No se encontraron datos en el CSV o el archivo está vacío.")

            # 2. Procesar filas y preparar datos
            all_barcodes = set()
            products_data = {}
            for i, row in enumerate(data):
                try:
                    row = dict(row)
                    main_vals, second_hand_vals = self._process_row_data(row)

                    if not main_vals:
                        skipped_count += 1
                        continue

                    # Almacenar para buscar existentes después
                    all_barcodes.add(main_vals['barcode'])
                    all_barcodes.add(second_hand_vals['barcode'])
                    products_data[main_vals['barcode']] = {'main': main_vals, 'second': second_hand_vals}

                except Exception as e:
                    _logger.error(f"Error procesando fila {i+1} del CSV: {row}. Error: {e}")
                    skipped_count += 1

            if not products_data:
                _logger.warning("No se procesaron productos válidos desde el CSV.")
                raise UserError("No se procesaron productos válidos desde el CSV.")

            # 3. Buscar productos existentes en Odoo eficientemente
            _logger.info(f"Buscando {len(all_barcodes)} códigos de barras existentes...")
            existing_products = ProductTemplate.with_context(active_test=False).search_read(
                [('barcode', 'in', list(all_barcodes))],
                ['barcode']
            )
            existing_barcodes = {p['barcode']: p['id'] for p in existing_products}
            _logger.info(f"Encontrados {len(existing_barcodes)} productos existentes.")

            # 4. Determinar qué crear y qué actualizar
            products_to_create = []
            products_to_update = {}

            for barcode, data_vals in products_data.items():
                main_vals = data_vals['main']
                second_vals = data_vals['second']

                # Producto Principal
                main_product_id = existing_barcodes.get(main_vals['barcode'])
                if main_product_id:
                    products_to_update[main_product_id] = main_vals
                else:
                    products_to_create.append(main_vals)

                # Producto Segunda Mano
                second_product_id = existing_barcodes.get(second_vals['barcode'])
                if second_product_id:
                    products_to_update[second_product_id] = second_vals
                else:
                    products_to_create.append(second_vals)

            # 5. Realizar actualizaciones
            _logger.info(f"Actualizando {len(products_to_update)} productos...")
            for product_id, vals in products_to_update.items():
                try:
                    ProductTemplate.browse(product_id).write(vals)
                    updated_count += 1
                except Exception as e:
                    _logger.error(f"Error actualizando producto ID {product_id} con barcode {vals.get('barcode')}: {e}")
            _logger.info(f"{updated_count} productos actualizados.")

            # 6. Realizar creaciones en lotes
            _logger.info(f"Creando {len(products_to_create)} productos nuevos...")
            total_to_create = len(products_to_create)
            for i in range(0, total_to_create, BATCH_SIZE):
                batch = products_to_create[i:i + BATCH_SIZE]
                _logger.info(f"Creando lote {i // BATCH_SIZE + 1}/{(total_to_create + BATCH_SIZE - 1) // BATCH_SIZE} (Tamaño: {len(batch)})")
                try:
                    created_products = ProductTemplate.create(batch)
                    created_count += len(created_products)
                except Exception as e:
                    _logger.error(f"Error creando lote de productos (inicia con barcode {batch[0].get('barcode') if batch else 'N/A'}): {e}")
            _logger.info(f"{created_count} productos creados.")

            _logger.info(f"Sincronización completada. Creados: {created_count}, Actualizados: {updated_count}, Ignorados/Errores: {skipped_count}")

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': ('Sincronización Completada'),
                    'message': ('Creados: %s, Actualizados: %s, Ignorados: %s') % (created_count, updated_count, skipped_count),
                    'sticky': False,
                }
            }

        except UserError as e:
            raise e
        except Exception as e:
            _logger.exception("Error fatal durante la sincronización de Canalocio.")
            raise UserError(("Ocurrió un error inesperado durante la sincronización. Revise los logs para más detalles. Error: %s") % e)

    def sync_database(self):
        """
        Sync the database with the leisure channel.
        """
        self.ensure_one()
        all_configs = self.env["leisure.channel.sync"].search([])
        _logger.info("Iniciando sincronización de Canalocio para %d configuraciones.", len(all_configs))

        error_count = 0
        success_count = 0

        for config in all_configs:
            try:
                _logger.info("Sincronizando configuración: %s", config.location)
                config.action_fetch_data()
                success_count += 1
            except UserError as e:
                _logger.error("Error en la configuración %s: %s", config.location, e)
                error_count += 1
            except Exception as e:
                _logger.exception("Error inesperado en la configuración %s: %s", config.location, e)
                error_count += 1
            finally:
                _logger.info("Sincronización de configuración %s finalizada.", config.location)
        _logger.info("Sincronización de Canalocio completada. Éxitos: %d, Errores: %d", success_count, error_count)
