"""Locust load test for MCP Gateway.

Run from the repo root:
    pip install locust
    locust -f locustfile.py --host http://localhost:8000 --users 20 --spawn-rate 2

Open http://localhost:8089 for the live dashboard.
"""

import random

from locust import HttpUser, between, task


READ_TASKS = [
    "List my GitHub repositories",
    "Show me the most recent Slack channels",
    "Search the knowledge base for deployment documentation",
    "List files in Google Drive",
]

WRITE_TASKS = [
    "List my GitHub repositories and post a summary to Slack",
]


class WorkflowUser(HttpUser):
    """Simulates a user submitting and monitoring workflows."""

    wait_time = between(2, 5)

    @task(5)
    def submit_read_workflow(self) -> None:
        self.client.post(
            "/workflows",
            json={"task": random.choice(READ_TASKS), "actor": "loadtest-reader"},
            name="/workflows [read]",
        )

    @task(2)
    def submit_write_workflow(self) -> None:
        self.client.post(
            "/workflows",
            json={"task": random.choice(WRITE_TASKS), "actor": "loadtest-writer"},
            name="/workflows [write]",
        )

    @task(8)
    def list_workflows(self) -> None:
        self.client.get("/workflows?limit=10", name="/workflows [list]")

    @task(3)
    def check_health(self) -> None:
        self.client.get("/health", name="/health")

    @task(2)
    def list_audit_logs(self) -> None:
        self.client.get("/audit-logs?limit=20", name="/audit-logs [list]")

    @task(1)
    def get_audit_stats(self) -> None:
        self.client.get("/audit-logs/stats", name="/audit-logs/stats")


class RegistryUser(HttpUser):
    """Simulates read-only access to the MCP registry."""

    wait_time = between(1, 3)

    @task(5)
    def list_servers(self) -> None:
        self.client.get("/registry/servers", name="/registry/servers [list]")

    @task(2)
    def list_tools(self) -> None:
        self.client.get("/registry/tools", name="/registry/tools [list]")
