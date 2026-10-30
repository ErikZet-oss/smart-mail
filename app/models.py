"""Imports every model module, so all tables and foreign keys are registered on the metadata (Alembic, API, CLI).

Without it, a process that imports only `app.auth.models` (the CLI) fails on `branches.mailbox_id` → `mailboxes`
(issue #33).
"""

import app.ai.models
import app.auth.models
import app.contacts.models
import app.core.audit
import app.documents.models
import app.mail.compose_models
import app.mail.models  # noqa: F401
