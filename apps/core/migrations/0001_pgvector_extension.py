"""Create pgvector extension before any model uses vector columns."""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def create_vector_extension(apps, schema_editor):
    """Try to create pgvector extension; skip gracefully if unavailable."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SAVEPOINT pgvector_ext")
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cursor.execute("RELEASE SAVEPOINT pgvector_ext")
        except Exception as e:
            cursor.execute("ROLLBACK TO SAVEPOINT pgvector_ext")
            logger.warning("pgvector extension not available — vector search disabled. %s", e)


def drop_vector_extension(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SAVEPOINT pgvector_drop")
        try:
            cursor.execute("DROP EXTENSION IF EXISTS vector;")
            cursor.execute("RELEASE SAVEPOINT pgvector_drop")
        except Exception:
            cursor.execute("ROLLBACK TO SAVEPOINT pgvector_drop")


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.RunPython(create_vector_extension, drop_vector_extension),
    ]
