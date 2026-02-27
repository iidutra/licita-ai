"""Run matching tests across different expected score levels."""
import django, os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from apps.clients.models import Client
from apps.opportunities.models import Opportunity
from apps.matching.engine import run_matching

client = Client.objects.order_by('-created_at').first()
print(f"Cliente: {client.name} ({client.cnpj})")
print(f"  Keywords: {client.keywords}")
print(f"  Regioes: {client.regions}")
print(f"  Valor max: {client.max_value}")
print("=" * 80)

# Selected opportunities across expected match levels
test_cases = [
    # (PK, expected_level, description)
    ("f0add837-b844-4592-bab4-f6ea16883260", "ALTO",       "RO + obra prevencao R$163k"),
    ("05888e88-431e-4b51-94f7-bf2635dc6007", "ALTO",       "RO + pavimentacao R$1.7M"),
    ("2951fc64-8eaa-486b-8c64-395f9325b947", "ALTO",       "RO + instalacao R$56k"),
    ("312f5aa9-9085-4762-b810-da04c0441319", "MEDIO",      "RO + combustivel R$1M"),
    ("cb7da96f-2284-42e6-b641-7a575f0ab814", "BAIXO",      "PR + TI R$248k"),
    ("aa7498ff-5499-4660-be78-07670c84b0a1", "BAIXO",      "RJ + proj tecnicos R$9M"),
    ("3aa438c8-76dd-4116-be64-4531593c310a", "MUITO_BAIXO", "PR + concessao R$7k"),
    ("cb5ae2e2-1377-4736-9561-676357c2d75d", "MUITO_BAIXO", "PE + camara fria R$3.8M"),
    ("4d8de16c-7e2a-42ec-ab9e-67becbc553b6", "MUITO_BAIXO", "PE + merenda R$81k"),
    ("bcd91bbd-26df-42b8-8fa8-f6716d781eb8", "ACIMA_ORC",  "SP + obra R$21M"),
]

results = []
for pk, expected, desc in test_cases:
    try:
        opp = Opportunity.objects.get(pk=pk)
    except Opportunity.DoesNotExist:
        print(f"[SKIP] {pk} nao encontrado")
        continue

    print(f"\n--- Matching: {desc} ---")
    print(f"  Oportunidade: {opp.title[:80]}")
    print(f"  UF: {opp.entity_uf} | Valor: R${opp.estimated_value:,.2f}" if opp.estimated_value else f"  UF: {opp.entity_uf} | Valor: s/valor")
    print(f"  Esperado: {expected}")

    try:
        match = run_matching(opp, client)
        print(f"  >>> SCORE: {match.score}/100")
        print(f"  Justificativa: {match.justification[:200]}")
        if match.missing_docs:
            print(f"  Docs faltantes: {match.missing_docs}")
        if match.missing_capabilities:
            print(f"  Competencias faltantes: {match.missing_capabilities}")
        results.append((desc, expected, match.score, match.justification[:100]))
    except Exception as e:
        print(f"  ERRO: {e}")
        results.append((desc, expected, -1, str(e)[:100]))

print("\n" + "=" * 80)
print("RESUMO DOS MATCHES")
print("=" * 80)
print(f"{'Descricao':<35} {'Esperado':<15} {'Score':>5}")
print("-" * 60)
for desc, expected, score, _ in results:
    print(f"{desc:<35} {expected:<15} {score:>5}")
