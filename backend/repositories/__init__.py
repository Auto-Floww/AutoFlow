"""Repositories for complex queries only.

No repository is required for WhatsApp QR generation because it uses a simple
tenant-scoped model query; creating one would only duplicate SQLAlchemy CRUD.
"""
