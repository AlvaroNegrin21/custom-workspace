from odoo import _
import requests
import logging
import io

from odoo.addons.connector_importer.utils.import_utils import (
    CSVReader,
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
        specified_encoding = kwargs.get('encoding')
        _logger.info("HTTPCSVReader: Initial kwargs encoding: %s", specified_encoding)

        downloaded_content = None
        final_kwargs = kwargs.copy() # Use a copy to pass to super

        if filepath and is_valid_url(filepath):
            _logger.info("HTTPCSVReader: Fetching CSV from URL: %s", filepath)
            response = None
            downloaded_content = b""

            try:
                with requests.get(
                    filepath,
                    stream=True,
                    timeout=REQUESTS_TIMEOUT,
                    headers={"Accept-Encoding": "gzip, deflate"},
                ) as response:
                    response.raise_for_status()

                    for chunk in response.iter_content(chunk_size=chunk_size):
                        downloaded_content += chunk

                    if not downloaded_content: # More explicit check
                        _logger.error("HTTPCSVReader: Downloaded content is empty from %s", filepath)
                        raise UserError(_("The HTTP response from %s is empty.") % filepath)

                    # LOGGING ADDED HERE
                    _logger.info("HTTPCSVReader: Downloaded %s bytes.", len(downloaded_content))
                    # Try guessing metadata *including* encoding for debugging
                    try:
                        meta = guess_csv_metadata(downloaded_content)
                        _logger.info("HTTPCSVReader: Guessed metadata: %s", meta)
                        # The base CSVReader expects 'delimiter' and 'quotechar' in kwargs.
                        # It handles encoding based on the 'encoding' kwarg given to __init__
                        # and the 'filedata' bytes.
                        final_kwargs.update({k: v for k, v in meta.items() if k in ("delimiter", "quotechar")})

                        # Crucially, we must ensure the decoding in the base CSVReader uses the *correct* encoding.
                        # The base CSVReader will decode the 'filedata' bytes using the 'encoding' kwarg it receives.
                        # If guess_csv_metadata's encoding is reliable, maybe pass that?
                        # Or, ensure the initial 'encoding' kwarg from XML is correct.
                        # Let's log what encoding is *actually* passed to super.
                        _logger.info("HTTPCSVReader: Encoding passed to super: %s", final_kwargs.get('encoding', 'Default/None'))


                    except Exception as meta_err:
                        _logger.error("HTTPCSVReader: Error guessing metadata: %s", meta_err)
                        # Decide if you want to fail or continue with default/specified delimiter/quotechar
                        # If you continue, ensure final_kwargs retains the initial delimiter/quotechar if specified.
                        # For now, let's re-raise to understand the issue.
                        raise meta_err


                    final_kwargs["filedata"] = downloaded_content
                    filepath = None # Set filepath to None so super uses filedata

            except requests.Timeout:
                _logger.error("HTTPCSVReader: Timeout while fetching CSV from %s", filepath)
                raise UserError(_("Timeout while fetching CSV from %s. Please try again later.") % filepath)
            except requests.RequestException as e:
                _logger.error("HTTPCSVReader: Error fetching CSV from %s: %s", filepath, e)
                raise UserError(_("Error fetching CSV from %s: %s") % (filepath, e))
            except Exception as e:
                _logger.exception("HTTPCSVReader: Unexpected error during HTTP fetch for %s", filepath)
                raise UserError(_("Unexpected error processing CSV from %s: %s") % (filepath, e))
            finally:
                if response:
                    response.close()

        # LOGGING ADDED HERE
        _logger.info("HTTPCSVReader: Calling super with filepath=%s and kwargs=%s", filepath, final_kwargs)
        super().__init__(filepath=filepath, **final_kwargs)
