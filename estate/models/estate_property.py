from odoo import fields, models, api
from datetime import date
from dateutil.relativedelta import relativedelta

class EstateProperty(models.Model):
    _name = 'estate.property'
    _description = 'Estate Property Management'
    _order = 'id desc'

    name = fields.Char(required=True)

    description = fields.Text()

    postcode = fields.Char()

    date_availability = fields.Date(default=lambda self: date.today() + relativedelta(days=90))

    expected_price = fields.Float(required=True)

    selling_price = fields.Float()

    bedrooms = fields.Integer(default=2)

    living_area = fields.Integer()

    facades = fields.Integer()

    garage = fields.Boolean()

    garden = fields.Boolean()

    garden_area = fields.Integer()

    garden_orientation = fields.Selection([
        ('north', 'North'),
        ('south', 'South'),
        ('east', 'East'),
        ('west', 'West'),
    ], string='Garden Orientation')

    active = fields.Boolean(default=True)

    sequence = fields.Integer()

    state = fields.Selection([
        ('new', 'New'),
        ('offer_received', 'Offer Received'),
        ('offer_accepted', 'Offer Accepted'),
        ('sold', 'Sold'),
        ('canceled', 'Canceled'),
    ], default='new', required=True, string='Status')

    property_type_id = fields.Many2one(
        'estate.property.type',
        string='Property Type',
        required=True,
        options="{'no_create': True, 'no_open': True}",
    )

    partner_id = fields.Many2one("res.partner", string="Partner")

    user_id = fields.Many2one('res.users', string='Salesperson', index=True, tracking=True, default=lambda self: self.env.user)

    tag_ids = fields.Many2many(
        'estate.property.tag',
        string='Tags',
    )

    offer_ids = fields.One2many(
        'estate.property.offer',
        'property_id',
        string='Offers',
    )

    total_area = fields.Integer(compute='_compute_total_area')


    @api.depends('living_area', 'garden_area', 'garden')
    def _compute_total_area(self):
        for record in self:
            record.total_area = record.living_area + (record.garden_area if record.garden else 0)

    best_price = fields.Float(compute='_compute_best_price')

    @api.depends('offer_ids.price')
    def _compute_best_price(self):
        for record in self:
            record.best_price = max(record.offer_ids.mapped('price'), default=0.0)

    @api.onchange('garden')
    def _onchange_garden(self):
        if not self.garden:
            self.garden_area = 0
            self.garden_orientation = False
        else:
            self.garden_area = 10
            self.garden_orientation = 'north'

    def action_sold(self):
        for record in self:
            if record.state == 'sold':
                raise models.ValidationError("This property is already sold.")
            if record.state == 'canceled':
                raise models.ValidationError("You cannot sell a canceled property.")
            record.state = 'sold'

    def action_cancel(self):
        for record in self:
            if record.state == 'canceled':
                raise models.ValidationError("This property is already canceled.")
            if record.state == 'sold':
                raise models.ValidationError("You cannot cancel a sold property.")
            record.state = 'canceled'

    _sql_constraints = [
        ('check_expected_price', 'CHECK(expected_price > 0)', 'The expected price must be stricly positive!'),
        ('check_selling_price', 'CHECK(selling_price >= 0)', 'The selling price must be positive or zero!'),
    ]

    @api.constrains('selling_price', 'expected_price')
    def _check_selling_price(self):
        for record in self:
            if record.selling_price and record.selling_price < (record.expected_price * 0.9):
                raise models.ValidationError("The selling price must be at least 90% of the expected price.")

    @api.model
    def ondelete(self):
        for record in self:
            if record.state == 'new':
                raise models.ValidationError("You cannot delete a new property.")
            if record.state == 'canceled':
                raise models.ValidationError("You cannot delete a canceled property.")
        return super(EstateProperty, self).unlink()

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
