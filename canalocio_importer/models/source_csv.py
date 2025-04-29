# Author: Rolando Pérez Rebollo
# Copyright 2025 Binhex
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import models

from ..utils.import_utils import HTTPCSVReader


class CSVSource(models.Model):
    _inherit = "import.source.csv"

    _csv_reader_klass = HTTPCSVReader

    @property
    def _config_summary_fields(self):
        _fields = super()._config_summary_fields
        return _fields + [
            "csv_path",
        ]

    def _generate_csv_reader(self, reader_args):
        res = super()._generate_csv_reader(reader_args)
        if self.csv_path:
            self.csv_delimiter = res.delimiter
            self.csv_quotechar = res.quotechar
        return res
