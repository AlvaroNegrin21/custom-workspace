# from urllib.parse import urlparse

# import requests

# from odoo.addons.connector_importer.utils.import_utils import (
#     CSVReader,
#     csv_content_to_file,
#     guess_csv_metadata
# )

# def is_valid_url(url):
#     try:
#         result = urlparse(url)
#         return all([result.scheme in ("http", "https"), result.netloc])
#     except Exception:
#         return False


# class HTTPCSVReader(CSVReader):
#     """CSV reader for HTTP URLs."""

#     def __init__(self, filepath=None, chunk_size=8192, **kwargs):
#         if filepath and is_valid_url(filepath):
#             with requests.get(
#                 filepath,
#                 stream=True,
#                 timeout=30,
#                 headers={'Accept-Encoding': 'gzip, deflate'}
#             ) as response:
#                 response.raise_for_status()

#                 content = b""
#                 for chunk in response.iter_content(chunk_size=chunk_size):
#                     content += chunk
#                 assert content, "Empty response content"
#                 content = csv_content_to_file(content)
#                 content = self.normalize_line_endings(content)
#                 meta = guess_csv_metadata(content)
#                 kwargs.update(
#                     {k: v for k, v in meta.items() if k in ("delimeter", "quotechar")}
#                 )
#                 kwargs["filepath"] = content
#                 filepath = None
#         super().__init__(filepath=filepath, **kwargs)

#     def _normalize_line_endings(self, content):
#         """Normalize line endings to \n."""
#         line_endings = [
#             b"\x85"
#         ]

#         for ending in line_endings:
#             content = content.replace(ending, b"\n")
#         return content

from urllib.parse import urlparse

import requests

from odoo import _

from odoo.addons.connector_importer.utils.import_utils import (
    CSVReader,
    csv_content_to_file,
    guess_csv_metadata,
)


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
            # Use streaming for memory efficiency
            with requests.get(
                filepath,
                stream=True,
                timeout=30,
                headers={"Accept-Encoding": "gzip, deflate"},
            ) as response:
                response.raise_for_status()
                # Read content in chunks
                content = b""
                for chunk in response.iter_content(chunk_size=chunk_size):
                    content += chunk
                assert content, _("The HTTP response is empty.")
                content = csv_content_to_file(content)
                content = self._normalize_line_endings(content)
                meta = guess_csv_metadata(content)
                kwargs.update(
                    {k: v for k, v in meta.items() if k in ("delimiter", "quotechar")}
                )
                kwargs["filedata"] = content
                filepath = None

        super().__init__(filepath=filepath, **kwargs)

    def _normalize_line_endings(self, content):
        """Replace all line ending variants with standard \n."""
        # Common line endings to replace (including \x85 which is NEXT LINE character)
        line_endings = [
            b"\x85",  # Next Line
        ]

        # First convert all line endings to \n
        for ending in line_endings:
            content = content.replace(ending, b"\n")

        return content
