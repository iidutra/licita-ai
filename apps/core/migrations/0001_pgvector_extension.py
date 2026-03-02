"""Create pgvector extension before any model uses vector columns."""

import logging

from django.db import migrations, transaction

logger = logging.getLogger(__name__)


def create_vector_extension(apps, schema_editor):
    """Try to create pgvector extension; skip gracefully if unavailable."""
    try:
        with transaction.atomic(using=schema_editor.connection.alias):
            schema_editor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    except Exception as e:
        logger.warning("pgvector extension not available — vector search disabled. %s", e)


def drop_vector_extension(apps, schema_editor):
    try:
        with transaction.atomic(using=schema_editor.connection.alias):
            schema_editor.execute("DROP EXTENSION IF EXISTS vector;")
    except Exception:
        pass


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.RunPython(create_vector_extension, drop_vector_extension),
    ]
