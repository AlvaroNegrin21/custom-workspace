from odoo import fields, models

class PropertyType(models.Model):

    _name="estate.property.type"

    _order = 'name'

    name = fields.Char(string="Property Type", required=True)

    sequence = fields.Integer()

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'The property type name must be unique!'),
    ]

    property_ids = fields.One2many(
        'estate.property',
        'property_type_id',
        string='Properties',
    )

    offer_ids = fields.One2many(
        'estate.property.offer',
        'property_type_id',
        string='Offers',
    )

    offer_count = fields.Integer(
        string='Offers Count',
        compute='_compute_offer_count',
    )
    def _compute_offer_count(self):
        for record in self:
            record.offer_count = len(record.offer_ids)

    def action_view_offers(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Offers',
            'view_mode': 'tree,form',
            'res_model': 'estate.property.offer',
            'domain': [('property_type_id', '=', self.id)],
            'context': {'default_property_type_id': self.id},
        }
