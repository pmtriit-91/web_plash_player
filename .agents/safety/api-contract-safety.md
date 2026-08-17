# API Contract Safety

Do not arbitrarily change:

- response field names
- request payload shapes
- enum values
- route paths
- query params
- validation schemas
- database field semantics

If a contract change is necessary:

- Explicitly state the breaking change.
- Check the consuming locations.
- Propose migration/backward compatibility strategies.
