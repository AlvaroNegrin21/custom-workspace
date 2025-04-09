from odoo import fields, models, api
from dateutil.relativedelta import relativedelta

class PropertyOffer(models.Model):

    _name = "estate.property.offer"
    _description = "Estate Property Offer"
    _order = 'price desc'

    price = fields.Float()
    status = fields.Selection([
        ('accepted', 'Accepted'),
        ('refused', 'Refused'),
    ])
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
    )
    property_id = fields.Many2one(
        'estate.property',
        string='Property',
        required=True,
    )

    validity = fields.Integer(default=7)

    date_deadline = fields.Date(compute='compute_date_deadline', inverse='inverse_date_deadline')

    @api.depends('validity')
    def inverse_date_deadline(self):
        for record in self:
            if record.validity < 0:
                record.validity = 7
            else:
                record.validity = (record.date_deadline - fields.Date.today()).days

    @api.depends('date_deadline')
    def compute_date_deadline(self):
        for record in self:
            if record.validity < 0:
                record.date_deadline = fields.Date.today()
            else:
                record.date_deadline = fields.Date.today() + relativedelta(days=record.validity)

    def action_accepted(self):
        for record in self:
            if record.property_id.offer_ids.filtered(lambda offer: offer.status == 'accepted'):
                raise models.UserError("There is already an accepted offer for this property.")
            record.status = 'accepted'
            record.property_id.state = 'offer_accepted'
            record.property_id.selling_price = record.price
            record.property_id.partner_id = record.partner_id

    def action_refused(self):
        for record in self:
            record.status = 'refused'
            record.property_id.state = 'offer_received'
            record.property_id.selling_price = 0.0

    _sql_constraints = [
        ('price_check', 'CHECK(price > 0)', 'The offer price must be positive!'),
    ]

    property_type_id = fields.Many2one(
        'estate.property.type',
        string='Property Type',
        related='property_id.property_type_id',
        Stored=True,
    )

    @api.model
    def create(self, vals):
        self.env['estate.property'].browse(vals.get('property_id')).write({'state': 'offer_received'})
        return super(PropertyOffer, self).create(vals)
