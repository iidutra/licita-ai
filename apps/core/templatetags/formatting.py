"""Custom template filters for formatting."""
from django import template

register = template.Library()


@register.filter
def format_cnpj(value):
    """Format CNPJ: 14117931000189 → 14.117.931/0001-89"""
    if not value:
        return value
    s = str(value).strip().replace(".", "").replace("/", "").replace("-", "")
    if len(s) != 14:
        return value
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


@register.filter
def format_currency(value):
    """Format currency: 1234567.89 → 1.234.567,89"""
    if value is None:
        return "\u2014"
    try:
        val = float(value)
    except (TypeError, ValueError):
        return value
    # Format with 2 decimal places, Brazilian style
    formatted = f"{val:,.2f}"
    # Swap , and . for Brazilian format
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"
