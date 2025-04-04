
from odoo import fields, models, api, Command

class EstateProperty(models.Model):
    _inherit = 'estate.property'



    def action_sold(self):
        for record in self:
            if record.state == 'sold':
                raise models.ValidationError("This property is already sold.")
            if record.state == 'canceled':
                raise models.ValidationError("You cannot sell a canceled property.")

            commission_amount = (record.selling_price * 6 / 100.0)
            fixed_fee = 100.0
            total_commission_charge = commission_amount + fixed_fee

            move_vals = {
                'partner_id': record.partner_id.id,
                'move_type': 'out_invoice',
                'invoice_date': fields.Date.context_today(record),
                'invoice_line_ids': [
                    Command.create({
                        'name': f"Sale of property: {record.name}",
                        'quantity': 1,
                        'price_unit': record.selling_price,
                    }),
                    Command.create({
                        'name': "Commission and Fees",
                        'quantity': 1,
                        'price_unit': total_commission_charge,
                    }),
                ]
            }
            try:
                record.state = 'sold'
            except Exception as e:
                raise models.UserError(("Failed to create the customer invoice. Error: %s") % e)

        invoice = self.env['account.move'].create(move_vals)

