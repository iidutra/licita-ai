"""Fast DB-level opportunity matching for a client (no AI calls)."""
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.utils import timezone

from apps.opportunities.models import Opportunity


def quick_match(client, limit: int = 10):
    """Score and return top opportunities for a client using DB-level filters.

    Scoring (0-100):
      - Keyword overlap:  0-50 pts  (most important signal)
      - Region match:     0-25 pts
      - Value in range:   0-15 pts
      - Recency:          0-10 pts
    """
    now = timezone.now()

    qs = Opportunity.objects.filter(
        status__in=["new", "analyzing", "eligible"],
    ).filter(
        Q(deadline__gte=now) | Q(deadline__isnull=True),
    )

    # Hard filter: region (if client has preferences)
    if client.regions:
        qs = qs.filter(
            Q(entity_uf__in=client.regions) | Q(entity_uf="") | Q(entity_uf__isnull=True),
        )

    # --- Keyword score (0-50) ---
    keywords = (client.keywords or [])[:20]
    if keywords:
        kw_cases = []
        for kw in keywords:
            kw_cases.append(
                When(
                    Q(title__icontains=kw) | Q(description__icontains=kw),
                    then=Value(1),
                )
            )
        kw_hits = Sum(Case(*kw_cases, default=Value(0), output_field=IntegerField()))
        # Normalize: (hits / total_keywords) * 50
        kw_score = Case(
            *[
                When(**{f"kw_hits__gte": i}, then=Value(min(50, int(i / len(keywords) * 50))))
                for i in range(len(keywords), 0, -1)
            ],
            default=Value(0),
            output_field=IntegerField(),
        )
        qs = qs.annotate(kw_hits=kw_hits)
    else:
        qs = qs.annotate(kw_hits=Value(0, output_field=IntegerField()))

    # --- Value score (0-15) ---
    if client.max_value:
        value_score = Case(
            When(estimated_value__isnull=True, then=Value(8)),
            When(estimated_value__lte=client.max_value, then=Value(15)),
            default=Value(0),
            output_field=IntegerField(),
        )
    else:
        value_score = Value(10, output_field=IntegerField())

    # --- Region score (0-25) ---
    if client.regions:
        region_score = Case(
            When(entity_uf__in=client.regions, then=Value(25)),
            default=Value(0),
            output_field=IntegerField(),
        )
    else:
        region_score = Value(15, output_field=IntegerField())

    # --- Recency score (0-10) ---
    seven_days_ago = now - timezone.timedelta(days=7)
    thirty_days_ago = now - timezone.timedelta(days=30)
    recency_score = Case(
        When(published_at__gte=seven_days_ago, then=Value(10)),
        When(published_at__gte=thirty_days_ago, then=Value(5)),
        default=Value(0),
        output_field=IntegerField(),
    )

    # Build keyword score from kw_hits
    if keywords:
        n = len(keywords)
        kw_score_expr = Case(
            *[
                When(kw_hits__gte=i, then=Value(min(50, int(i / n * 50))))
                for i in range(n, 0, -1)
            ],
            default=Value(0),
            output_field=IntegerField(),
        )
    else:
        kw_score_expr = Value(0, output_field=IntegerField())

    qs = qs.annotate(
        kw_score=kw_score_expr,
        value_score=value_score,
        region_score=region_score,
        recency_score=recency_score,
    ).annotate(
        quick_score=Sum("kw_score") + Sum("value_score") + Sum("region_score") + Sum("recency_score"),
    ).filter(
        quick_score__gt=0,
    ).order_by("-quick_score", "-published_at")[:limit]

    return qs
