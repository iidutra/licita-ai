"""Client forms."""
from django import forms

from .models import Client, ClientDocument


class ClientForm(forms.ModelForm):
    regions_input = forms.CharField(
        label="UFs de interesse",
        required=False,
        help_text="Separadas por vírgula: SP, RJ, MG",
        widget=forms.TextInput(attrs={"placeholder": "SP, RJ, MG"}),
    )
    keywords_input = forms.CharField(
        label="Palavras-chave",
        required=False,
        help_text="Separadas por vírgula",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "tecnologia, software, TI"}),
    )
    categories_input = forms.CharField(
        label="Categorias",
        required=False,
        help_text="Separadas por vírgula",
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    class Meta:
        model = Client
        fields = [
            "name", "cnpj", "trade_name", "email", "phone",
            "min_margin_pct", "max_value", "restrictions",
            "is_active", "notify_email", "webhook_url",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["regions_input"].initial = ", ".join(self.instance.regions)
            self.fields["keywords_input"].initial = ", ".join(self.instance.keywords)
            self.fields["categories_input"].initial = ", ".join(self.instance.categories)

    def _split_csv(self, field_name: str) -> list[str]:
        raw = self.cleaned_data.get(field_name, "")
        return [v.strip().upper() if "region" in field_name else v.strip()
                for v in raw.split(",") if v.strip()]

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.regions = self._split_csv("regions_input")
        instance.keywords = [v.strip() for v in
                             self.cleaned_data.get("keywords_input", "").split(",") if v.strip()]
        instance.categories = [v.strip() for v in
                               self.cleaned_data.get("categories_input", "").split(",") if v.strip()]
        instance.logistics_reach = instance.regions  # default: mesmas UFs
        if commit:
            instance.save()
        return instance


class ClientDocumentForm(forms.ModelForm):
    class Meta:
        model = ClientDocument
        fields = ["doc_type", "description", "file", "url", "issued_at", "expires_at", "status"]
        widgets = {
            "issued_at": forms.DateInput(attrs={"type": "date"}),
            "expires_at": forms.DateInput(attrs={"type": "date"}),
        }
