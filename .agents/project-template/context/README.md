# Context Memory project template

These files document the application-owned layout. Do not copy the placeholder
manifest hashes as authority. After the Project Adapter is valid and `BOUND`, run:

```bash
python3 .agents/_tools/agent_os_cli.py memory initialize
python3 .agents/_tools/agent_os_cli.py memory apply --plan PLAN_ID --confirm
```

The initializer derives project ID, remote aliases, content hashes, Git HEAD, and the
Project Memory projection transactionally. Consumer updates preserve the resulting
`project/context/**` and `skills/project-memory/**` bytes.
