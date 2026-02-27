"""Find opportunities for different match levels against the latest client."""
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.opportunities.models import Opportunity
from apps.clients.models import Client

client = Client.objects.order_by('-created_at').first()
print(f"Cliente: {client.name} ({client.cnpj})")
print(f"  Keywords: {client.keywords}")
print(f"  Regioes: {client.regions}")
print(f"  Valor max: {client.max_value}")
print(f"  Margem min: {client.min_margin_pct}%")
print()

# RO opportunities
ro_all = Opportunity.objects.filter(entity_uf='RO')
print(f"Oportunidades em RO: {ro_all.count()}")
print(f"Total oportunidades: {Opportunity.objects.count()}")
print()

# 1. Best: RO + tech keywords
print("=== MELHOR MATCH (RO + tecnologia/TI/infra) ===")
for kw in ['tecnologia', 'informática', 'software', 'sistema', 'infraestrutura', 'obra', 'rede']:
    qs = ro_all.filter(title__icontains=kw)
    for o in qs[:2]:
        val = f"R${o.estimated_value:,.2f}" if o.estimated_value else "s/valor"
        print(f"  [{o.entity_uf}] {val} - {o.title[:90]}")
        print(f"    PK: {o.pk}")

# 2. Medium: RO but unrelated sector
print("\n=== MATCH MEDIO (RO, setor diferente) ===")
qs = ro_all.filter(title__icontains='saude')
for o in qs[:2]:
    val = f"R${o.estimated_value:,.2f}" if o.estimated_value else "s/valor"
    print(f"  [{o.entity_uf}] {val} - {o.title[:90]}")
    print(f"    PK: {o.pk}")
qs = ro_all.filter(title__icontains='veículo')
for o in qs[:2]:
    val = f"R${o.estimated_value:,.2f}" if o.estimated_value else "s/valor"
    print(f"  [{o.entity_uf}] {val} - {o.title[:90]}")
    print(f"    PK: {o.pk}")

# 3. Low: Other state + tech
print("\n=== MATCH BAIXO (outro estado + tecnologia) ===")
qs = Opportunity.objects.exclude(entity_uf='RO').filter(title__icontains='tecnologia')[:3]
for o in qs:
    val = f"R${o.estimated_value:,.2f}" if o.estimated_value else "s/valor"
    print(f"  [{o.entity_uf}] {val} - {o.title[:90]}")
    print(f"    PK: {o.pk}")

# 4. Very low: Other state + unrelated
print("\n=== MATCH MUITO BAIXO (outro estado + alimentacao/combustivel) ===")
for kw in ['alimenta', 'combustível', 'medicamento', 'merenda']:
    qs = Opportunity.objects.exclude(entity_uf='RO').filter(title__icontains=kw)[:1]
    for o in qs:
        val = f"R${o.estimated_value:,.2f}" if o.estimated_value else "s/valor"
        print(f"  [{o.entity_uf}] {val} - {o.title[:90]}")
        print(f"    PK: {o.pk}")

# 5. Way over budget (> 2M)
print("\n=== ACIMA DO ORCAMENTO (valor > 2M, outro estado) ===")
qs = Opportunity.objects.exclude(entity_uf='RO').filter(estimated_value__gt=10000000)[:3]
for o in qs:
    val = f"R${o.estimated_value:,.2f}" if o.estimated_value else "s/valor"
    print(f"  [{o.entity_uf}] {val} - {o.title[:90]}")
    print(f"    PK: {o.pk}")
