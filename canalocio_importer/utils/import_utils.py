from odoo import _
import requests
import logging

from odoo.addons.connector_importer.utils.import_utils import (
    CSVReader,
    csv_content_to_file,
    guess_csv_metadata,
)
from odoo.exceptions import UserError
from urllib.parse import urlparse

from ..utils.url_constants import *

_logger = logging.getLogger(__name__)


def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False

class HTTPCSVReader(CSVReader):
    """CSVReader with support for HTTP URLs."""

    def __init__(self, filepath=None, chunk_size=8192, **kwargs):
        if filepath and is_valid_url(filepath):
            _logger.info("Fetching CSV from URL: %s", filepath)
            response = None
            try:
                with requests.get(
                    filepath,
                    stream=True,
                    timeout=REQUESTS_TIMEOUT,
                    headers={"Accept-Encoding": "gzip, deflate"},
                ) as response:
                    response.raise_for_status()
                    content = b""
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        content += chunk
                    assert content, _("The HTTP response is empty.")

                    try:
                        decoded_content = content.decode("utf-8")
                        _logger.debug("CSV decoded as UTF-8")
                    except UnicodeDecodeError:
                        _logger.warning("CSV not UTF-8, trying ISO-8859-1.")
                        decoded_content = content.decode("ISO-8859-1")
                        _logger.debug("CSV decoded as ISO-8859-1")
                    except Exception as decode_err:
                        _logger.error("Failed to decode CSV content: %s", decode_err)
                        raise UserError(f"Failed to decode CSV content: {decode_err}")


                    content_file = csv_content_to_file(decoded_content.encode('utf-8'))
                    content_file.seek(0)
                    content = content_file.read().encode('utf-8')

                    content_file.seek(0)
                    meta = guess_csv_metadata(content_file)

                    kwargs.update(
                        {k: v for k, v in meta.items() if k in ("delimiter", "quotechar")}
                    )
                    kwargs["filedata"] = content_file
                    filepath = None

            except requests.Timeout:
                _logger.error("Timeout while fetching CSV from %s", filepath)
                raise UserError(_("Timeout while fetching CSV from %s. Please try again later.") % filepath)
            except requests.RequestException as e:
                _logger.error("Error fetching CSV from %s: %s", filepath, e)
                raise UserError(_("Error fetching CSV from %s: %s") % (filepath, e))
            except AssertionError as ae:
                _logger.error("Fetched CSV content is empty from %s", filepath)
                raise UserError(_("The HTTP response from %s is empty.") % filepath)
            except Exception as e:
                _logger.exception("Unexpected error during HTTP fetch/metadata guess for %s", filepath)
                raise UserError(_("Unexpected error processing CSV from %s: %s") % (filepath, e))
            finally:
                if response:
                    response.close()


        super().__init__(filepath=filepath, **kwargs)

