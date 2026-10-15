from django import template

register = template.Library()

@register.filter
def override_tag(message_tags):
    if message_tags == 'error':
        return 'danger'
    else:
        return message_tags
