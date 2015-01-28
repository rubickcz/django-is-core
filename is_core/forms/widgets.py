from __future__ import unicode_literals

import os

from itertools import chain

from django import forms
from django.utils.encoding import force_text
from django.utils.safestring import mark_safe
from django.utils.html import format_html, format_html_join, conditional_escape
from django.utils.translation import ugettext_lazy as _
from django.db.models.fields.files import FieldFile
from django.core.exceptions import ImproperlyConfigured
from django.forms.widgets import Widget, URLInput
from django.forms.util import flatatt
from django.core.validators import EMPTY_VALUES


try:
    from sorl.thumbnail import default
except ImportError:
    default = None


EMPTY_VALUE = '---'


def flat_data_attrs(attrs):
    return format_html_join('', ' data-{0}="{1}"', sorted(attrs.items()))


class WrapperWidget(forms.Widget):

    def __init__(self, widget):
        self.widget = widget

    @property
    def media(self):
        return self.widget.media

    @property
    def attrs(self):
        return self.widget.attrs

    def build_attrs(self, extra_attrs=None, **kwargs):
        "Helper function for building an attribute dictionary."
        self.attrs = self.widget.build_attrs(extra_attrs=None, **kwargs)
        return self.attrs

    def value_from_datadict(self, data, files, name):
        return self.widget.value_from_datadict(data, files, name)

    def id_for_label(self, id_):
        return self.widget.id_for_label(id_)

    def render(self, name, value, attrs=None):
        return self.widget.render(name, value, attrs)


class SelectMixin(object):

    def render_option(self, selected_choices, option_value, option_label, option_attrs):
        option_value = force_text(option_value)
        if option_value in selected_choices:
            selected_html = mark_safe(' selected="selected"')
            if not self.allow_multiple_selected:
                # Only allow for a single selection.
                selected_choices.remove(option_value)
        else:
            selected_html = ''
        return format_html('<option value="{0}"{1}{2}>{3}</option>',
                           option_value,
                           selected_html,
                           flat_data_attrs(option_attrs) or '',
                           force_text(option_label))

    def render_options(self, choices, selected_choices):
        # Normalize to strings.
        selected_choices = set(force_text(v) for v in selected_choices)
        output = []
        for choice in chain(self.choices, choices):
            option_value, option_label = choice
            if isinstance(option_label, (list, tuple)):
                output.append(format_html('<optgroup label="{0}">', force_text(option_value)))
                for option in option_label:
                    output.append(self.render_option(selected_choices, *option))
                output.append('</optgroup>')
            else:
                output.append(self.render_option(selected_choices, option_value, option_label, choice.attrs))
        return '\n'.join(output)


class Select(SelectMixin, forms.Select):

    class_name = 'fulltext-search'
    placeholder = _('Search...')


class MultipleSelect(SelectMixin, forms.SelectMultiple):

    class_name = 'fulltext-search-multiple'
    placeholder = _('Search...')


class ClearableFileInput(forms.ClearableFileInput):

    def render(self, name, value, attrs=None):
        substitutions = {
            'initial_text': self.initial_text,
            'input_text': self.input_text,
            'clear_template': '',
            'clear_checkbox_label': self.clear_checkbox_label,
        }
        template = '%(input)s'
        substitutions['input'] = super(forms.ClearableFileInput, self).render(name, value, attrs)

        if value and hasattr(value, "url"):
            template = self.template_with_initial
            substitutions['initial'] = format_html(self.url_markup_template,
                                                   value.url,
                                                   os.path.basename(force_text(value)))
            if not self.is_required:
                checkbox_name = self.clear_checkbox_name(name)
                checkbox_id = self.clear_checkbox_id(checkbox_name)
                substitutions['clear_checkbox_name'] = conditional_escape(checkbox_name)
                substitutions['clear_checkbox_id'] = conditional_escape(checkbox_id)
                substitutions['clear'] = forms.CheckboxInput().render(checkbox_name, False, attrs={'id': checkbox_id})
                substitutions['clear_template'] = self.template_with_clear % substitutions

        return mark_safe(template % substitutions)


class DragAndDropFileInput(ClearableFileInput):

    def _render_value(self, value):
        return '<a href="%s">%s</a>' % (value.url, os.path.basename(value.name))

    def render(self, name, value, attrs={}):
        output = ['<div class="drag-and-drop-wrapper">']
        output.append('<div class="drag-and-drop-placeholder"%s></div>' % (id and 'data-for="%s"' % id or ''))
        output.append('<div class="thumbnail-wrapper">')
        if value and isinstance(value, FieldFile):
            output.append(self._render_value(value))
        output.append('</div><div class=file-input-wrapper>')
        output.append(super(DragAndDropFileInput, self).render(name, value, attrs=attrs))
        output.append(2 * '</div>')
        return mark_safe('\n'.join(output))


class DragAndDropImageInput(DragAndDropFileInput):

    def _get_thumbnail(self, value):
        if not default:
            raise ImproperlyConfigured('Please install sorl.thumbnail before using drag-and-drop file input')
        return default.backend.get_thumbnail(value, '64x64', crop='center')

    def _render_value(self, value):
        thumbnail = self._get_thumbnail(value)
        return '<img src="%s" alt="%s">' % (thumbnail.url, thumbnail.name)


class SmartWidgetMixin(object):

    def smart_render(self, request, *args, **kwargs):
        return self.render(*args, **kwargs)


class ReadonlyWidget(SmartWidgetMixin, Widget):

    def __init__(self, widget=None, attrs=None):
        super(ReadonlyWidget, self).__init__(attrs)
        self.widget = widget

    def _get_value(self, value):
        from is_core.utils import display_for_value

        if self.widget and hasattr(self.widget, 'choices'):
            result = dict(self.widget.choices).get(value)
        else:
            result = value

        if result in EMPTY_VALUES:
            result = EMPTY_VALUE

        if result and isinstance(self.widget, URLInput):
            return mark_safe('<a href="%s">%s</a>' % (result, result))
        if isinstance(result, FieldFile):
            return mark_safe('<a href="%s">%s</a>' % (result.url, os.path.basename(result.name)))
        return display_for_value(result)

    def render(self, name, value, attrs=None, choices=()):
        if isinstance(value, (list, tuple)):
            out = ', '.join([self._get_value(val) for val in value])
        else:
            out = self._get_value(value)
        return mark_safe('<p>%s</p>' % conditional_escape(out))

    def _has_changed(self, initial, data):
        return False


class ModelChoiceReadonlyWidget(ReadonlyWidget):

    def _get_widget(self):
        widget = self.widget
        while isinstance(widget, WrapperWidget):
            widget = widget.widget
        return widget

    def _get_choice(self, value):
        widget = self._get_widget()
        if hasattr(widget, 'choices'):
            for choice in widget.choices:
                if choice[0] == value:
                    return choice

    def smart_render(self, request, name, value, attrs=None, choices=()):
        choice = self._get_choice(value)

        out = []
        if choice:
            value = force_text(choice[1])
            if (choice.obj and hasattr(getattr(choice.obj, 'get_absolute_url', None), '__call__')
                and hasattr(getattr(choice.obj, 'can_see_edit_link', None), '__call__')
                and choice.obj.can_see_edit_link(request)):
                value = '<a href="%s">%s</a>' % (choice.obj.get_absolute_url(), value)
        else:
            if value in EMPTY_VALUES:
                value = EMPTY_VALUE

        out.append(value)
        return mark_safe('<p>%s</p>' % '\n'.join(out))


class EmptyWidget(ReadonlyWidget):

    def render(self, name, value, attrs=None):
        return ''


class ButtonWidget(ReadonlyWidget):

    def render(self, name, value, attrs=None):
        final_attrs = self.build_attrs(attrs, name=name)

        return format_html('<button %(attrs)s>%(value)s</button>' %
                           {'value': value, 'attrs': flatatt(final_attrs)})


class DivButtonWidget(ReadonlyWidget):

    def render(self, name, value, attrs=None):
        final_attrs = self.build_attrs(attrs)
        class_name = final_attrs.pop('class', '')
        return format_html('<div class="%(class_name)s btn btn-primary btn-small" '
                           '%(attrs)s>%(value)s</div>' %
                           {'class_name': class_name, 'value': value, 'attrs': flatatt(final_attrs)})

